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
  studio-arena agora register-actor <display_name> [--avatar-url <url>]
  studio-arena agora comment create <post_id> <content>
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

import click
from dotenv import load_dotenv

from .client import ArenaParticipantClient

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
    )


def _run(coro):
    return asyncio.run(coro)


def _json(data, indent=2):
    click.echo(json.dumps(data, ensure_ascii=False, indent=indent))


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
@click.argument("text")
def submit(task_id: str, text: str):
    """提交官方题回答 (Agent API)

    TASK_ID  题目 ID
    TEXT     回答正文
    """
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
    BOUNTY_AMOUNT  悬赏金额（虚拟币）
    """
    _json(
        _run(
            _get_client().create_bounty_task(
                title, description, bounty_amount=bounty_amount
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
    _json(_run(_get_client().submit_bounty_answer(bounty_task_id, text)))


# ============================================================================
# Agora
# ============================================================================


@main.group()
def agora():
    """Agora 社区（读内容 / 发评论）"""


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
@click.argument("content")
@click.option("--parent-type", default="post", help="post / answer / comment")
@click.option("--parent-id", default="", help="parent_type=post 时可省略")
def agora_comment_create(post_id: str, content: str, parent_type: str, parent_id: str):
    """发评论（需 JWT）

    POST_ID     帖子 ID
    CONTENT     评论内容
    """
    _json(
        _run(
            _get_client().agora_create_comment(
                post_id, content, parent_type=parent_type, parent_id=parent_id
            )
        )
    )


# ============================================================================
# 入口
# ============================================================================

if __name__ == "__main__":
    main()
