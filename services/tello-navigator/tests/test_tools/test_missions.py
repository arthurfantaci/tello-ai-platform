"""Tests for mission lifecycle MCP tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tello_navigator.tools.missions import register


class TestCreateMission:
    @pytest.fixture(autouse=True)
    def setup_mcp(self):
        self.mcp = MagicMock()
        self.registered_tools: dict = {}

        def mock_tool(*args, **kwargs):
            if args and callable(args[0]):
                fn = args[0]
                self.registered_tools[fn.__name__] = fn
                return fn

            def decorator(fn):
                self.registered_tools[fn.__name__] = fn
                return fn

            return decorator

        self.mcp.tool = mock_tool
        register(self.mcp)

        self.mock_repo = MagicMock()
        self.mock_planner = MagicMock()
        self.mock_planner.plan = AsyncMock()
        self.mock_events = AsyncMock()
        self.mock_ctx = MagicMock()
        self.mock_ctx.lifespan_context = {
            "planner": self.mock_planner,
            "repo": self.mock_repo,
            "events": self.mock_events,
        }

    async def test_happy_path(self):
        self.mock_planner.plan.return_value = {
            "status": "planned",
            "waypoints": [
                {"id": "wp_0", "sequence": 0, "room_id": "living", "action": "takeoff"},
                {
                    "id": "wp_1",
                    "sequence": 1,
                    "room_id": "living",
                    "pad_id": 1,
                    "action": "goto_pad",
                },
                {"id": "wp_2", "sequence": 2, "room_id": "living", "action": "land"},
            ],
            "error": None,
        }

        result = await self.registered_tools["create_mission"](
            self.mock_ctx, goal="Survey living room", room_ids=["living"]
        )

        assert result["status"] == "planned"
        assert result["waypoint_count"] == 3
        assert result["mission_id"]  # non-empty
        assert len(result["waypoints"]) == 3
        self.mock_planner.plan.assert_awaited_once()
        self.mock_repo.create_mission.assert_called_once()
        self.mock_repo.save_waypoints.assert_called_once()
        self.mock_events.mission_created.assert_awaited_once()

    async def test_planning_error(self):
        self.mock_planner.plan.return_value = {
            "status": "error",
            "waypoints": [],
            "error": "Unknown rooms: ['garage']",
        }

        result = await self.registered_tools["create_mission"](
            self.mock_ctx, goal="Explore garage", room_ids=["garage"]
        )

        assert result["error"] == "PLANNING_FAILED"
        assert "garage" in result["detail"]
        self.mock_repo.create_mission.assert_not_called()
        self.mock_events.mission_created.assert_not_awaited()


class TestStartMission:
    @pytest.fixture(autouse=True)
    def setup_mcp(self):
        self.mcp = MagicMock()
        self.registered_tools: dict = {}

        def mock_tool(*args, **kwargs):
            if args and callable(args[0]):
                fn = args[0]
                self.registered_tools[fn.__name__] = fn
                return fn

            def decorator(fn):
                self.registered_tools[fn.__name__] = fn
                return fn

            return decorator

        self.mcp.tool = mock_tool
        register(self.mcp)

        self.mock_repo = MagicMock()
        self.mock_events = AsyncMock()
        self.mock_ctx = MagicMock()
        self.mock_ctx.lifespan_context = {
            "planner": MagicMock(),
            "repo": self.mock_repo,
            "events": self.mock_events,
        }

    async def test_start_planned_mission(self):
        self.mock_repo.get_mission.return_value = {"id": "m1", "status": "planned"}
        self.mock_repo.get_mission_waypoints.return_value = [
            {"id": "wp_0", "sequence": 0, "room_id": "living", "action": "takeoff"},
            {"id": "wp_1", "sequence": 1, "room_id": "living", "action": "land"},
        ]

        result = await self.registered_tools["start_mission"](self.mock_ctx, mission_id="m1")

        assert result["status"] == "executing"
        assert result["mission_id"] == "m1"
        assert result["current_waypoint"]["id"] == "wp_0"
        assert result["suggested_command"]["tool"] == "takeoff"
        assert result["total_waypoints"] == 2
        self.mock_repo.update_mission_status.assert_called_once()
        self.mock_events.mission_started.assert_awaited_once_with("m1")

    async def test_not_found(self):
        self.mock_repo.get_mission.return_value = None

        result = await self.registered_tools["start_mission"](
            self.mock_ctx, mission_id="nonexistent"
        )

        assert result["error"] == "NOT_FOUND"

    async def test_invalid_transition(self):
        self.mock_repo.get_mission.return_value = {"id": "m1", "status": "executing"}

        result = await self.registered_tools["start_mission"](self.mock_ctx, mission_id="m1")

        assert result["error"] == "INVALID_TRANSITION"
        assert "executing" in result["detail"]


class TestAdvanceMission:
    @pytest.fixture(autouse=True)
    def setup_mcp(self):
        self.mcp = MagicMock()
        self.registered_tools: dict = {}

        def mock_tool(*args, **kwargs):
            if args and callable(args[0]):
                fn = args[0]
                self.registered_tools[fn.__name__] = fn
                return fn

            def decorator(fn):
                self.registered_tools[fn.__name__] = fn
                return fn

            return decorator

        self.mcp.tool = mock_tool
        register(self.mcp)

        self.mock_repo = MagicMock()
        self.mock_events = AsyncMock()
        self.mock_ctx = MagicMock()
        self.mock_ctx.lifespan_context = {
            "planner": MagicMock(),
            "repo": self.mock_repo,
            "events": self.mock_events,
        }

    async def test_advance_to_next_waypoint(self):
        self.mock_repo.get_mission.return_value = {"id": "m1", "status": "executing"}
        self.mock_repo.get_mission_waypoints.return_value = [
            {"id": "wp_0", "sequence": 0, "room_id": "living", "action": "takeoff"},
            {
                "id": "wp_1",
                "sequence": 1,
                "room_id": "living",
                "action": "move",
                "direction": "forward",
                "distance_cm": 100,
            },
            {"id": "wp_2", "sequence": 2, "room_id": "living", "action": "land"},
        ]

        result = await self.registered_tools["advance_mission"](
            self.mock_ctx, mission_id="m1", current_waypoint_idx=0
        )

        assert result["status"] == "executing"
        assert result["next_waypoint"]["id"] == "wp_1"
        assert result["suggested_command"]["tool"] == "move"
        assert result["waypoints_remaining"] == 1
        self.mock_events.waypoint_reached.assert_awaited_once_with("m1", "wp_1", 1)

    async def test_completion(self):
        self.mock_repo.get_mission.return_value = {"id": "m1", "status": "executing"}
        self.mock_repo.get_mission_waypoints.return_value = [
            {"id": "wp_0", "sequence": 0, "room_id": "living", "action": "takeoff"},
            {"id": "wp_1", "sequence": 1, "room_id": "living", "action": "land"},
        ]

        result = await self.registered_tools["advance_mission"](
            self.mock_ctx, mission_id="m1", current_waypoint_idx=1
        )

        assert result["status"] == "completed"
        assert result["mission_id"] == "m1"
        self.mock_repo.update_mission_status.assert_called_once()
        self.mock_events.mission_completed.assert_awaited_once()

    async def test_invalid_state(self):
        self.mock_repo.get_mission.return_value = {"id": "m1", "status": "planned"}

        result = await self.registered_tools["advance_mission"](
            self.mock_ctx, mission_id="m1", current_waypoint_idx=0
        )

        assert result["error"] == "INVALID_TRANSITION"
        assert "planned" in result["detail"]


class TestAbortMission:
    @pytest.fixture(autouse=True)
    def setup_mcp(self):
        self.mcp = MagicMock()
        self.registered_tools: dict = {}

        def mock_tool(*args, **kwargs):
            if args and callable(args[0]):
                fn = args[0]
                self.registered_tools[fn.__name__] = fn
                return fn

            def decorator(fn):
                self.registered_tools[fn.__name__] = fn
                return fn

            return decorator

        self.mcp.tool = mock_tool
        register(self.mcp)

        self.mock_repo = MagicMock()
        self.mock_events = AsyncMock()
        self.mock_ctx = MagicMock()
        self.mock_ctx.lifespan_context = {
            "planner": MagicMock(),
            "repo": self.mock_repo,
            "events": self.mock_events,
        }

    async def test_abort_from_executing(self):
        self.mock_repo.get_mission.return_value = {"id": "m1", "status": "executing"}

        result = await self.registered_tools["abort_mission"](
            self.mock_ctx, mission_id="m1", reason="Battery low"
        )

        assert result["status"] == "aborted"
        assert result["mission_id"] == "m1"
        self.mock_repo.update_mission_status.assert_called_once()
        call_kwargs = self.mock_repo.update_mission_status.call_args
        assert call_kwargs[1]["error"] == "Battery low"
        self.mock_events.mission_aborted.assert_awaited_once_with("m1", "Battery low")

    async def test_abort_from_planned(self):
        self.mock_repo.get_mission.return_value = {"id": "m1", "status": "planned"}

        result = await self.registered_tools["abort_mission"](
            self.mock_ctx, mission_id="m1", reason="Changed plans"
        )

        assert result["status"] == "aborted"
        self.mock_events.mission_aborted.assert_awaited_once()

    async def test_abort_completed_errors(self):
        self.mock_repo.get_mission.return_value = {"id": "m1", "status": "completed"}

        result = await self.registered_tools["abort_mission"](
            self.mock_ctx, mission_id="m1", reason="Too late"
        )

        assert result["error"] == "INVALID_TRANSITION"
        assert "completed" in result["detail"]
        self.mock_repo.update_mission_status.assert_not_called()
