"""Web search decision and query planning."""

from __future__ import annotations

from typing import Any, Optional

from .budget import DEFAULT_HIGH_REWARD_THRESHOLD
from .difficulty import estimate_task_difficulty
from .domain import (
    authoritative_sources_for_domain,
    classify_domain,
    extract_search_keywords,
    extract_task_text,
    task_reward,
    task_title,
)


def should_search_task(
    task_or_text: dict[str, Any] | str,
    *,
    reward: Optional[float] = None,
    difficulty: Optional[dict[str, Any]] = None,
    mode: str = "save",
    high_reward_threshold: float = DEFAULT_HIGH_REWARD_THRESHOLD,
) -> dict[str, Any]:
    domain = classify_domain(task_or_text)
    text = (
        extract_task_text(task_or_text)
        if isinstance(task_or_text, dict)
        else str(task_or_text)
    )
    text_lower = text.lower()
    reward_value = (
        task_reward(task_or_text) if isinstance(task_or_text, dict) else float(reward or 0)
    )
    difficulty_info = difficulty or (
        estimate_task_difficulty(task_or_text)
        if isinstance(task_or_text, dict)
        else {"score": 0, "signals": [], "level": "low"}
    )
    signals = list(difficulty_info.get("signals", []))
    reasons: list[str] = []

    high_risk_domain = domain["domain"] in {
        "economy", "medical", "legal", "industry", "science",
    }
    if high_risk_domain:
        reasons.append("specialized_or_high_risk_domain")
    if reward_value >= high_reward_threshold:
        reasons.append("high_reward")
    if difficulty_info.get("score", 0) >= 4:
        reasons.append("medium_or_high_difficulty")
    if any(
        marker in text_lower
        for marker in (
            "latest", "current", "today", "2025", "2026", "source",
            "citation", "standard", "regulation", "最新", "当前",
            "引用", "来源", "标准", "法规",
        )
    ):
        reasons.append("fact_sensitive_or_citation_needed")
    if any(signal in signals for signal in ("time_sensitive", "ambiguous_or_conflicting_prompt")):
        reasons.append("needs_verification")

    required = bool(reasons)
    if not required:
        tier = "skip"
        max_queries = 0
    elif mode == "relaxed" and (reward_value >= high_reward_threshold or difficulty_info.get("score", 0) >= 6):
        tier = "standard"
        max_queries = 5
    else:
        tier = "light"
        max_queries = 1 if mode == "save" else 2

    return {
        "required": required,
        "tier": tier,
        "max_queries": max_queries,
        "reasons": reasons or ["simple_low_risk_task"],
        "domain": domain,
    }


def build_websearch_plan(
    task_or_text: dict[str, Any] | str,
    *,
    mode: str = "save",
    max_queries: Optional[int] = None,
    difficulty: Optional[dict[str, Any]] = None,
    high_reward_threshold: float = DEFAULT_HIGH_REWARD_THRESHOLD,
) -> dict[str, Any]:
    domain = classify_domain(task_or_text)
    search_decision = should_search_task(
        task_or_text,
        difficulty=difficulty,
        mode=mode,
        high_reward_threshold=high_reward_threshold,
    )
    if not search_decision["required"]:
        return {
            "enabled": False,
            "execution": "skipped_to_save_tokens",
            "domain": domain,
            "mode": mode,
            "keywords": extract_search_keywords(task_or_text, limit=5),
            "authoritative_sources": authoritative_sources_for_domain(domain["domain"]),
            "queries": [],
            "search_tier": "skip",
            "search_reasons": search_decision["reasons"],
            "token_policy": "No web search for simple low-risk tasks; answer from the prompt and self-check.",
            "not_executed_by_cli": True,
        }

    keywords = extract_search_keywords(task_or_text)
    sources = authoritative_sources_for_domain(domain["domain"])
    query_budget = max_queries if max_queries is not None else search_decision["max_queries"]
    base_query = " ".join(keywords[:5]) or (
        task_title(task_or_text) if isinstance(task_or_text, dict) else str(task_or_text)[:120]
    )

    queries: list[dict[str, Any]] = []
    for source in sources[: max(1, query_budget)]:
        queries.append(
            {
                "query": f"{base_query} site:{source['domain']}",
                "domain": source["domain"],
                "reason": source["reason"],
            }
        )

    if domain["domain"] != "general" and len(queries) < query_budget:
        queries.append(
            {
                "query": f"{base_query} official source OR primary source",
                "domain": "cross-source",
                "reason": "Find an additional primary source for cross-checking",
            }
        )

    return {
        "enabled": True,
        "execution": "external_web_tool_required",
        "domain": domain,
        "mode": mode,
        "keywords": keywords,
        "authoritative_sources": sources,
        "queries": queries,
        "search_tier": search_decision["tier"],
        "search_reasons": search_decision["reasons"],
        "token_policy": (
            "Use only the listed authoritative-site queries; summarize evidence briefly."
        ),
        "source_policy": [
            "Prefer official, primary, government, standards, regulator, academic, or peer-reviewed sources.",
            "Use Agora comments and other participants only as leads, never as standalone evidence.",
            "Cross-check high-value or high-risk facts with at least two authoritative sources when possible.",
            "Record publication dates and jurisdiction/scope for time-sensitive, legal, medical, and financial facts.",
        ],
        "not_executed_by_cli": True,
    }
