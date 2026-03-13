"""Tests for query MCP tools."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tello_navigator.tools.queries import register


class TestGetMission:
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
        self.mock_ctx = MagicMock()
        self.mock_ctx.lifespan_context = {"repo": self.mock_repo}

    async def test_get_mission_found(self):
        mission = {"id": "m1", "status": "planned", "goal": "Survey living room"}
        waypoints = [
            {"id": "wp_0", "sequence": 0, "room_id": "living", "action": "takeoff"},
            {"id": "wp_1", "sequence": 1, "room_id": "living", "action": "land"},
        ]
        self.mock_repo.get_mission.return_value = mission
        self.mock_repo.get_mission_waypoints.return_value = waypoints

        result = await self.registered_tools["get_mission"](self.mock_ctx, mission_id="m1")

        assert result["mission"] == mission
        assert result["waypoints"] == waypoints
        self.mock_repo.get_mission.assert_called_once_with("m1")
        self.mock_repo.get_mission_waypoints.assert_called_once_with("m1")

    async def test_get_mission_not_found(self):
        self.mock_repo.get_mission.return_value = None

        result = await self.registered_tools["get_mission"](self.mock_ctx, mission_id="nonexistent")

        assert result["error"] == "NOT_FOUND"
        assert "nonexistent" in result["detail"]
        self.mock_repo.get_mission_waypoints.assert_not_called()


class TestListMissions:
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
        self.mock_ctx = MagicMock()
        self.mock_ctx.lifespan_context = {"repo": self.mock_repo}

    async def test_list_missions(self):
        missions = [
            {"id": "m1", "status": "planned"},
            {"id": "m2", "status": "completed"},
        ]
        self.mock_repo.list_missions.return_value = missions

        result = await self.registered_tools["list_missions"](self.mock_ctx)

        assert result["missions"] == missions
        assert result["count"] == 2
        self.mock_repo.list_missions.assert_called_once_with(10, None)

    async def test_list_missions_with_status(self):
        missions = [{"id": "m1", "status": "planned"}]
        self.mock_repo.list_missions.return_value = missions

        result = await self.registered_tools["list_missions"](
            self.mock_ctx, limit=5, status="planned"
        )

        assert result["missions"] == missions
        assert result["count"] == 1
        self.mock_repo.list_missions.assert_called_once_with(5, "planned")


class TestSeedRoomGraph:
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
        self.mock_ctx = MagicMock()
        self.mock_ctx.lifespan_context = {"repo": self.mock_repo}

    async def test_seed_room_graph(self):
        rooms = [{"id": "living", "name": "Living Room"}, {"id": "bedroom", "name": "Bedroom"}]
        pads = [{"id": 1, "room_id": "living"}, {"id": 2, "room_id": "bedroom"}]
        connections = [{"from_room": "living", "to_room": "bedroom", "distance_cm": 300}]

        result = await self.registered_tools["seed_room_graph"](
            self.mock_ctx, rooms=rooms, pads=pads, connections=connections
        )

        assert result["status"] == "seeded"
        assert result["rooms_seeded"] == 2
        assert result["pads_seeded"] == 2
        assert result["connections_seeded"] == 1
        self.mock_repo.seed_room_graph.assert_called_once_with(rooms, pads, connections)
