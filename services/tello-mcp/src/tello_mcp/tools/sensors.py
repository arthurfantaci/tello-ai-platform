"""Sensor and state MCP tools (read-only)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register sensor tools on the MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_telemetry() -> dict:
        """Get current telemetry: battery, height, ToF, attitude, temp, flight time."""
        drone = mcp.state["drone"]
        frame = drone.get_telemetry()
        return frame.model_dump()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_tof_distance() -> dict:
        """Get Time-of-Flight distance sensor reading in cm."""
        drone = mcp.state["drone"]
        frame = drone.get_telemetry()
        return {"tof_cm": frame.tof_cm}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def detect_mission_pad() -> dict:
        """Scan for the nearest mission pad. Returns pad ID or -1 if none detected."""
        drone = mcp.state["drone"]
        return drone.detect_mission_pad()
