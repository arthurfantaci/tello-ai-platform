"""Tests for mission query MCP tools."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tello_navigator.tools import queries


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
    queries.register(mcp)

    mock_ctx = MagicMock()
    mock_repo = MagicMock()
    mock_ctx.lifespan_context = {"repo": mock_repo}
    return registered_tools, mock_ctx, mock_repo


class TestGetMission:
    async def test_returns_mission(self, setup):
        tools, ctx, repo = setup
        repo.get_mission.return_value = {"id": "m_001", "goal": "Patrol"}
        repo.get_mission_waypoints.return_value = [{"id": "wp_0"}]
        result = await tools["get_mission"](ctx, mission_id="m_001")
        assert result["mission"]["id"] == "m_001"
        assert len(result["waypoints"]) == 1

    async def test_not_found(self, setup):
        tools, ctx, repo = setup
        repo.get_mission.return_value = None
        result = await tools["get_mission"](ctx, mission_id="nonexistent")
        assert result["error"] == "NOT_FOUND"


class TestListMissions:
    async def test_returns_list(self, setup):
        tools, ctx, repo = setup
        repo.list_missions.return_value = [
            {"id": "m_001"},
            {"id": "m_002"},
        ]
        result = await tools["list_missions"](ctx, limit=10)
        assert result["count"] == 2

    async def test_filters_by_status(self, setup):
        tools, ctx, repo = setup
        repo.list_missions.return_value = [{"id": "m_001"}]
        await tools["list_missions"](ctx, limit=10, status="planned")
        repo.list_missions.assert_called_once_with(10, status="planned")


class TestSeedRoomGraph:
    async def test_seeds_rooms(self, setup):
        tools, ctx, repo = setup
        rooms = [
            {"id": "living", "name": "Living", "width_cm": 400, "depth_cm": 500, "height_cm": 234},
        ]
        pads = [{"id": 1, "room_id": "living", "x_cm": 100, "y_cm": 100}]
        connections = []
        result = await tools["seed_room_graph"](
            ctx,
            rooms=rooms,
            pads=pads,
            connections=connections,
        )
        assert result["status"] == "ok"
        repo.seed_room_graph.assert_called_once()
