"""Sensor and state MCP tools (read-only)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import Context
from mcp.types import ToolAnnotations

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
        """Get Time-of-Flight distance sensor reading in cm."""
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
