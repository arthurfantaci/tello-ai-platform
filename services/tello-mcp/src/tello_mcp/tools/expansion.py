"""Expansion board MCP tools (LED, matrix display, ESP32)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import Context
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register expansion board tools on the MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def set_led_color(ctx: Context, r: int, g: int, b: int) -> dict:
        """Set the LED color (RGB values 0-255)."""
        drone = ctx.lifespan_context["drone"]
        queue = ctx.lifespan_context["queue"]
        return await queue.enqueue(lambda: drone.set_led(r, g, b))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def display_matrix_text(ctx: Context, text: str) -> dict:
        """Display scrolling text on the 8x8 LED matrix.

        Args:
            text: Text to display (will scroll if longer than 1 character).
        """
        drone = ctx.lifespan_context["drone"]
        queue = ctx.lifespan_context["queue"]
        return await queue.enqueue(lambda: drone.display_text(text))
