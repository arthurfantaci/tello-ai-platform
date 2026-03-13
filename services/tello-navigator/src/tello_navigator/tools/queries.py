"""Read-only mission query tools and room graph seeding."""

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
        """Get detailed info for a mission including waypoints.

        Args:
            mission_id: The mission ID to look up.
        """
        repo = ctx.lifespan_context["repo"]
        mission = await asyncio.to_thread(repo.get_mission, mission_id)
        if mission is None:
            return {"error": "NOT_FOUND", "detail": f"Mission {mission_id} not found"}
        waypoints = await asyncio.to_thread(repo.get_mission_waypoints, mission_id)
        return {"mission": mission, "waypoints": waypoints}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def list_missions(ctx: Context, limit: int = 10, status: str | None = None) -> dict:
        """List recent missions with optional status filter.

        Args:
            limit: Maximum number of missions to return (default 10).
            status: Optional status filter (planned, executing, completed, aborted).
        """
        repo = ctx.lifespan_context["repo"]
        missions = await asyncio.to_thread(repo.list_missions, limit, status=status)
        return {"missions": missions, "count": len(missions)}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    async def seed_room_graph(
        ctx: Context,
        rooms: list[dict],
        pads: list[dict],
        connections: list[dict] | None = None,
    ) -> dict:
        """Seed rooms, mission pads, and connections into Neo4j.

        Args:
            rooms: List of room dicts with id, name, width_cm, depth_cm, height_cm.
            pads: List of pad dicts with id, room_id, x_cm, y_cm.
            connections: Optional connection dicts (from_room, to_room, via_pad, direction).
        """
        repo = ctx.lifespan_context["repo"]
        await asyncio.to_thread(repo.seed_room_graph, rooms, pads, connections or [])
        return {
            "status": "ok",
            "rooms_seeded": len(rooms),
            "pads_seeded": len(pads),
            "connections_seeded": len(connections or []),
        }
