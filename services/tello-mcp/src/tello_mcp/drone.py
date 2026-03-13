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
            return {"status": "ok"}
        except Exception as e:
            logger.exception("Failed to connect to drone")
            return {"error": "CONNECTION_FAILED", "detail": str(e)}

    def disconnect(self) -> None:
        """Disconnect from the drone."""
        if self._connected:
            self._tello.end()
            self._connected = False
            logger.info("Drone disconnected")

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
            Dict with pad_id (int) or -1 if none detected.
        """
        if err := self._require_connection():
            return err
        pad_id = self._tello.get_mission_pad_id()
        return {"pad_id": pad_id, "detected": pad_id != -1}

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
            self._tello.set_led(r=r, g=g, b=b)
            return {"status": "ok"}
        except Exception as e:
            logger.exception("set_led failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}

    def display_text(self, text: str) -> dict:
        """Display scrolling text on the 8x8 LED matrix.

        Args:
            text: Text to display.
        """
        if err := self._require_connection():
            return err
        try:
            self._tello.set_display(text)
            return {"status": "ok"}
        except Exception as e:
            logger.exception("display_text failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}
