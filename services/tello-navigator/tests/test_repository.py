"""Tests for MissionRepository (Neo4j CRUD)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from tello_core.models import MissionStatus, Waypoint
from tello_navigator.repository import MissionRepository


@pytest.fixture
def mock_driver():
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver, session


@pytest.fixture
def repo(mock_driver):
    driver, _ = mock_driver
    return MissionRepository(driver)


class TestCreateMission:
    def test_creates_mission_node(self, repo, mock_driver):
        _, session = mock_driver
        repo.create_mission(
            mission_id="m_001",
            goal="Patrol living room",
            room_ids=["living"],
            status=MissionStatus.PLANNED,
            created_at=datetime(2026, 3, 13, 10, 0, 0),
        )
        session.run.assert_called_once()
        cypher = session.run.call_args[0][0]
        assert "CREATE" in cypher
        assert "Mission" in cypher

    def test_passes_correct_params(self, repo, mock_driver):
        _, session = mock_driver
        repo.create_mission(
            mission_id="m_002",
            goal="Check kitchen",
            room_ids=["kitchen", "hall"],
            status=MissionStatus.PLANNED,
            created_at=datetime(2026, 3, 13, 10, 0, 0),
        )
        kwargs = session.run.call_args[1]
        assert kwargs["mission_id"] == "m_002"
        assert kwargs["goal"] == "Check kitchen"
        assert kwargs["room_ids"] == ["kitchen", "hall"]


class TestSaveWaypoints:
    def test_saves_waypoints_linked_to_mission(self, repo, mock_driver):
        _, session = mock_driver
        waypoints = [
            Waypoint(id="wp_1", sequence=0, room_id="living", action="takeoff"),
            Waypoint(
                id="wp_2",
                sequence=1,
                room_id="living",
                action="move",
                direction="forward",
                distance_cm=100,
            ),
        ]
        repo.save_waypoints("m_001", waypoints)
        assert session.run.call_count == 2


class TestUpdateMissionStatus:
    def test_updates_status(self, repo, mock_driver):
        _, session = mock_driver
        repo.update_mission_status("m_001", MissionStatus.EXECUTING)
        session.run.assert_called_once()
        kwargs = session.run.call_args[1]
        assert kwargs["status"] == "executing"

    def test_updates_with_timestamps(self, repo, mock_driver):
        _, session = mock_driver
        now = datetime(2026, 3, 13, 10, 5, 0)
        repo.update_mission_status(
            "m_001",
            MissionStatus.EXECUTING,
            started_at=now,
        )
        kwargs = session.run.call_args[1]
        assert kwargs["started_at"] == now.isoformat()


class TestGetMission:
    def test_returns_mission_dict(self, repo, mock_driver):
        _, session = mock_driver
        session.run.return_value.single.return_value = MagicMock(
            data=lambda: {"mission": {"id": "m_001", "goal": "Patrol", "status": "planned"}}
        )
        result = repo.get_mission("m_001")
        assert result["id"] == "m_001"

    def test_returns_none_when_not_found(self, repo, mock_driver):
        _, session = mock_driver
        session.run.return_value.single.return_value = None
        result = repo.get_mission("nonexistent")
        assert result is None


class TestListMissions:
    def test_returns_list(self, repo, mock_driver):
        _, session = mock_driver
        session.run.return_value = [
            MagicMock(data=lambda: {"mission": {"id": "m_001"}}),
            MagicMock(data=lambda: {"mission": {"id": "m_002"}}),
        ]
        result = repo.list_missions(limit=10)
        assert len(result) == 2

    def test_filters_by_status(self, repo, mock_driver):
        _, session = mock_driver
        session.run.return_value = []
        repo.list_missions(limit=5, status="executing")
        kwargs = session.run.call_args[1]
        assert kwargs["status"] == "executing"


class TestGetMissionWaypoints:
    def test_returns_ordered_waypoints(self, repo, mock_driver):
        _, session = mock_driver
        session.run.return_value = [
            MagicMock(data=lambda: {"waypoint": {"id": "wp_1", "sequence": 0}}),
            MagicMock(data=lambda: {"waypoint": {"id": "wp_2", "sequence": 1}}),
        ]
        result = repo.get_mission_waypoints("m_001")
        assert len(result) == 2
        assert result[0]["sequence"] == 0


class TestRoomGraphQueries:
    def test_get_rooms(self, repo, mock_driver):
        _, session = mock_driver
        session.run.return_value = [
            MagicMock(data=lambda: {"room": {"id": "living", "name": "Living Room"}}),
        ]
        result = repo.get_rooms(["living"])
        assert len(result) == 1

    def test_get_room_pads(self, repo, mock_driver):
        _, session = mock_driver
        session.run.return_value = [
            MagicMock(data=lambda: {"pad": {"id": 1, "room_id": "living"}}),
        ]
        result = repo.get_room_pads(["living"])
        assert len(result) == 1


class TestSeedRoomGraph:
    def test_seeds_rooms_and_pads(self, repo, mock_driver):
        _, session = mock_driver
        rooms = [
            {
                "id": "living",
                "name": "Living Room",
                "width_cm": 400,
                "depth_cm": 500,
                "height_cm": 234,
            },
        ]
        pads = [
            {"id": 1, "room_id": "living", "x_cm": 100, "y_cm": 100},
        ]
        connections = [
            {"from_room": "living", "to_room": "kitchen", "via_pad": 2, "direction": "east"},
        ]
        repo.seed_room_graph(rooms, pads, connections)
        # At minimum, should call run for rooms, pads, and connections
        assert session.run.call_count >= 3
