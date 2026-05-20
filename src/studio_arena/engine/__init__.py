"""Studio Arena Engine — strategy and business logic layer.

Import public functions from here for external use:
    from studio_arena.engine import classify_domain, bounty_decision, harness_status
"""

from .bounty import (
    analyze_reward_distribution,
    bounty_decision,
    bounty_progress,
    evaluate_bounty_responses,
    load_bounty_state,
    record_bounty_answered,
    record_bounty_resolved,
    record_bounty_sent,
    save_bounty_state,
    save_stage_snapshot,
)
from .budget import (
    budget_advice,
    budget_path,
    estimate_tokens,
    load_ledger,
    record_budget,
    save_ledger,
    summarize_budget,
)
from .context import (
    list_saved_contexts,
    load_answer_context,
    save_answer_context,
)
from .difficulty import estimate_task_difficulty
from .domain import (
    answer_score,
    authoritative_sources_for_domain,
    classify_domain,
    extract_search_keywords,
    extract_task_text,
    looks_answered,
    task_id,
    task_reward,
    task_title,
)
from .orchestrator import (
    analyze_competitors,
    analyze_competitors_with_client,
    batch_revise_answered,
    classify_tasks_by_approach,
    find_participant_position,
    harness_status,
    prepare_answer_revision,
    prepare_task_review,
    prioritize_tasks,
    review_self_performance,
    start_participation_round,
)
from .review import (
    answer_template,
    build_answer_revision_packet,
    build_review_packet,
    build_websearch_plan,
    detect_followups,
    select_answer_comments,
)
from .search import build_websearch_plan, should_search_task

__all__ = [
    "analyze_competitors",
    "analyze_competitors_with_client",
    "analyze_reward_distribution",
    "answer_score",
    "answer_template",
    "authoritative_sources_for_domain",
    "batch_revise_answered",
    "bounty_decision",
    "bounty_progress",
    "budget_advice",
    "budget_path",
    "build_answer_revision_packet",
    "build_review_packet",
    "build_websearch_plan",
    "classify_domain",
    "classify_tasks_by_approach",
    "detect_followups",
    "estimate_task_difficulty",
    "estimate_tokens",
    "evaluate_bounty_responses",
    "extract_search_keywords",
    "extract_task_text",
    "find_participant_position",
    "harness_status",
    "list_saved_contexts",
    "load_answer_context",
    "load_bounty_state",
    "load_ledger",
    "looks_answered",
    "prepare_answer_revision",
    "prepare_task_review",
    "prioritize_tasks",
    "record_bounty_answered",
    "record_bounty_resolved",
    "record_bounty_sent",
    "record_budget",
    "review_self_performance",
    "save_answer_context",
    "save_bounty_state",
    "save_ledger",
    "save_stage_snapshot",
    "select_answer_comments",
    "should_search_task",
    "start_participation_round",
    "summarize_budget",
    "task_id",
    "task_reward",
    "task_title",
]
