"""Tests for tello_core shared Pydantic models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from tello_core.models import (
    Anomaly,
    Dwelling,
    FlightCommand,
    FlightSession,
    Mission,
    MissionPad,
    MissionStatus,
    RoomNode,
    TelemetryFrame,
    TelemetrySample,
    VisualEntity,
    Waypoint,
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


class TestWaypoint:
    def test_valid_move_waypoint(self):
        wp = Waypoint(
            id="wp_1",
            sequence=0,
            room_id="living",
            action="move",
            direction="forward",
            distance_cm=100,
        )
        assert wp.pad_id is None
        assert wp.degrees is None

    def test_valid_rotate_waypoint(self):
        wp = Waypoint(
            id="wp_2",
            sequence=1,
            room_id="living",
            action="rotate",
            degrees=90,
        )
        assert wp.direction is None
        assert wp.distance_cm is None

    def test_valid_takeoff_waypoint(self):
        wp = Waypoint(id="wp_0", sequence=0, room_id="living", action="takeoff")
        assert wp.action == "takeoff"

    def test_valid_goto_pad_waypoint(self):
        wp = Waypoint(
            id="wp_3",
            sequence=2,
            room_id="living",
            action="goto_pad",
            pad_id=3,
        )
        assert wp.pad_id == 3

    def test_invalid_action_rejected(self):
        with pytest.raises(ValidationError):
            Waypoint(id="wp_x", sequence=0, room_id="r", action="fly_home")

    def test_distance_bounds(self):
        with pytest.raises(ValidationError):
            Waypoint(
                id="wp_x",
                sequence=0,
                room_id="r",
                action="move",
                direction="forward",
                distance_cm=10,
            )
        with pytest.raises(ValidationError):
            Waypoint(
                id="wp_x",
                sequence=0,
                room_id="r",
                action="move",
                direction="forward",
                distance_cm=600,
            )

    def test_degrees_bounds(self):
        with pytest.raises(ValidationError):
            Waypoint(
                id="wp_x",
                sequence=0,
                room_id="r",
                action="rotate",
                degrees=400,
            )

    def test_negative_sequence_rejected(self):
        with pytest.raises(ValidationError):
            Waypoint(id="wp_x", sequence=-1, room_id="r", action="takeoff")


class TestMissionStatus:
    def test_enum_values(self):
        assert MissionStatus.PLANNED == "planned"
        assert MissionStatus.EXECUTING == "executing"
        assert MissionStatus.COMPLETED == "completed"
        assert MissionStatus.ABORTED == "aborted"

    def test_string_coercion(self):
        assert MissionStatus("planned") is MissionStatus.PLANNED


class TestMission:
    def test_valid_mission(self):
        mission = Mission(
            id="m_001",
            goal="Patrol living room",
            room_ids=["living"],
            created_at=datetime(2026, 3, 13, 10, 0, 0),
        )
        assert mission.status == MissionStatus.PLANNED
        assert mission.waypoints == []
        assert mission.started_at is None
        assert mission.completed_at is None
        assert mission.error is None

    def test_mission_with_waypoints(self):
        wp = Waypoint(id="wp_1", sequence=0, room_id="living", action="takeoff")
        mission = Mission(
            id="m_002",
            goal="Inspect kitchen",
            room_ids=["kitchen"],
            waypoints=[wp],
            created_at=datetime(2026, 3, 13, 10, 0, 0),
        )
        assert len(mission.waypoints) == 1

    def test_serialization_roundtrip(self):
        mission = Mission(
            id="m_003",
            goal="Check bedroom",
            room_ids=["bedroom"],
            status=MissionStatus.EXECUTING,
            created_at=datetime(2026, 3, 13, 10, 0, 0),
            started_at=datetime(2026, 3, 13, 10, 1, 0),
        )
        data = mission.model_dump()
        restored = Mission.model_validate(data)
        assert restored == mission


class TestDwelling:
    def test_valid_dwelling(self):
        dwelling = Dwelling(
            id="arthurs-apt",
            name="Arthur's Apartment",
            address="123 Main St",
        )
        assert dwelling.id == "arthurs-apt"

    def test_defaults(self):
        dwelling = Dwelling(id="apt1", name="Apt 1")
        assert dwelling.address is None
