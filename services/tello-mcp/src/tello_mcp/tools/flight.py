"""Flight control MCP tools."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog
from fastmcp import Context
from mcp.types import ToolAnnotations

logger = structlog.get_logger("tello_mcp.tools.flight")

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register flight control tools on the MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def takeoff(ctx: Context, room_id: str = "unknown") -> Any:
        """Take off and hover at ~50cm.

        Args:
            room_id: Room identifier for session tracking (default "unknown").
        """
        drone = ctx.lifespan_context["drone"]
        coordinator = ctx.lifespan_context["coordinator"]
        telemetry = ctx.lifespan_context["telemetry"]
        result = await coordinator.execute(drone.takeoff, heavy=True)
        if result.get("status") == "ok":
            await telemetry.publish_event("takeoff", {"room_id": room_id})
        else:
            logger.warning(
                "event.skipped_command_failed",
                event_type="takeoff",
                error=result.get("error"),
            )
        return result

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def land(ctx: Context) -> Any:
        """Land the drone safely."""
        drone = ctx.lifespan_context["drone"]
        coordinator = ctx.lifespan_context["coordinator"]
        telemetry = ctx.lifespan_context["telemetry"]
        result = await coordinator.execute(drone.safe_land)
        if result.get("status") == "ok":
            await telemetry.publish_event("land", {})
        else:
            logger.warning(
                "event.skipped_command_failed",
                event_type="land",
                error=result.get("error"),
            )
        return result

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    async def emergency_stop(ctx: Context) -> Any:
        """Kill motors immediately. DANGER: drone will fall.

        Bypasses the coordinator entirely — safety-critical, no ownership check.
        """
        drone = ctx.lifespan_context["drone"]
        return await asyncio.to_thread(drone.emergency)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def move(ctx: Context, direction: str, distance_cm: int) -> Any:
        """Move the drone in a direction.

        Long moves are decomposed into 20cm chunks with obstacle checking
        between each chunk. Returns partial completion info if aborted.

        Args:
            direction: One of forward, back, left, right, up, down.
            distance_cm: Distance in centimeters (20-500).
        """
        coordinator = ctx.lifespan_context["coordinator"]
        return await coordinator.execute_move(direction, distance_cm)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def rotate(ctx: Context, degrees: int) -> Any:
        """Rotate the drone. Positive = clockwise, negative = counter-clockwise.

        Args:
            degrees: Rotation angle (-360 to 360).
        """
        drone = ctx.lifespan_context["drone"]
        coordinator = ctx.lifespan_context["coordinator"]
        return await coordinator.execute(lambda: drone.rotate(degrees))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def go_to_mission_pad(ctx: Context, x: int, y: int, z: int, speed: int, mid: int) -> Any:
        """Fly to coordinates relative to a detected mission pad.

        Args:
            x: X position relative to pad (-500 to 500 cm).
            y: Y position relative to pad (-500 to 500 cm).
            z: Altitude above pad (0 to 500 cm, must be positive).
            speed: Flight speed (10-100 cm/s).
            mid: Target mission pad ID (1-8).
        """
        drone = ctx.lifespan_context["drone"]
        coordinator = ctx.lifespan_context["coordinator"]
        last_command = ctx.lifespan_context["last_command"]
        result = await coordinator.execute(lambda: drone.go_xyz_speed_mid(x, y, z, speed, mid))
        if result.get("status") == "ok":
            last_command["direction"] = ""
            last_command["distance_cm"] = 0
        return result
