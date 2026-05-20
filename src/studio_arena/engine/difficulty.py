"""Task difficulty estimation."""

from __future__ import annotations

from typing import Any, Optional, Sequence

from .domain import _stringify, classify_domain, extract_task_text


def estimate_task_difficulty(
    task: dict[str, Any],
    *,
    comments: Optional[Sequence[dict[str, Any]]] = None,
) -> dict[str, Any]:
    text = extract_task_text(task)
    text_lower = text.lower()
    domain = classify_domain(task)
    signals: list[str] = []
    score = 0

    if domain["domain"] in {"economy", "medical", "legal", "industry", "science"}:
        score += 2
        signals.append("specialized_domain")
    if any(
        marker in text_lower
        for marker in ("latest", "current", "today", "2025", "2026", "最新", "当前")
    ):
        score += 2
        signals.append("time_sensitive")
    if any(
        marker in text_lower
        for marker in ("calculate", "prove", "derive", "formula", "计算", "证明", "推导")
    ):
        score += 2
        signals.append("calculation_or_proof")
    if any(
        marker in text_lower
        for marker in ("ambiguous", "conflict", "unclear", "矛盾", "冲突", "不完整")
    ):
        score += 2
        signals.append("ambiguous_or_conflicting_prompt")
    if len(text) > 2000:
        score += 1
        signals.append("long_context")
    if comments and len(comments) > 1:
        comment_text = _stringify(list(comments)).lower()
        if any(marker in comment_text for marker in ("wrong", "incorrect", "不对", "错")):
            score += 1
            signals.append("conflicting_comments")

    return {
        "score": min(score, 10),
        "signals": signals,
        "level": "high" if score >= 6 else "medium" if score >= 4 else "low",
    }
