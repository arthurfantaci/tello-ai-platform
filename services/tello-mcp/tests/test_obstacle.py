"""Tests for ObstacleMonitor, ObstacleConfig, and ObstacleResponseHandler."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from tello_core.models import ObstacleReading, ObstacleZone
from tello_mcp.obstacle import (
    CLIResponseProvider,
    ObstacleConfig,
    ObstacleMonitor,
    ObstacleResponse,
    ObstacleResponseHandler,
)


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
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 1200}
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)
        await monitor.start()
        await asyncio.sleep(0.15)  # allow a few polls
        await monitor.stop()
        assert monitor.latest is not None
        assert monitor.latest.distance_mm == 1200
        assert monitor.latest.zone == ObstacleZone.CAUTION

    async def test_danger_zone_calls_stop(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 200}
        drone.stop = MagicMock(return_value={"status": "ok"})
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)
        await monitor.start()
        await asyncio.sleep(0.15)
        await monitor.stop()
        drone.stop.assert_called()

    async def test_clear_zone_does_not_call_stop(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 8192}
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

    async def test_execute_return_to_home_not_implemented(self):
        drone = MagicMock()
        handler = ObstacleResponseHandler(drone)
        result = await handler.execute(ObstacleResponse.RETURN_TO_HOME)
        assert result["error"] == "NOT_IMPLEMENTED"

    async def test_execute_avoid_and_continue_not_implemented(self):
        drone = MagicMock()
        handler = ObstacleResponseHandler(drone)
        result = await handler.execute(ObstacleResponse.AVOID_AND_CONTINUE)
        assert result["error"] == "NOT_IMPLEMENTED"


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
