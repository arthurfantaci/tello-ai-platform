"""Flight control MCP tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register flight control tools on the MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def takeoff(room_id: str = "unknown") -> dict:
        """Take off and hover at ~50cm.

        Args:
            room_id: Room identifier for session tracking (default "unknown").
        """
        drone = mcp.state["drone"]
        queue = mcp.state["queue"]
        telemetry = mcp.state["telemetry"]
        result = await queue.enqueue(drone.takeoff)
        await telemetry.publish_event("takeoff", {"room_id": room_id})
        return result

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def land() -> dict:
        """Land the drone safely."""
        drone = mcp.state["drone"]
        queue = mcp.state["queue"]
        return await queue.enqueue(drone.land)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    async def emergency_stop() -> dict:
        """Kill motors immediately. DANGER: drone will fall."""
        drone = mcp.state["drone"]
        queue = mcp.state["queue"]
        return await queue.enqueue(drone.emergency)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def move(direction: str, distance_cm: int) -> dict:
        """Move the drone in a direction.

        Args:
            direction: One of forward, back, left, right, up, down.
            distance_cm: Distance in centimeters (20-500).
        """
        drone = mcp.state["drone"]
        queue = mcp.state["queue"]
        return await queue.enqueue(lambda: drone.move(direction, distance_cm))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def rotate(degrees: int) -> dict:
        """Rotate the drone. Positive = clockwise, negative = counter-clockwise.

        Args:
            degrees: Rotation angle (-360 to 360).
        """
        drone = mcp.state["drone"]
        queue = mcp.state["queue"]
        return await queue.enqueue(lambda: drone.rotate(degrees))
