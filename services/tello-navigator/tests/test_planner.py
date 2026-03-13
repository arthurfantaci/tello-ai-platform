"""Tests for MissionPlanner (LangGraph StateGraph)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tello_navigator.planner import MissionPlanner, PlannerState


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    return repo


@pytest.fixture
def planner(mock_repo):
    config = MagicMock()
    config.max_waypoints_per_mission = 20
    config.default_move_distance_cm = 100
    return MissionPlanner(mock_repo, config)


class TestFetchRooms:
    def test_fetches_rooms_from_repo(self, planner, mock_repo):
        mock_repo.get_rooms.return_value = [
            {
                "id": "living",
                "name": "Living Room",
                "width_cm": 400,
                "depth_cm": 500,
                "height_cm": 234,
            },
        ]
        mock_repo.get_room_pads.return_value = [
            {"id": 1, "room_id": "living", "x_cm": 100, "y_cm": 100},
        ]
        state: PlannerState = {
            "mission_id": "m_001",
            "goal": "Patrol",
            "room_ids": ["living"],
            "rooms": [],
            "mission_pads": [],
            "waypoints": [],
            "current_waypoint_idx": 0,
            "status": "planning",
            "error": None,
        }
        result = planner.fetch_rooms(state)
        assert len(result["rooms"]) == 1
        assert len(result["mission_pads"]) == 1


class TestValidateRooms:
    def test_valid_rooms_pass(self, planner):
        state: PlannerState = {
            "mission_id": "m_001",
            "goal": "Patrol",
            "room_ids": ["living"],
            "rooms": [{"id": "living", "name": "Living Room"}],
            "mission_pads": [{"id": 1, "room_id": "living"}],
            "waypoints": [],
            "current_waypoint_idx": 0,
            "status": "planning",
            "error": None,
        }
        result = planner.validate_rooms(state)
        assert result.get("error") is None

    def test_missing_room_sets_error(self, planner):
        state: PlannerState = {
            "mission_id": "m_001",
            "goal": "Patrol",
            "room_ids": ["living", "kitchen"],
            "rooms": [{"id": "living"}],
            "mission_pads": [],
            "waypoints": [],
            "current_waypoint_idx": 0,
            "status": "planning",
            "error": None,
        }
        result = planner.validate_rooms(state)
        assert result["error"] is not None
        assert "kitchen" in result["error"]
        assert result["status"] == "error"


class TestGenerateWaypoints:
    def test_generates_waypoints_for_single_room(self, planner):
        state: PlannerState = {
            "mission_id": "m_001",
            "goal": "Patrol living room",
            "room_ids": ["living"],
            "rooms": [{"id": "living", "width_cm": 400, "depth_cm": 500}],
            "mission_pads": [{"id": 1, "room_id": "living", "x_cm": 200, "y_cm": 250}],
            "waypoints": [],
            "current_waypoint_idx": 0,
            "status": "planning",
            "error": None,
        }
        result = planner.generate_waypoints(state)
        assert len(result["waypoints"]) > 0
        # First waypoint should be takeoff
        assert result["waypoints"][0]["action"] == "takeoff"
        # Last waypoint should be land
        assert result["waypoints"][-1]["action"] == "land"

    def test_generates_waypoints_for_multi_room(self, planner):
        state: PlannerState = {
            "mission_id": "m_001",
            "goal": "Patrol living and kitchen",
            "room_ids": ["living", "kitchen"],
            "rooms": [
                {"id": "living", "width_cm": 400, "depth_cm": 500},
                {"id": "kitchen", "width_cm": 300, "depth_cm": 200},
            ],
            "mission_pads": [
                {"id": 1, "room_id": "living", "x_cm": 200, "y_cm": 250},
                {"id": 3, "room_id": "kitchen", "x_cm": 150, "y_cm": 100},
            ],
            "waypoints": [],
            "current_waypoint_idx": 0,
            "status": "planning",
            "error": None,
        }
        result = planner.generate_waypoints(state)
        waypoints = result["waypoints"]
        assert waypoints[0]["action"] == "takeoff"
        assert waypoints[-1]["action"] == "land"
        # Should have waypoints in both rooms
        room_ids = {wp["room_id"] for wp in waypoints}
        assert "living" in room_ids
        assert "kitchen" in room_ids


class TestValidatePlan:
    def test_valid_plan_passes(self, planner):
        waypoints = [
            {"id": "wp_0", "action": "takeoff", "room_id": "living", "sequence": 0},
            {
                "id": "wp_1",
                "action": "move",
                "room_id": "living",
                "sequence": 1,
                "distance_cm": 100,
            },
            {"id": "wp_2", "action": "land", "room_id": "living", "sequence": 2},
        ]
        state: PlannerState = {
            "mission_id": "m_001",
            "goal": "Patrol",
            "room_ids": ["living"],
            "rooms": [],
            "mission_pads": [],
            "waypoints": waypoints,
            "current_waypoint_idx": 0,
            "status": "planning",
            "error": None,
        }
        result = planner.validate_plan(state)
        assert result.get("error") is None

    def test_too_many_waypoints_errors(self, planner):
        planner._config.max_waypoints_per_mission = 3
        waypoints = [
            {"id": f"wp_{i}", "action": "move", "room_id": "r", "sequence": i} for i in range(5)
        ]
        state: PlannerState = {
            "mission_id": "m_001",
            "goal": "Patrol",
            "room_ids": ["r"],
            "rooms": [],
            "mission_pads": [],
            "waypoints": waypoints,
            "current_waypoint_idx": 0,
            "status": "planning",
            "error": None,
        }
        result = planner.validate_plan(state)
        assert result["error"] is not None
        assert result["status"] == "error"


class TestFinalize:
    def test_sets_planned_status(self, planner):
        state: PlannerState = {
            "mission_id": "m_001",
            "goal": "Patrol",
            "room_ids": ["living"],
            "rooms": [],
            "mission_pads": [],
            "waypoints": [{"id": "wp_0", "action": "takeoff"}],
            "current_waypoint_idx": 0,
            "status": "planning",
            "error": None,
        }
        result = planner.finalize(state)
        assert result["status"] == "planned"


class TestFullGraph:
    async def test_plan_happy_path(self, planner, mock_repo):
        mock_repo.get_rooms.return_value = [
            {
                "id": "living",
                "name": "Living Room",
                "width_cm": 400,
                "depth_cm": 500,
                "height_cm": 234,
            },
        ]
        mock_repo.get_room_pads.return_value = [
            {"id": 1, "room_id": "living", "x_cm": 200, "y_cm": 250},
        ]
        result = await planner.plan(
            mission_id="m_001",
            goal="Patrol living room",
            room_ids=["living"],
        )
        assert result["status"] == "planned"
        assert len(result["waypoints"]) > 0
        assert result["error"] is None

    async def test_plan_unknown_room_errors(self, planner, mock_repo):
        mock_repo.get_rooms.return_value = []
        mock_repo.get_room_pads.return_value = []
        result = await planner.plan(
            mission_id="m_002",
            goal="Check nonexistent room",
            room_ids=["fantasy"],
        )
        assert result["status"] == "error"
        assert result["error"] is not None
        assert "fantasy" in result["error"]
