"""Tests for mission lifecycle MCP tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tello_navigator.tools import missions


@pytest.fixture
def setup():
    mcp = MagicMock()
    registered_tools = {}

    def mock_tool(*args, **kwargs):
        if args and callable(args[0]):
            fn = args[0]
            registered_tools[fn.__name__] = fn
            return fn

        def decorator(fn):
            registered_tools[fn.__name__] = fn
            return fn

        return decorator

    mcp.tool = mock_tool
    missions.register(mcp)

    mock_ctx = MagicMock()
    mock_planner = MagicMock()
    mock_repo = MagicMock()
    mock_events = AsyncMock()
    mock_ctx.lifespan_context = {
        "planner": mock_planner,
        "repo": mock_repo,
        "events": mock_events,
    }
    return registered_tools, mock_ctx, mock_planner, mock_repo, mock_events


class TestCreateMission:
    async def test_creates_mission_happy_path(self, setup):
        tools, ctx, planner, repo, events = setup
        planner.plan = AsyncMock(
            return_value={
                "mission_id": "m_001",
                "status": "planned",
                "waypoints": [
                    {"id": "wp_0", "sequence": 0, "action": "takeoff", "room_id": "living"},
                    {"id": "wp_1", "sequence": 1, "action": "land", "room_id": "living"},
                ],
                "error": None,
            }
        )
        result = await tools["create_mission"](
            ctx,
            goal="Patrol living room",
            room_ids=["living"],
        )
        assert result["status"] == "planned"
        assert result["waypoint_count"] == 2
        events.mission_created.assert_called_once()

    async def test_creates_mission_planning_error(self, setup):
        tools, ctx, planner, repo, events = setup
        planner.plan = AsyncMock(
            return_value={
                "mission_id": "m_002",
                "status": "error",
                "waypoints": [],
                "error": "Unknown rooms: fantasy",
            }
        )
        result = await tools["create_mission"](
            ctx,
            goal="Check fantasy room",
            room_ids=["fantasy"],
        )
        assert result["error"] == "PLANNING_FAILED"
        events.mission_created.assert_not_called()


class TestStartMission:
    async def test_starts_planned_mission(self, setup):
        tools, ctx, planner, repo, events = setup
        repo.get_mission.return_value = {"id": "m_001", "status": "planned"}
        repo.get_mission_waypoints.return_value = [
            {"id": "wp_0", "sequence": 0, "action": "takeoff", "room_id": "living"},
            {"id": "wp_1", "sequence": 1, "action": "move", "room_id": "living"},
        ]
        result = await tools["start_mission"](ctx, mission_id="m_001")
        assert result["status"] == "executing"
        assert result["current_waypoint"]["action"] == "takeoff"
        events.mission_started.assert_called_once()

    async def test_start_nonexistent_mission(self, setup):
        tools, ctx, planner, repo, events = setup
        repo.get_mission.return_value = None
        result = await tools["start_mission"](ctx, mission_id="nonexistent")
        assert result["error"] == "NOT_FOUND"

    async def test_start_non_planned_mission(self, setup):
        tools, ctx, planner, repo, events = setup
        repo.get_mission.return_value = {"id": "m_001", "status": "executing"}
        result = await tools["start_mission"](ctx, mission_id="m_001")
        assert result["error"] == "INVALID_TRANSITION"


class TestAdvanceMission:
    async def test_advances_to_next_waypoint(self, setup):
        tools, ctx, planner, repo, events = setup
        repo.get_mission.return_value = {"id": "m_001", "status": "executing"}
        repo.get_mission_waypoints.return_value = [
            {"id": "wp_0", "sequence": 0, "action": "takeoff", "room_id": "living"},
            {
                "id": "wp_1",
                "sequence": 1,
                "action": "move",
                "room_id": "living",
                "direction": "forward",
                "distance_cm": 100,
            },
            {"id": "wp_2", "sequence": 2, "action": "land", "room_id": "living"},
        ]
        result = await tools["advance_mission"](
            ctx,
            mission_id="m_001",
            current_waypoint_idx=0,
        )
        assert result["next_waypoint"]["action"] == "move"
        assert result["suggested_command"]["tool"] == "move"
        events.waypoint_reached.assert_called_once()

    async def test_completes_mission_at_last_waypoint(self, setup):
        tools, ctx, planner, repo, events = setup
        repo.get_mission.return_value = {"id": "m_001", "status": "executing"}
        repo.get_mission_waypoints.return_value = [
            {"id": "wp_0", "sequence": 0, "action": "takeoff", "room_id": "living"},
            {"id": "wp_1", "sequence": 1, "action": "land", "room_id": "living"},
        ]
        result = await tools["advance_mission"](
            ctx,
            mission_id="m_001",
            current_waypoint_idx=1,
        )
        assert result["status"] == "completed"
        events.mission_completed.assert_called_once()

    async def test_advance_non_executing_mission(self, setup):
        tools, ctx, planner, repo, events = setup
        repo.get_mission.return_value = {"id": "m_001", "status": "planned"}
        result = await tools["advance_mission"](
            ctx,
            mission_id="m_001",
            current_waypoint_idx=0,
        )
        assert result["error"] == "INVALID_TRANSITION"


class TestAbortMission:
    async def test_aborts_executing_mission(self, setup):
        tools, ctx, planner, repo, events = setup
        repo.get_mission.return_value = {"id": "m_001", "status": "executing"}
        result = await tools["abort_mission"](
            ctx,
            mission_id="m_001",
            reason="Low battery",
        )
        assert result["status"] == "aborted"
        events.mission_aborted.assert_called_once()

    async def test_aborts_planned_mission(self, setup):
        tools, ctx, planner, repo, events = setup
        repo.get_mission.return_value = {"id": "m_001", "status": "planned"}
        result = await tools["abort_mission"](ctx, mission_id="m_001")
        assert result["status"] == "aborted"

    async def test_abort_completed_mission_errors(self, setup):
        tools, ctx, planner, repo, events = setup
        repo.get_mission.return_value = {"id": "m_001", "status": "completed"}
        result = await tools["abort_mission"](ctx, mission_id="m_001")
        assert result["error"] == "INVALID_TRANSITION"
