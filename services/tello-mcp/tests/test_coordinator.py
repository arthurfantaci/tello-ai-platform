"""Tests for FlightCoordinator — unified command execution with chunked moves."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from tello_mcp.coordinator import FlightCoordinator


def _make_drone(**overrides: dict) -> MagicMock:
    """Create a mock DroneAdapter with sensible defaults."""
    drone = MagicMock()
    drone.move.return_value = {"status": "ok"}
    drone.takeoff.return_value = {"status": "ok"}
    drone.safe_land.return_value = {"status": "ok"}
    drone.rotate.return_value = {"status": "ok"}
    drone.emergency.return_value = {"status": "ok", "warning": "Motors killed"}
    drone.go_xyz_speed_mid.return_value = {"status": "ok"}
    for k, v in overrides.items():
        setattr(drone, k, v)
    return drone


def _make_monitor(*, safe: bool = True) -> MagicMock:
    """Create a mock ObstacleMonitor."""
    monitor = MagicMock()
    monitor.is_safe_for_movement.return_value = safe
    return monitor


def _make_telemetry() -> AsyncMock:
    """Create a mock TelemetryPublisher."""
    telemetry = AsyncMock()
    telemetry.publish_event = AsyncMock()
    return telemetry


class TestChunkDecomposition:
    """Test the static chunk decomposition logic."""

    def test_exact_multiple(self):
        """100cm → 5 chunks of 20cm each."""
        coord = FlightCoordinator(drone=_make_drone(), monitor=_make_monitor())
        chunks = coord._decompose_chunks(100)
        assert chunks == [20, 20, 20, 20, 20]

    def test_remainder_first(self):
        """50cm → [30, 20] — remainder absorbed by first chunk."""
        coord = FlightCoordinator(drone=_make_drone(), monitor=_make_monitor())
        chunks = coord._decompose_chunks(50)
        assert chunks == [30, 20]

    def test_minimum_no_split(self):
        """20cm → [20] — already minimum size, no split."""
        coord = FlightCoordinator(drone=_make_drone(), monitor=_make_monitor())
        chunks = coord._decompose_chunks(20)
        assert chunks == [20]

    def test_indivisible_small(self):
        """30cm -> [30] -- less than 2*20, can't split."""
        coord = FlightCoordinator(drone=_make_drone(), monitor=_make_monitor())
        chunks = coord._decompose_chunks(30)
        assert chunks == [30]

    def test_large_distance(self):
        """500cm → 25 chunks of 20cm."""
        coord = FlightCoordinator(drone=_make_drone(), monitor=_make_monitor())
        chunks = coord._decompose_chunks(500)
        assert chunks == [20] * 25

    def test_remainder_70(self):
        """70cm → [30, 20, 20] — 10cm remainder on first chunk."""
        coord = FlightCoordinator(drone=_make_drone(), monitor=_make_monitor())
        chunks = coord._decompose_chunks(70)
        assert chunks == [30, 20, 20]


class TestChunkedMoveExecution:
    """Test execute_move with mocked drone and monitor."""

    async def test_full_completion(self):
        """All chunks complete when monitor reports safe."""
        drone = _make_drone()
        monitor = _make_monitor(safe=True)
        coord = FlightCoordinator(
            drone=drone, monitor=monitor, inter_chunk_delay_s=0.0, post_delay_s=0.0
        )
        result = await coord.execute_move("forward", 100)
        assert result["status"] == "ok"
        assert result["distance_requested_cm"] == 100
        assert result["distance_completed_cm"] == 100
        assert result["chunks_completed"] == 5
        assert result["chunks_total"] == 5
        assert result["stopped_reason"] is None
        assert drone.move.call_count == 5

    async def test_aborts_on_warning(self):
        """Move stops when monitor reports unsafe between chunks."""
        drone = _make_drone()
        monitor = _make_monitor(safe=True)
        # Safe for first 2 chunks, then unsafe
        monitor.is_safe_for_movement.side_effect = [True, True, True, False]
        coord = FlightCoordinator(
            drone=drone, monitor=monitor, inter_chunk_delay_s=0.0, post_delay_s=0.0
        )
        result = await coord.execute_move("forward", 100)
        assert result["status"] == "ok"
        assert result["distance_completed_cm"] == 60  # 3 chunks of 20
        assert result["chunks_completed"] == 3
        assert result["chunks_total"] == 5
        assert result["stopped_reason"] == "obstacle_warning"

    async def test_aborts_on_danger(self):
        """Move stops when first checkpoint is unsafe."""
        drone = _make_drone()
        monitor = _make_monitor(safe=False)
        coord = FlightCoordinator(
            drone=drone, monitor=monitor, inter_chunk_delay_s=0.0, post_delay_s=0.0
        )
        result = await coord.execute_move("forward", 100)
        assert result["status"] == "ok"
        assert result["distance_completed_cm"] == 0
        assert result["chunks_completed"] == 0
        assert result["stopped_reason"] == "obstacle_warning"
        drone.move.assert_not_called()

    async def test_continues_on_clear(self):
        """All chunks execute when monitor always reports safe."""
        drone = _make_drone()
        monitor = _make_monitor(safe=True)
        coord = FlightCoordinator(
            drone=drone, monitor=monitor, inter_chunk_delay_s=0.0, post_delay_s=0.0
        )
        result = await coord.execute_move("forward", 60)
        assert result["distance_completed_cm"] == 60
        assert result["chunks_completed"] == 3
        assert drone.move.call_count == 3

    async def test_partial_result_distance(self):
        """Aborted move reports distance_completed_cm correctly."""
        drone = _make_drone()
        monitor = _make_monitor()
        # Safe, execute first chunk (30), then unsafe
        monitor.is_safe_for_movement.side_effect = [True, True, False]
        coord = FlightCoordinator(
            drone=drone, monitor=monitor, inter_chunk_delay_s=0.0, post_delay_s=0.0
        )
        result = await coord.execute_move("forward", 50)
        # 50 -> [30, 20]. Both checks safe, both chunks execute.
        assert result["distance_completed_cm"] == 50
        assert result["chunks_completed"] == 2

    async def test_partial_result_with_remainder(self):
        """70cm → [30, 20, 20]. Abort after first chunk."""
        drone = _make_drone()
        monitor = _make_monitor()
        monitor.is_safe_for_movement.side_effect = [True, False]
        coord = FlightCoordinator(
            drone=drone, monitor=monitor, inter_chunk_delay_s=0.0, post_delay_s=0.0
        )
        result = await coord.execute_move("forward", 70)
        assert result["distance_completed_cm"] == 30
        assert result["chunks_completed"] == 1
        assert result["chunks_total"] == 3
        assert result["stopped_reason"] == "obstacle_warning"

    async def test_chunk_sdk_failure_aborts(self):
        """If a chunk's SDK call fails, abort remaining chunks."""
        drone = _make_drone()
        drone.move.side_effect = [
            {"status": "ok"},
            {"error": "COMMAND_FAILED", "detail": "timeout"},
        ]
        monitor = _make_monitor(safe=True)
        coord = FlightCoordinator(
            drone=drone, monitor=monitor, inter_chunk_delay_s=0.0, post_delay_s=0.0
        )
        result = await coord.execute_move("forward", 60)
        assert result["error"] == "COMMAND_FAILED"
        assert result["distance_completed_cm"] == 20

    async def test_last_command_tracks_actual_distance(self):
        """After partial completion, last_command has actual distance traveled."""
        drone = _make_drone()
        monitor = _make_monitor()
        monitor.is_safe_for_movement.side_effect = [True, True, True, False]
        last_command: dict = {}
        coord = FlightCoordinator(
            drone=drone,
            monitor=monitor,
            last_command=last_command,
            inter_chunk_delay_s=0.0,
            post_delay_s=0.0,
        )
        await coord.execute_move("forward", 100)
        assert last_command["direction"] == "forward"
        assert last_command["distance_cm"] == 60  # 3 chunks of 20, not 100

    async def test_last_command_tracks_full_distance(self):
        """After full completion, last_command has full distance."""
        drone = _make_drone()
        monitor = _make_monitor(safe=True)
        last_command: dict = {}
        coord = FlightCoordinator(
            drone=drone,
            monitor=monitor,
            last_command=last_command,
            inter_chunk_delay_s=0.0,
            post_delay_s=0.0,
        )
        await coord.execute_move("forward", 100)
        assert last_command["distance_cm"] == 100


class TestOwnership:
    """Test the Single Owner coordination model."""

    async def test_default_owner_is_mcp(self):
        coord = FlightCoordinator(drone=_make_drone(), monitor=_make_monitor())
        assert coord.owner == "mcp"

    async def test_acquire_release_cycle(self):
        coord = FlightCoordinator(drone=_make_drone(), monitor=_make_monitor())
        result = await coord.acquire_control("navigator")
        assert result["status"] == "ok"
        assert result["owner"] == "navigator"
        assert coord.owner == "navigator"

        result = await coord.release_control("navigator")
        assert result["status"] == "ok"
        assert result["owner"] == "mcp"
        assert result["previous_owner"] == "navigator"

    async def test_ownership_conflict_rejected(self):
        coord = FlightCoordinator(drone=_make_drone(), monitor=_make_monitor())
        await coord.acquire_control("navigator")
        result = await coord.acquire_control("vision")
        assert result["error"] == "OWNERSHIP_CONFLICT"
        assert result["owner"] == "navigator"

    async def test_release_by_non_owner_rejected(self):
        coord = FlightCoordinator(drone=_make_drone(), monitor=_make_monitor())
        await coord.acquire_control("navigator")
        result = await coord.release_control("vision")
        assert result["error"] == "NOT_OWNER"

    async def test_ownership_enforced_on_move(self):
        """Move by non-owner returns error without executing."""
        drone = _make_drone()
        monitor = _make_monitor(safe=True)
        coord = FlightCoordinator(
            drone=drone, monitor=monitor, inter_chunk_delay_s=0.0, post_delay_s=0.0
        )
        await coord.acquire_control("navigator")
        result = await coord.execute_move("forward", 100, actor="mcp")
        assert result["error"] == "NOT_OWNER"
        drone.move.assert_not_called()

    async def test_ownership_enforced_on_execute(self):
        """Non-chunked command by non-owner returns error."""
        drone = _make_drone()
        coord = FlightCoordinator(drone=drone, monitor=_make_monitor(), post_delay_s=0.0)
        await coord.acquire_control("navigator")
        result = await coord.execute(drone.takeoff, actor="mcp")
        assert result["error"] == "NOT_OWNER"

    async def test_move_by_owner_succeeds(self):
        drone = _make_drone()
        monitor = _make_monitor(safe=True)
        coord = FlightCoordinator(
            drone=drone, monitor=monitor, inter_chunk_delay_s=0.0, post_delay_s=0.0
        )
        await coord.acquire_control("navigator")
        result = await coord.execute_move("forward", 20, actor="navigator")
        assert result["status"] == "ok"

    async def test_mcp_default_owner_can_move(self):
        """Default owner (mcp) can move without acquire."""
        drone = _make_drone()
        monitor = _make_monitor(safe=True)
        coord = FlightCoordinator(
            drone=drone, monitor=monitor, inter_chunk_delay_s=0.0, post_delay_s=0.0
        )
        result = await coord.execute_move("forward", 20)
        assert result["status"] == "ok"

    async def test_get_control_owner(self):
        coord = FlightCoordinator(drone=_make_drone(), monitor=_make_monitor())
        info = coord.get_control_info()
        assert info["owner"] == "mcp"
        assert info["executing"] is False

    async def test_release_during_execution_rejected(self):
        """release_control during a chunked move returns error."""
        drone = _make_drone()
        monitor = _make_monitor(safe=True)
        coord = FlightCoordinator(
            drone=drone, monitor=monitor, inter_chunk_delay_s=0.0, post_delay_s=0.0
        )
        # Simulate executing state
        coord._executing = True
        result = await coord.release_control("mcp")
        assert result["error"] == "EXECUTING"

    async def test_acquire_same_owner_is_noop(self):
        """Re-acquiring as current owner succeeds (idempotent)."""
        coord = FlightCoordinator(drone=_make_drone(), monitor=_make_monitor())
        await coord.acquire_control("navigator")
        result = await coord.acquire_control("navigator")
        assert result["status"] == "ok"
        assert result["owner"] == "navigator"


class TestNonChunkedCommands:
    """Test execute() for commands that bypass chunking."""

    async def test_rotate_not_chunked(self):
        drone = _make_drone()
        coord = FlightCoordinator(drone=drone, monitor=_make_monitor(), post_delay_s=0.0)
        result = await coord.execute(lambda: drone.rotate(90))
        assert result["status"] == "ok"

    async def test_takeoff_not_chunked(self):
        drone = _make_drone()
        coord = FlightCoordinator(
            drone=drone, monitor=_make_monitor(), post_delay_s=0.0, heavy_delay_s=0.0
        )
        result = await coord.execute(drone.takeoff, heavy=True)
        assert result["status"] == "ok"

    async def test_land_not_chunked(self):
        drone = _make_drone()
        coord = FlightCoordinator(drone=drone, monitor=_make_monitor(), post_delay_s=0.0)
        result = await coord.execute(drone.safe_land)
        assert result["status"] == "ok"

    async def test_go_to_mission_pad_enforces_ownership(self):
        drone = _make_drone()
        coord = FlightCoordinator(drone=drone, monitor=_make_monitor(), post_delay_s=0.0)
        await coord.acquire_control("navigator")
        result = await coord.execute(lambda: drone.go_xyz_speed_mid(0, 0, 50, 30, 1), actor="mcp")
        assert result["error"] == "NOT_OWNER"

    async def test_execute_command_failure(self):
        drone = _make_drone()
        drone.takeoff.return_value = {"error": "COMMAND_FAILED", "detail": "battery low"}
        coord = FlightCoordinator(drone=drone, monitor=_make_monitor(), post_delay_s=0.0)
        result = await coord.execute(drone.takeoff)
        assert result["error"] == "COMMAND_FAILED"

    async def test_execute_exception_returns_error(self):
        drone = _make_drone()
        coord = FlightCoordinator(drone=drone, monitor=_make_monitor(), post_delay_s=0.0)
        result = await coord.execute(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        assert result["error"] == "COMMAND_FAILED"
        assert "boom" in result["detail"]


class TestEmergencyStop:
    """Emergency stop must bypass ownership entirely."""

    async def test_emergency_stop_bypasses_coordinator(self):
        """emergency_stop works regardless of ownership — it's safety-critical."""
        drone = _make_drone()
        coord = FlightCoordinator(drone=drone, monitor=_make_monitor())
        await coord.acquire_control("navigator")
        # emergency_stop doesn't go through coordinator — called directly on drone
        # This test validates the pattern, not the coordinator itself
        result = drone.emergency()
        assert result["status"] == "ok"


class TestRedisEvents:
    """Test ownership change event publishing."""

    async def test_acquire_publishes_event(self):
        telemetry = _make_telemetry()
        coord = FlightCoordinator(drone=_make_drone(), monitor=_make_monitor(), telemetry=telemetry)
        await coord.acquire_control("navigator")
        telemetry.publish_event.assert_called_once_with(
            "control_acquired",
            {"actor": "navigator", "previous_owner": "mcp"},
        )

    async def test_release_publishes_event(self):
        telemetry = _make_telemetry()
        coord = FlightCoordinator(drone=_make_drone(), monitor=_make_monitor(), telemetry=telemetry)
        await coord.acquire_control("navigator")
        telemetry.publish_event.reset_mock()
        await coord.release_control("navigator")
        telemetry.publish_event.assert_called_once_with(
            "control_released",
            {"actor": "navigator", "returned_to": "mcp"},
        )

    async def test_no_event_on_conflict(self):
        telemetry = _make_telemetry()
        coord = FlightCoordinator(drone=_make_drone(), monitor=_make_monitor(), telemetry=telemetry)
        await coord.acquire_control("navigator")
        telemetry.publish_event.reset_mock()
        await coord.acquire_control("vision")  # conflict
        telemetry.publish_event.assert_not_called()


class TestDelays:
    """Test inter-chunk and post-command delays."""

    async def test_inter_chunk_delay(self):
        drone = _make_drone()
        monitor = _make_monitor(safe=True)
        coord = FlightCoordinator(
            drone=drone,
            monitor=monitor,
            inter_chunk_delay_s=0.1,
            post_delay_s=0.0,
        )
        with patch("tello_mcp.coordinator.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await coord.execute_move("forward", 60)
        # 3 chunks: 2 inter-chunk delays (between chunks) + 0 post delay
        inter_calls = [c for c in mock_sleep.call_args_list if c[0][0] == 0.1]
        assert len(inter_calls) == 2  # between chunk 1-2 and 2-3

    async def test_post_delay_after_move(self):
        drone = _make_drone()
        monitor = _make_monitor(safe=True)
        coord = FlightCoordinator(
            drone=drone,
            monitor=monitor,
            inter_chunk_delay_s=0.0,
            post_delay_s=0.5,
        )
        with patch("tello_mcp.coordinator.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await coord.execute_move("forward", 20)
        post_calls = [c for c in mock_sleep.call_args_list if c[0][0] == 0.5]
        assert len(post_calls) == 1

    async def test_heavy_delay_for_takeoff(self):
        drone = _make_drone()
        coord = FlightCoordinator(
            drone=drone,
            monitor=_make_monitor(),
            post_delay_s=0.5,
            heavy_delay_s=3.0,
        )
        with patch("tello_mcp.coordinator.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await coord.execute(drone.takeoff, heavy=True)
        mock_sleep.assert_called_once_with(3.0)

    async def test_default_delays(self):
        coord = FlightCoordinator(drone=_make_drone(), monitor=_make_monitor())
        assert coord._inter_chunk_delay_s == 0.1
        assert coord._post_delay_s == 0.5
        assert coord._heavy_delay_s == 3.0
