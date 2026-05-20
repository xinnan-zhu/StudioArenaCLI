"""High-level orchestration: start participation, batch revise, self-review, competitors."""

from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from .bounty import analyze_reward_distribution, bounty_decision
from .budget import summarize_budget
from .difficulty import estimate_task_difficulty
from .domain import (
    SCORE_KEYS,
    _first_number,
    _stringify,
    answer_score,
    classify_domain,
    looks_answered,
    task_id,
    task_title,
    task_reward,
)
from .review import build_answer_revision_packet, build_review_packet


def prioritize_tasks(tasks: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for task in tasks:
        domain = classify_domain(task)
        difficulty = estimate_task_difficulty(task)
        reward = task_reward(task)
        priority_score = reward - difficulty["score"] * 50
        ranked.append(
            {
                "task_id": task_id(task),
                "title": task_title(task),
                "reward": reward,
                "domain": domain["label"],
                "difficulty_score": difficulty["score"],
                "priority_score": priority_score,
            }
        )

    return sorted(
        ranked,
        key=lambda item: (
            item["priority_score"],
            item["reward"],
            -item["difficulty_score"],
        ),
        reverse=True,
    )


def classify_tasks_by_approach(
    tasks: Sequence[dict[str, Any]],
    *,
    balance: Optional[float] = None,
) -> dict[str, Any]:
    """Split tasks into self-doable vs bounty-candidate batches."""
    reward_dist = analyze_reward_distribution(list(tasks))
    solo: list[dict[str, Any]] = []
    pending_bounty: list[dict[str, Any]] = []

    for task in tasks:
        bd = bounty_decision(task, balance=balance, reward_dist=reward_dist)
        entry = {
            "task_id": task_id(task),
            "title": task_title(task),
            "reward": task_reward(task),
            "difficulty": bd["difficulty"],
            "domain": bd["domain"],
            "bounty_decision": bd,
        }
        if bd["should_bounty"]:
            pending_bounty.append(entry)
        else:
            solo.append(entry)

    solo_sorted = sorted(solo, key=lambda x: (-x["reward"], x["difficulty"]["score"]))
    pending_sorted = sorted(pending_bounty, key=lambda x: -x["reward"])

    return {
        "reward_distribution": reward_dist,
        "round1_solo": solo_sorted,
        "round2_pending": pending_sorted,
        "solo_count": len(solo_sorted),
        "pending_count": len(pending_sorted),
        "summary": (
            f"共 {len(tasks)} 题：{len(solo_sorted)} 题可自主完成，"
            f"{len(pending_sorted)} 题难度较高建议等用户决定是否分包。"
            f"本轮奖励中位数={reward_dist['median']}，"
            f"分包最低门槛(奖池≥)={reward_dist['bounty_min_pool']}，"
            f"单次赏金上限={reward_dist['bounty_max_amount']}"
        ),
    }


def harness_status() -> dict[str, Any]:
    return {
        "delivery_shape": "Skill + Synergy plugin tools + MCP-ready CLI harness",
        "submission_mode": "review_by_default_autonomous_when_explicit",
        "submission_modes": {
            "default": "human_review_required",
            "explicit_autonomous": (
                "enabled_by_user_trigger: 全自动模式 / 完全自动化 / 自动提交 / autonomous mode"
            ),
        },
        "implemented": [
            "domain_routing",
            "authoritative_websearch_planning",
            "budget_guardrails",
            "review_packet_generation",
            "answer_comment_full_revision_packets",
            "task_prioritization",
            "self_review_summary",
            "competitor_analysis",
            "followup_detection",
            "optional_mcp_entrypoint",
            "synergy_plugin_autonomous_write_tools",
        ],
        "review_mode_write_actions_blocked_until_review": [
            "submit_answer", "create_bounty", "create_agora_comment",
        ],
        "cli_harness_planning_only": True,
        "autonomous_writes_supported_via_synergy_plugin": True,
        "autonomous_write_tools": [
            "studio_arena_submit_answer",
            "studio_arena_create_comment",
            "studio_arena_create_bounty",
            "studio_arena_record_budget",
        ],
        "revision_tools": [
            "studio_arena_revise_answer",
            "studio-arena harness revise <task_id>",
        ],
    }


async def prepare_task_review(
    client: Any,
    task_id_value: str,
    *,
    balance: Optional[float] = None,
    ledger_file: Optional[str] = None,
) -> dict[str, Any]:
    task = await client.get_task_with_content(task_id_value)
    comments: list[dict[str, Any]] = []
    post_id = task.get("agora_post_id")
    if post_id:
        try:
            comments = await client.agora_list_comments(post_id)
        except Exception as exc:
            task["agora_comments_error"] = str(exc)
    return build_review_packet(
        task,
        balance=balance,
        comments=comments,
        ledger_file=ledger_file,
    )


async def prepare_answer_revision(
    client: Any,
    task_id_value: str,
    *,
    balance: Optional[float] = None,
    ledger_file: Optional[str] = None,
) -> dict[str, Any]:
    task = await client.get_task_with_content(task_id_value)
    comments: list[dict[str, Any]] = []
    post_id = task.get("agora_post_id")
    if post_id:
        try:
            comments = await client.agora_list_comments(post_id)
        except Exception as exc:
            task["agora_comments_error"] = str(exc)
    try:
        my_answer = await client.get_my_task_answer(task_id_value)
    except Exception as exc:
        my_answer = {"error": str(exc)}
    return build_answer_revision_packet(
        task,
        my_answer=my_answer,
        comments=comments,
        balance=balance,
        ledger_file=ledger_file,
    )


async def batch_revise_answered(
    client: Any,
    *,
    limit: int = 10,
    balance: Optional[float] = None,
    stage_id: Optional[str] = None,
    ledger_file: Optional[str] = None,
    only_with_comments: bool = True,
) -> dict[str, Any]:
    """Find answered tasks with comments and generate revision packets."""
    stage = await client.get_current_stage()
    current_stage_id = stage_id or stage.get("id") or stage.get("stage_id")
    tasks = await client.list_visible_tasks(stage_id=current_stage_id)

    revision_packets: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for task_item in tasks:
        if len(revision_packets) >= limit:
            break
        tid = task_id(task_item)
        try:
            my_answer = await client.get_my_task_answer(tid)
        except Exception:
            continue
        if not looks_answered(my_answer):
            continue

        post_id = task_item.get("agora_post_id")
        comments: list[dict[str, Any]] = []
        if post_id:
            try:
                comments = await client.agora_list_comments(post_id)
            except Exception:
                pass

        if only_with_comments and not comments:
            skipped.append({"task_id": tid, "reason": "no_comments"})
            continue

        packet = build_answer_revision_packet(
            task_item,
            my_answer=my_answer,
            comments=comments,
            balance=balance,
            ledger_file=ledger_file,
        )
        revision_packets.append(packet)

    return {
        "trigger": "批量修订已答题",
        "stage": stage,
        "revision_packets": revision_packets,
        "revision_count": len(revision_packets),
        "skipped": skipped,
        "limit": limit,
        "only_with_comments": only_with_comments,
        "human_review_required": True,
        "autonomous_mode_available_via_plugin": True,
    }


async def start_participation_round(
    client: Any,
    *,
    limit: int = 1,
    balance: Optional[float] = None,
    stage_id: Optional[str] = None,
    ledger_file: Optional[str] = None,
    skip_answered: bool = True,
) -> dict[str, Any]:
    stage = await client.get_current_stage()
    current_stage_id = stage_id or stage.get("id") or stage.get("stage_id")
    tasks = await client.list_visible_tasks(stage_id=current_stage_id)
    candidate_tasks: list[dict[str, Any]] = []
    skipped_answered: list[dict[str, Any]] = []

    for task in tasks:
        tid = task_id(task)
        if not skip_answered:
            candidate_tasks.append(task)
            continue
        try:
            my_answer = await client.get_my_task_answer(tid)
        except Exception:
            candidate_tasks.append(task)
            continue
        if looks_answered(my_answer):
            skipped_answered.append(
                {
                    "task_id": tid,
                    "title": task_title(task),
                    "score": answer_score(my_answer),
                }
            )
        else:
            candidate_tasks.append(task)

    ranked = prioritize_tasks(candidate_tasks)

    review_packets = []
    for item in ranked[: max(0, limit)]:
        review_packets.append(
            await prepare_task_review(
                client,
                item["task_id"],
                balance=balance,
                ledger_file=ledger_file,
            )
        )

    return {
        "trigger": "开始参赛",
        "stage": stage,
        "task_count": len(tasks),
        "candidate_task_count": len(candidate_tasks),
        "skip_answered": skip_answered,
        "skipped_answered_tasks": skipped_answered,
        "ranked_tasks": ranked,
        "review_packets": review_packets,
        "human_review_required": True,
        "autonomous_mode_available_via_plugin": True,
        "autonomous_mode_requires_explicit_user_trigger": True,
        "cli_harness_planning_only": True,
        "write_actions_performed": [],
    }


async def review_self_performance(
    client: Any,
    *,
    task_ids: Optional[Iterable[str]] = None,
    ledger_file: Optional[str] = None,
) -> dict[str, Any]:
    me = await client.get_me()
    leaderboard = await client.get_leaderboard()
    budget = summarize_budget(path=ledger_file)
    answers: list[dict[str, Any]] = []
    task_id_list = list(task_ids or [])

    for tid in task_id_list:
        try:
            answer = await client.get_my_task_answer(tid)
            answers.append({"task_id": tid, "answer": answer, "score": answer_score(answer)})
        except Exception as exc:
            answers.append({"task_id": tid, "error": str(exc), "score": None})

    scored = [item for item in answers if item.get("score") is not None]
    low_score = [item for item in scored if float(item["score"]) < 0.6]
    high_score = [item for item in scored if float(item["score"]) >= 0.8]

    return {
        "trigger": "复盘今天",
        "me": me,
        "budget": budget,
        "leaderboard_position": find_participant_position(leaderboard, me),
        "answers_reviewed": answers,
        "summary": {
            "reviewed_count": len(answers),
            "high_score_count": len(high_score),
            "low_score_count": len(low_score),
            "needs_task_ids_for_answer_scores": not bool(task_id_list),
        },
        "next_actions": [
            "compare low-score tasks against domain templates",
            "tighten budget thresholds if low balance or weak bounty ROI appears",
            "check Agora comments for follow-up revisions",
        ],
    }


async def analyze_competitors_with_client(
    client: Any,
    *,
    window: int = 5,
) -> dict[str, Any]:
    me = await client.get_me()
    leaderboard = await client.get_leaderboard()
    return analyze_competitors(leaderboard, me=me, window=window)


def find_participant_position(
    leaderboard: Sequence[dict[str, Any]],
    me: Optional[dict[str, Any]],
) -> Optional[int]:
    if not me:
        return None
    my_values = {
        _stringify(me.get(key))
        for key in ("participant_id", "id", "agent_id", "name", "display_name")
        if me.get(key) is not None
    }
    for index, row in enumerate(leaderboard):
        row_values = {
            _stringify(row.get(key))
            for key in ("participant_id", "id", "agent_id", "name", "display_name")
            if row.get(key) is not None
        }
        if my_values & row_values:
            return index
    return None


def analyze_competitors(
    leaderboard: Sequence[dict[str, Any]],
    *,
    me: Optional[dict[str, Any]] = None,
    window: int = 5,
) -> dict[str, Any]:
    position = find_participant_position(leaderboard, me)
    if position is None:
        targets = list(leaderboard[:window])
        me_row = None
    else:
        start = max(0, position - window)
        targets = list(leaderboard[start:position])
        me_row = leaderboard[position] if position < len(leaderboard) else None

    my_score = _first_number(me_row or me or {}, SCORE_KEYS) or 0.0
    comparisons = []
    for row in targets:
        competitor_score = _first_number(row, SCORE_KEYS) or 0.0
        comparisons.append(
            {
                "rank": row.get("rank") or row.get("position"),
                "participant_id": row.get("participant_id") or row.get("id"),
                "name": row.get("name") or row.get("display_name"),
                "score": competitor_score,
                "score_gap": competitor_score - my_score,
                "raw": row,
            }
        )

    return {
        "trigger": "分析对手",
        "my_position": position + 1 if position is not None else None,
        "competitors_above": comparisons,
        "data_limitations": [
            "Opponent historical answers are only available if exposed by Arena or Agora APIs.",
            "Bounty revenue can only be inferred when leaderboard or bounty list exposes it.",
        ],
        "recommended_focus": [
            "Compare answer completeness and structure against higher-ranked public answers.",
            "Prioritize high-reward tasks where the score gap is largest.",
            "Review bounty ROI before spending wallet balance.",
        ],
    }
