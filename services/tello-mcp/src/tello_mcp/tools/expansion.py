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
    async def display_scroll_text(
        ctx: Context,
        text: str,
        direction: str = "l",
        color: str = "r",
        rate: float = 0.5,
    ) -> dict:
        """Scroll text on the 8x8 LED matrix.

        Args:
            text: Text to display (max 70 characters).
            direction: Scroll direction (l=left, r=right, u=up, d=down).
            color: Display color (r=red, b=blue, p=purple).
            rate: Frame rate in Hz (0.1-2.5).
        """
        drone = ctx.lifespan_context["drone"]
        queue = ctx.lifespan_context["queue"]
        return await queue.enqueue(lambda: drone.display_scroll_text(text, direction, color, rate))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def display_static_char(ctx: Context, char: str, color: str = "r") -> dict:
        """Display a static character on the 8x8 LED matrix.

        Args:
            char: Single ASCII character or "heart".
            color: Display color (r=red, b=blue, p=purple).
        """
        drone = ctx.lifespan_context["drone"]
        queue = ctx.lifespan_context["queue"]
        return await queue.enqueue(lambda: drone.display_static_char(char, color))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def display_pattern(ctx: Context, pattern: str) -> dict:
        """Display a dot-matrix pattern on the 8x8 LED matrix.

        Args:
            pattern: Up to 64 chars using r (red), b (blue), p (purple), 0 (off).
        """
        drone = ctx.lifespan_context["drone"]
        queue = ctx.lifespan_context["queue"]
        return await queue.enqueue(lambda: drone.display_pattern(pattern))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def set_pad_detection_direction(ctx: Context, direction: int = 0) -> dict:
        """Set mission pad detection direction.

        Args:
            direction: 0=downward (20Hz), 1=forward (20Hz), 2=both (10Hz each).
        """
        drone = ctx.lifespan_context["drone"]
        queue = ctx.lifespan_context["queue"]
        return await queue.enqueue(lambda: drone.set_pad_detection_direction(direction))
