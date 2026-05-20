"""Review packet generation, revision logic, and comment analysis."""

from __future__ import annotations

from typing import Any, Optional, Sequence

from .bounty import bounty_decision
from .budget import (
    DEFAULT_HIGH_REWARD_THRESHOLD,
    DEFAULT_RESERVE_BALANCE,
    budget_advice,
    estimate_tokens,
)
from .context import load_answer_context
from .difficulty import estimate_task_difficulty
from .domain import (
    DOMAIN_RULES,
    FOLLOWUP_KEYWORDS,
    _stringify,
    classify_domain,
    extract_task_text,
    task_id,
    task_title,
    task_reward,
)
from .search import build_websearch_plan


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
        compact_ctx = saved_ctx.get("compact", {})
        reasoning_ctx = saved_ctx.get("reasoning", "")
        search_ctx = saved_ctx.get("search_results", [])
    else:
        previous_answer_text = _stringify(previous_answer).strip()[:6000]
        compact_ctx = {}
        reasoning_ctx = ""
        search_ctx = []

    comment_lines = []
    for item in comment_analysis["items"]:
        categories = ", ".join(item["categories"])
        comment_lines.append(f"- [{categories}] {item['excerpt']}")
    comments_text = "\n".join(comment_lines) or "- 暂无明确 comments；仍需完整自检。"

    context_block = ""
    if compact_ctx:
        parts = []
        if compact_ctx.get("key_conclusions"):
            parts.append("结论: " + "; ".join(compact_ctx["key_conclusions"]))
        if compact_ctx.get("reasoning_chain"):
            parts.append("推理链: " + "; ".join(compact_ctx["reasoning_chain"]))
        if compact_ctx.get("key_facts"):
            parts.append("关键事实: " + "; ".join(compact_ctx["key_facts"]))
        if compact_ctx.get("uncertainties"):
            parts.append("不确定性: " + "; ".join(compact_ctx["uncertainties"]))
        if compact_ctx.get("search_summary"):
            parts.append("搜索发现: " + "; ".join(compact_ctx["search_summary"]))
        context_block += "\n【原始推理摘要（compact）】\n" + "\n".join(parts) + "\n"
    elif reasoning_ctx:
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
                "full_answer_sections": ["结论", "依据", "推理与计算", "验证", "风险与假设"],
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
            "submit_answer", "create_bounty", "create_agora_comment",
        ],
        "review_packet": {
            "must_show_before_write": [
                "task_summary", "domain", "reward", "budget",
                "draft_answer", "risk_points", "recommended_action",
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
