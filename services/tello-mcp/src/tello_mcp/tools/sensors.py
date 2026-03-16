"""Sensor and state MCP tools (read-only)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import Context
from mcp.types import ToolAnnotations

from tello_core.models import ObstacleZone

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register sensor tools on the MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_telemetry(ctx: Context) -> dict:
        """Get current telemetry: battery, height, ToF, attitude, temp, flight time."""
        drone = ctx.lifespan_context["drone"]
        result = drone.get_telemetry()
        if isinstance(result, dict):
            return result
        return result.model_dump()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_tof_distance(ctx: Context) -> dict:
        """Get DOWNWARD Time-of-Flight distance in cm (built-in Vision Positioning System).

        This is the drone's built-in downward-facing sensor for altitude/ground distance.
        For forward obstacle detection, use get_forward_distance instead.
        """
        drone = ctx.lifespan_context["drone"]
        result = drone.get_telemetry()
        if isinstance(result, dict):
            return result
        return {"tof_cm": result.tof_cm}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def detect_mission_pad(ctx: Context) -> dict:
        """Scan for the nearest mission pad. Returns pad ID or -1 if none detected."""
        drone = ctx.lifespan_context["drone"]
        return drone.detect_mission_pad()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_forward_distance(ctx: Context) -> dict:
        """Get forward-facing ToF distance in mm (Dot-Matrix Module sensor).

        Returns distance to nearest obstacle ahead. 8192 means nothing detected.
        Includes obstacle zone classification (CLEAR/CAUTION/WARNING/DANGER).
        """
        monitor = ctx.lifespan_context["monitor"]
        latest = monitor.latest
        if latest is None:
            return {
                "error": "NO_READING",
                "detail": "Forward ToF not yet polled or sensor unavailable",
            }
        return latest.model_dump()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_obstacle_status(ctx: Context) -> dict:
        """Check if the path ahead is clear. Returns zone and distance.

        Zones: CLEAR (safe), CAUTION (<150cm), WARNING (<80cm), DANGER (<40cm).
        In DANGER zone, the drone has already been stopped automatically.
        """
        monitor = ctx.lifespan_context["monitor"]
        latest = monitor.latest
        if latest is None:
            return {"zone": "unknown", "detail": "Sensor unavailable"}
        return {
            "zone": latest.zone.value,
            "distance_mm": latest.distance_mm,
            "is_safe": latest.zone in (ObstacleZone.CLEAR, ObstacleZone.CAUTION),
            "timestamp": latest.timestamp.isoformat(),
        }
