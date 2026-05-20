"""Bounty decision engine and state persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Sequence

from .budget import DEFAULT_HIGH_REWARD_THRESHOLD, DEFAULT_RESERVE_BALANCE
from .difficulty import estimate_task_difficulty
from .domain import _stringify, classify_domain, task_id, task_reward

DEFAULT_BOUNTY_DIFFICULTY_THRESHOLD = 5
DEFAULT_BOUNTY_COST_RATIO_BASE = 0.20


def analyze_reward_distribution(
    tasks: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze reward POOL distribution of all tasks in the current stage."""
    rewards = sorted([task_reward(t) for t in tasks if task_reward(t) > 0])
    if not rewards:
        return {
            "count": 0,
            "min": 0, "max": 0, "mean": 0, "median": 0,
            "p25": 0, "p50": 0, "p75": 0,
            "total_pool": 0,
            "bounty_min_pool": 0,
            "bounty_max_amount": 0,
            "bounty_cost_ratio": DEFAULT_BOUNTY_COST_RATIO_BASE,
            "reward_model": "proportional_pool",
        }

    n = len(rewards)
    total = sum(rewards)
    mean = total / n
    median = rewards[n // 2] if n % 2 else (rewards[n // 2 - 1] + rewards[n // 2]) / 2
    p25 = rewards[max(0, n // 4)]
    p75 = rewards[min(n - 1, n * 3 // 4)]

    est_participants = 10
    est_base_score = 70
    est_score_gain = 10
    expected_income_per_task = p75 / est_participants
    bounty_max = expected_income_per_task * 0.5

    spread = (p75 - p25) / mean if mean > 0 else 0
    cost_ratio = min(0.30, DEFAULT_BOUNTY_COST_RATIO_BASE + spread * 0.05)

    return {
        "count": n,
        "min": rewards[0],
        "max": rewards[-1],
        "mean": round(mean, 1),
        "median": median,
        "p25": p25,
        "p50": median,
        "p75": p75,
        "total_pool": total,
        "bounty_min_pool": median,
        "bounty_max_amount": round(bounty_max, 0),
        "bounty_cost_ratio": round(cost_ratio, 3),
        "reward_model": "proportional_pool",
        "assumptions": {
            "est_participants": est_participants,
            "est_base_score": est_base_score,
            "est_score_gain_from_bounty": est_score_gain,
            "expected_income_per_p75_task": round(expected_income_per_task, 1),
        },
    }


def bounty_decision(
    task: dict[str, Any],
    *,
    balance: Optional[float] = None,
    reserve_balance: float = DEFAULT_RESERVE_BALANCE,
    reward_dist: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Decide whether to subcontract part of a task via bounty."""
    reward = task_reward(task)
    difficulty = estimate_task_difficulty(task)
    domain = classify_domain(task)
    diff_score = difficulty.get("score", 0)

    if reward_dist and reward_dist["count"] > 0:
        min_pool = reward_dist["bounty_min_pool"]
        max_amount = reward_dist["bounty_max_amount"]
        cost_ratio = reward_dist["bounty_cost_ratio"]
    else:
        min_pool = DEFAULT_HIGH_REWARD_THRESHOLD * 0.6
        max_amount = 500.0
        cost_ratio = DEFAULT_BOUNTY_COST_RATIO_BASE

    reasons_for: list[str] = []
    reasons_against: list[str] = []

    if reward < min_pool:
        reasons_against.append(f"pool_below_median ({reward} < {min_pool})")
    if diff_score < DEFAULT_BOUNTY_DIFFICULTY_THRESHOLD:
        reasons_against.append(f"difficulty_too_low_score_gain_minimal ({diff_score} < {DEFAULT_BOUNTY_DIFFICULTY_THRESHOLD})")
    if balance is not None and balance < reserve_balance * 1.5:
        reasons_against.append(f"balance_tight ({balance} < {reserve_balance * 1.5})")

    if diff_score >= 7:
        reasons_for.append("very_high_difficulty_large_score_gap")
    elif diff_score >= DEFAULT_BOUNTY_DIFFICULTY_THRESHOLD:
        reasons_for.append("medium_difficulty_moderate_score_gap")

    if reward_dist and reward >= reward_dist.get("p75", float("inf")):
        reasons_for.append("top_quartile_pool_high_marginal_value")
    elif reward >= DEFAULT_HIGH_REWARD_THRESHOLD:
        reasons_for.append("large_pool_justifies_investment")

    signals = difficulty.get("signals", [])
    if "calculation_or_proof" in signals:
        reasons_for.append("verification_could_prevent_scoring_errors")
    if "ambiguous_or_conflicting_prompt" in signals:
        reasons_for.append("external_check_reduces_wrong_answer_risk")
    if "time_sensitive" in signals:
        reasons_for.append("fact_verification_prevents_outdated_answer")

    should_bounty = bool(reasons_for) and not bool(reasons_against)

    if should_bounty:
        assumptions = (reward_dist or {}).get("assumptions", {})
        est_n = assumptions.get("est_participants", 10)
        expected_income = reward / est_n
        spend_ratio = 0.3 if diff_score < 7 else 0.4
        recommended_amount = min(expected_income * spend_ratio, max_amount)
        recommended_amount = max(50.0, round(recommended_amount / 10) * 10)
    else:
        recommended_amount = 0.0
        expected_income = reward / 10

    sub_question_hints = _generate_subquestion_hints(domain, difficulty)

    return {
        "should_bounty": should_bounty,
        "confidence": "high" if (diff_score >= 7 and reasons_for) else "medium",
        "recommended_amount": recommended_amount,
        "expected_income_if_average": round(expected_income, 1),
        "expected_net": round(expected_income - recommended_amount, 1) if should_bounty else round(expected_income, 1),
        "reasons_for": reasons_for,
        "reasons_against": reasons_against,
        "task_id": task_id(task),
        "pool_size": reward,
        "difficulty": difficulty,
        "domain": domain["label"],
        "sub_question_hints": sub_question_hints,
        "timing_advice": _bounty_timing_advice(diff_score),
        "thresholds_used": {
            "min_pool": min_pool,
            "max_amount": max_amount,
            "source": "distribution" if (reward_dist and reward_dist["count"] > 0) else "fallback",
        },
        "reward_model_note": "pool shared proportionally: income = your_score/sum_scores × pool; bounty improves score → larger share + better quality ranking",
    }


def _generate_subquestion_hints(
    domain: dict[str, Any],
    difficulty: dict[str, Any],
) -> list[str]:
    hints: list[str] = []
    signals = difficulty.get("signals", [])

    if "calculation_or_proof" in signals:
        hints.append("请验证以下计算/推导过程是否正确：[具体公式或步骤]")
    if "time_sensitive" in signals:
        hints.append("请查证以下事实的最新数据/状态：[具体事实点]")
    if "ambiguous_or_conflicting_prompt" in signals:
        hints.append("题目中存在矛盾信息，请帮忙确认哪个解读更合理：[列出矛盾点]")

    domain_name = domain.get("domain", "general")
    if domain_name == "medical":
        hints.append("请验证该临床指南/药物剂量/诊断标准的准确性")
    elif domain_name == "legal":
        hints.append("请确认该法规条款在指定司法辖区的适用性")
    elif domain_name == "economy":
        hints.append("请核实该经济数据/指标的最新数值和来源")
    elif domain_name == "science":
        hints.append("请验证该科学原理/公式/实验数据的正确性")
    elif domain_name == "industry":
        hints.append("请确认该工业标准/安全规范的具体参数")

    if not hints:
        hints.append("请帮忙验证我的推理中最不确定的1-2个关键点")
    return hints


def _bounty_timing_advice(diff_score: int) -> str:
    if diff_score >= 8:
        return "early (开市后立即发布，留足时间收集回复)"
    elif diff_score >= 6:
        return "mid (先自己尝试30分钟，卡住再发)"
    return "late (自己做完初版后发悬赏做验证)"


def evaluate_bounty_responses(
    responses: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Score and rank bounty responses, flagging likely NPC interference."""
    evaluated: list[dict[str, Any]] = []

    for resp in responses:
        content = _stringify({
            "content": resp.get("content"),
            "text": resp.get("text"),
            "body": resp.get("body"),
            "answer": resp.get("answer"),
        }).strip()
        content_lower = content.lower()

        quality_signals: list[str] = []
        npc_signals: list[str] = []
        score = 50

        if any(w in content_lower for w in ("因为", "根据", "来源", "source", "because", "according")):
            quality_signals.append("has_reasoning_or_source")
            score += 15
        if any(w in content_lower for w in ("计算", "公式", "=", "calculate", "formula")):
            quality_signals.append("has_calculation")
            score += 10
        if len(content) > 200:
            quality_signals.append("substantial_length")
            score += 5
        if any(w in content_lower for w in (".gov", ".org", ".edu", "官方", "标准")):
            quality_signals.append("cites_authority")
            score += 15

        if len(content) < 50:
            npc_signals.append("too_short_likely_noise")
            score -= 20
        if content_lower.count("可能") > 3 or content_lower.count("maybe") > 3:
            npc_signals.append("overly_hedged")
            score -= 10
        if any(w in content_lower for w in ("我不确定", "i'm not sure", "不太清楚")):
            npc_signals.append("low_confidence_filler")
            score -= 15
        if "但是" in content and "然而" in content and "不过" in content:
            npc_signals.append("self_contradicting")
            score -= 20

        evaluated.append({
            "response_id": resp.get("id") or resp.get("answer_id"),
            "author": resp.get("author") or resp.get("participant_id"),
            "score": max(0, min(100, score)),
            "quality_signals": quality_signals,
            "npc_signals": npc_signals,
            "likely_npc": len(npc_signals) >= 2,
            "recommendation": "adopt" if score >= 65 else "verify" if score >= 40 else "ignore",
            "excerpt": content[:300],
        })

    return sorted(evaluated, key=lambda x: x["score"], reverse=True)


# ============================================================================
# Bounty state persistence
# ============================================================================

_BOUNTY_STATE_FILE = ".studio-arena-bounty-state.json"


def _bounty_state_path() -> Path:
    return Path(_BOUNTY_STATE_FILE)


def load_bounty_state() -> dict[str, Any]:
    path = _bounty_state_path()
    if not path.exists():
        return {
            "stage_id": None,
            "reward_distribution": None,
            "round2_pending": [],
            "bounties_sent": [],
            "bounties_answered": [],
            "collaboration_count": 0,
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "stage_id": None,
            "reward_distribution": None,
            "round2_pending": [],
            "bounties_sent": [],
            "bounties_answered": [],
            "collaboration_count": 0,
        }


def save_bounty_state(state: dict[str, Any]) -> Path:
    path = _bounty_state_path()
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def record_bounty_sent(
    task_id_value: str,
    *,
    bounty_title: str,
    amount: float,
    draft_answer: str = "",
    sub_questions: Optional[list[str]] = None,
) -> dict[str, Any]:
    state = load_bounty_state()
    record = {
        "task_id": task_id_value,
        "bounty_title": bounty_title,
        "amount": amount,
        "draft_answer": draft_answer[:8000],
        "sub_questions": sub_questions or [],
        "status": "waiting",
        "created_at": int(import_time()),
    }
    state["bounties_sent"].append(record)
    save_bounty_state(state)
    return record


def record_bounty_answered(
    bounty_id: str,
    *,
    amount: float,
    domain: str = "",
) -> dict[str, Any]:
    state = load_bounty_state()
    record = {
        "bounty_id": bounty_id,
        "amount": amount,
        "domain": domain,
        "created_at": int(import_time()),
    }
    state["bounties_answered"].append(record)
    state["collaboration_count"] = state.get("collaboration_count", 0) + 1
    save_bounty_state(state)
    return record


def record_bounty_resolved(
    task_id_value: str,
    *,
    adopted_count: int = 0,
    npc_count: int = 0,
) -> dict[str, Any]:
    state = load_bounty_state()
    for record in state["bounties_sent"]:
        if record["task_id"] == task_id_value and record["status"] == "waiting":
            record["status"] = "resolved"
            record["adopted_count"] = adopted_count
            record["npc_count"] = npc_count
            break
    if adopted_count > 0:
        state["collaboration_count"] = state.get("collaboration_count", 0) + 1
    save_bounty_state(state)
    return state


def save_stage_snapshot(
    stage_id: str,
    reward_dist: dict[str, Any],
    round2_pending: list[dict[str, Any]],
) -> dict[str, Any]:
    state = load_bounty_state()
    state["stage_id"] = stage_id
    state["reward_distribution"] = reward_dist
    state["round2_pending"] = [
        {
            "task_id": t.get("task_id"),
            "title": t.get("title"),
            "reward": t.get("reward"),
            "difficulty_score": t.get("difficulty", {}).get("score"),
            "recommended_amount": t.get("bounty_decision", {}).get("recommended_amount"),
        }
        for t in round2_pending
    ]
    save_bounty_state(state)
    return state


def bounty_progress() -> dict[str, Any]:
    """Summary of bounty/collaboration progress."""
    state = load_bounty_state()
    waiting = [r for r in state.get("bounties_sent", []) if r.get("status") == "waiting"]
    resolved = [r for r in state.get("bounties_sent", []) if r.get("status") == "resolved"]
    return {
        "collaboration_count": state.get("collaboration_count", 0),
        "l2_goal_met": state.get("collaboration_count", 0) >= 2,
        "bounties_sent_total": len(state.get("bounties_sent", [])),
        "bounties_waiting": len(waiting),
        "bounties_resolved": len(resolved),
        "bounties_answered": len(state.get("bounties_answered", [])),
        "total_spent": sum(r.get("amount", 0) for r in state.get("bounties_sent", [])),
        "total_earned": sum(r.get("amount", 0) for r in state.get("bounties_answered", [])),
        "pending_tasks": [r.get("task_id") for r in waiting],
        "stage_id": state.get("stage_id"),
        "reward_distribution_cached": state.get("reward_distribution") is not None,
    }


def import_time() -> float:
    import time as _time
    return _time.time()
