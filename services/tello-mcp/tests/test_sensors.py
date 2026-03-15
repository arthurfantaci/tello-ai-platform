"""Tests for sensor tools — telemetry guard behavior."""

from __future__ import annotations

from unittest.mock import patch

from tello_mcp.drone import DroneAdapter


class TestGetTelemetryGuard:
    def test_telemetry_when_not_connected(self):
        with patch("tello_mcp.drone.Tello"):
            adapter = DroneAdapter()
            result = adapter.get_telemetry()
            assert isinstance(result, dict)
            assert result["error"] == "DRONE_NOT_CONNECTED"

    def test_telemetry_when_connected(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.get_telemetry()
            # Should return TelemetryFrame, not dict
            assert not isinstance(result, dict)
            assert result.battery_pct == 85

    def test_telemetry_sdk_exception(self, mock_drone):
        mock_drone.get_battery.side_effect = Exception("socket timeout")
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.get_telemetry()
            assert isinstance(result, dict)
            assert result["error"] == "TELEMETRY_FAILED"
            assert "socket timeout" in result["detail"]
