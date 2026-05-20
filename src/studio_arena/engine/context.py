"""Answer context persistence — save reasoning on submit, reload on revise."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

_CONTEXT_DIR = Path(__file__).resolve().parent.parent.parent.parent / ".studio-arena-answers"

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
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": True, "path": str(path), "task_id": task_id_value}


def load_answer_context(task_id_value: str) -> Optional[dict[str, Any]]:
    """Load previously saved answer context, or None if not found."""
    path = _context_path(task_id_value)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
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
