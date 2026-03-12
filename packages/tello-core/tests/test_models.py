"""Tests for tello_core shared Pydantic models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from tello_core.models import (
    Anomaly,
    FlightCommand,
    FlightSession,
    MissionPad,
    RoomNode,
    TelemetryFrame,
    TelemetrySample,
    VisualEntity,
)


class TestFlightCommand:
    def test_valid_command(self):
        cmd = FlightCommand(direction="forward", distance_cm=100)
        assert cmd.direction == "forward"
        assert cmd.distance_cm == 100
        assert cmd.speed is None

    def test_with_speed(self):
        cmd = FlightCommand(direction="up", distance_cm=50, speed=30)
        assert cmd.speed == 30

    def test_invalid_direction_rejected(self):
        with pytest.raises(ValidationError):
            FlightCommand(direction="diagonal", distance_cm=100)

    def test_distance_bounds(self):
        with pytest.raises(ValidationError):
            FlightCommand(direction="forward", distance_cm=10)  # below 20

        with pytest.raises(ValidationError):
            FlightCommand(direction="forward", distance_cm=600)  # above 500


class TestTelemetryFrame:
    def test_valid_frame(self):
        frame = TelemetryFrame(
            battery_pct=85,
            height_cm=120,
            tof_cm=95,
            temp_c=42.5,
            pitch=1.2,
            roll=-0.5,
            yaw=180.0,
            flight_time_s=45,
            timestamp=datetime(2026, 3, 12, 10, 0, 0),
        )
        assert frame.battery_pct == 85

    def test_serialization_roundtrip(self):
        frame = TelemetryFrame(
            battery_pct=50,
            height_cm=100,
            tof_cm=80,
            temp_c=40.0,
            pitch=0.0,
            roll=0.0,
            yaw=0.0,
            flight_time_s=10,
            timestamp=datetime(2026, 3, 12, 10, 0, 0),
        )
        data = frame.model_dump()
        restored = TelemetryFrame.model_validate(data)
        assert restored == frame


class TestRoomNode:
    def test_valid_room(self):
        room = RoomNode(
            id="living_room", name="Living Room", width_cm=400, depth_cm=500, height_cm=270
        )
        assert room.id == "living_room"


class TestMissionPad:
    def test_valid_pad(self):
        pad = MissionPad(id=1, room_id="living_room", x_cm=200, y_cm=150)
        assert pad.last_visited is None

    def test_pad_id_range(self):
        with pytest.raises(ValidationError):
            MissionPad(id=0, room_id="r", x_cm=0, y_cm=0)
        with pytest.raises(ValidationError):
            MissionPad(id=9, room_id="r", x_cm=0, y_cm=0)


class TestVisualEntity:
    def test_valid_entity(self):
        entity = VisualEntity(
            name="couch",
            type="furniture",
            confidence=0.92,
            room_id="living_room",
            last_seen=datetime(2026, 3, 12, 10, 0, 0),
        )
        assert entity.position is None


class TestFlightSession:
    def test_valid_session(self):
        session = FlightSession(
            id="sess_001",
            start_time=datetime(2026, 3, 12, 10, 0, 0),
            room_id="living_room",
        )
        assert session.end_time is None
        assert session.mission_id is None


class TestTelemetrySample:
    def test_valid_sample(self):
        sample = TelemetrySample(
            battery_pct=75,
            height_cm=100,
            tof_cm=90,
            temp_c=41.0,
            timestamp=datetime(2026, 3, 12, 10, 0, 0),
        )
        assert sample.battery_pct == 75


class TestAnomaly:
    def test_valid_anomaly(self):
        anomaly = Anomaly(
            type="battery_drain",
            severity="warning",
            detail="Drain rate >5%/min",
            timestamp=datetime(2026, 3, 12, 10, 0, 0),
        )
        assert anomaly.severity == "warning"

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValidationError):
            Anomaly(
                type="battery_drain",
                severity="info",
                detail="x",
                timestamp=datetime(2026, 3, 12, 10, 0, 0),
            )
