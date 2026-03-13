"""Query tools — read-only FastMCP tools for flight session data.

Template queries that call SessionRepository methods. Each tool
wraps sync Neo4j calls with asyncio.to_thread() to keep the
event loop responsive.

Tools follow the register(mcp) pattern. The SessionRepository
is accessed from ctx.lifespan_context["session_repo"].
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastmcp import Context
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register query tools on the MCP server.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def list_flight_sessions(ctx: Context, limit: int = 10) -> dict:
        """List recent flight sessions with summary stats.

        Args:
            limit: Maximum number of sessions to return (default 10).
        """
        repo = ctx.lifespan_context["session_repo"]
        sessions = await asyncio.to_thread(repo.list_sessions, limit)
        return {"sessions": sessions, "count": len(sessions)}

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def get_flight_session(ctx: Context, session_id: str) -> dict:
        """Get detailed info for one flight session.

        Args:
            session_id: The session ID to look up.
        """
        repo = ctx.lifespan_context["session_repo"]
        session = await asyncio.to_thread(repo.get_session, session_id)
        if session is None:
            return {
                "error": "NOT_FOUND",
                "detail": f"No session with ID {session_id}",
            }
        return {"session": session}

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def get_session_telemetry(ctx: Context, session_id: str) -> dict:
        """Get sampled telemetry curve for a session.

        Returns battery, altitude, temperature over time.

        Args:
            session_id: The session to get telemetry for.
        """
        repo = ctx.lifespan_context["session_repo"]
        samples = await asyncio.to_thread(
            repo.get_session_samples,
            session_id,
        )
        return {"samples": samples, "count": len(samples)}

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def get_session_anomalies(ctx: Context, session_id: str) -> dict:
        """Get anomalies detected during a flight session.

        Args:
            session_id: The session to get anomalies for.
        """
        repo = ctx.lifespan_context["session_repo"]
        anomalies = await asyncio.to_thread(
            repo.get_session_anomalies,
            session_id,
        )
        return {"anomalies": anomalies, "count": len(anomalies)}

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def get_anomaly_summary(ctx: Context) -> dict:
        """Get anomaly counts by type across all sessions."""
        repo = ctx.lifespan_context["session_repo"]
        summary = await asyncio.to_thread(repo.get_anomaly_summary)
        return {"summary": summary}
