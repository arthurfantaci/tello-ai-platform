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
            "last_command": overrides.get("last_command", {}),
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

    def test_go_to_mission_pad_registered(self):
        assert "go_to_mission_pad" in self.registered_tools

    async def test_go_to_mission_pad_calls_drone(self):
        mock_queue = AsyncMock()
        mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
        ctx = self._make_ctx(queue=mock_queue)
        result = await self.registered_tools["go_to_mission_pad"](
            ctx,
            x=0,
            y=0,
            z=50,
            speed=30,
            mid=1,
        )
        mock_queue.enqueue.assert_called_once()
        assert result["status"] == "ok"

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

    async def test_takeoff_does_not_publish_on_failure(self):
        """Takeoff event is NOT published when SDK command fails."""
        mock_queue = AsyncMock()
        mock_queue.enqueue = AsyncMock(
            return_value={"error": "COMMAND_FAILED", "detail": "timeout"}
        )
        mock_telemetry = AsyncMock()
        ctx = self._make_ctx(queue=mock_queue, telemetry=mock_telemetry)
        await self.registered_tools["takeoff"](ctx, room_id="living-room")
        mock_telemetry.publish_event.assert_not_called()

    async def test_land_does_not_publish_on_failure(self):
        """Land event is NOT published when SDK command fails."""
        mock_queue = AsyncMock()
        mock_queue.enqueue = AsyncMock(return_value={"error": "LAND_FAILED", "detail": "timeout"})
        mock_telemetry = AsyncMock()
        ctx = self._make_ctx(queue=mock_queue, telemetry=mock_telemetry)
        await self.registered_tools["land"](ctx)
        mock_telemetry.publish_event.assert_not_called()

    async def test_land_publishes_on_success(self):
        """Land event IS published when SDK command succeeds."""
        mock_queue = AsyncMock()
        mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
        mock_telemetry = AsyncMock()
        ctx = self._make_ctx(queue=mock_queue, telemetry=mock_telemetry)
        await self.registered_tools["land"](ctx)
        mock_telemetry.publish_event.assert_called_once()
        assert mock_telemetry.publish_event.call_args[0][0] == "land"
