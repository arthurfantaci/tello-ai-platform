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
            mock_drone.send_expansion_command.assert_called_once_with("led 255 0 0")
            assert result["status"] == "ok"

    def test_set_led_when_not_connected(self):
        with patch("tello_mcp.drone.Tello"):
            adapter = DroneAdapter()
            result = adapter.set_led(255, 0, 0)
            assert result["error"] == "DRONE_NOT_CONNECTED"

    def test_display_scroll_text(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.display_scroll_text("hello")
            mock_drone.send_expansion_command.assert_called_once_with("mled l r 0.5 hello")
            assert result["status"] == "ok"

    def test_display_static_char(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.display_static_char("heart", "b")
            mock_drone.send_expansion_command.assert_called_once_with("mled s b heart")
            assert result["status"] == "ok"

    def test_display_pattern(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.display_pattern("rrrrbbbb" + "0" * 56)
            mock_drone.send_expansion_command.assert_called_once_with("mled g rrrrbbbb" + "0" * 56)
            assert result["status"] == "ok"

    def test_display_scroll_text_when_not_connected(self):
        with patch("tello_mcp.drone.Tello"):
            adapter = DroneAdapter()
            result = adapter.display_scroll_text("hi")
            assert result["error"] == "DRONE_NOT_CONNECTED"

    def test_safe_land_success(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.safe_land()
            mock_drone.land.assert_called_once()
            assert result["status"] == "ok"
            assert "warning" not in result

    def test_safe_land_falls_back_to_emergency(self, mock_drone):
        mock_drone.land.side_effect = Exception("land rejected")
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.safe_land()
            mock_drone.emergency.assert_called_once()
            assert result["status"] == "ok"
            assert "emergency" in result["warning"].lower()

    def test_safe_land_both_fail(self, mock_drone):
        mock_drone.land.side_effect = Exception("land rejected")
        mock_drone.emergency.side_effect = Exception("motor fault")
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.safe_land()
            assert result["error"] == "LAND_FAILED"

    def test_safe_land_when_not_connected(self):
        with patch("tello_mcp.drone.Tello"):
            adapter = DroneAdapter()
            result = adapter.safe_land()
            assert result["error"] == "DRONE_NOT_CONNECTED"

    def test_host_parameter(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone) as mock_cls:
            DroneAdapter(host="192.168.68.107")
            mock_cls.assert_called_once_with(host="192.168.68.107")

    def test_connect_enables_mission_pads(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            mock_drone.enable_mission_pads.assert_called_once()
            mock_drone.set_mission_pad_detection_direction.assert_called_once_with(0)

    def test_connect_succeeds_if_pad_enable_fails(self, mock_drone):
        mock_drone.enable_mission_pads.side_effect = Exception("pad error")
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            result = adapter.connect()
            assert result["status"] == "ok"
            assert adapter.is_connected

    def test_keepalive(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            adapter.keepalive()
            mock_drone.send_keepalive.assert_called_once()

    def test_keepalive_when_not_connected(self):
        with patch("tello_mcp.drone.Tello"):
            adapter = DroneAdapter()
            adapter.keepalive()  # should not raise

    def test_set_pad_detection_direction(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            # Reset after connect() which calls set_mission_pad_detection_direction(0)
            mock_drone.set_mission_pad_detection_direction.reset_mock()
            result = adapter.set_pad_detection_direction(2)
            mock_drone.set_mission_pad_detection_direction.assert_called_once_with(2)
            assert result["status"] == "ok"

    def test_detect_mission_pad_with_pad(self, mock_drone):
        mock_drone.get_mission_pad_id.return_value = 3
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.detect_mission_pad()
            assert result["pad_id"] == 3
            assert result["detected"] is True
            assert result["x_cm"] == 10
            assert result["y_cm"] == 20
            assert result["z_cm"] == 50

    def test_detect_mission_pad_no_pad(self, mock_drone):
        mock_drone.get_mission_pad_id.return_value = -1
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.detect_mission_pad()
            assert result["pad_id"] == -1
            assert result["detected"] is False
            assert "x_cm" not in result

    def test_go_xyz_speed_mid(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.go_xyz_speed_mid(0, 0, 50, 30, 1)
            mock_drone.go_xyz_speed_mid.assert_called_once_with(0, 0, 50, 30, 1)
            assert result["status"] == "ok"

    def test_go_xyz_speed_mid_when_not_connected(self):
        with patch("tello_mcp.drone.Tello"):
            adapter = DroneAdapter()
            result = adapter.go_xyz_speed_mid(0, 0, 50, 30, 1)
            assert result["error"] == "DRONE_NOT_CONNECTED"

    def test_get_forward_distance_success(self, mock_drone):
        mock_drone.send_read_command.return_value = "tof 1245"
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.get_forward_distance()
            mock_drone.send_read_command.assert_called_with("EXT tof?")
            assert result["status"] == "ok"
            assert result["distance_mm"] == 1245

    def test_get_forward_distance_out_of_range(self, mock_drone):
        mock_drone.send_read_command.return_value = "tof 8190"
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.get_forward_distance()
            assert result["status"] == "ok"
            assert result["distance_mm"] == 8190

    def test_get_forward_distance_parse_error(self, mock_drone):
        mock_drone.send_read_command.return_value = "error"
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.get_forward_distance()
            assert result["error"] == "PARSE_ERROR"

    def test_get_forward_distance_command_failed(self, mock_drone):
        mock_drone.send_read_command.side_effect = Exception("timeout")
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.get_forward_distance()
            assert result["error"] == "COMMAND_FAILED"

    def test_get_forward_distance_when_not_connected(self):
        with patch("tello_mcp.drone.Tello"):
            adapter = DroneAdapter()
            result = adapter.get_forward_distance()
            assert result["error"] == "DRONE_NOT_CONNECTED"

    def test_get_telemetry_includes_forward_tof(self, mock_drone):
        mock_drone.send_read_command.return_value = "tof 750"
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            frame = adapter.get_telemetry()
            assert frame.forward_tof_mm == 750

    def test_get_telemetry_forward_tof_none_on_failure(self, mock_drone):
        mock_drone.send_read_command.return_value = "error"
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            frame = adapter.get_telemetry()
            assert frame.forward_tof_mm is None
