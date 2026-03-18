"""Tests for RTH strategies and ObstacleContext."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from tello_core.models import ObstacleIncident
from tello_mcp.strategies import ObstacleContext, SimpleReverseRTH


class TestObstacleIncidentModel:
    def test_create_incident(self):
        incident = ObstacleIncident(
            id="inc-1",
            timestamp=datetime(2026, 3, 18, tzinfo=UTC),
            forward_distance_mm=185,
            forward_distance_in=7.3,
            height_cm=80,
            zone="DANGER",
            response="RETURN_TO_HOME",
            outcome="landed",
        )
        assert incident.forward_distance_mm == 185
        assert incident.mission_id is None

    def test_incident_with_optional_fields(self):
        incident = ObstacleIncident(
            id="inc-2",
            timestamp=datetime(2026, 3, 18, tzinfo=UTC),
            forward_distance_mm=185,
            forward_distance_in=7.3,
            height_cm=80,
            zone="DANGER",
            response="RETURN_TO_HOME",
            outcome="landed",
            mission_id="mission-1",
            room_id="living-room",
            reversed_direction="back",
        )
        assert incident.mission_id == "mission-1"
        assert incident.reversed_direction == "back"


class TestObstacleContext:
    def test_create_context(self):
        ctx = ObstacleContext(
            last_direction="forward",
            last_distance_cm=100,
            height_cm=80,
            forward_distance_mm=185,
        )
        assert ctx.last_direction == "forward"
        assert ctx.mission_id is None

    def test_context_is_frozen(self):
        ctx = ObstacleContext(
            last_direction="forward",
            last_distance_cm=100,
            height_cm=80,
            forward_distance_mm=185,
        )
        with pytest.raises(AttributeError):
            ctx.last_direction = "back"


class TestSimpleReverseRTH:
    def test_reverses_and_lands(self):
        drone = MagicMock()
        drone.move.return_value = {"status": "ok"}
        drone.land.return_value = {"status": "ok"}
        ctx = ObstacleContext(
            last_direction="forward",
            last_distance_cm=100,
            height_cm=80,
            forward_distance_mm=185,
        )
        rth = SimpleReverseRTH()
        result = rth.return_to_home(drone, ctx)
        drone.move.assert_called_once_with("back", 100)
        drone.land.assert_called_once()
        assert result["status"] == "returned"
        assert result["reversed_direction"] == "back"
        assert result["height_cm"] == 80
        assert result["landed"] is True

    def test_skips_reverse_when_no_last_direction(self):
        drone = MagicMock()
        drone.land.return_value = {"status": "ok"}
        ctx = ObstacleContext(
            last_direction="",
            last_distance_cm=0,
            height_cm=80,
            forward_distance_mm=185,
        )
        rth = SimpleReverseRTH()
        result = rth.return_to_home(drone, ctx)
        drone.move.assert_not_called()
        drone.land.assert_called_once()
        assert result["reversed_direction"] is None

    def test_lands_even_if_reverse_fails(self):
        drone = MagicMock()
        drone.move.return_value = {"error": "COMMAND_FAILED", "detail": "timeout"}
        drone.land.return_value = {"status": "ok"}
        ctx = ObstacleContext(
            last_direction="forward",
            last_distance_cm=100,
            height_cm=80,
            forward_distance_mm=185,
        )
        rth = SimpleReverseRTH()
        result = rth.return_to_home(drone, ctx)
        drone.move.assert_called_once()
        drone.land.assert_called_once()
        assert result["landed"] is True

    def test_all_directions_reverse_correctly(self):
        pairs = [
            ("forward", "back"),
            ("back", "forward"),
            ("left", "right"),
            ("right", "left"),
            ("up", "down"),
            ("down", "up"),
        ]
        for direction, expected_opposite in pairs:
            drone = MagicMock()
            drone.move.return_value = {"status": "ok"}
            drone.land.return_value = {"status": "ok"}
            ctx = ObstacleContext(
                last_direction=direction,
                last_distance_cm=50,
                height_cm=80,
                forward_distance_mm=185,
            )
            rth = SimpleReverseRTH()
            result = rth.return_to_home(drone, ctx)
            drone.move.assert_called_once_with(expected_opposite, 50)
            assert result["reversed_direction"] == expected_opposite
