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

    def test_get_forward_distance_registered(self):
        assert "get_forward_distance" in self.registered_tools

    def test_get_obstacle_status_registered(self):
        assert "get_obstacle_status" in self.registered_tools

    async def test_get_forward_distance_returns_reading(self):
        from datetime import datetime
        from unittest.mock import MagicMock

        from tello_core.models import ObstacleReading, ObstacleZone

        mock_monitor = MagicMock()
        mock_monitor.latest = ObstacleReading(
            distance_mm=750,
            zone=ObstacleZone.WARNING,
            timestamp=datetime(2026, 3, 16, 14, 0, 0),
        )
        ctx = MagicMock()
        ctx.lifespan_context = {"monitor": mock_monitor, "drone": MagicMock()}
        tool_fn = self.registered_tools["get_forward_distance"]
        result = await tool_fn(ctx)
        assert result["distance_mm"] == 750
        assert result["zone"] == "warning"

    async def test_get_forward_distance_no_reading(self):
        from unittest.mock import MagicMock

        mock_monitor = MagicMock()
        mock_monitor.latest = None
        ctx = MagicMock()
        ctx.lifespan_context = {"monitor": mock_monitor}
        tool_fn = self.registered_tools["get_forward_distance"]
        result = await tool_fn(ctx)
        assert result["error"] == "NO_READING"

    async def test_get_obstacle_status_safe(self):
        from datetime import datetime
        from unittest.mock import MagicMock

        from tello_core.models import ObstacleReading, ObstacleZone

        mock_monitor = MagicMock()
        mock_monitor.latest = ObstacleReading(
            distance_mm=2000,
            zone=ObstacleZone.CLEAR,
            timestamp=datetime(2026, 3, 16, 14, 0, 0),
        )
        ctx = MagicMock()
        ctx.lifespan_context = {"monitor": mock_monitor}
        tool_fn = self.registered_tools["get_obstacle_status"]
        result = await tool_fn(ctx)
        assert result["zone"] == "clear"
        assert result["is_safe"] is True

    async def test_get_obstacle_status_danger(self):
        from datetime import datetime
        from unittest.mock import MagicMock

        from tello_core.models import ObstacleReading, ObstacleZone

        mock_monitor = MagicMock()
        mock_monitor.latest = ObstacleReading(
            distance_mm=300,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 16, 14, 0, 0),
        )
        ctx = MagicMock()
        ctx.lifespan_context = {"monitor": mock_monitor}
        tool_fn = self.registered_tools["get_obstacle_status"]
        result = await tool_fn(ctx)
        assert result["zone"] == "danger"
        assert result["is_safe"] is False

    async def test_get_obstacle_status_no_sensor(self):
        from unittest.mock import MagicMock

        mock_monitor = MagicMock()
        mock_monitor.latest = None
        ctx = MagicMock()
        ctx.lifespan_context = {"monitor": mock_monitor}
        tool_fn = self.registered_tools["get_obstacle_status"]
        result = await tool_fn(ctx)
        assert result["zone"] == "unknown"
