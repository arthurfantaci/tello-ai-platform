"""Coordination MCP tools — ownership management for multi-actor control."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastmcp import Context
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register coordination tools on the MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def acquire_control(ctx: Context, actor: str) -> Any:
        """Acquire exclusive control of the drone.

        Only one actor can control the drone at a time. Default owner is "mcp".

        Args:
            actor: Identifier for the requesting actor (e.g. "navigator", "vision").
        """
        coordinator = ctx.lifespan_context["coordinator"]
        return await coordinator.acquire_control(actor)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def release_control(ctx: Context, actor: str) -> Any:
        """Release drone control back to the default owner (mcp).

        Only the current owner can release control.

        Args:
            actor: Identifier of the actor releasing control.
        """
        coordinator = ctx.lifespan_context["coordinator"]
        return await coordinator.release_control(actor)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_control_owner(ctx: Context) -> Any:
        """Get the current drone control owner and execution state."""
        coordinator = ctx.lifespan_context["coordinator"]
        return coordinator.get_control_info()
