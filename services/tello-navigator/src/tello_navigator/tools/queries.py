"""Query tools — read-only MCP tools for missions + room graph seeding."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastmcp import Context
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register query tools on the MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_mission(ctx: Context, mission_id: str) -> dict:
        """Get mission details and waypoints."""
        repo = ctx.lifespan_context["repo"]
        mission = await asyncio.to_thread(repo.get_mission, mission_id)
        if mission is None:
            return {"error": "NOT_FOUND", "detail": f"No mission with ID {mission_id}"}
        waypoints = await asyncio.to_thread(repo.get_mission_waypoints, mission_id)
        return {"mission": mission, "waypoints": waypoints}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def list_missions(ctx: Context, limit: int = 10, status: str | None = None) -> dict:
        """List missions, optionally filtered by status."""
        repo = ctx.lifespan_context["repo"]
        missions = await asyncio.to_thread(repo.list_missions, limit, status)
        return {"missions": missions, "count": len(missions)}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def seed_room_graph(
        ctx: Context, rooms: list[dict], pads: list[dict], connections: list[dict]
    ) -> dict:
        """Seed the room graph with rooms, pads, and connections (idempotent)."""
        repo = ctx.lifespan_context["repo"]
        await asyncio.to_thread(repo.seed_room_graph, rooms, pads, connections)
        return {
            "status": "seeded",
            "rooms_seeded": len(rooms),
            "pads_seeded": len(pads),
            "connections_seeded": len(connections),
        }
