"""Tests for flight control MCP tools."""

from unittest.mock import AsyncMock, MagicMock

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

    def _make_ctx(self, **overrides):
        """Build a mock Context with lifespan_context."""
        ctx = MagicMock()
        ctx.lifespan_context = {
            "drone": overrides.get("drone", MagicMock()),
            "queue": overrides.get("queue", AsyncMock()),
            "telemetry": overrides.get("telemetry", AsyncMock()),
            "config": overrides.get("config", MagicMock()),
        }
        return ctx

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

    async def test_takeoff_publishes_room_id(self):
        """Takeoff tool publishes room_id in the stream event."""
        mock_queue = AsyncMock()
        mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
        mock_telemetry = AsyncMock()
        ctx = self._make_ctx(queue=mock_queue, telemetry=mock_telemetry)
        takeoff = self.registered_tools["takeoff"]
        await takeoff(ctx, room_id="living_room")
        mock_telemetry.publish_event.assert_called_once()
        call_args = mock_telemetry.publish_event.call_args
        assert call_args[0][0] == "takeoff"
        assert call_args[0][1]["room_id"] == "living_room"
