"""Tests for ObstacleMonitor, ObstacleConfig, and ObstacleResponseHandler."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from tello_core.models import ObstacleZone
from tello_mcp.obstacle import ObstacleConfig, ObstacleMonitor


class TestObstacleConfig:
    def test_default_values(self):
        config = ObstacleConfig()
        assert config.caution_mm == 1500
        assert config.warning_mm == 800
        assert config.danger_mm == 400
        assert config.out_of_range == 8192
        assert config.poll_interval_ms == 200

    def test_custom_values(self):
        config = ObstacleConfig(danger_mm=500, poll_interval_ms=100)
        assert config.danger_mm == 500
        assert config.poll_interval_ms == 100
        assert config.caution_mm == 1500  # unchanged default

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("OBSTACLE_DANGER_MM", "500")
        monkeypatch.setenv("OBSTACLE_POLL_INTERVAL_MS", "100")
        config = ObstacleConfig.from_env()
        assert config.danger_mm == 500
        assert config.poll_interval_ms == 100
        assert config.caution_mm == 1500  # default

    def test_from_env_no_vars(self):
        config = ObstacleConfig.from_env()
        assert config.danger_mm == 400  # default

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
        assert self.monitor.classify_zone(8192) == ObstacleZone.CLEAR

    def test_above_caution_is_clear(self):
        assert self.monitor.classify_zone(2000) == ObstacleZone.CLEAR

    def test_at_caution_boundary_is_clear(self):
        assert self.monitor.classify_zone(1500) == ObstacleZone.CLEAR

    def test_below_caution_is_caution(self):
        assert self.monitor.classify_zone(1499) == ObstacleZone.CAUTION

    def test_at_warning_boundary_is_caution(self):
        assert self.monitor.classify_zone(800) == ObstacleZone.CAUTION

    def test_below_warning_is_warning(self):
        assert self.monitor.classify_zone(799) == ObstacleZone.WARNING

    def test_at_danger_boundary_is_warning(self):
        assert self.monitor.classify_zone(400) == ObstacleZone.WARNING

    def test_below_danger_is_danger(self):
        assert self.monitor.classify_zone(399) == ObstacleZone.DANGER

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
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 8192}
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
