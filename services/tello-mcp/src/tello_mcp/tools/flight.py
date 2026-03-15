"""Flight control MCP tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import Context
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register flight control tools on the MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def takeoff(ctx: Context, room_id: str = "unknown") -> dict:
        """Take off and hover at ~50cm.

        Args:
            room_id: Room identifier for session tracking (default "unknown").
        """
        drone = ctx.lifespan_context["drone"]
        queue = ctx.lifespan_context["queue"]
        telemetry = ctx.lifespan_context["telemetry"]
        result = await queue.enqueue(drone.takeoff, heavy=True)
        await telemetry.publish_event("takeoff", {"room_id": room_id})
        return result

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def land(ctx: Context) -> dict:
        """Land the drone safely."""
        drone = ctx.lifespan_context["drone"]
        queue = ctx.lifespan_context["queue"]
        return await queue.enqueue(drone.safe_land)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    async def emergency_stop(ctx: Context) -> dict:
        """Kill motors immediately. DANGER: drone will fall."""
        drone = ctx.lifespan_context["drone"]
        queue = ctx.lifespan_context["queue"]
        return await queue.enqueue(drone.emergency)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def move(ctx: Context, direction: str, distance_cm: int) -> dict:
        """Move the drone in a direction.

        Args:
            direction: One of forward, back, left, right, up, down.
            distance_cm: Distance in centimeters (20-500).
        """
        drone = ctx.lifespan_context["drone"]
        queue = ctx.lifespan_context["queue"]
        return await queue.enqueue(lambda: drone.move(direction, distance_cm))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def rotate(ctx: Context, degrees: int) -> dict:
        """Rotate the drone. Positive = clockwise, negative = counter-clockwise.

        Args:
            degrees: Rotation angle (-360 to 360).
        """
        drone = ctx.lifespan_context["drone"]
        queue = ctx.lifespan_context["queue"]
        return await queue.enqueue(lambda: drone.rotate(degrees))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def go_to_mission_pad(ctx: Context, x: int, y: int, z: int, speed: int, mid: int) -> dict:
        """Fly to coordinates relative to a detected mission pad.

        Args:
            x: X position relative to pad (-500 to 500 cm).
            y: Y position relative to pad (-500 to 500 cm).
            z: Altitude above pad (0 to 500 cm, must be positive).
            speed: Flight speed (10-100 cm/s).
            mid: Target mission pad ID (1-8).
        """
        drone = ctx.lifespan_context["drone"]
        queue = ctx.lifespan_context["queue"]
        return await queue.enqueue(lambda: drone.go_xyz_speed_mid(x, y, z, speed, mid))
