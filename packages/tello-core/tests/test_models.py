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
    def test_valid_waypoint(self):
        wp = Waypoint(
            id="wp_001",
            sequence=0,
            room_id="living_room",
            action="move",
            direction="forward",
            distance_cm=100,
        )
        assert wp.id == "wp_001"
        assert wp.sequence == 0
        assert wp.pad_id is None
        assert wp.degrees is None

    def test_takeoff_action(self):
        wp = Waypoint(id="wp_t", sequence=0, room_id="living_room", action="takeoff")
        assert wp.action == "takeoff"
        assert wp.direction is None
        assert wp.distance_cm is None

    def test_rotate_action(self):
        wp = Waypoint(id="wp_r", sequence=1, room_id="kitchen", action="rotate", degrees=90)
        assert wp.degrees == 90

    def test_goto_pad_action(self):
        wp = Waypoint(id="wp_gp", sequence=2, room_id="bedroom", action="goto_pad", pad_id=3)
        assert wp.action == "goto_pad"
        assert wp.pad_id == 3

    def test_invalid_action_rejected(self):
        with pytest.raises(ValidationError):
            Waypoint(id="wp_bad", sequence=0, room_id="r", action="flip")

    def test_sequence_negative_rejected(self):
        with pytest.raises(ValidationError):
            Waypoint(id="wp_neg", sequence=-1, room_id="r", action="takeoff")

    def test_distance_below_minimum_rejected(self):
        with pytest.raises(ValidationError):
            Waypoint(
                id="wp_d",
                sequence=0,
                room_id="r",
                action="move",
                direction="forward",
                distance_cm=10,
            )

    def test_distance_above_maximum_rejected(self):
        with pytest.raises(ValidationError):
            Waypoint(
                id="wp_d",
                sequence=0,
                room_id="r",
                action="move",
                direction="forward",
                distance_cm=501,
            )

    def test_degrees_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            Waypoint(id="wp_d", sequence=0, room_id="r", action="rotate", degrees=361)
        with pytest.raises(ValidationError):
            Waypoint(id="wp_d", sequence=0, room_id="r", action="rotate", degrees=-361)

    def test_serialization_roundtrip(self):
        wp = Waypoint(
            id="wp_rt",
            sequence=3,
            room_id="hallway",
            pad_id=2,
            action="move",
            direction="left",
            distance_cm=200,
        )
        data = wp.model_dump()
        restored = Waypoint.model_validate(data)
        assert restored == wp

    def test_waypoint_with_speed(self):
        wp = Waypoint(
            id="wp1",
            sequence=0,
            room_id="living",
            action="goto_pad",
            pad_id=1,
            speed_cm_s=30,
        )
        assert wp.speed_cm_s == 30

    def test_waypoint_speed_bounds(self):
        with pytest.raises(ValidationError):
            Waypoint(
                id="wp1",
                sequence=0,
                room_id="living",
                action="goto_pad",
                speed_cm_s=5,  # below 10
            )
        with pytest.raises(ValidationError):
            Waypoint(
                id="wp1",
                sequence=0,
                room_id="living",
                action="goto_pad",
                speed_cm_s=200,  # above 100
            )

    def test_waypoint_speed_optional(self):
        wp = Waypoint(
            id="wp1",
            sequence=0,
            room_id="living",
            action="move",
            direction="forward",
            distance_cm=100,
        )
        assert wp.speed_cm_s is None


class TestMissionStatus:
    def test_enum_values(self):
        assert MissionStatus.PLANNED == "planned"
        assert MissionStatus.EXECUTING == "executing"
        assert MissionStatus.COMPLETED == "completed"
        assert MissionStatus.ABORTED == "aborted"

    def test_is_string(self):
        assert isinstance(MissionStatus.PLANNED, str)

    def test_all_values(self):
        values = {s.value for s in MissionStatus}
        assert values == {"planned", "executing", "completed", "aborted"}


class TestMission:
    def test_valid_mission(self):
        now = datetime(2026, 3, 13, 10, 0, 0)
        mission = Mission(
            id="m_001",
            goal="Survey living room",
            room_ids=["living_room"],
            created_at=now,
        )
        assert mission.status == MissionStatus.PLANNED
        assert mission.waypoints == []
        assert mission.started_at is None
        assert mission.completed_at is None
        assert mission.error is None

    def test_mission_with_waypoints(self):
        now = datetime(2026, 3, 13, 10, 0, 0)
        wp = Waypoint(id="wp_1", sequence=0, room_id="kitchen", action="takeoff")
        mission = Mission(
            id="m_002",
            goal="Go to kitchen",
            status=MissionStatus.EXECUTING,
            room_ids=["living_room", "kitchen"],
            waypoints=[wp],
            created_at=now,
            started_at=now,
        )
        assert len(mission.waypoints) == 1
        assert mission.status == MissionStatus.EXECUTING

    def test_serialization_roundtrip(self):
        now = datetime(2026, 3, 13, 10, 0, 0)
        wp = Waypoint(
            id="wp_1",
            sequence=0,
            room_id="lr",
            action="move",
            direction="forward",
            distance_cm=100,
        )
        mission = Mission(
            id="m_rt",
            goal="Roundtrip test",
            room_ids=["lr"],
            waypoints=[wp],
            created_at=now,
        )
        data = mission.model_dump()
        restored = Mission.model_validate(data)
        assert restored == mission
        assert restored.waypoints[0].distance_cm == 100


class TestDwelling:
    def test_valid_dwelling(self):
        dw = Dwelling(
            id="4309_Donny_Martel_Way",
            name="Arthur's Apartment",
            address="4309 Donny Martel Way, Tewksbury, MA",
        )
        assert dw.id == "4309_Donny_Martel_Way"
        assert dw.address is not None

    def test_dwelling_address_optional(self):
        dw = Dwelling(id="test_home", name="Test Home")
        assert dw.address is None

    def test_serialization_roundtrip(self):
        dw = Dwelling(id="dw_rt", name="Roundtrip", address="123 Main St")
        data = dw.model_dump()
        restored = Dwelling.model_validate(data)
        assert restored == dw
