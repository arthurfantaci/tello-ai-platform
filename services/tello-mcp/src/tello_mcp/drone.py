"""DroneAdapter — single point of djitellopy dependency.

All other modules interact with the drone through this adapter.
If djitellopy ever needs a patch, this is the only file to change.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from djitellopy import Tello

from tello_core.models import TelemetryFrame

logger = structlog.get_logger("tello_mcp.drone")

MOVE_METHODS = {
    "forward": "move_forward",
    "back": "move_back",
    "left": "move_left",
    "right": "move_right",
    "up": "move_up",
    "down": "move_down",
}


class DroneAdapter:
    """Abstraction layer over djitellopy.Tello.

    Provides structured return values (never raw exceptions)
    and a consistent interface for the command queue.
    """

    def __init__(self, host: str = "192.168.10.1") -> None:
        self._tello = Tello(host=host)
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Whether the drone connection is active."""
        return self._connected

    def connect(self) -> dict:
        """Connect to the Tello drone over WiFi."""
        try:
            self._tello.connect()
            self._connected = True
            logger.info("Drone connected, battery=%d%%", self._tello.get_battery())
        except Exception as e:
            logger.exception("Failed to connect to drone")
            return {"error": "CONNECTION_FAILED", "detail": str(e)}

        # Best-effort pad enablement — warn on failure, don't kill connection
        try:
            self._tello.enable_mission_pads()
            self._tello.set_mission_pad_detection_direction(0)  # downward, 20Hz
        except Exception:
            logger.warning("Mission pad enablement failed — pad detection unavailable")

        return {"status": "ok"}

    def disconnect(self) -> None:
        """Disconnect from the drone."""
        if self._connected:
            self._tello.end()
            self._connected = False
            logger.info("Drone disconnected")

    def keepalive(self) -> None:
        """Send keepalive to prevent 15-second auto-land timeout."""
        if self._connected:
            self._tello.send_keepalive()

    def set_pad_detection_direction(self, direction: int = 0) -> dict:
        """Set mission pad detection direction.

        Args:
            direction: 0 = downward only (20Hz),
                       1 = forward only (20Hz),
                       2 = both (10Hz each, alternating).
        """
        if err := self._require_connection():
            return err
        try:
            self._tello.set_mission_pad_detection_direction(direction)
            return {"status": "ok"}
        except Exception as e:
            logger.exception("set_pad_detection_direction failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}

    def _require_connection(self) -> dict | None:
        """Return error dict if not connected, None if OK."""
        if not self._connected:
            return {"error": "DRONE_NOT_CONNECTED", "detail": "Call connect() first"}
        return None

    def takeoff(self) -> dict:
        """Take off and hover."""
        if err := self._require_connection():
            return err
        try:
            self._tello.takeoff()
            return {"status": "ok"}
        except Exception as e:
            logger.exception("Takeoff failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}

    def land(self) -> dict:
        """Land the drone."""
        if err := self._require_connection():
            return err
        try:
            self._tello.land()
            return {"status": "ok"}
        except Exception as e:
            logger.exception("Land failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}

    def emergency(self) -> dict:
        """Emergency motor stop."""
        if err := self._require_connection():
            return err
        try:
            self._tello.emergency()
            return {"status": "ok", "warning": "Motors killed"}
        except Exception as e:
            logger.exception("Emergency stop failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}

    def move(self, direction: str, distance_cm: int) -> dict:
        """Move in a direction.

        Args:
            direction: One of forward, back, left, right, up, down.
            distance_cm: Distance in centimeters (20-500).
        """
        if err := self._require_connection():
            return err
        method_name = MOVE_METHODS.get(direction)
        if not method_name:
            return {"error": "INVALID_DIRECTION", "detail": f"Unknown direction: {direction}"}
        try:
            getattr(self._tello, method_name)(distance_cm)
            return {"status": "ok"}
        except Exception as e:
            logger.exception("Move %s failed", direction)
            return {"error": "COMMAND_FAILED", "detail": str(e)}

    def rotate(self, degrees: int) -> dict:
        """Rotate clockwise (positive) or counter-clockwise (negative)."""
        if err := self._require_connection():
            return err
        try:
            if degrees >= 0:
                self._tello.rotate_clockwise(degrees)
            else:
                self._tello.rotate_counter_clockwise(abs(degrees))
            return {"status": "ok"}
        except Exception as e:
            logger.exception("Rotate failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}

    def get_telemetry(self) -> TelemetryFrame:
        """Get current telemetry snapshot."""
        return TelemetryFrame(
            battery_pct=self._tello.get_battery(),
            height_cm=self._tello.get_height(),
            tof_cm=self._tello.get_distance_tof(),
            temp_c=float(self._tello.get_temperature()),
            pitch=float(self._tello.get_pitch()),
            roll=float(self._tello.get_roll()),
            yaw=float(self._tello.get_yaw()),
            flight_time_s=self._tello.get_flight_time(),
            timestamp=datetime.now(tz=UTC),
        )

    def detect_mission_pad(self) -> dict:
        """Scan for nearest mission pad.

        Returns:
            Dict with pad_id and detection status. When detected,
            includes x/y/z coordinates (cm) relative to the pad.
            pad_id values: -2 (detection disabled), -1 (enabled but
            no pad detected), 1-8 (detected pad ID).
        """
        if err := self._require_connection():
            return err
        pad_id = self._tello.get_mission_pad_id()
        if pad_id < 1:
            return {"pad_id": pad_id, "detected": False}
        return {
            "pad_id": pad_id,
            "detected": True,
            "x_cm": self._tello.get_mission_pad_distance_x(),
            "y_cm": self._tello.get_mission_pad_distance_y(),
            "z_cm": self._tello.get_mission_pad_distance_z(),
        }

    def go_xyz_speed_mid(self, x: int, y: int, z: int, speed: int, mid: int) -> dict:
        """Fly to coordinates relative to a mission pad.

        Args:
            x: -500 to 500 cm (pad-relative X axis).
            y: -500 to 500 cm (pad-relative Y axis).
            z: 0 to 500 cm (altitude above pad, must be positive).
            speed: 10-100 cm/s.
            mid: Mission pad ID (1-8).
        """
        if err := self._require_connection():
            return err
        try:
            self._tello.go_xyz_speed_mid(x, y, z, speed, mid)
            return {"status": "ok"}
        except Exception as e:
            logger.exception("go_xyz_speed_mid failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}

    def set_led(self, r: int, g: int, b: int) -> dict:
        """Set expansion board LED color.

        Args:
            r: Red value (0-255).
            g: Green value (0-255).
            b: Blue value (0-255).
        """
        if err := self._require_connection():
            return err
        try:
            self._tello.send_expansion_command(f"led {r} {g} {b}")
            return {"status": "ok"}
        except Exception as e:
            logger.exception("set_led failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}

    def display_scroll_text(
        self, text: str, direction: str = "l", color: str = "r", rate: float = 0.5
    ) -> dict:
        """Scroll text on the 8x8 LED matrix.

        Args:
            text: Text to display (max 70 characters).
            direction: Scroll direction — l (left), r (right), u (up), d (down).
            color: Display color — r (red), b (blue), p (purple).
            rate: Frame rate in Hz (0.1-2.5).
        """
        if err := self._require_connection():
            return err
        try:
            self._tello.send_expansion_command(f"mled {direction} {color} {rate} {text}")
            return {"status": "ok"}
        except Exception as e:
            logger.exception("display_scroll_text failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}

    def display_static_char(self, char: str, color: str = "r") -> dict:
        """Display a static character on the 8x8 LED matrix.

        Args:
            char: Single ASCII character or "heart".
            color: Display color — r (red), b (blue), p (purple).
        """
        if err := self._require_connection():
            return err
        try:
            self._tello.send_expansion_command(f"mled s {color} {char}")
            return {"status": "ok"}
        except Exception as e:
            logger.exception("display_static_char failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}

    def display_pattern(self, pattern: str) -> dict:
        """Display a dot-matrix pattern on the 8x8 LED matrix.

        Args:
            pattern: Up to 64 characters using r (red), b (blue),
                     p (purple), 0 (off). Unspecified positions are off.
        """
        if err := self._require_connection():
            return err
        try:
            self._tello.send_expansion_command(f"mled g {pattern}")
            return {"status": "ok"}
        except Exception as e:
            logger.exception("display_pattern failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}
