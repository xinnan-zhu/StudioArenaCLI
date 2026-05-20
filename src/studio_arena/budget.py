"""Local token-budget ledger for Studio Arena runs."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

DEFAULT_BUDGET_FILE = ".studio-arena-budget.json"
DEFAULT_FREE_TOKEN_BUDGET = 1_000_000
DEFAULT_TOKEN_COST_PER_MILLION = 2.0
DEFAULT_HIGH_REWARD_THRESHOLD = 1_000.0
DEFAULT_RESERVE_BALANCE = 5_000.0


def estimate_tokens(text: str) -> int:
    """Estimate mixed Chinese/English token use without external dependencies."""
    normalized = text.strip()
    if not normalized:
        return 0

    ascii_chars = sum(1 for char in normalized if ord(char) < 128)
    non_ascii_chars = len(normalized) - ascii_chars
    return max(1, round(ascii_chars / 4 + non_ascii_chars * 1.2))


def budget_path(path: Optional[str] = None) -> Path:
    return Path(path or os.environ.get("ARENA_BUDGET_FILE") or DEFAULT_BUDGET_FILE)


def load_ledger(path: Optional[str] = None) -> dict[str, Any]:
    resolved = budget_path(path)
    if not resolved.exists():
        return {
            "free_token_budget": DEFAULT_FREE_TOKEN_BUDGET,
            "token_cost_per_million": DEFAULT_TOKEN_COST_PER_MILLION,
            "records": [],
        }

    with resolved.open("r", encoding="utf-8") as file:
        data = json.load(file)
    data.setdefault("free_token_budget", DEFAULT_FREE_TOKEN_BUDGET)
    data.setdefault("token_cost_per_million", DEFAULT_TOKEN_COST_PER_MILLION)
    data.setdefault("records", [])
    return data


def save_ledger(data: dict[str, Any], path: Optional[str] = None) -> Path:
    resolved = budget_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return resolved


def record_budget(
    task_id: str,
    *,
    estimated_tokens: int,
    actual_tokens: Optional[int] = None,
    reward: Optional[float] = None,
    mode: str = "save",
    note: str = "",
    path: Optional[str] = None,
) -> dict[str, Any]:
    ledger = load_ledger(path)
    record = {
        "task_id": task_id,
        "estimated_tokens": int(estimated_tokens),
        "actual_tokens": int(actual_tokens) if actual_tokens is not None else None,
        "reward": float(reward) if reward is not None else None,
        "mode": mode,
        "note": note,
        "created_at": int(time.time()),
    }
    ledger["records"].append(record)
    save_ledger(ledger, path)
    return record


def summarize_budget(path: Optional[str] = None) -> dict[str, Any]:
    ledger = load_ledger(path)
    records = ledger["records"]
    used_tokens = sum(
        int(record.get("actual_tokens") or record.get("estimated_tokens") or 0)
        for record in records
    )
    estimated_tokens = sum(int(record.get("estimated_tokens") or 0) for record in records)
    actual_tokens = sum(int(record.get("actual_tokens") or 0) for record in records)
    reward = sum(float(record.get("reward") or 0) for record in records)
    free_budget = int(ledger.get("free_token_budget", DEFAULT_FREE_TOKEN_BUDGET))
    cost_per_million = float(
        ledger.get("token_cost_per_million", DEFAULT_TOKEN_COST_PER_MILLION)
    )
    billable_tokens = max(0, used_tokens - free_budget)
    token_cost = billable_tokens / 1_000_000 * cost_per_million

    return {
        "records": len(records),
        "estimated_tokens": estimated_tokens,
        "actual_tokens": actual_tokens,
        "used_tokens": used_tokens,
        "free_token_budget": free_budget,
        "token_cost_per_million": cost_per_million,
        "billable_tokens": billable_tokens,
        "token_cost": round(token_cost, 6),
        "reward": round(reward, 6),
        "net_reward_after_token_cost": round(reward - token_cost, 6),
        "path": str(budget_path(path)),
    }


def budget_advice(
    *,
    estimated_tokens: int,
    reward: Optional[float] = None,
    balance: Optional[float] = None,
    high_reward_threshold: float = DEFAULT_HIGH_REWARD_THRESHOLD,
    reserve_balance: float = DEFAULT_RESERVE_BALANCE,
    path: Optional[str] = None,
) -> dict[str, Any]:
    summary = summarize_budget(path)
    free_remaining = max(
        0, int(summary["free_token_budget"]) - int(summary["used_tokens"])
    )
    reward_value = float(reward or 0)
    estimated_cost = (
        max(0, int(estimated_tokens) - free_remaining)
        / 1_000_000
        * float(summary["token_cost_per_million"])
    )

    high_value = reward_value >= high_reward_threshold
    low_balance = balance is not None and float(balance) < reserve_balance
    if high_value and not low_balance:
        mode = "relaxed"
        reason = "reward is high enough to justify extra checking"
    elif low_balance:
        mode = "save"
        reason = "balance is below reserve, avoid bounty and long reasoning"
    else:
        mode = "save"
        reason = "default mode keeps token cost low"

    return {
        "mode": mode,
        "reason": reason,
        "estimated_tokens": int(estimated_tokens),
        "free_tokens_remaining": free_remaining,
        "estimated_extra_token_cost": round(estimated_cost, 6),
        "reward": reward_value if reward is not None else None,
        "balance": float(balance) if balance is not None else None,
        "high_reward_threshold": high_reward_threshold,
        "reserve_balance": reserve_balance,
    }
