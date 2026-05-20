"""Domain classification, task text extraction, and authoritative source routing."""

from __future__ import annotations

import re
from typing import Any, Optional, Sequence

DOMAIN_RULES: dict[str, dict[str, Any]] = {
    "economy": {
        "label": "经济",
        "keywords": [
            "finance", "financial", "economy", "economic", "market",
            "revenue", "profit", "price", "cost", "investment",
            "gdp", "inflation", "金融", "经济", "市场",
            "收入", "利润", "价格", "成本", "投资", "通胀",
        ],
        "focus": "Define metric scope, cite data, state assumptions, sensitivity, and risk.",
    },
    "medical": {
        "label": "医疗",
        "keywords": [
            "medical", "medicine", "clinical", "patient", "diagnosis",
            "treatment", "drug", "disease", "symptom", "trial",
            "医学", "医疗", "临床", "患者", "诊断",
            "治疗", "药物", "疾病", "症状",
        ],
        "focus": "Avoid diagnosis, use authoritative evidence, and mark population limits.",
    },
    "legal": {
        "label": "法律",
        "keywords": [
            "law", "legal", "court", "contract", "regulation",
            "statute", "liability", "compliance", "jurisdiction",
            "法律", "法院", "合同", "法规", "条例",
            "责任", "合规", "司法辖区",
        ],
        "focus": "State jurisdiction, time, rule source, uncertainty, and non-advice limits.",
    },
    "industry": {
        "label": "工业",
        "keywords": [
            "industrial", "manufacturing", "factory", "process",
            "equipment", "safety", "engineering", "production",
            "工厂", "工业", "制造", "工艺", "设备",
            "安全", "工程", "生产",
        ],
        "focus": "Cover process, parameters, constraints, safety limits, and verification.",
    },
    "science": {
        "label": "自然科学",
        "keywords": [
            "physics", "chemistry", "biology", "scientific",
            "experiment", "formula", "model", "hypothesis", "data",
            "物理", "化学", "生物", "科学", "实验",
            "公式", "模型", "假设",
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
    "追问", "补充", "解释", "为什么", "不对", "错误", "修正",
    "clarify", "follow up", "revise", "wrong", "incorrect", "explain", "why",
    "?", "？",
]

SEARCH_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into",
    "your", "about", "请", "分析", "解释", "比较", "回答",
    "说明", "什么", "如何", "为什么",
}

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

REWARD_KEYS = (
    "reward", "reward_amount", "bounty_amount", "amount", "points",
    "score_reward", "max_reward",
)

SCORE_KEYS = (
    "score", "final_score", "rubric_score", "quality_score", "grade",
)


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
        "answer", "answer_text", "text", "content", "submitted_at",
        "created_at", "updated_at", "score", "final_score", "rubric_score", "status",
    )
    return any(answer.get(key) not in (None, "", [], {}) for key in answer_markers)


def extract_task_text(task: dict[str, Any]) -> str:
    keys = (
        "title", "name", "summary", "description", "prompt",
        "question", "content", "body", "text", "requirements",
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
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9.-]{2,}|[一-鿿]{2,}", text)
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
