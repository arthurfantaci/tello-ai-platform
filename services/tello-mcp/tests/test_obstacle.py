"""Tests for ObstacleMonitor, ObstacleConfig, and ObstacleResponseHandler."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from tello_core.models import ObstacleReading, ObstacleZone
from tello_mcp.obstacle import (
    CLIResponseProvider,
    ObstacleConfig,
    ObstacleMonitor,
    ObstacleResponse,
    ObstacleResponseHandler,
)
from tello_mcp.strategies import ObstacleContext


class TestObstacleConfig:
    def test_default_values(self):
        config = ObstacleConfig()
        assert config.caution_mm == 500
        assert config.warning_mm == 300
        assert config.danger_mm == 200
        assert config.out_of_range_min == 8000
        assert config.required_clear_readings == 3
        assert config.poll_interval_ms == 200

    def test_custom_values(self):
        config = ObstacleConfig(danger_mm=500, poll_interval_ms=100)
        assert config.danger_mm == 500
        assert config.poll_interval_ms == 100
        assert config.caution_mm == 500  # unchanged default

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("OBSTACLE_DANGER_MM", "500")
        monkeypatch.setenv("OBSTACLE_POLL_INTERVAL_MS", "100")
        config = ObstacleConfig.from_env()
        assert config.danger_mm == 500
        assert config.poll_interval_ms == 100
        assert config.caution_mm == 500  # default

    def test_from_env_no_vars(self):
        config = ObstacleConfig.from_env()
        assert config.danger_mm == 200  # default

    def test_frozen(self):
        config = ObstacleConfig()
        with pytest.raises(AttributeError):
            config.danger_mm = 999


class TestClassifyZone:
    """Tests for the pure zone classification function."""

    def setup_method(self):
        self.config = ObstacleConfig()
        self.monitor = ObstacleMonitor(MagicMock(), self.config)

    def test_out_of_range_is_clear(self):
        assert self.monitor.classify_zone(8000) == ObstacleZone.CLEAR

    def test_well_above_out_of_range_is_clear(self):
        assert self.monitor.classify_zone(8190) == ObstacleZone.CLEAR

    def test_above_caution_is_clear(self):
        assert self.monitor.classify_zone(600) == ObstacleZone.CLEAR

    def test_at_caution_boundary_is_clear(self):
        assert self.monitor.classify_zone(500) == ObstacleZone.CLEAR

    def test_below_caution_is_caution(self):
        assert self.monitor.classify_zone(499) == ObstacleZone.CAUTION

    def test_at_warning_boundary_is_caution(self):
        assert self.monitor.classify_zone(300) == ObstacleZone.CAUTION

    def test_below_warning_is_warning(self):
        assert self.monitor.classify_zone(299) == ObstacleZone.WARNING

    def test_at_danger_boundary_is_warning(self):
        assert self.monitor.classify_zone(200) == ObstacleZone.WARNING

    def test_below_danger_is_danger(self):
        assert self.monitor.classify_zone(199) == ObstacleZone.DANGER

    def test_zero_is_danger(self):
        assert self.monitor.classify_zone(0) == ObstacleZone.DANGER

    def test_custom_thresholds(self):
        config = ObstacleConfig(caution_mm=1000, warning_mm=500, danger_mm=200)
        monitor = ObstacleMonitor(MagicMock(), config)
        assert monitor.classify_zone(999) == ObstacleZone.CAUTION
        assert monitor.classify_zone(499) == ObstacleZone.WARNING
        assert monitor.classify_zone(199) == ObstacleZone.DANGER


class TestObstacleMonitorLifecycle:
    async def test_start_is_idempotent(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 8000}
        monitor = ObstacleMonitor(drone, ObstacleConfig(poll_interval_ms=50))
        await monitor.start()
        task1 = monitor._task
        await monitor.start()  # second call
        assert monitor._task is task1  # same task
        await monitor.stop()

    async def test_stop_when_not_started(self):
        drone = MagicMock()
        monitor = ObstacleMonitor(drone)
        await monitor.stop()  # should not raise


class TestObstacleMonitorPolling:
    async def test_poll_caches_latest_reading(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 400}
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)
        await monitor.start()
        await asyncio.sleep(0.15)  # allow a few polls
        await monitor.stop()
        assert monitor.latest is not None
        assert monitor.latest.distance_mm == 400
        assert monitor.latest.zone == ObstacleZone.CAUTION

    async def test_danger_zone_calls_stop(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 150}
        drone.stop = MagicMock(return_value={"status": "ok"})
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)
        await monitor.start()
        await asyncio.sleep(0.15)
        await monitor.stop()
        drone.stop.assert_called()

    async def test_clear_zone_does_not_call_stop(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 8000}
        drone.stop = MagicMock()
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)
        await monitor.start()
        await asyncio.sleep(0.15)
        await monitor.stop()
        drone.stop.assert_not_called()

    async def test_sensor_error_skips_reading(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"error": "COMMAND_FAILED", "detail": "timeout"}
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)
        await monitor.start()
        await asyncio.sleep(0.15)
        await monitor.stop()
        assert monitor.latest is None

    async def test_sync_callback_invoked(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 500}
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)
        readings: list = []
        monitor.on_reading(readings.append)
        await monitor.start()
        await asyncio.sleep(0.15)
        await monitor.stop()
        assert len(readings) > 0
        assert readings[0].distance_mm == 500

    async def test_async_callback_invoked(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 600}
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)
        readings: list = []

        async def async_cb(r):
            readings.append(r)

        monitor.on_reading(async_cb)
        await monitor.start()
        await asyncio.sleep(0.15)
        await monitor.stop()
        assert len(readings) > 0
        assert readings[0].distance_mm == 600

    async def test_callback_exception_does_not_kill_monitor(self):
        """Poll loop survives a callback that raises an exception."""
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 600}
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)

        call_count = 0

        def exploding_callback(reading):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                msg = "boom"
                raise RuntimeError(msg)

        monitor.on_reading(exploding_callback)
        await monitor.start()
        await asyncio.sleep(0.2)
        await monitor.stop()
        assert call_count >= 2

    async def test_callback_exception_is_logged(self, capsys):
        """Callback exception is logged for diagnosis."""
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 600}
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)

        def exploding_callback(reading):
            msg = "boom"
            raise RuntimeError(msg)

        monitor.on_reading(exploding_callback)
        await monitor.start()
        await asyncio.sleep(0.15)
        await monitor.stop()
        captured = capsys.readouterr()
        assert "callback_failed" in captured.out or "boom" in captured.out


class TestObstacleResponse:
    def test_response_values(self):
        assert ObstacleResponse.EMERGENCY_LAND == "emergency_land"
        assert ObstacleResponse.RETURN_TO_HOME == "return_to_home"
        assert ObstacleResponse.AVOID_AND_CONTINUE == "avoid_and_continue"
        assert ObstacleResponse.MANUAL_OVERRIDE == "manual_override"


class TestObstacleResponseHandler:
    async def test_execute_emergency_land(self):
        drone = MagicMock()
        drone.safe_land.return_value = {"status": "ok"}
        handler = ObstacleResponseHandler(drone)
        result = await handler.execute(ObstacleResponse.EMERGENCY_LAND)
        drone.safe_land.assert_called_once()
        assert result["status"] == "ok"

    async def test_execute_manual_override(self):
        drone = MagicMock()
        handler = ObstacleResponseHandler(drone)
        result = await handler.execute(ObstacleResponse.MANUAL_OVERRIDE)
        assert result["status"] == "ok"

    async def test_execute_return_to_home_not_configured(self):
        drone = MagicMock()
        handler = ObstacleResponseHandler(drone)
        result = await handler.execute(ObstacleResponse.RETURN_TO_HOME)
        assert result["error"] == "NOT_CONFIGURED"

    async def test_execute_avoid_and_continue_not_implemented(self):
        drone = MagicMock()
        handler = ObstacleResponseHandler(drone)
        result = await handler.execute(ObstacleResponse.AVOID_AND_CONTINUE)
        assert result["error"] == "NOT_IMPLEMENTED"


class TestObstacleResponseHandlerDI:
    """Tests for the updated handler with DI and event publishing."""

    def _make_handler(self):
        drone = MagicMock()
        drone.safe_land.return_value = {"status": "ok"}
        strategy = MagicMock()
        strategy.return_to_home.return_value = {
            "status": "returned",
            "method": "simple_reverse",
            "reversed_direction": "back",
            "height_cm": 80,
            "forward_distance_mm": 185,
            "landed": True,
        }
        telemetry = AsyncMock()
        telemetry.publish_event = AsyncMock()
        handler = ObstacleResponseHandler(
            drone=drone,
            rth_strategy=strategy,
            telemetry=telemetry,
        )
        return handler, drone, strategy, telemetry

    async def test_return_to_home_calls_strategy(self):
        handler, drone, strategy, _tel = self._make_handler()
        ctx = ObstacleContext(
            last_direction="forward",
            last_distance_cm=100,
            height_cm=80,
            forward_distance_mm=185,
        )
        result = await handler.execute(ObstacleResponse.RETURN_TO_HOME, ctx)
        strategy.return_to_home.assert_called_once_with(drone, ctx)
        assert result["status"] == "returned"

    async def test_return_to_home_publishes_obstacle_event(self):
        handler, _drone, _strategy, telemetry = self._make_handler()
        ctx = ObstacleContext(
            last_direction="forward",
            last_distance_cm=100,
            height_cm=80,
            forward_distance_mm=185,
            mission_id="m1",
            room_id="living-room",
        )
        await handler.execute(ObstacleResponse.RETURN_TO_HOME, ctx)
        calls = telemetry.publish_event.call_args_list
        event_types = [c[0][0] for c in calls]
        assert "obstacle_danger" in event_types
        assert "land" in event_types

    async def test_emergency_land_still_works(self):
        handler, drone, _strategy, _tel = self._make_handler()
        result = await handler.execute(ObstacleResponse.EMERGENCY_LAND)
        drone.safe_land.assert_called_once()
        assert result["status"] == "ok"

    async def test_manual_override_still_works(self):
        handler, _drone, _strategy, _tel = self._make_handler()
        result = await handler.execute(ObstacleResponse.MANUAL_OVERRIDE)
        assert result["status"] == "ok"

    async def test_on_obstacle_reading_triggers_rth_on_danger(self):
        handler, drone, strategy, _tel = self._make_handler()
        handler._last_command = {"direction": "forward", "distance_cm": 100}
        drone.get_height.return_value = {"status": "ok", "height_cm": 80}

        reading = ObstacleReading(
            distance_mm=185,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 18),
        )
        await handler.on_obstacle_reading(reading)
        strategy.return_to_home.assert_called_once()

    async def test_on_obstacle_reading_ignores_non_danger(self):
        handler, _drone, strategy, _tel = self._make_handler()
        reading = ObstacleReading(
            distance_mm=400,
            zone=ObstacleZone.CAUTION,
            timestamp=datetime(2026, 3, 18),
        )
        await handler.on_obstacle_reading(reading)
        strategy.return_to_home.assert_not_called()


class TestObstacleMonitorDebounce:
    """Tests for DANGER exit debouncing in the poll loop."""

    def _make_monitor(self, readings: list[int], poll_ms: int = 50) -> tuple:
        """Create a monitor with a sequence of mocked readings.

        A sentinel error dict is appended so the poll loop skips cleanly
        after the reading list is exhausted rather than raising StopIteration
        inside asyncio.to_thread.
        """
        drone = MagicMock()
        _sentinel = {"error": "EXHAUSTED", "detail": "no more readings"}
        drone.get_forward_distance.side_effect = [
            {"status": "ok", "distance_mm": mm} for mm in readings
        ] + [_sentinel] * 20
        drone.stop = MagicMock(return_value={"status": "ok"})
        config = ObstacleConfig(
            poll_interval_ms=poll_ms,
            required_clear_readings=3,
        )
        monitor = ObstacleMonitor(drone, config)
        return monitor, drone

    async def test_danger_entry_is_immediate(self):
        """Single DANGER reading triggers drone.stop() with no delay."""
        monitor, drone = self._make_monitor([150])
        await monitor.start()
        await asyncio.sleep(0.1)
        await monitor.stop()
        drone.stop.assert_called()
        assert monitor.latest.zone == ObstacleZone.DANGER

    async def test_danger_exit_requires_consecutive_clear(self):
        """3 consecutive non-DANGER readings needed to exit DANGER."""
        # DANGER, then 2 clear (not enough), then 1 DANGER (reset),
        # then 3 clear (enough to exit)
        readings = [150, 600, 600, 150, 600, 600, 600]
        monitor, drone = self._make_monitor(readings)
        collected: list[ObstacleReading] = []
        monitor.on_reading(collected.append)
        await monitor.start()
        await asyncio.sleep(0.5)
        await monitor.stop()
        zones = [r.zone for r in collected]
        assert zones[0] == ObstacleZone.DANGER
        assert zones[1] == ObstacleZone.DANGER
        assert zones[2] == ObstacleZone.DANGER
        assert zones[3] == ObstacleZone.DANGER
        assert zones[4] == ObstacleZone.DANGER
        assert zones[5] == ObstacleZone.DANGER
        assert zones[6] == ObstacleZone.CLEAR

    async def test_debounce_does_not_apply_to_non_danger(self):
        """CAUTION/WARNING/CLEAR transitions are instant, no debounce."""
        readings = [400, 250, 400]  # CAUTION -> WARNING -> CAUTION
        monitor, _drone = self._make_monitor(readings)
        collected: list[ObstacleReading] = []
        monitor.on_reading(collected.append)
        await monitor.start()
        await asyncio.sleep(0.25)
        await monitor.stop()
        zones = [r.zone for r in collected]
        assert zones[0] == ObstacleZone.CAUTION
        assert zones[1] == ObstacleZone.WARNING
        assert zones[2] == ObstacleZone.CAUTION

    async def test_single_danger_during_debounce_resets_counter(self):
        """A DANGER reading mid-debounce resets the clear counter."""
        readings = [150, 600, 600, 150, 600]
        monitor, _drone = self._make_monitor(readings)
        collected: list[ObstacleReading] = []
        monitor.on_reading(collected.append)
        await monitor.start()
        await asyncio.sleep(0.35)
        await monitor.stop()
        zones = [r.zone for r in collected]
        assert all(z == ObstacleZone.DANGER for z in zones)


class TestRTHGuards:
    """Tests for on_obstacle_reading guards that prevent re-entry and grounded RTH."""

    def _make_handler(self):
        drone = MagicMock()
        drone.safe_land.return_value = {"status": "ok"}
        strategy = MagicMock()
        strategy.return_to_home.return_value = {
            "status": "returned",
            "method": "simple_reverse",
            "reversed_direction": "back",
            "height_cm": 80,
            "forward_distance_mm": 185,
            "landed": True,
        }
        telemetry = AsyncMock()
        telemetry.publish_event = AsyncMock()
        handler = ObstacleResponseHandler(
            drone=drone,
            rth_strategy=strategy,
            telemetry=telemetry,
            last_command={"direction": "forward", "distance_cm": 50},
        )
        return handler, drone, strategy, telemetry

    async def test_rth_skipped_when_active(self):
        """on_obstacle_reading returns immediately if RTH is already in progress."""
        handler, _drone, strategy, _tel = self._make_handler()
        handler._rth_active = True

        reading = ObstacleReading(
            distance_mm=185,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 20),
        )
        await handler.on_obstacle_reading(reading)
        strategy.return_to_home.assert_not_called()

    async def test_rth_skipped_when_grounded(self):
        """on_obstacle_reading returns immediately if drone is on the ground."""
        handler, drone, strategy, _tel = self._make_handler()
        drone.get_height.return_value = {"status": "ok", "height_cm": 0}

        reading = ObstacleReading(
            distance_mm=185,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 20),
        )
        await handler.on_obstacle_reading(reading)
        strategy.return_to_home.assert_not_called()

    async def test_rth_not_skipped_when_height_query_fails(self):
        """A failed get_height must NOT suppress RTH — drone may be airborne."""
        handler, drone, strategy, _tel = self._make_handler()
        drone.get_height.return_value = {"error": "HEIGHT_FAILED", "detail": "timeout"}

        reading = ObstacleReading(
            distance_mm=185,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 20),
        )
        await handler.on_obstacle_reading(reading)
        strategy.return_to_home.assert_called_once()

    async def test_rth_active_flag_set_during_execution(self):
        """_rth_active is True while execute() is running, False after."""
        handler, drone, strategy, _tel = self._make_handler()
        drone.get_height.return_value = {"status": "ok", "height_cm": 80}

        observed_during: list[bool] = []
        original_execute = handler.execute

        async def spy_execute(*args, **kwargs):
            observed_during.append(handler._rth_active)
            return await original_execute(*args, **kwargs)

        handler.execute = spy_execute

        reading = ObstacleReading(
            distance_mm=185,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 20),
        )
        await handler.on_obstacle_reading(reading)
        assert observed_during == [True]
        assert handler._rth_active is False

    async def test_rth_active_flag_cleared_on_exception(self):
        """_rth_active is cleared even if execute() raises."""
        handler, drone, _strategy, _tel = self._make_handler()
        drone.get_height.return_value = {"status": "ok", "height_cm": 80}
        handler.execute = AsyncMock(side_effect=RuntimeError("execute failed"))

        reading = ObstacleReading(
            distance_mm=185,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 20),
        )
        with pytest.raises(RuntimeError, match="execute failed"):
            await handler.on_obstacle_reading(reading)
        assert handler._rth_active is False


class TestCLIResponseProvider:
    async def test_present_options_emergency_land(self, monkeypatch):
        provider = CLIResponseProvider()
        reading = ObstacleReading(
            distance_mm=350,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 16, 14, 0, 0),
        )
        monkeypatch.setattr("builtins.input", lambda _: "1")
        choice = await provider.present_options(reading)
        assert choice == ObstacleResponse.EMERGENCY_LAND

    async def test_present_options_manual_override(self, monkeypatch):
        provider = CLIResponseProvider()
        reading = ObstacleReading(
            distance_mm=350,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 16, 14, 0, 0),
        )
        monkeypatch.setattr("builtins.input", lambda _: "4")
        choice = await provider.present_options(reading)
        assert choice == ObstacleResponse.MANUAL_OVERRIDE

    async def test_present_options_invalid_then_valid(self, monkeypatch):
        provider = CLIResponseProvider()
        reading = ObstacleReading(
            distance_mm=350,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 16, 14, 0, 0),
        )
        inputs = iter(["invalid", "0", "5", "2"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        choice = await provider.present_options(reading)
        assert choice == ObstacleResponse.RETURN_TO_HOME


class TestObstacleMonitorStatus:
    def test_status_initial_state(self):
        monitor = ObstacleMonitor(MagicMock())
        status = monitor.status()
        assert status == {
            "running": False,
            "in_danger": False,
            "danger_clear_count": 0,
            "latest_reading_mm": None,
            "latest_zone": None,
        }

    async def test_status_after_start(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 600}
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)
        await monitor.start()
        await asyncio.sleep(0.1)
        status = monitor.status()
        assert status["running"] is True
        assert status["latest_reading_mm"] == 600
        assert status["latest_zone"] == "clear"
        await monitor.stop()

    async def test_start_resets_stale_state(self):
        """Starting the monitor resets _in_danger and _danger_clear_count."""
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"error": "EXHAUSTED"}
        monitor = ObstacleMonitor(drone, ObstacleConfig(poll_interval_ms=50))
        monitor._in_danger = True
        monitor._danger_clear_count = 2
        await monitor.start()
        assert monitor._in_danger is False
        assert monitor._danger_clear_count == 0
        await monitor.stop()


class TestObstacleResponseHandlerStatus:
    def test_status_initial(self):
        handler = ObstacleResponseHandler(MagicMock())
        assert handler.status() == {"rth_active": False}

    def test_status_rth_active(self):
        handler = ObstacleResponseHandler(MagicMock())
        handler._rth_active = True
        assert handler.status() == {"rth_active": True}
