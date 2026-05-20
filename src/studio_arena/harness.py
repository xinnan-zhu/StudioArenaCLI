"""Studio Arena harness planning and Synergy automation support.

The Python harness prepares decisions for Synergy without performing write
actions. In default review mode, submitting answers, creating bounties, and
writing Agora comments require confirmation. Explicit autonomous writes are
handled by the Synergy plugin tools, which call the existing write-capable CLI
commands after the user opts into full-auto mode.
"""

from __future__ import annotations

import json as _json_mod
import re
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from .budget import (
    DEFAULT_HIGH_REWARD_THRESHOLD,
    DEFAULT_RESERVE_BALANCE,
    budget_advice,
    estimate_tokens,
    summarize_budget,
)

DOMAIN_RULES: dict[str, dict[str, Any]] = {
    "economy": {
        "label": "经济",
        "keywords": [
            "finance",
            "financial",
            "economy",
            "economic",
            "market",
            "revenue",
            "profit",
            "price",
            "cost",
            "investment",
            "gdp",
            "inflation",
            "金融",
            "经济",
            "市场",
            "收入",
            "利润",
            "价格",
            "成本",
            "投资",
            "通胀",
        ],
        "focus": "Define metric scope, cite data, state assumptions, sensitivity, and risk.",
    },
    "medical": {
        "label": "医疗",
        "keywords": [
            "medical",
            "medicine",
            "clinical",
            "patient",
            "diagnosis",
            "treatment",
            "drug",
            "disease",
            "symptom",
            "trial",
            "医学",
            "医疗",
            "临床",
            "患者",
            "诊断",
            "治疗",
            "药物",
            "疾病",
            "症状",
        ],
        "focus": "Avoid diagnosis, use authoritative evidence, and mark population limits.",
    },
    "legal": {
        "label": "法律",
        "keywords": [
            "law",
            "legal",
            "court",
            "contract",
            "regulation",
            "statute",
            "liability",
            "compliance",
            "jurisdiction",
            "法律",
            "法院",
            "合同",
            "法规",
            "条例",
            "责任",
            "合规",
            "司法辖区",
        ],
        "focus": "State jurisdiction, time, rule source, uncertainty, and non-advice limits.",
    },
    "industry": {
        "label": "工业",
        "keywords": [
            "industrial",
            "manufacturing",
            "factory",
            "process",
            "equipment",
            "safety",
            "engineering",
            "production",
            "工厂",
            "工业",
            "制造",
            "工艺",
            "设备",
            "安全",
            "工程",
            "生产",
        ],
        "focus": "Cover process, parameters, constraints, safety limits, and verification.",
    },
    "science": {
        "label": "自然科学",
        "keywords": [
            "physics",
            "chemistry",
            "biology",
            "scientific",
            "experiment",
            "formula",
            "model",
            "hypothesis",
            "data",
            "物理",
            "化学",
            "生物",
            "科学",
            "实验",
            "公式",
            "模型",
            "假设",
        ],
        "focus": "Name model, formula, evidence, uncertainty, and boundary conditions.",
    },
    "general": {
        "label": "通用推理",
        "keywords": [],
        "focus": "Break down the task, state assumptions, reason stepwise, and self-check.",
    },
}

FOLLOWUP_KEYWORDS = [
    "追问",
    "补充",
    "解释",
    "为什么",
    "不对",
    "错误",
    "修正",
    "clarify",
    "follow up",
    "revise",
    "wrong",
    "incorrect",
    "explain",
    "why",
    "?",
    "？",
]

REWARD_KEYS = (
    "reward",
    "reward_amount",
    "bounty_amount",
    "amount",
    "points",
    "score_reward",
    "max_reward",
)

SCORE_KEYS = (
    "score",
    "final_score",
    "rubric_score",
    "quality_score",
    "grade",
)

AUTHORITATIVE_SOURCES: dict[str, list[dict[str, str]]] = {
    "economy": [
        {"domain": "worldbank.org", "reason": "World Bank macroeconomic and development data"},
        {"domain": "imf.org", "reason": "IMF country reports and financial statistics"},
        {"domain": "oecd.org", "reason": "OECD economic indicators and policy reports"},
        {"domain": "fred.stlouisfed.org", "reason": "Federal Reserve economic time series"},
        {"domain": "sec.gov", "reason": "Official public company filings"},
        {"domain": "bls.gov", "reason": "US labor and price statistics"},
    ],
    "medical": [
        {"domain": "who.int", "reason": "WHO public health guidance"},
        {"domain": "nih.gov", "reason": "US National Institutes of Health resources"},
        {"domain": "ncbi.nlm.nih.gov", "reason": "PubMed and biomedical literature records"},
        {"domain": "cdc.gov", "reason": "US disease and public health guidance"},
        {"domain": "fda.gov", "reason": "Drug, device, and safety regulatory source"},
        {"domain": "cochranelibrary.com", "reason": "Systematic reviews and evidence summaries"},
    ],
    "legal": [
        {"domain": "congress.gov", "reason": "US federal legislation"},
        {"domain": "govinfo.gov", "reason": "Official US government publications"},
        {"domain": "ecfr.gov", "reason": "Electronic Code of Federal Regulations"},
        {"domain": "justice.gov", "reason": "US Department of Justice source"},
        {"domain": "law.cornell.edu", "reason": "Legal Information Institute statutes and cases"},
        {"domain": "supreme.justia.com", "reason": "US Supreme Court opinions"},
    ],
    "industry": [
        {"domain": "nist.gov", "reason": "US standards, measurements, and technical guidance"},
        {"domain": "osha.gov", "reason": "Workplace safety rules and guidance"},
        {"domain": "energy.gov", "reason": "US energy and industrial technology sources"},
        {"domain": "iso.org", "reason": "International standards references"},
        {"domain": "ieee.org", "reason": "Engineering standards and technical references"},
        {"domain": "asme.org", "reason": "Mechanical engineering standards body"},
    ],
    "science": [
        {"domain": "nasa.gov", "reason": "Space science and aeronautics primary source"},
        {"domain": "noaa.gov", "reason": "Climate, ocean, and atmospheric data"},
        {"domain": "usgs.gov", "reason": "Earth science and geospatial data"},
        {"domain": "nist.gov", "reason": "Measurement science and reference data"},
        {"domain": "ncbi.nlm.nih.gov", "reason": "Life science literature and databases"},
        {"domain": "arxiv.org", "reason": "Preprint discovery; verify against peer-reviewed sources"},
    ],
    "general": [
        {"domain": "gov", "reason": "Official government sources"},
        {"domain": "edu", "reason": "University and research institution sources"},
        {"domain": "wikipedia.org", "reason": "Orientation only; follow citations to primary sources"},
    ],
}

SEARCH_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "your",
    "about",
    "请",
    "分析",
    "解释",
    "比较",
    "回答",
    "说明",
    "什么",
    "如何",
    "为什么",
}


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(_stringify(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_stringify(v) for v in value)
    return str(value)


def _first_number(mapping: dict[str, Any], keys: Sequence[str]) -> Optional[float]:
    for key in keys:
        if key not in mapping:
            continue
        value = mapping.get(key)
        if isinstance(value, dict):
            nested = _first_number(value, keys)
            if nested is not None:
                return nested
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_text(mapping: dict[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def task_id(task: dict[str, Any]) -> str:
    return _first_text(task, ("task_id", "id", "uid")) or "unknown-task"


def task_title(task: dict[str, Any]) -> str:
    return _first_text(task, ("title", "name", "summary")) or task_id(task)


def task_reward(task: dict[str, Any]) -> float:
    return _first_number(task, REWARD_KEYS) or 0.0


def answer_score(answer: dict[str, Any]) -> Optional[float]:
    return _first_number(answer, SCORE_KEYS)


def looks_answered(answer: Any) -> bool:
    if not isinstance(answer, dict) or not answer:
        return False
    if isinstance(answer.get("data"), dict):
        return looks_answered(answer["data"])
    answer_markers = (
        "answer",
        "answer_text",
        "text",
        "content",
        "submitted_at",
        "created_at",
        "updated_at",
        "score",
        "final_score",
        "rubric_score",
        "status",
    )
    return any(answer.get(key) not in (None, "", [], {}) for key in answer_markers)


def extract_task_text(task: dict[str, Any]) -> str:
    keys = (
        "title",
        "name",
        "summary",
        "description",
        "prompt",
        "question",
        "content",
        "body",
        "text",
        "requirements",
    )
    parts: list[str] = []
    for key in keys:
        value = task.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{key}: {value.strip()}")

    post = task.get("agora_post")
    if isinstance(post, dict):
        for key in keys:
            value = post.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(f"agora_{key}: {value.strip()}")

    return "\n".join(parts) or _stringify(task)


def classify_domain(task_or_text: dict[str, Any] | str) -> dict[str, Any]:
    text = (
        extract_task_text(task_or_text)
        if isinstance(task_or_text, dict)
        else str(task_or_text)
    )
    text_lower = text.lower()
    matches: dict[str, list[str]] = {}
    scores: dict[str, int] = {}

    for domain, rule in DOMAIN_RULES.items():
        if domain == "general":
            continue
        found = [
            keyword
            for keyword in rule["keywords"]
            if keyword.lower() in text_lower
        ]
        matches[domain] = found
        scores[domain] = len(found)

    best_domain = max(scores, key=scores.get, default="general")
    if scores.get(best_domain, 0) == 0:
        best_domain = "general"

    rule = DOMAIN_RULES[best_domain]
    return {
        "domain": best_domain,
        "label": rule["label"],
        "score": scores.get(best_domain, 0),
        "matched_keywords": matches.get(best_domain, []),
        "template_focus": rule["focus"],
    }


def extract_search_keywords(task_or_text: dict[str, Any] | str, limit: int = 8) -> list[str]:
    text = (
        extract_task_text(task_or_text)
        if isinstance(task_or_text, dict)
        else str(task_or_text)
    )
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9.-]{2,}|[\u4e00-\u9fff]{2,}", text)
    seen: set[str] = set()
    keywords: list[str] = []
    for token in tokens:
        normalized = token.lower()
        if normalized in SEARCH_STOPWORDS or normalized in seen:
            continue
        seen.add(normalized)
        keywords.append(token)
        if len(keywords) >= limit:
            break
    return keywords


def authoritative_sources_for_domain(domain: str) -> list[dict[str, str]]:
    return AUTHORITATIVE_SOURCES.get(domain, AUTHORITATIVE_SOURCES["general"])


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
        "economy",
        "medical",
        "legal",
        "industry",
        "science",
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
            "latest",
            "current",
            "today",
            "2025",
            "2026",
            "source",
            "citation",
            "standard",
            "regulation",
            "最新",
            "当前",
            "引用",
            "来源",
            "标准",
            "法规",
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


def answer_template(domain: str) -> dict[str, Any]:
    rule = DOMAIN_RULES.get(domain, DOMAIN_RULES["general"])
    return {
        "domain": domain,
        "label": rule["label"],
        "focus": rule["focus"],
        "sections": ["结论", "依据", "推理与计算", "验证", "风险与假设"],
    }


def detect_followups(comments: Optional[Sequence[dict[str, Any]]]) -> dict[str, Any]:
    found: list[dict[str, Any]] = []
    for comment in comments or []:
        content = _stringify(
            {
                "content": comment.get("content"),
                "text": comment.get("text"),
                "body": comment.get("body"),
            }
        ).strip()
        content_lower = content.lower()
        matched = [
            keyword
            for keyword in FOLLOWUP_KEYWORDS
            if keyword.lower() in content_lower
        ]
        if matched:
            found.append(
                {
                    "id": comment.get("id") or comment.get("comment_id"),
                    "matched_keywords": matched,
                    "excerpt": content[:240],
                }
            )

    return {"has_followups": bool(found), "items": found, "count": len(found)}


def _answer_identity_values(answer: Any) -> set[str]:
    if not isinstance(answer, dict):
        return set()
    values = set()
    for key in ("id", "answer_id", "task_answer_id", "agora_answer_id"):
        value = answer.get(key)
        if value not in (None, "", [], {}):
            values.add(_stringify(value))
    data = answer.get("data")
    if isinstance(data, dict):
        values |= _answer_identity_values(data)
    return values


def select_answer_comments(
    comments: Sequence[dict[str, Any]],
    my_answer: Any,
) -> dict[str, Any]:
    """Select comments that likely apply to the user's answer.

    Agora schemas may differ by deployment. Prefer explicit parent_id matches
    when my-answer exposes an answer id; otherwise keep answer-parent comments,
    and finally fall back to all comments so revision still has context.
    """

    answer_ids = _answer_identity_values(my_answer)
    explicit: list[dict[str, Any]] = []
    answer_parent: list[dict[str, Any]] = []
    followup_like: list[dict[str, Any]] = []

    for comment in comments:
        parent_id = _stringify(comment.get("parent_id") or comment.get("reply_to_id"))
        parent_type = _stringify(comment.get("parent_type") or comment.get("parent")).lower()
        if answer_ids and parent_id in answer_ids:
            explicit.append(comment)
            continue
        if parent_type == "answer":
            answer_parent.append(comment)
            continue
        content = _stringify(
            {
                "content": comment.get("content"),
                "text": comment.get("text"),
                "body": comment.get("body"),
            }
        ).lower()
        if any(keyword.lower() in content for keyword in FOLLOWUP_KEYWORDS):
            followup_like.append(comment)

    if explicit:
        selected = explicit
        reason = "matched_my_answer_parent_id"
    elif answer_parent:
        selected = answer_parent
        reason = "answer_parent_comments_without_my_answer_id"
    elif followup_like:
        selected = followup_like
        reason = "followup_like_comments"
    else:
        selected = list(comments)
        reason = "fallback_all_post_comments"

    return {
        "selected": selected,
        "selection_reason": reason,
        "selected_count": len(selected),
        "total_comments_seen": len(comments),
        "my_answer_ids": sorted(answer_ids),
    }


def analyze_revision_comments(comments: Sequence[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    category_keywords = {
        "correction": ("wrong", "incorrect", "不对", "错误", "错了", "修正"),
        "missing_evidence": ("source", "citation", "evidence", "依据", "来源", "引用", "证明"),
        "calculation": ("calculate", "formula", "unit", "计算", "公式", "单位", "推导"),
        "completeness": ("missing", "incomplete", "补充", "遗漏", "没有回答", "展开"),
        "clarification": ("why", "clarify", "explain", "为什么", "解释", "澄清"),
        "format": ("format", "structure", "格式", "结构"),
    }

    for comment in comments:
        content = _stringify(
            {
                "content": comment.get("content"),
                "text": comment.get("text"),
                "body": comment.get("body"),
            }
        ).strip()
        content_lower = content.lower()
        categories = [
            category
            for category, keywords in category_keywords.items()
            if any(keyword in content_lower for keyword in keywords)
        ]
        if not categories and content:
            categories = ["general_feedback"]
        if content:
            items.append(
                {
                    "comment_id": comment.get("id") or comment.get("comment_id"),
                    "parent_type": comment.get("parent_type"),
                    "parent_id": comment.get("parent_id"),
                    "categories": categories,
                    "excerpt": content[:300],
                    "revision_instruction": (
                        "Treat this as feedback to verify and integrate into the full answer, "
                        "not as a standalone comment reply."
                    ),
                }
            )

    return {
        "requires_full_answer_regeneration": bool(items),
        "comment_reply_is_secondary": True,
        "final_output_must_be_complete_answer": True,
        "items": items,
        "summary": {
            "comment_count": len(items),
            "categories": sorted({category for item in items for category in item["categories"]}),
        },
    }


def build_revision_prompt(
    task: dict[str, Any],
    domain: dict[str, Any],
    previous_answer: Any,
    comment_analysis: dict[str, Any],
) -> str:
    tid = task_id(task)
    saved_ctx = load_answer_context(tid)

    if saved_ctx:
        previous_answer_text = saved_ctx.get("answer_text", "")[:6000]
        reasoning_ctx = saved_ctx.get("reasoning", "")
        search_ctx = saved_ctx.get("search_results", [])
    else:
        previous_answer_text = _stringify(previous_answer).strip()[:6000]
        reasoning_ctx = ""
        search_ctx = []

    comment_lines = []
    for item in comment_analysis["items"]:
        categories = ", ".join(item["categories"])
        comment_lines.append(f"- [{categories}] {item['excerpt']}")
    comments_text = "\n".join(comment_lines) or "- 暂无明确 comments；仍需完整自检。"

    context_block = ""
    if reasoning_ctx:
        context_block += f"\n【原始推理过程】\n{reasoning_ctx[:3000]}\n"
    if search_ctx:
        search_summary = "\n".join(
            f"- {r.get('query', '')}: {r.get('result', r.get('summary', ''))[:200]}"
            for r in search_ctx[:5]
        )
        context_block += f"\n【原始搜索结果摘要】\n{search_summary}\n"

    return (
        "收到对我答案的实质性反馈，需要针对性修订。\n"
        "最终回复必须是可独立评分的完整答案，而不是片段补充或只回答评论的问题。\n"
        "原则：保留原答案中正确的部分，只修改反馈指出的问题；即使只是格式、澄清或一般追问，也要输出完整独立答案。\n\n"
        f"领域：{domain['label']}；答题重点：{domain['template_focus']}。\n\n"
        f"我的原答案（完整）：\n{previous_answer_text}\n\n"
        f"{context_block}"
        f"收到的反馈：\n{comments_text}\n\n"
        "修订要求：\n"
        "1. 判断每条反馈是否有效。\n"
        "2. 对有效反馈：在原答案基础上修正对应部分（补数据、改计算、补子问）。\n"
        "3. 对无效/误导性反馈：保持原答案不变，在验证部分说明为什么不采纳。\n"
        "4. 输出修订后的完整独立答案，格式仍为：结论、依据、推理与计算、验证、风险与假设。\n"
        "5. 保留原答案中正确且不受影响的部分，不要重新措辞或扩写。\n"
    )


def build_answer_revision_packet(
    task: dict[str, Any],
    *,
    my_answer: Any,
    comments: Optional[Sequence[dict[str, Any]]] = None,
    balance: Optional[float] = None,
    ledger_file: Optional[str] = None,
    high_reward_threshold: float = DEFAULT_HIGH_REWARD_THRESHOLD,
) -> dict[str, Any]:
    selected = select_answer_comments(list(comments or []), my_answer)
    answer_comments = selected["selected"]
    base_packet = build_review_packet(
        task,
        balance=balance,
        comments=answer_comments,
        ledger_file=ledger_file,
        high_reward_threshold=high_reward_threshold,
    )
    comment_analysis = analyze_revision_comments(answer_comments)
    revision_prompt = build_revision_prompt(
        task,
        base_packet["domain"],
        my_answer,
        comment_analysis,
    )
    base_packet.update(
        {
            "trigger": "Answer comments 完整答案修订",
            "revision_mode": "full_answer_regeneration",
            "must_regenerate_complete_answer": True,
            "final_output_must_be_complete_answer": True,
            "output_target": "agora_create_comment (not submit_task_answer)",
            "must_load_saved_context": True,
            "previous_answer": my_answer,
            "answer_comment_selection": {
                key: value
                for key, value in selected.items()
                if key != "selected"
            },
            "answer_comments": answer_comments,
            "comment_analysis": comment_analysis,
            "recommended_action": "regenerate_complete_answer_post_as_comment",
            "revision_packet": {
                "revision_prompt": revision_prompt,
                "full_answer_sections": [
                    "结论",
                    "依据",
                    "推理与计算",
                    "验证",
                    "风险与假设",
                ],
                "must_integrate_comments": True,
                "must_be_standalone_answer": True,
                "do_not_only_reply_to_comments": True,
                "comment_reply_is_never_final_output": True,
                "comment_reply_must_contain_complete_answer": True,
                "output_via": "agora_create_comment",
                "do_not_use_submit_task_answer": True,
                "must_load_saved_context_first": True,
            },
        }
    )
    return base_packet


def build_review_packet(
    task: dict[str, Any],
    *,
    balance: Optional[float] = None,
    comments: Optional[Sequence[dict[str, Any]]] = None,
    ledger_file: Optional[str] = None,
    high_reward_threshold: float = DEFAULT_HIGH_REWARD_THRESHOLD,
    reserve_balance: float = DEFAULT_RESERVE_BALANCE,
) -> dict[str, Any]:
    text = extract_task_text(task)
    domain = classify_domain(task)
    difficulty = estimate_task_difficulty(task, comments=comments)
    reward = task_reward(task)
    estimated_tokens = max(800, estimate_tokens(text) + 1200)
    advice = budget_advice(
        estimated_tokens=estimated_tokens,
        reward=reward,
        balance=balance,
        high_reward_threshold=high_reward_threshold,
        reserve_balance=reserve_balance,
        path=ledger_file,
    )
    search_plan = build_websearch_plan(
        task,
        mode=advice["mode"],
        difficulty=difficulty,
        high_reward_threshold=high_reward_threshold,
    )
    low_balance = balance is not None and balance < reserve_balance
    bounty_info = bounty_decision(
        task,
        balance=balance,
        reserve_balance=reserve_balance,
    )
    should_consider_bounty = bounty_info["should_bounty"]
    followups = detect_followups(comments)

    return {
        "task_id": task_id(task),
        "title": task_title(task),
        "reward": reward,
        "domain": domain,
        "difficulty": difficulty,
        "budget": advice,
        "websearch": search_plan,
        "followups": followups,
        "answer_template": answer_template(domain["domain"]),
        "recommended_action": (
            "consider_bounty_after_review"
            if should_consider_bounty
            else "draft_answer_for_review"
        ),
        "bounty_allowed": should_consider_bounty,
        "bounty_decision": bounty_info,
        "human_review_required": True,
        "autonomous_mode_available_via_plugin": True,
        "autonomous_mode_requires_explicit_user_trigger": True,
        "write_actions_blocked_until_review": [
            "submit_answer",
            "create_bounty",
            "create_agora_comment",
        ],
        "review_packet": {
            "must_show_before_write": [
                "task_summary",
                "domain",
                "reward",
                "budget",
                "draft_answer",
                "risk_points",
                "recommended_action",
            ],
            "draft_prompt": build_draft_prompt(task, domain, difficulty),
            "risk_points": build_risk_points(task, difficulty, followups, low_balance),
        },
    }


def build_draft_prompt(
    task: dict[str, Any],
    domain: dict[str, Any],
    difficulty: dict[str, Any],
) -> str:
    text = extract_task_text(task)

    base = (
        "你是该领域的资深专家。请严格按照以下步骤回答题目，每一步都必须写出来：\n\n"
        f"【完整题目】\n{text}\n\n"
        f"【领域】{domain.get('label', '')}\n"
        f"【答题重点】{domain.get('template_focus', '')}\n\n"
        "【长度控制——评分是 rubric-based，维度覆盖优先】\n"
        "- 简单题：800-2500 字符。复杂题：2000-4000 字符。绝不超过 5000 字符。\n"
        "- 维度覆盖优先：先确保每个评分维度都有实质内容覆盖。\n"
        "- 覆盖后用具体计算、参数约束、因果链、边界条件充实深度，不铺泛泛背景。\n"
        "- 删除：背景介绍、重述题目、废话填充、重复表述、多余总结。\n\n"
        "【强制步骤——必须按顺序逐步写出】\n\n"
        "Step 1 - 识别题目要求：列出题目的所有子问题/要求（用编号列出）。\n\n"
        "Step 2 - 关键信息提取：从题面中提取解题所需的关键数据、约束、条件。\n\n"
        "Step 3 - 逐个子问题求解：\n"
        "  对每个子问题，写出：\n"
        "  - 适用的规则/公式/原理\n"
        "  - 代入数据和计算过程（如有）\n"
        "  - 该子问题的结论\n\n"
        "Step 4 - 综合结论：基于所有子问题的结果，给出最终明确答案。\n\n"
        "Step 5 - 自检：检查答案是否完整回答了 Step 1 列出的所有要求，单位/量纲是否正确。\n\n"
        "【输出格式——简洁精准，不要水字数】\n"
        "# 结论\n"
        "（1-3 句话，直接给最终答案）\n\n"
        "## 依据\n"
        "（2-5 条关键事实/规则，每条一句话）\n\n"
        "## 推理与计算\n"
        "（只写关键步骤，不要堆砌教科书内容）\n\n"
        "## 验证\n"
        "（1-3 句：答案与题面一致性）\n\n"
        "## 风险与假设\n"
        "（1-3 条不确定性）\n\n"
        "【禁止事项】\n"
        '- 不要写"这个问题很复杂"之类的废话\n'
        "- 不要回避给出具体答案\n"
        "- 不要在没有推理的情况下直接给结论\n"
        "- 不要堆砌与题目无关的背景知识\n"
        "- 不要写超过 5000 字符\n"
    )

    if difficulty.get("level") == "high":
        base += (
            "\n【高难度补充指令】\n"
            "- 如果信息不足以确定唯一答案，选最可能的解释并明确说明为什么排除其他\n"
            "- 如果需要假设，先声明假设再基于假设推理\n"
            "- 涉及数值时给出区间或量级估计，不要只说'取决于具体情况'\n"
        )

    return base


def build_risk_points(
    task: dict[str, Any],
    difficulty: dict[str, Any],
    followups: dict[str, Any],
    low_balance: bool,
) -> list[str]:
    risks: list[str] = []
    if difficulty["signals"]:
        risks.append("difficulty_signals: " + ", ".join(difficulty["signals"]))
    if followups["has_followups"]:
        risks.append("agora_followups_detected")
    if low_balance:
        risks.append("balance_below_reserve_do_not_create_bounty")
    if task.get("agora_post_error"):
        risks.append("agora_post_load_failed")
    if not risks:
        risks.append("standard_self_check_required")
    return risks


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
    """Split tasks into self-doable vs bounty-candidate batches.

    First analyzes the reward distribution of all tasks to calibrate
    dynamic thresholds, then classifies each task.

    Round 1 (solo): tasks agent can handle alone (low/medium difficulty).
    Round 2 (pending): harder tasks where user decides solo vs bounty.
    """
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
            "submit_answer",
            "create_bounty",
            "create_agora_comment",
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
        except Exception as exc:  # pragma: no cover - defensive API fallback
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
        except Exception as exc:  # pragma: no cover - defensive API fallback
            task["agora_comments_error"] = str(exc)
    try:
        my_answer = await client.get_my_task_answer(task_id_value)
    except Exception as exc:  # pragma: no cover - defensive API fallback
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
        except Exception as exc:  # pragma: no cover - defensive API fallback
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


# ============================================================================
# Bounty / subcontracting decision engine
# ============================================================================

DEFAULT_BOUNTY_DIFFICULTY_THRESHOLD = 5
DEFAULT_BOUNTY_COST_RATIO_BASE = 0.20


def analyze_reward_distribution(
    tasks: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze reward POOL distribution of all tasks in the current stage.

    Important: Each task has a reward POOL shared proportionally among all
    participants based on relative score. The actual reward you receive is:
        your_score / sum_of_all_scores × pool

    This means:
    - Not answering = guaranteed 0 (always worse than a mediocre answer)
    - Bounty ROI = (score_gain × pool / est_total_scores) - bounty_cost
    - High pool tasks benefit most from score improvement via bounty
    """
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

    # Dynamic thresholds:
    # - bounty_min_pool: only bounty tasks whose pool >= p50 (top half worth investing)
    # - bounty_max_amount: based on expected income from that task
    #   Expected income per task ≈ pool / N_participants (if average)
    #   Bounty should be < 50% of expected income (ensure positive ROI)
    #   PLUS: quality score (50% of final ranking) also benefits from higher rubric score,
    #   so the real value of bounty > pure financial return
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
    """Decide whether to subcontract part of a task via bounty.

    Key insight: rewards are PROPORTIONAL to relative score.
    Bounty ROI = (score_gain / total_scores) × pool - bounty_cost.
    So bounty is worth it when:
    1. The pool is large (high reward task)
    2. The expected score gain from bounty is significant
    3. The bounty cost is less than the expected marginal revenue
    """
    reward = task_reward(task)  # This is the POOL size, not what you'll get
    difficulty = estimate_task_difficulty(task)
    domain = classify_domain(task)
    diff_score = difficulty.get("score", 0)

    # Use distribution-based thresholds when available
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

    # Gate: pool too small → marginal gain from better score not worth bounty cost
    if reward < min_pool:
        reasons_against.append(f"pool_below_median ({reward} < {min_pool})")
    if diff_score < DEFAULT_BOUNTY_DIFFICULTY_THRESHOLD:
        reasons_against.append(f"difficulty_too_low_score_gain_minimal ({diff_score} < {DEFAULT_BOUNTY_DIFFICULTY_THRESHOLD})")
    if balance is not None and balance < reserve_balance * 1.5:
        reasons_against.append(f"balance_tight ({balance} < {reserve_balance * 1.5})")

    # Positive: high difficulty means score gap between solo vs bounty-assisted is large
    if diff_score >= 7:
        reasons_for.append("very_high_difficulty_large_score_gap")
    elif diff_score >= DEFAULT_BOUNTY_DIFFICULTY_THRESHOLD:
        reasons_for.append("medium_difficulty_moderate_score_gap")

    # Large pool amplifies marginal score gains
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

    # Amount: based on expected income from this task
    # Expected income (if average) = pool / N_participants
    # Bounty investment should be a fraction of expected income
    if should_bounty:
        assumptions = (reward_dist or {}).get("assumptions", {})
        est_n = assumptions.get("est_participants", 10)
        expected_income = reward / est_n
        # Spend up to 30-40% of expected income on bounty (quality score benefit justifies)
        # Higher difficulty = more score gap = higher fraction worthwhile
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
# Bounty state persistence — track across sessions
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
        return _json_mod.loads(path.read_text(encoding="utf-8"))
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
        _json_mod.dumps(state, ensure_ascii=False, indent=2),
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
    """Record that we sent a bounty for a task. Persists draft answer for later integration."""
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
    """Record that we answered someone else's bounty (income tracking)."""
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
    """Mark a sent bounty as resolved (responses processed)."""
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
    """Cache the stage analysis so later steps don't re-compute."""
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
    """Summary of bounty/collaboration progress (for L2 tracking)."""
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


# ============================================================================
# Answer context persistence — save reasoning on submit, reload on revise
# ============================================================================

_CONTEXT_DIR = Path(__file__).resolve().parent.parent.parent / ".studio-arena-answers"

_MIN_ANSWER_LENGTH = 200


def _context_path(task_id_value: str) -> Path:
    return Path(_CONTEXT_DIR) / f"{task_id_value}.json"


def save_answer_context(
    task_id_value: str,
    answer_text: str,
    *,
    reasoning: str = "",
    search_results: Optional[list[dict[str, Any]]] = None,
    domain: str = "",
    difficulty: int = 0,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Persist answer reasoning context for efficient future revision."""
    if len(answer_text.strip()) < _MIN_ANSWER_LENGTH:
        return {
            "saved": False,
            "error": f"answer_text too short ({len(answer_text.strip())} chars, min {_MIN_ANSWER_LENGTH}). Refusing to save broken context.",
            "task_id": task_id_value,
        }
    Path(_CONTEXT_DIR).mkdir(parents=True, exist_ok=True)
    compressed_answer = answer_text[:16000]
    compressed_reasoning = reasoning[:16000]
    data = {
        "task_id": task_id_value,
        "answer_text": compressed_answer,
        "reasoning": compressed_reasoning,
        "search_results": (search_results or [])[:10],
        "domain": domain,
        "difficulty": difficulty,
        "extra": extra or {},
    }
    path = _context_path(task_id_value)
    path.write_text(_json_mod.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": True, "path": str(path), "task_id": task_id_value}


def load_answer_context(task_id_value: str) -> Optional[dict[str, Any]]:
    """Load previously saved answer context, or None if not found.

    Returns context with 'usable' flag indicating if answer_text is valid.
    """
    path = _context_path(task_id_value)
    if not path.exists():
        return None
    try:
        data = _json_mod.loads(path.read_text(encoding="utf-8"))
        answer_len = len(data.get("answer_text", "").strip())
        data["usable"] = answer_len >= _MIN_ANSWER_LENGTH
        if not data["usable"]:
            data["warning"] = f"Saved answer_text is only {answer_len} chars (broken context). Treat as no prior answer."
        return data
    except Exception:
        return None


def list_saved_contexts() -> list[str]:
    """List task IDs that have saved answer contexts."""
    context_dir = Path(_CONTEXT_DIR)
    if not context_dir.exists():
        return []
    return [p.stem for p in context_dir.glob("*.json")]
