"""Tests for the DroneAdapter — djitellopy abstraction layer."""

from unittest.mock import patch

from tello_mcp.drone import DroneAdapter


class TestDroneAdapter:
    def test_connect(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            mock_drone.connect.assert_called_once()

    def test_disconnect_when_connected(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            adapter.disconnect()
            mock_drone.end.assert_called_once()

    def test_is_connected_property(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            assert not adapter.is_connected
            adapter.connect()
            assert adapter.is_connected

    def test_takeoff(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.takeoff()
            mock_drone.takeoff.assert_called_once()
            assert result["status"] == "ok"

    def test_land(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.land()
            mock_drone.land.assert_called_once()
            assert result["status"] == "ok"

    def test_command_when_not_connected_returns_error(self):
        with patch("tello_mcp.drone.Tello"):
            adapter = DroneAdapter()
            result = adapter.takeoff()
            assert result["error"] == "DRONE_NOT_CONNECTED"

    def test_get_telemetry(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            frame = adapter.get_telemetry()
            assert frame.battery_pct == 85
            assert frame.height_cm == 120

    def test_move(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.move("forward", 100)
            mock_drone.move_forward.assert_called_once_with(100)
            assert result["status"] == "ok"

    def test_set_led(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.set_led(255, 0, 0)
            mock_drone.set_led.assert_called_once_with(r=255, g=0, b=0)
            assert result["status"] == "ok"

    def test_set_led_when_not_connected(self):
        with patch("tello_mcp.drone.Tello"):
            adapter = DroneAdapter()
            result = adapter.set_led(255, 0, 0)
            assert result["error"] == "DRONE_NOT_CONNECTED"

    def test_display_text(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.display_text("hi")
            mock_drone.set_display.assert_called_once_with("hi")
            assert result["status"] == "ok"

    def test_display_text_when_not_connected(self):
        with patch("tello_mcp.drone.Tello"):
            adapter = DroneAdapter()
            result = adapter.display_text("hi")
            assert result["error"] == "DRONE_NOT_CONNECTED"

    def test_host_parameter(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone) as mock_cls:
            DroneAdapter(host="192.168.68.107")
            mock_cls.assert_called_once_with(host="192.168.68.107")
