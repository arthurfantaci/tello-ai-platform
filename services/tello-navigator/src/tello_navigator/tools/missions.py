"""Mission lifecycle MCP tools -- create, start, advance, abort missions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import structlog
from fastmcp import Context
from mcp.types import ToolAnnotations

from tello_core.models import Waypoint

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = structlog.get_logger("tello_navigator.tools.missions")


def _suggested_command(waypoint: dict) -> dict | None:
    """Map a waypoint action to a suggested MCP tool invocation."""
    action = waypoint.get("action")
    if action == "takeoff":
        return {"tool": "takeoff", "args": {"room_id": waypoint.get("room_id", "unknown")}}
    if action == "land":
        return {"tool": "land", "args": {}}
    if action == "move":
        return {
            "tool": "move",
            "args": {
                "direction": waypoint.get("direction"),
                "distance_cm": waypoint.get("distance_cm"),
            },
        }
    if action == "rotate":
        return {"tool": "rotate", "args": {"degrees": waypoint.get("degrees")}}
    if action == "goto_pad":
        return {"tool": "detect_mission_pad", "args": {}}
    if action == "hover":
        return None
    return None


def register(mcp: FastMCP) -> None:
    """Register mission lifecycle tools on the MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def create_mission(ctx: Context, goal: str, room_ids: list[str]) -> dict:
        """Plan a new mission for the given rooms.

        Args:
            ctx: MCP request context.
            goal: Human-readable mission objective.
            room_ids: Ordered list of room IDs to visit.
        """
        deps = ctx.lifespan_context
        planner = deps["planner"]
        repo = deps["repo"]
        events = deps["events"]

        mission_id = uuid4().hex[:12]
        state = await planner.plan(mission_id, goal, room_ids)

        if state["status"] == "error":
            return {"error": "PLANNING_FAILED", "detail": state["error"]}

        now = datetime.now(UTC).isoformat()
        await asyncio.to_thread(
            repo.create_mission,
            mission_id,
            goal,
            room_ids,
            "planned",
            now,
        )

        waypoints = [Waypoint(**wp) for wp in state["waypoints"]]
        await asyncio.to_thread(repo.save_waypoints, mission_id, waypoints)
        await events.mission_created(mission_id, goal, room_ids)

        return {
            "mission_id": mission_id,
            "status": "planned",
            "waypoint_count": len(waypoints),
            "waypoints": state["waypoints"],
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def start_mission(ctx: Context, mission_id: str) -> dict:
        """Start executing a planned mission.

        Args:
            ctx: MCP request context.
            mission_id: ID of the mission to start.
        """
        deps = ctx.lifespan_context
        repo = deps["repo"]
        events = deps["events"]

        mission = await asyncio.to_thread(repo.get_mission, mission_id)
        if mission is None:
            return {"error": "NOT_FOUND", "detail": f"Mission '{mission_id}' not found"}

        status = mission["status"]
        if status != "planned":
            return {
                "error": "INVALID_TRANSITION",
                "detail": f"Cannot start mission in '{status}' state",
            }

        now = datetime.now(UTC).isoformat()
        await asyncio.to_thread(
            repo.update_mission_status,
            mission_id,
            "executing",
            started_at=now,
        )
        await events.mission_started(mission_id)

        waypoints = await asyncio.to_thread(repo.get_mission_waypoints, mission_id)
        return {
            "status": "executing",
            "mission_id": mission_id,
            "current_waypoint": waypoints[0],
            "suggested_command": _suggested_command(waypoints[0]),
            "total_waypoints": len(waypoints),
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def advance_mission(ctx: Context, mission_id: str, current_waypoint_idx: int) -> dict:
        """Advance to the next waypoint in a mission.

        Args:
            ctx: MCP request context.
            mission_id: ID of the executing mission.
            current_waypoint_idx: Index of the waypoint just completed.
        """
        deps = ctx.lifespan_context
        repo = deps["repo"]
        events = deps["events"]

        mission = await asyncio.to_thread(repo.get_mission, mission_id)
        if mission is None:
            return {"error": "NOT_FOUND", "detail": f"Mission '{mission_id}' not found"}

        status = mission["status"]
        if status != "executing":
            return {
                "error": "INVALID_TRANSITION",
                "detail": f"Cannot advance mission in '{status}' state",
            }

        waypoints = await asyncio.to_thread(repo.get_mission_waypoints, mission_id)
        next_idx = current_waypoint_idx + 1

        if next_idx >= len(waypoints):
            now = datetime.now(UTC).isoformat()
            await asyncio.to_thread(
                repo.update_mission_status,
                mission_id,
                "completed",
                completed_at=now,
            )
            await events.mission_completed(mission_id, duration_s=0.0)
            return {"status": "completed", "mission_id": mission_id}

        wp = waypoints[next_idx]
        await events.waypoint_reached(mission_id, wp["id"], wp["sequence"])
        return {
            "status": "executing",
            "mission_id": mission_id,
            "next_waypoint": wp,
            "suggested_command": _suggested_command(wp),
            "waypoints_remaining": len(waypoints) - next_idx - 1,
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    async def abort_mission(ctx: Context, mission_id: str, reason: str = "User requested") -> dict:
        """Abort a mission that is planned or executing.

        Args:
            ctx: MCP request context.
            mission_id: ID of the mission to abort.
            reason: Human-readable abort reason.
        """
        deps = ctx.lifespan_context
        repo = deps["repo"]
        events = deps["events"]

        mission = await asyncio.to_thread(repo.get_mission, mission_id)
        if mission is None:
            return {"error": "NOT_FOUND", "detail": f"Mission '{mission_id}' not found"}

        status = mission["status"]
        if status not in ("planned", "executing"):
            return {
                "error": "INVALID_TRANSITION",
                "detail": f"Cannot abort mission in '{status}' state",
            }

        await asyncio.to_thread(
            repo.update_mission_status,
            mission_id,
            "aborted",
            error=reason,
        )
        await events.mission_aborted(mission_id, reason)

        return {"status": "aborted", "mission_id": mission_id}
