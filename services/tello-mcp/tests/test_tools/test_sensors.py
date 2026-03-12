"""Tests for sensor MCP tools."""

from unittest.mock import MagicMock

import pytest

from tello_mcp.tools.sensors import register


class TestSensorTools:
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

    def test_get_telemetry_registered(self):
        assert "get_telemetry" in self.registered_tools

    def test_get_tof_distance_registered(self):
        assert "get_tof_distance" in self.registered_tools

    def test_detect_mission_pad_registered(self):
        assert "detect_mission_pad" in self.registered_tools
