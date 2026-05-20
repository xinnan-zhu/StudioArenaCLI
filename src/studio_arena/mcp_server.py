"""Optional MCP server for the Studio Arena harness.

This module is intentionally optional: the normal CLI and tests do not require
the `mcp` package. Install the project with the `mcp` extra before running the
server entrypoint.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from dotenv import load_dotenv

from .client import ArenaParticipantClient
from .harness import (
    analyze_competitors_with_client,
    build_websearch_plan,
    harness_status,
    prepare_answer_revision,
    prepare_task_review,
    review_self_performance,
    start_participation_round,
)

try:  # pragma: no cover - depends on optional runtime dependency
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised by CLI error path instead
    FastMCP = None  # type: ignore[assignment]


def get_client_from_env() -> ArenaParticipantClient:
    load_dotenv()
    arena_base = os.environ.get("ARENA_BASE_URL", "https://api.holosai.io")
    agora_base = os.environ.get("AGORA_BASE_URL", "https://agora.holosai.io")
    competition_id = os.environ.get("ARENA_COMPETITION_ID", "")
    agent_secret = os.environ.get("ARENA_AGENT_SECRET", "")

    if not competition_id:
        raise RuntimeError("Missing ARENA_COMPETITION_ID in environment or .env")
    if not agent_secret:
        raise RuntimeError("Missing ARENA_AGENT_SECRET in environment or .env")

    return ArenaParticipantClient(
        arena_base_url=arena_base,
        competition_id=competition_id,
        agent_secret=agent_secret,
        agora_base_url=agora_base,
    )


def create_mcp_server() -> Any:
    if FastMCP is None:
        raise RuntimeError(
            "The optional 'mcp' package is not installed. "
            "Install with: pip install -e '.[mcp]'"
        )

    server = FastMCP("studio-arena-harness")

    @server.tool()
    def status() -> dict[str, Any]:
        """Return implemented harness capabilities and safety mode."""
        return harness_status()

    @server.tool()
    async def start_participation(
        limit: int = 1,
        balance: Optional[float] = None,
        stage_id: Optional[str] = None,
        skip_answered: bool = True,
    ) -> dict[str, Any]:
        """Run the human-reviewed '开始参赛' preparation workflow."""
        return await start_participation_round(
            get_client_from_env(),
            limit=limit,
            balance=balance,
            stage_id=stage_id,
            skip_answered=skip_answered,
        )

    @server.tool()
    async def prepare_review(
        task_id: str,
        balance: Optional[float] = None,
    ) -> dict[str, Any]:
        """Prepare a human-review packet for one official task."""
        return await prepare_task_review(
            get_client_from_env(),
            task_id,
            balance=balance,
        )

    @server.tool()
    async def prepare_revision(
        task_id: str,
        balance: Optional[float] = None,
    ) -> dict[str, Any]:
        """Prepare a full-answer revision packet from Answer comments."""
        return await prepare_answer_revision(
            get_client_from_env(),
            task_id,
            balance=balance,
        )

    @server.tool()
    async def websearch_plan(
        task_id: str,
        mode: str = "save",
        max_queries: Optional[int] = None,
    ) -> dict[str, Any]:
        """Build authoritative-source web search queries for one task."""
        task = await get_client_from_env().get_task_with_content(task_id)
        return build_websearch_plan(
            task,
            mode=mode,
            max_queries=max_queries,
        )

    @server.tool()
    async def self_review(task_ids: Optional[list[str]] = None) -> dict[str, Any]:
        """Summarize own submissions, budget, and improvement actions."""
        return await review_self_performance(
            get_client_from_env(),
            task_ids=task_ids or [],
        )

    @server.tool()
    async def competitor_analysis(window: int = 5) -> dict[str, Any]:
        """Compare against participants ranked immediately above us."""
        return await analyze_competitors_with_client(
            get_client_from_env(),
            window=window,
        )

    return server


def main() -> None:
    server = create_mcp_server()
    server.run()


if __name__ == "__main__":  # pragma: no cover
    main()
