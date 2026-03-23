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
            "coordinator": overrides.get("coordinator", AsyncMock()),
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

    async def test_go_to_mission_pad_calls_coordinator(self):
        mock_coordinator = AsyncMock()
        mock_coordinator.execute = AsyncMock(return_value={"status": "ok"})
        ctx = self._make_ctx(coordinator=mock_coordinator)
        result = await self.registered_tools["go_to_mission_pad"](
            ctx,
            x=0,
            y=0,
            z=50,
            speed=30,
            mid=1,
        )
        mock_coordinator.execute.assert_called_once()
        assert result["status"] == "ok"

    async def test_takeoff_publishes_room_id(self):
        """Takeoff tool publishes room_id in the stream event."""
        mock_coordinator = AsyncMock()
        mock_coordinator.execute = AsyncMock(return_value={"status": "ok"})
        mock_telemetry = AsyncMock()
        ctx = self._make_ctx(coordinator=mock_coordinator, telemetry=mock_telemetry)
        takeoff = self.registered_tools["takeoff"]
        await takeoff(ctx, room_id="living_room")
        mock_telemetry.publish_event.assert_called_once()
        call_args = mock_telemetry.publish_event.call_args
        assert call_args[0][0] == "takeoff"
        assert call_args[0][1]["room_id"] == "living_room"

    async def test_takeoff_does_not_publish_on_failure(self):
        """Takeoff event is NOT published when SDK command fails."""
        mock_coordinator = AsyncMock()
        mock_coordinator.execute = AsyncMock(
            return_value={"error": "COMMAND_FAILED", "detail": "timeout"}
        )
        mock_telemetry = AsyncMock()
        ctx = self._make_ctx(coordinator=mock_coordinator, telemetry=mock_telemetry)
        await self.registered_tools["takeoff"](ctx, room_id="living-room")
        mock_telemetry.publish_event.assert_not_called()

    async def test_land_does_not_publish_on_failure(self):
        """Land event is NOT published when SDK command fails."""
        mock_coordinator = AsyncMock()
        mock_coordinator.execute = AsyncMock(
            return_value={"error": "LAND_FAILED", "detail": "timeout"}
        )
        mock_telemetry = AsyncMock()
        ctx = self._make_ctx(coordinator=mock_coordinator, telemetry=mock_telemetry)
        await self.registered_tools["land"](ctx)
        mock_telemetry.publish_event.assert_not_called()

    async def test_land_publishes_on_success(self):
        """Land event IS published when SDK command succeeds."""
        mock_coordinator = AsyncMock()
        mock_coordinator.execute = AsyncMock(return_value={"status": "ok"})
        mock_telemetry = AsyncMock()
        ctx = self._make_ctx(coordinator=mock_coordinator, telemetry=mock_telemetry)
        await self.registered_tools["land"](ctx)
        mock_telemetry.publish_event.assert_called_once()
        assert mock_telemetry.publish_event.call_args[0][0] == "land"

    async def test_move_uses_coordinator(self):
        """Move tool delegates to coordinator.execute_move()."""
        mock_coordinator = AsyncMock()
        mock_coordinator.execute_move = AsyncMock(
            return_value={
                "status": "ok",
                "distance_requested_cm": 100,
                "distance_completed_cm": 100,
                "chunks_completed": 5,
                "chunks_total": 5,
                "stopped_reason": None,
            }
        )
        ctx = self._make_ctx(coordinator=mock_coordinator)
        result = await self.registered_tools["move"](ctx, direction="forward", distance_cm=100)
        mock_coordinator.execute_move.assert_called_once_with("forward", 100)
        assert result["status"] == "ok"

    async def test_emergency_stop_bypasses_coordinator(self):
        """Emergency stop calls drone.emergency() directly, not coordinator."""
        mock_drone = MagicMock()
        mock_drone.emergency.return_value = {"status": "ok", "warning": "Motors killed"}
        mock_coordinator = AsyncMock()
        ctx = self._make_ctx(drone=mock_drone, coordinator=mock_coordinator)
        result = await self.registered_tools["emergency_stop"](ctx)
        assert result["status"] == "ok"
        mock_coordinator.execute.assert_not_called()
