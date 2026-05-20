"""Arena 参赛者 CLI — studio-arena 命令入口。

环境变量（.env）:
  ARENA_COMPETITION_ID     比赛 ID
  ARENA_AGENT_SECRET       Agent Secret
  ARENA_BASE_URL           Arena 后端（默认 https://api.holosai.io）
  AGORA_BASE_URL           Agora 后端（默认 https://agora.holosai.io）

Usage:
  studio-arena me
  studio-arena competition
  studio-arena current-stage
  studio-arena tasks
  studio-arena task show <task_id> [--no-content]
  studio-arena submit <task_id> <text>
  studio-arena my-answer <task_id>
  studio-arena leaderboard
  studio-arena bounty list
  studio-arena bounty create <title> <desc> <amount>
  studio-arena bounty submit <bounty_task_id> <text>
  studio-arena budget summary
  studio-arena harness status
  studio-arena harness start
  studio-arena harness revise <task_id>
  studio-arena harness websearch <task_id>
  studio-arena kb query "<text>" [--limit N] [--language cn|global]
  studio-arena agora token
  studio-arena agora post <post_id>
  studio-arena agora register-actor <display_name> [--avatar-url <url>]
  studio-arena agora comment create <post_id> <content>
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

import click
from dotenv import load_dotenv

from .client import ArenaParticipantClient
from .engine import (
    analyze_competitors_with_client,
    batch_revise_answered,
    budget_advice,
    build_websearch_plan,
    estimate_tokens,
    harness_status,
    list_saved_contexts,
    load_answer_context,
    prepare_answer_revision,
    prepare_task_review,
    record_budget,
    review_self_performance,
    save_answer_context,
    start_participation_round,
    summarize_budget,
)

load_dotenv()


def _get_client() -> ArenaParticipantClient:
    arena_base = os.environ.get("ARENA_BASE_URL", "https://api.holosai.io")
    agora_base = os.environ.get("AGORA_BASE_URL", "https://agora.holosai.io")
    cid = os.environ.get("ARENA_COMPETITION_ID", "")
    secret = os.environ.get("ARENA_AGENT_SECRET", "")

    if not cid:
        raise click.UsageError("缺少 ARENA_COMPETITION_ID（请在 .env 中设置）")
    if not secret:
        raise click.UsageError("缺少 ARENA_AGENT_SECRET（请在 .env 中设置）")

    return ArenaParticipantClient(
        arena_base_url=arena_base,
        competition_id=cid,
        agent_secret=secret,
        agora_base_url=agora_base,
        timeout=120.0,
    )


def _run(coro):
    return asyncio.run(coro)


def _json(data, indent=2):
    click.echo(json.dumps(data, ensure_ascii=False, indent=indent))


def _read_text(text: Optional[str], input_file: Optional[str]) -> str:
    if input_file:
        return Path(input_file).read_text(encoding="utf-8")
    if text == "-":
        return click.get_text_stream("stdin").read()
    return text or ""


# ============================================================================
# 主 CLI
# ============================================================================


@click.group()
@click.version_option(version="0.1.0", prog_name="studio-arena")
def main():
    """🎯 Arena 参赛者 CLI — 参加 Holos AI Arena 比赛的命令行工具"""


# ============================================================================
# 身份 & 比赛信息
# ============================================================================


@main.command()
def me():
    """查看自己的参赛身份 (Agent API)"""
    _json(_run(_get_client().get_me()))


@main.command()
def competition():
    """查看比赛详情 (Agent API)"""
    _json(_run(_get_client().get_competition()))


@main.command(name="current-stage")
def current_stage():
    """查看当前活跃 Stage (Agent API)"""
    _json(_run(_get_client().get_current_stage()))


@main.command()
def leaderboard():
    """查看排行榜 (Agent API)"""
    _json(_run(_get_client().get_leaderboard()))


# ============================================================================
# 官方题
# ============================================================================


@main.command()
@click.option("--stage-id", default=None, help="按 stage_id 过滤")
@click.option("--current", "use_current", is_flag=True, default=False, help="只看当前活跃 Stage 的题目")
def tasks(stage_id: Optional[str], use_current: bool):
    """列出可见官方题 (Agent API)"""
    client = _get_client()
    if use_current:
        stage = _run(client.get_current_stage())
        stage_id = stage.get("id") or stage.get("stage_id")
        if not stage_id:
            raise click.ClickException("无法获取当前 Stage ID，请检查比赛是否有活跃 Stage")
    _json(_run(client.list_visible_tasks(stage_id=stage_id)))


# ============================================================================
# 单题详情
# ============================================================================


@main.group()
def task():
    """官方题详情"""


@task.command(name="show")
@click.argument("task_id")
@click.option(
    "--no-content",
    is_flag=True,
    default=False,
    help="只看 Arena 元数据，不拉 Agora 帖子正文",
)
def task_show(task_id: str, no_content: bool):
    """查看单道官方题详情（元数据 + Agora 正文）

    TASK_ID  题目 ID
    """
    client = _get_client()
    if no_content:
        _json(_run(client.get_task(task_id)))
    else:
        _json(_run(client.get_task_with_content(task_id)))


# ============================================================================
# 提交答案
# ============================================================================


@main.command()
@click.argument("task_id")
@click.argument("text", default="")
@click.option("--file", "-f", "file_path", default=None, help="从文件读取答案正文（避免 shell 转义问题）")
def submit(task_id: str, text: str, file_path: str):
    """提交官方题回答 (Agent API)

    TASK_ID  题目 ID
    TEXT     回答正文（也可用 --file 或 stdin 传入）
    """
    if file_path:
        text = Path(file_path).read_text(encoding="utf-8")
    elif not text:
        text = click.get_text_stream("stdin").read()
    stripped = text.strip()
    if len(stripped) < 200:
        _json({"error": f"Answer too short ({len(stripped)} chars). Minimum 200 chars required. Refusing to submit broken answer.", "task_id": task_id})
        raise SystemExit(1)
    _BANNED_PREFIXES = ["回复追问", "提交答案", "开始修订", "修订任务", "执行步骤"]
    for prefix in _BANNED_PREFIXES:
        if stripped == prefix or (len(stripped) < 50 and stripped.startswith(prefix)):
            _json({"error": f"Content looks like a step label, not an answer: '{stripped[:50]}'", "task_id": task_id})
            raise SystemExit(1)
    _json(_run(_get_client().submit_task_answer(task_id, text)))


@main.command(name="my-answer")
@click.argument("task_id")
def my_answer(task_id: str):
    """查看自己在该题的提交和得分 (Agent API)

    TASK_ID  题目 ID
    """
    _json(_run(_get_client().get_my_task_answer(task_id)))


# ============================================================================
# 子问题悬赏
# ============================================================================


@main.group()
def bounty():
    """子问题悬赏"""


@bounty.command(name="list")
@click.option("--stage-id", default=None)
@click.option("--status", default=None, help="open / closed / accepted / cancelled")
@click.option("--publisher", default=None, help="发布者 participant_id")
def bounty_list(
    stage_id: Optional[str], status: Optional[str], publisher: Optional[str]
):
    """列出子问题悬赏 (Agent API)"""
    _json(
        _run(
            _get_client().list_bounty_tasks(
                stage_id=stage_id,
                status=status,
                publisher_participant_id=publisher,
            )
        )
    )


@bounty.command(name="create")
@click.argument("title")
@click.argument("description")
@click.argument("bounty_amount", type=int)
def bounty_create(title: str, description: str, bounty_amount: int):
    """发布子问题悬赏，扣钱包 (Agent API)

    TITLE          标题
    DESCRIPTION    描述
    BOUNTY_AMOUNT  悬赏金额（忽略，强制为 1）
    """
    _json(
        _run(
            _get_client().create_bounty_task(
                title, description, bounty_amount=1
            )
        )
    )


@bounty.command(name="submit")
@click.argument("bounty_task_id")
@click.argument("text")
def bounty_submit(bounty_task_id: str, text: str):
    """回答子问题悬赏 (Agent API)

    BOUNTY_TASK_ID  悬赏 ID
    TEXT            回答正文
    """
    stripped = text.strip()
    if len(stripped) < 200:
        _json({"error": f"Bounty answer too short ({len(stripped)} chars). Minimum 200 chars required.", "bounty_task_id": bounty_task_id})
        raise SystemExit(1)
    _BANNED_PREFIXES = ["回复追问", "提交答案", "开始修订", "修订任务", "执行步骤"]
    for prefix in _BANNED_PREFIXES:
        if stripped == prefix or (len(stripped) < 50 and stripped.startswith(prefix)):
            _json({"error": f"Content looks like a step label, not an answer: '{stripped[:50]}'", "bounty_task_id": bounty_task_id})
            raise SystemExit(1)
    _json(_run(_get_client().submit_bounty_answer(bounty_task_id, text)))


@bounty.command(name="replies")
@click.argument("bounty_task_id")
def bounty_replies(bounty_task_id: str):
    """获取悬赏回复列表（通过 Agora）

    BOUNTY_TASK_ID  悬赏 ID
    """
    _json(_run(_get_client().list_bounty_answers(bounty_task_id)))


@bounty.command(name="accept")
@click.argument("bounty_task_id")
@click.argument("answer_id")
def bounty_accept(bounty_task_id: str, answer_id: str):
    """采纳悬赏回复

    BOUNTY_TASK_ID  悬赏 ID
    ANSWER_ID       要采纳的回复 ID
    """
    _json(_run(_get_client().accept_bounty_answer(bounty_task_id, answer_id)))


@bounty.command(name="wait")
@click.argument("bounty_task_id")
@click.option("--interval", default=40, type=int, help="轮询间隔（秒）")
@click.option("--max-attempts", default=7, type=int, help="最大轮询次数")
def bounty_wait(bounty_task_id: str, interval: int, max_attempts: int):
    """轮询等待悬赏回复，有回复或超时后返回 (Agent API)

    BOUNTY_TASK_ID  悬赏 ID

    返回 JSON：
      - status: "got_replies" | "timeout"
      - replies: [...] (回复列表，timeout 时为空)
      - attempts: 实际轮询次数
    """
    for attempt in range(1, max_attempts + 1):
        time.sleep(interval)
        replies = _run(_get_client().list_bounty_answers(bounty_task_id))
        if replies:
            _json({"status": "got_replies", "replies": replies, "attempts": attempt})
            return
    _json({"status": "timeout", "replies": [], "attempts": max_attempts})


# ============================================================================
# Token 预算
# ============================================================================


@main.group()
def budget():
    """Token 预算与投入产出台账"""


@budget.command(name="estimate")
@click.argument("text", required=False)
@click.option(
    "--file", "input_file", default=None, type=click.Path(exists=True, dir_okay=False)
)
def budget_estimate(text: Optional[str], input_file: Optional[str]):
    """估算一段文本的 token 消耗。

    TEXT 可传普通文本；传 '-' 时从 stdin 读取。
    """
    content = _read_text(text, input_file)
    if not content:
        raise click.UsageError("请提供 TEXT、'-' 或 --file")
    _json({"estimated_tokens": estimate_tokens(content)})


@budget.command(name="record")
@click.argument("task_id")
@click.option("--estimated-tokens", type=int, default=None, help="预估 token 数")
@click.option("--actual-tokens", type=int, default=None, help="实际 token 数")
@click.option("--reward", type=float, default=None, help="该题收益或预期收益")
@click.option("--mode", type=click.Choice(["save", "relaxed"]), default="save")
@click.option("--note", default="", help="备注")
@click.option("--text", default=None, help="用文本估算 token 后记录")
@click.option(
    "--file", "input_file", default=None, type=click.Path(exists=True, dir_okay=False)
)
@click.option("--ledger-file", default=None, help="预算台账路径，默认 .studio-arena-budget.json")
def budget_record(
    task_id: str,
    estimated_tokens: Optional[int],
    actual_tokens: Optional[int],
    reward: Optional[float],
    mode: str,
    note: str,
    text: Optional[str],
    input_file: Optional[str],
    ledger_file: Optional[str],
):
    """记录某题 token 消耗、收益和预算模式。"""
    if estimated_tokens is None:
        content = _read_text(text, input_file)
        if not content:
            raise click.UsageError("请提供 --estimated-tokens，或通过 --text/--file 提供文本")
        estimated_tokens = estimate_tokens(content)
    _json(
        record_budget(
            task_id,
            estimated_tokens=estimated_tokens,
            actual_tokens=actual_tokens,
            reward=reward,
            mode=mode,
            note=note,
            path=ledger_file,
        )
    )


@budget.command(name="summary")
@click.option("--ledger-file", default=None, help="预算台账路径，默认 .studio-arena-budget.json")
def budget_summary(ledger_file: Optional[str]):
    """汇总 token 消耗、超额成本和收益。"""
    _json(summarize_budget(path=ledger_file))


@budget.command(name="advice")
@click.option("--estimated-tokens", type=int, default=None, help="预估 token 数")
@click.option("--reward", type=float, default=None, help="题目奖励或预期收益")
@click.option("--balance", type=float, default=None, help="当前钱包余额")
@click.option("--high-reward-threshold", type=float, default=1000.0)
@click.option("--reserve-balance", type=float, default=5000.0)
@click.option("--text", default=None, help="用文本估算 token 后给建议")
@click.option(
    "--file", "input_file", default=None, type=click.Path(exists=True, dir_okay=False)
)
@click.option("--ledger-file", default=None, help="预算台账路径，默认 .studio-arena-budget.json")
def budget_advice_cmd(
    estimated_tokens: Optional[int],
    reward: Optional[float],
    balance: Optional[float],
    high_reward_threshold: float,
    reserve_balance: float,
    text: Optional[str],
    input_file: Optional[str],
    ledger_file: Optional[str],
):
    """按奖励、余额和剩余 token 给出 save/relaxed 建议。"""
    if estimated_tokens is None:
        content = _read_text(text, input_file)
        if not content:
            raise click.UsageError("请提供 --estimated-tokens，或通过 --text/--file 提供文本")
        estimated_tokens = estimate_tokens(content)
    _json(
        budget_advice(
            estimated_tokens=estimated_tokens,
            reward=reward,
            balance=balance,
            high_reward_threshold=high_reward_threshold,
            reserve_balance=reserve_balance,
            path=ledger_file,
        )
    )


# ============================================================================
# Harness 编排（CLI 只生成规划/审阅包；自动提交由 Synergy 插件工具执行）
# ============================================================================


@main.group()
def harness():
    """Skill/MCP harness 编排：开始参赛、复盘、对手分析"""


@harness.command(name="status")
def harness_status_cmd():
    """查看 harness 已实现能力、审阅模式和全自动模式护栏。"""
    _json(harness_status())


@harness.command(name="start")
@click.option("--limit", type=int, default=1, show_default=True, help="生成审阅包的题目数")
@click.option("--balance", type=float, default=None, help="当前钱包余额，用于预算护栏")
@click.option("--stage-id", default=None, help="指定 stage_id；默认使用当前 Stage")
@click.option("--ledger-file", default=None, help="预算台账路径，默认 .studio-arena-budget.json")
@click.option("--include-answered", is_flag=True, default=False, help="包含已经提交过的题目")
def harness_start(
    limit: int,
    balance: Optional[float],
    stage_id: Optional[str],
    ledger_file: Optional[str],
    include_answered: bool,
):
    """执行“开始参赛”准备流程，输出规划/审阅包；CLI 本身不提交答案。"""
    _json(
        _run(
            start_participation_round(
                _get_client(),
                limit=limit,
                balance=balance,
                stage_id=stage_id,
                ledger_file=ledger_file,
                skip_answered=not include_answered,
            )
        )
    )


@harness.command(name="review")
@click.argument("task_id")
@click.option("--balance", type=float, default=None, help="当前钱包余额，用于预算护栏")
@click.option("--ledger-file", default=None, help="预算台账路径，默认 .studio-arena-budget.json")
def harness_review(
    task_id: str,
    balance: Optional[float],
    ledger_file: Optional[str],
):
    """为单题生成答案规划/审阅包；CLI 本身不提交答案。"""
    _json(
        _run(
            prepare_task_review(
                _get_client(),
                task_id,
                balance=balance,
                ledger_file=ledger_file,
            )
        )
    )


@harness.command(name="revise")
@click.argument("task_id")
@click.option("--balance", type=float, default=None, help="当前钱包余额，用于预算护栏")
@click.option("--ledger-file", default=None, help="预算台账路径，默认 .studio-arena-budget.json")
def harness_revise(
    task_id: str,
    balance: Optional[float],
    ledger_file: Optional[str],
):
    """基于 Answer comments 生成完整答案修订包；CLI 本身不提交答案。"""
    _json(
        _run(
            prepare_answer_revision(
                _get_client(),
                task_id,
                balance=balance,
                ledger_file=ledger_file,
            )
        )
    )


@harness.command(name="batch-revise")
@click.option("--limit", type=int, default=10, show_default=True, help="最多修订几题")
@click.option("--balance", type=float, default=None, help="当前钱包余额")
@click.option("--stage-id", default=None, help="指定 stage_id；默认当前 Stage")
@click.option("--ledger-file", default=None, help="预算台账路径")
@click.option("--include-no-comments", is_flag=True, default=False, help="包含没有 comments 的已答题")
def harness_batch_revise(
    limit: int,
    balance: Optional[float],
    stage_id: Optional[str],
    ledger_file: Optional[str],
    include_no_comments: bool,
):
    """批量查找有 comments 的已答题并生成修订包；CLI 本身不提交答案。"""
    _json(
        _run(
            batch_revise_answered(
                _get_client(),
                limit=limit,
                balance=balance,
                stage_id=stage_id,
                ledger_file=ledger_file,
                only_with_comments=not include_no_comments,
            )
        )
    )


@harness.command(name="websearch")
@click.argument("task_id")
@click.option(
    "--mode",
    type=click.Choice(["save", "relaxed"]),
    default="save",
    show_default=True,
    help="搜索预算模式",
)
@click.option("--max-queries", type=int, default=None, help="最多生成多少条查询")
def harness_websearch(task_id: str, mode: str, max_queries: Optional[int]):
    """为单题生成权威网站优先的 Web Search 计划，不执行联网搜索。"""
    task = _run(_get_client().get_task_with_content(task_id))
    _json(build_websearch_plan(task, mode=mode, max_queries=max_queries))


@harness.command(name="self-review")
@click.option("--task-id", "task_ids", multiple=True, help="需要拉取 my-answer 的题目 ID")
@click.option("--ledger-file", default=None, help="预算台账路径，默认 .studio-arena-budget.json")
def harness_self_review(task_ids: tuple[str, ...], ledger_file: Optional[str]):
    """执行“复盘今天”：汇总预算、排行榜和自己的题目得分。"""
    _json(
        _run(
            review_self_performance(
                _get_client(),
                task_ids=task_ids,
                ledger_file=ledger_file,
            )
        )
    )


@harness.command(name="competitors")
@click.option("--window", type=int, default=5, show_default=True, help="比较前面多少名")
def harness_competitors(window: int):
    """执行“分析对手”：比较排行榜上比自己高的 3-5 名参赛者。"""
    _json(_run(analyze_competitors_with_client(_get_client(), window=window)))


# ============================================================================
# Answer context persistence
# ============================================================================


@main.group()
def context():
    """答案上下文存储：提交时保存推理过程，修订时读回"""


@context.command(name="save")
@click.argument("task_id")
@click.argument("answer_text", default="")
@click.option("--file", "-f", "file_path", default=None, help="从文件读取答案正文")
@click.option("--reasoning", default="", help="推理过程摘要")
@click.option("--reasoning-file", default=None, help="从文件读取推理过程")
@click.option("--domain", default="", help="领域标签")
@click.option("--difficulty", type=int, default=0, help="难度评分")
def context_save(task_id: str, answer_text: str, file_path: str, reasoning: str, reasoning_file: str, domain: str, difficulty: int):
    """保存答案上下文（答案正文 + 推理过程），供后续修订时读回。

    TASK_ID       题目 ID
    ANSWER_TEXT   答案正文（也可用 --file 传入）
    """
    if file_path:
        answer_text = Path(file_path).read_text(encoding="utf-8")
    elif not answer_text:
        answer_text = click.get_text_stream("stdin").read()
    if reasoning_file:
        reasoning = Path(reasoning_file).read_text(encoding="utf-8")
    _json(
        save_answer_context(
            task_id,
            answer_text,
            reasoning=reasoning,
            domain=domain,
            difficulty=difficulty,
        )
    )


@context.command(name="load")
@click.argument("task_id")
def context_load(task_id: str):
    """读取已保存的答案上下文。

    TASK_ID  题目 ID
    """
    ctx = load_answer_context(task_id)
    if ctx is None:
        _json({"found": False, "task_id": task_id})
    else:
        _json(ctx)


@context.command(name="list")
def context_list():
    """列出所有已保存上下文的 task_id。"""
    _json({"task_ids": list_saved_contexts()})


@context.command(name="clean")
def context_clean():
    """清理无效上下文（answer_text < 200 字符的文件）。"""
    all_ids = list_saved_contexts()
    removed = []
    kept = []
    for tid in all_ids:
        ctx = load_answer_context(tid)
        if ctx and not ctx.get("usable", True):
            from .engine.context import _context_path
            path = _context_path(tid)
            path.unlink(missing_ok=True)
            removed.append(tid)
        else:
            kept.append(tid)
    _json({"removed": removed, "kept_count": len(kept), "removed_count": len(removed)})


# ============================================================================
# Agora
# ============================================================================


@main.group()
def agora():
    """Agora 社区（读内容 / 发评论）"""


@agora.command(name="token")
@click.option("--force", is_flag=True, default=False, help="强制重新签发 token")
def agora_token(force: bool):
    """签发 Agora JWT（调试用）"""
    _json(_run(_get_client().get_agora_token_info(force=force)))


@agora.command(name="posts")
@click.argument("space")
@click.option("--no-jwt", is_flag=True, default=False, help="不用 JWT 读取公开内容")
def agora_posts(space: str, no_jwt: bool):
    """按 space 列帖子"""
    _json(_run(_get_client().agora_list_posts(space, use_jwt=not no_jwt)))


@agora.command(name="post")
@click.argument("post_id")
@click.option("--no-jwt", is_flag=True, default=False, help="不用 JWT 读取公开帖子")
def agora_post(post_id: str, no_jwt: bool):
    """读帖子正文"""
    _json(_run(_get_client().agora_get_post(post_id, use_jwt=not no_jwt)))


@agora.command(name="answers")
@click.argument("post_id")
def agora_answers(post_id: str):
    """列帖子下全部回答"""
    _json(_run(_get_client().agora_list_answers(post_id)))


@agora.command(name="answer")
@click.argument("answer_id")
def agora_answer(answer_id: str):
    """读单个回答正文"""
    _json(_run(_get_client().agora_get_answer(answer_id)))


@agora.command(name="comments")
@click.argument("post_id")
def agora_comments(post_id: str):
    """列帖子评论"""
    _json(_run(_get_client().agora_list_comments(post_id)))


@agora.command(name="register-actor")
@click.argument("display_name")
@click.option("--avatar-url", default=None, help="头像 URL（可省略）")
def agora_register_actor(display_name: str, avatar_url: Optional[str]):
    """注册 Agora actor（首次直接调用 Agora 前需完成）

    DISPLAY_NAME  显示名称
    """
    _json(_run(_get_client().agora_register_actor(display_name, avatar_url=avatar_url)))



@agora.group(name="comment")
def agora_comment_group():
    """评论管理"""


@agora_comment_group.command(name="create")
@click.argument("post_id")
@click.argument("content", default="")
@click.option("--parent-type", default="post", help="post / answer / comment")
@click.option("--parent-id", default="", help="parent_type=post 时可省略")
@click.option("--file", "-f", "file_path", default=None, help="从文件读取评论内容")
def agora_comment_create(post_id: str, content: str, parent_type: str, parent_id: str, file_path: str):
    """发评论（需 JWT）

    POST_ID     帖子 ID
    CONTENT     评论内容（也可用 --file 或 stdin 传入）
    """
    if file_path:
        content = Path(file_path).read_text(encoding="utf-8")
    elif not content:
        content = click.get_text_stream("stdin").read()
    stripped = content.strip()
    if len(stripped) < 200:
        _json({"error": f"Comment too short ({len(stripped)} chars). Minimum 200 chars for answer comments. Refusing to post.", "post_id": post_id})
        raise SystemExit(1)
    _BANNED_PREFIXES = ["回复追问", "提交答案", "开始修订", "修订任务", "执行步骤"]
    for prefix in _BANNED_PREFIXES:
        if stripped == prefix or (len(stripped) < 50 and stripped.startswith(prefix)):
            _json({"error": f"Content looks like a step label, not an answer. Refusing to post: '{stripped[:50]}'", "post_id": post_id})
            raise SystemExit(1)
    _json(
        _run(
            _get_client().agora_create_comment(
                post_id, content, parent_type=parent_type, parent_id=parent_id
            )
        )
    )


# ============================================================================
# Knowledge Base
# ============================================================================


@main.group()
def kb():
    """知识库检索：用题目全文检索背景提示"""


@kb.command(name="query")
@click.argument("query_text", default="")
@click.option("--file", "-f", "file_path", default=None, help="从文件读取查询文本")
@click.option("--limit", type=int, default=3, show_default=True, help="返回条目数")
@click.option("--language", type=click.Choice(["cn", "global"]), default=None, help="语言过滤")
@click.option("--subset", default=None, help="领域过滤")
def kb_query(query_text: str, file_path: Optional[str], limit: int, language: Optional[str], subset: Optional[str]):
    """用题目全文检索知识库，获取答题提示。

    QUERY_TEXT  查询文本（整道题放进来效果最好）
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "mcp"))
    from mcp_hint_kb_server import HintKbServer

    kb_path = Path(__file__).resolve().parents[3] / "mcp" / "task_hint_kb.jsonl"
    if not kb_path.exists():
        _json({"error": f"KB file not found: {kb_path}"})
        raise SystemExit(1)

    if file_path:
        query_text = Path(file_path).read_text(encoding="utf-8")
    elif not query_text:
        query_text = click.get_text_stream("stdin").read()

    if not query_text.strip():
        _json({"error": "Empty query. Provide task text as argument, --file, or stdin."})
        raise SystemExit(1)

    server = HintKbServer(kb_path)
    result = server.retrieve_context(query_text.strip(), limit=limit, language=language, subset=subset)
    _json(result)


# ============================================================================
# 入口
# ============================================================================

if __name__ == "__main__":
    main()
