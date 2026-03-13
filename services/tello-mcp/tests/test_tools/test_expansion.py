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

    def test_display_matrix_text_registered(self):
        assert "display_matrix_text" in self.registered_tools

    async def test_set_led_color_calls_drone(self):
        mock_queue = AsyncMock()
        mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
        ctx = self._make_ctx(queue=mock_queue)
        result = await self.registered_tools["set_led_color"](ctx, r=255, g=0, b=0)
        mock_queue.enqueue.assert_called_once()
        assert result["status"] == "ok"

    async def test_display_matrix_text_calls_drone(self):
        mock_queue = AsyncMock()
        mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
        ctx = self._make_ctx(queue=mock_queue)
        result = await self.registered_tools["display_matrix_text"](ctx, text="hello")
        mock_queue.enqueue.assert_called_once()
        assert result["status"] == "ok"
