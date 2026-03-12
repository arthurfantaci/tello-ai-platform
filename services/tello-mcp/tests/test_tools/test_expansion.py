"""Tests for expansion board MCP tools."""

from unittest.mock import MagicMock

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

    def test_set_led_color_registered(self):
        assert "set_led_color" in self.registered_tools

    def test_display_matrix_text_registered(self):
        assert "display_matrix_text" in self.registered_tools
