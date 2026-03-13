"""Mission lifecycle MCP tools — create, start, advance, abort."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastmcp import Context
from mcp.types import ToolAnnotations

from tello_core.models import MissionStatus

if TYPE_CHECKING:
    from fastmcp import FastMCP


def _suggested_command(waypoint: dict) -> dict | None:
    """Generate an advisory tello-mcp command for a waypoint."""
    action = waypoint.get("action")
    if action == "takeoff":
        return {"tool": "takeoff", "args": {}}
    if action == "land":
        return {"tool": "land", "args": {}}
    if action == "move":
        return {
            "tool": "move",
            "args": {
                "direction": waypoint.get("direction", "forward"),
                "distance_cm": waypoint.get("distance_cm", 100),
            },
        }
    if action == "rotate":
        return {"tool": "rotate", "args": {"degrees": waypoint.get("degrees", 90)}}
    if action == "goto_pad":
        return {"tool": "detect_mission_pad", "args": {}}
    return None


def register(mcp: FastMCP) -> None:
    """Register mission lifecycle tools on the MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    async def create_mission(ctx: Context, goal: str, room_ids: list[str]) -> dict:
        """Plan a new mission from a goal and room list.

        Args:
            goal: Human-readable mission objective.
            room_ids: List of room IDs to include in the mission.
        """
        planner = ctx.lifespan_context["planner"]
        repo = ctx.lifespan_context["repo"]
        events = ctx.lifespan_context["events"]

        mission_id = f"m_{uuid.uuid4().hex[:8]}"
        result = await planner.plan(
            mission_id=mission_id,
            goal=goal,
            room_ids=room_ids,
        )

        if result["status"] == "error":
            return {"error": "PLANNING_FAILED", "detail": result["error"]}

        # Persist mission and waypoints to Neo4j
        now = datetime.now(tz=UTC)
        await asyncio.to_thread(
            repo.create_mission,
            mission_id=mission_id,
            goal=goal,
            room_ids=room_ids,
            status=MissionStatus.PLANNED,
            created_at=now,
        )
        from tello_core.models import Waypoint

        waypoint_models = [
            Waypoint(
                id=wp["id"],
                sequence=wp["sequence"],
                room_id=wp["room_id"],
                action=wp["action"],
                pad_id=wp.get("pad_id"),
                direction=wp.get("direction"),
                distance_cm=wp.get("distance_cm"),
                degrees=wp.get("degrees"),
            )
            for wp in result["waypoints"]
        ]
        await asyncio.to_thread(repo.save_waypoints, mission_id, waypoint_models)
        await events.mission_created(mission_id, goal, room_ids)

        return {
            "mission_id": mission_id,
            "status": "planned",
            "waypoint_count": len(result["waypoints"]),
            "waypoints": result["waypoints"],
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    async def start_mission(ctx: Context, mission_id: str) -> dict:
        """Start executing a planned mission. Returns the first waypoint.

        Args:
            mission_id: ID of the mission to start.
        """
        repo = ctx.lifespan_context["repo"]
        events = ctx.lifespan_context["events"]

        mission = await asyncio.to_thread(repo.get_mission, mission_id)
        if mission is None:
            return {"error": "NOT_FOUND", "detail": f"Mission {mission_id} not found"}

        if mission["status"] != "planned":
            return {
                "error": "INVALID_TRANSITION",
                "detail": f"Cannot start mission in '{mission['status']}' state",
            }

        now = datetime.now(tz=UTC)
        await asyncio.to_thread(
            repo.update_mission_status,
            mission_id,
            MissionStatus.EXECUTING,
            started_at=now,
        )
        waypoints = await asyncio.to_thread(repo.get_mission_waypoints, mission_id)
        await events.mission_started(mission_id)

        first_wp = waypoints[0] if waypoints else None
        return {
            "status": "executing",
            "mission_id": mission_id,
            "current_waypoint": first_wp,
            "suggested_command": _suggested_command(first_wp) if first_wp else None,
            "total_waypoints": len(waypoints),
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    async def advance_mission(ctx: Context, mission_id: str, current_waypoint_idx: int) -> dict:
        """Mark current waypoint done and get the next one.

        Args:
            mission_id: ID of the executing mission.
            current_waypoint_idx: Index of the waypoint just completed.
        """
        repo = ctx.lifespan_context["repo"]
        events = ctx.lifespan_context["events"]

        mission = await asyncio.to_thread(repo.get_mission, mission_id)
        if mission is None:
            return {"error": "NOT_FOUND", "detail": f"Mission {mission_id} not found"}

        if mission["status"] != "executing":
            return {
                "error": "INVALID_TRANSITION",
                "detail": f"Cannot advance mission in '{mission['status']}' state",
            }

        waypoints = await asyncio.to_thread(repo.get_mission_waypoints, mission_id)
        current_wp = waypoints[current_waypoint_idx]
        await events.waypoint_reached(mission_id, current_wp["id"], current_waypoint_idx)

        next_idx = current_waypoint_idx + 1
        if next_idx >= len(waypoints):
            now = datetime.now(tz=UTC)
            await asyncio.to_thread(
                repo.update_mission_status,
                mission_id,
                MissionStatus.COMPLETED,
                completed_at=now,
            )
            await events.mission_completed(mission_id, 0.0)
            return {"status": "completed", "mission_id": mission_id}

        next_wp = waypoints[next_idx]
        return {
            "status": "executing",
            "mission_id": mission_id,
            "next_waypoint": next_wp,
            "suggested_command": _suggested_command(next_wp),
            "waypoints_remaining": len(waypoints) - next_idx,
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    async def abort_mission(
        ctx: Context,
        mission_id: str,
        reason: str = "Aborted by user",
    ) -> dict:
        """Cancel an in-progress or planned mission.

        Args:
            mission_id: ID of the mission to abort.
            reason: Reason for aborting.
        """
        repo = ctx.lifespan_context["repo"]
        events = ctx.lifespan_context["events"]

        mission = await asyncio.to_thread(repo.get_mission, mission_id)
        if mission is None:
            return {"error": "NOT_FOUND", "detail": f"Mission {mission_id} not found"}

        if mission["status"] not in ("planned", "executing"):
            return {
                "error": "INVALID_TRANSITION",
                "detail": f"Cannot abort mission in '{mission['status']}' state",
            }

        await asyncio.to_thread(
            repo.update_mission_status,
            mission_id,
            MissionStatus.ABORTED,
            error=reason,
        )
        await events.mission_aborted(mission_id, reason)
        return {"status": "aborted", "mission_id": mission_id}
