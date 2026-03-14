"""Tests for expansion board MCP tools."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tello_mcp.tools.expansion import register


class TestExpansionTools:
    @pytest.fixture(autouse=True)
    def setup_mcp(self):
        self.mcp = MagicMock()
        self.registered_tools = {}

        def mock_tool(*args, **kwargs):
            if args and callable(args[0]):
                fn = args[0]
                self.registered_tools[fn.__name__] = fn
                return fn

            def decorator(fn):
                self.registered_tools[fn.__name__] = fn
                return fn

            return decorator

        self.mcp.tool = mock_tool
        register(self.mcp)

    def _make_ctx(self, **overrides):
        ctx = MagicMock()
        ctx.lifespan_context = {
            "drone": overrides.get("drone", MagicMock()),
            "queue": overrides.get("queue", AsyncMock()),
        }
        return ctx

    def test_set_led_color_registered(self):
        assert "set_led_color" in self.registered_tools

    def test_display_scroll_text_registered(self):
        assert "display_scroll_text" in self.registered_tools

    def test_display_static_char_registered(self):
        assert "display_static_char" in self.registered_tools

    def test_display_pattern_registered(self):
        assert "display_pattern" in self.registered_tools

    def test_set_pad_detection_direction_registered(self):
        assert "set_pad_detection_direction" in self.registered_tools

    async def test_set_led_color_calls_drone(self):
        mock_queue = AsyncMock()
        mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
        ctx = self._make_ctx(queue=mock_queue)
        result = await self.registered_tools["set_led_color"](ctx, r=255, g=0, b=0)
        mock_queue.enqueue.assert_called_once()
        assert result["status"] == "ok"

    async def test_display_scroll_text_calls_drone(self):
        mock_queue = AsyncMock()
        mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
        ctx = self._make_ctx(queue=mock_queue)
        result = await self.registered_tools["display_scroll_text"](
            ctx,
            text="hello",
            direction="l",
            color="r",
            rate=0.5,
        )
        mock_queue.enqueue.assert_called_once()
        assert result["status"] == "ok"

    async def test_display_static_char_calls_drone(self):
        mock_queue = AsyncMock()
        mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
        ctx = self._make_ctx(queue=mock_queue)
        result = await self.registered_tools["display_static_char"](
            ctx,
            char="heart",
            color="b",
        )
        mock_queue.enqueue.assert_called_once()
        assert result["status"] == "ok"

    async def test_display_pattern_calls_drone(self):
        mock_queue = AsyncMock()
        mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
        ctx = self._make_ctx(queue=mock_queue)
        result = await self.registered_tools["display_pattern"](
            ctx,
            pattern="rrrrbbbb" + "0" * 56,
        )
        mock_queue.enqueue.assert_called_once()
        assert result["status"] == "ok"

    async def test_set_pad_detection_direction_calls_drone(self):
        mock_queue = AsyncMock()
        mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
        ctx = self._make_ctx(queue=mock_queue)
        result = await self.registered_tools["set_pad_detection_direction"](
            ctx,
            direction=2,
        )
        mock_queue.enqueue.assert_called_once()
        assert result["status"] == "ok"
