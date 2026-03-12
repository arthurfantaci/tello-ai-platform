"""Tests for flight control MCP tools."""

from unittest.mock import MagicMock

import pytest

from tello_mcp.tools.flight import register


class TestFlightTools:
    @pytest.fixture(autouse=True)
    def setup_mcp(self):
        """Create a mock FastMCP server and register tools."""
        self.mcp = MagicMock()
        self.registered_tools = {}

        def mock_tool(*args, **kwargs):
            """Capture tool registrations."""
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

    def test_takeoff_registered(self):
        assert "takeoff" in self.registered_tools

    def test_land_registered(self):
        assert "land" in self.registered_tools

    def test_emergency_stop_registered(self):
        assert "emergency_stop" in self.registered_tools

    def test_move_registered(self):
        assert "move" in self.registered_tools

    def test_rotate_registered(self):
        assert "rotate" in self.registered_tools
