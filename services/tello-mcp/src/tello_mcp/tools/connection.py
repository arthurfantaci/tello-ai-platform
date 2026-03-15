"""Connection management MCP tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import Context
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register connection management tools on the MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def connect_drone(ctx: Context) -> dict:
        """Connect to the Tello drone. Called automatically at startup, but can retry manually."""
        drone = ctx.lifespan_context["drone"]
        if drone.is_connected:
            return {"status": "already_connected"}
        return drone.connect()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def disconnect_drone(ctx: Context) -> dict:
        """Disconnect from the Tello drone."""
        drone = ctx.lifespan_context["drone"]
        if not drone.is_connected:
            return {"status": "already_disconnected"}
        drone.disconnect()
        return {"status": "ok"}
