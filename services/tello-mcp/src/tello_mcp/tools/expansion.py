"""Expansion board MCP tools (LED, matrix display, ESP32)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastmcp import Context
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register expansion board tools on the MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def set_led_color(ctx: Context, r: int, g: int, b: int) -> Any:
        """Set the LED color (RGB values 0-255)."""
        drone = ctx.lifespan_context["drone"]
        coordinator = ctx.lifespan_context["coordinator"]
        return await coordinator.execute(lambda: drone.set_led(r, g, b))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def display_scroll_text(
        ctx: Context,
        text: str,
        direction: str = "l",
        color: str = "r",
        rate: float = 0.5,
    ) -> Any:
        """Scroll text on the 8x8 LED matrix.

        Args:
            text: Text to display (max 70 characters).
            direction: Scroll direction (l=left, r=right, u=up, d=down).
            color: Display color (r=red, b=blue, p=purple).
            rate: Frame rate in Hz (0.1-2.5).
        """
        drone = ctx.lifespan_context["drone"]
        coordinator = ctx.lifespan_context["coordinator"]
        return await coordinator.execute(
            lambda: drone.display_scroll_text(text, direction, color, rate)
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def display_static_char(ctx: Context, char: str, color: str = "r") -> Any:
        """Display a static character on the 8x8 LED matrix.

        Args:
            char: Single ASCII character or "heart".
            color: Display color (r=red, b=blue, p=purple).
        """
        drone = ctx.lifespan_context["drone"]
        coordinator = ctx.lifespan_context["coordinator"]
        return await coordinator.execute(lambda: drone.display_static_char(char, color))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def display_pattern(ctx: Context, pattern: str) -> Any:
        """Display a dot-matrix pattern on the 8x8 LED matrix.

        Args:
            pattern: Up to 64 chars using r (red), b (blue), p (purple), 0 (off).
        """
        drone = ctx.lifespan_context["drone"]
        coordinator = ctx.lifespan_context["coordinator"]
        return await coordinator.execute(lambda: drone.display_pattern(pattern))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def set_pad_detection_direction(ctx: Context, direction: int = 0) -> Any:
        """Set mission pad detection direction.

        Args:
            direction: 0=downward (20Hz), 1=forward (20Hz), 2=both (10Hz each).
        """
        drone = ctx.lifespan_context["drone"]
        coordinator = ctx.lifespan_context["coordinator"]
        return await coordinator.execute(lambda: drone.set_pad_detection_direction(direction))
