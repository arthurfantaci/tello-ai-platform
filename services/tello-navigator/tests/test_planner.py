"""Tests for MissionPlanner."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tello_navigator.planner import MissionPlanner, PlannerState

# -- Fixtures ---------------------------------------------------------


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.get_rooms.return_value = [
        {"id": "living", "name": "Living", "width_cm": 400, "depth_cm": 500, "height_cm": 234},
        {"id": "kitchen", "name": "Kitchen", "width_cm": 300, "depth_cm": 300, "height_cm": 234},
    ]
    repo.get_room_pads.return_value = [
        {"id": 1, "room_id": "living", "x_cm": 200, "y_cm": 250},
        {"id": 2, "room_id": "living", "x_cm": 100, "y_cm": 100},
        {"id": 3, "room_id": "kitchen", "x_cm": 150, "y_cm": 150},
    ]
    return repo


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.max_waypoints_per_mission = 20
    config.planning_timeout_s = 30.0
    config.default_move_distance_cm = 100
    return config


@pytest.fixture
def planner(mock_repo, mock_config):
    return MissionPlanner(mock_repo, mock_config, checkpointer=None)


def _make_state(**overrides) -> PlannerState:
    """Build a minimal PlannerState with defaults, applying overrides."""
    base: PlannerState = {
        "mission_id": "m1",
        "goal": "patrol",
        "room_ids": ["living", "kitchen"],
        "rooms": [],
        "mission_pads": [],
        "waypoints": [],
        "current_waypoint_idx": 0,
        "status": "planning",
        "error": None,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


# -- Unit tests: individual nodes ------------------------------------


class TestFetchRooms:
    def test_populates_rooms_and_pads(self, planner, mock_repo):
        state = _make_state()
        result = planner._fetch_rooms(state)

        mock_repo.get_rooms.assert_called_once_with(["living", "kitchen"])
        mock_repo.get_room_pads.assert_called_once_with(["living", "kitchen"])
        assert len(result["rooms"]) == 2
        assert len(result["mission_pads"]) == 3


class TestValidateRooms:
    def test_all_rooms_found_returns_empty(self, planner):
        state = _make_state(
            rooms=[{"id": "living"}, {"id": "kitchen"}],
        )
        result = planner._validate_rooms(state)
        assert result == {}

    def test_missing_room_returns_error(self, planner):
        state = _make_state(
            room_ids=["living", "kitchen", "bathroom"],
            rooms=[{"id": "living"}, {"id": "kitchen"}],
        )
        result = planner._validate_rooms(state)
        assert result["status"] == "error"
        assert "bathroom" in result["error"]


class TestGenerateWaypoints:
    def test_single_room_with_pads(self, planner):
        state = _make_state(
            room_ids=["living"],
            rooms=[{"id": "living", "depth_cm": 500}],
            mission_pads=[
                {"id": 1, "room_id": "living"},
                {"id": 2, "room_id": "living"},
            ],
        )
        result = planner._generate_waypoints(state)
        wps = result["waypoints"]

        assert wps[0]["action"] == "takeoff"
        assert wps[1]["action"] == "goto_pad"
        assert wps[2]["action"] == "goto_pad"
        assert wps[-1]["action"] == "land"
        assert result["current_waypoint_idx"] == 0

    def test_goto_pad_waypoints_include_speed(self, planner):
        state = _make_state(
            room_ids=["living"],
            rooms=[{"id": "living", "depth_cm": 500}],
            mission_pads=[
                {"id": 1, "room_id": "living"},
                {"id": 2, "room_id": "living"},
            ],
        )
        result = planner._generate_waypoints(state)
        goto_pads = [wp for wp in result["waypoints"] if wp["action"] == "goto_pad"]
        assert len(goto_pads) > 0
        for wp in goto_pads:
            assert wp["speed_cm_s"] == 30

    def test_multi_room_with_pads(self, planner):
        state = _make_state(
            room_ids=["living", "kitchen"],
            rooms=[
                {"id": "living", "depth_cm": 500},
                {"id": "kitchen", "depth_cm": 300},
            ],
            mission_pads=[
                {"id": 1, "room_id": "living"},
                {"id": 3, "room_id": "kitchen"},
            ],
        )
        result = planner._generate_waypoints(state)
        wps = result["waypoints"]

        # takeoff + 1 pad (living) + 1 pad (kitchen) + land = 4
        assert len(wps) == 4
        assert wps[0]["action"] == "takeoff"
        assert wps[0]["room_id"] == "living"
        assert wps[-1]["action"] == "land"
        assert wps[-1]["room_id"] == "kitchen"

    def test_room_without_pads_uses_forward_move(self, planner):
        state = _make_state(
            room_ids=["hallway"],
            rooms=[{"id": "hallway", "depth_cm": 300}],
            mission_pads=[],
        )
        result = planner._generate_waypoints(state)
        wps = result["waypoints"]

        # takeoff + move + land = 3
        assert len(wps) == 3
        move_wp = wps[1]
        assert move_wp["action"] == "move"
        assert move_wp["direction"] == "forward"
        assert move_wp["distance_cm"] == 150  # 300 // 2


class TestValidatePlan:
    def test_under_limit_passes(self, planner):
        state = _make_state(waypoints=[{"id": f"wp_{i}"} for i in range(5)])
        result = planner._validate_plan(state)
        assert result == {}

    def test_over_limit_returns_error(self, planner, mock_config):
        mock_config.max_waypoints_per_mission = 3
        state = _make_state(waypoints=[{"id": f"wp_{i}"} for i in range(5)])
        result = planner._validate_plan(state)
        assert result["status"] == "error"
        assert "exceeds max waypoints" in result["error"]


class TestFinalize:
    def test_sets_status_planned(self, planner):
        state = _make_state()
        result = planner._finalize(state)
        assert result == {"status": "planned"}


# -- Integration tests: full graph -----------------------------------


class TestFullGraph:
    async def test_happy_path(self, planner):
        result = await planner.plan("m1", "patrol", ["living", "kitchen"])

        assert result["status"] == "planned"
        assert result["error"] is None
        assert len(result["waypoints"]) > 0
        assert result["waypoints"][0]["action"] == "takeoff"
        assert result["waypoints"][-1]["action"] == "land"

    async def test_unknown_room_error(self, planner, mock_repo):
        # Repo only returns "living" -- "garage" is missing
        mock_repo.get_rooms.return_value = [{"id": "living"}]
        mock_repo.get_room_pads.return_value = []

        result = await planner.plan("m2", "explore", ["living", "garage"])

        assert result["status"] == "error"
        assert "garage" in result["error"]
        assert result["waypoints"] == []
