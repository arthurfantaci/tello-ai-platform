"""Tests for DroneAdapter command lock, stop(), and get_height()."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tello_mcp.drone import DroneAdapter


class TestDroneStop:
    def test_stop_sends_control_command(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter._connected = True
            mock_drone.send_control_command = MagicMock()
            result = adapter.stop()
            mock_drone.send_control_command.assert_called_once_with("stop")
            assert result["status"] == "ok"

    def test_stop_requires_connection(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter._connected = False
            result = adapter.stop()
            assert result["error"] == "DRONE_NOT_CONNECTED"

    def test_stop_handles_exception(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter._connected = True
            mock_drone.send_control_command.side_effect = Exception("fail")
            result = adapter.stop()
            assert result["error"] == "STOP_FAILED"


class TestDroneGetHeight:
    def test_get_height_returns_distance(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter._connected = True
            mock_drone.get_distance_tof.return_value = 80
            result = adapter.get_height()
            assert result == {"status": "ok", "height_cm": 80}

    def test_get_height_requires_connection(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter._connected = False
            result = adapter.get_height()
            assert result["error"] == "DRONE_NOT_CONNECTED"


class TestDroneRLock:
    def test_get_telemetry_does_not_deadlock(self, mock_drone):
        """get_telemetry calls get_forward_distance internally.

        With threading.Lock this would deadlock. RLock allows reentrance.
        """
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter._connected = True
            # Should complete without deadlock
            result = adapter.get_telemetry()
            assert hasattr(result, "battery_pct")  # TelemetryFrame

    def test_lock_is_rlock(self, mock_drone):
        """Verify we use RLock, not Lock."""
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            # Verify it's reentrant: acquire twice without deadlock
            lock = adapter._command_lock
            lock.acquire()
            lock.acquire()  # Would deadlock with threading.Lock
            lock.release()
            lock.release()
