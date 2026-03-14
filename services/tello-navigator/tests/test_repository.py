"""Tests for Neo4j mission repository.

All tests mock the Neo4j driver -- no real database connections.
Tests verify that correct Cypher queries are executed with the
right parameters.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tello_navigator.repository import MissionRepository


@pytest.fixture()
def mock_session():
    """Mock Neo4j session with run() method."""
    session = MagicMock()
    session.run = MagicMock()
    return session


@pytest.fixture()
def mock_driver(mock_session):
    """Mock Neo4j driver that yields mock_session."""
    driver = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(
        return_value=mock_session,
    )
    driver.session.return_value.__exit__ = MagicMock(
        return_value=False,
    )
    return driver


@pytest.fixture()
def repo(mock_driver):
    return MissionRepository(mock_driver)


class TestCreateMission:
    def test_creates_mission_node(self, repo, mock_session):
        repo.create_mission(
            mission_id="mission-1",
            goal="Survey the living room",
            room_ids=["living_room"],
            status="planned",
            created_at="2026-03-13T10:00:00Z",
        )
        mock_session.run.assert_called_once()
        cypher = mock_session.run.call_args[0][0]
        params = mock_session.run.call_args[1]
        assert "CREATE" in cypher
        assert ":Mission" in cypher
        assert params["mission_id"] == "mission-1"
        assert params["goal"] == "Survey the living room"
        assert params["room_ids"] == ["living_room"]
        assert params["status"] == "planned"


class TestSaveWaypoints:
    def test_creates_linked_waypoint_nodes(self, repo, mock_session):
        from tello_core.models import Waypoint

        wp1 = Waypoint(
            id="wp-1",
            sequence=0,
            room_id="living_room",
            pad_id=1,
            action="takeoff",
        )
        wp2 = Waypoint(
            id="wp-2",
            sequence=1,
            room_id="living_room",
            pad_id=None,
            action="move",
            direction="forward",
            distance_cm=100,
        )
        repo.save_waypoints("mission-1", [wp1, wp2])
        assert mock_session.run.call_count == 2
        cypher = mock_session.run.call_args_list[0][0][0]
        assert ":CONTAINS_WAYPOINT" in cypher
        assert ":Waypoint" in cypher
        params = mock_session.run.call_args_list[0][1]
        assert params["wp_id"] == "wp-1"
        assert params["sequence"] == 0

    def test_saves_speed_cm_s_for_goto_pad(self, repo, mock_session):
        from tello_core.models import Waypoint

        wp = Waypoint(
            id="wp-1",
            sequence=0,
            room_id="living_room",
            pad_id=1,
            action="goto_pad",
            speed_cm_s=30,
        )
        repo.save_waypoints("mission-1", [wp])
        cypher = mock_session.run.call_args_list[0][0][0]
        assert "speed_cm_s" in cypher
        params = mock_session.run.call_args_list[0][1]
        assert params["speed_cm_s"] == 30


class TestUpdateMissionStatus:
    def test_updates_status(self, repo, mock_session):
        repo.update_mission_status("mission-1", "executing", started_at="2026-03-13T10:01:00Z")
        mock_session.run.assert_called_once()
        cypher = mock_session.run.call_args[0][0]
        params = mock_session.run.call_args[1]
        assert "SET" in cypher
        assert "status" in cypher
        assert params["status"] == "executing"
        assert params["started_at"] == "2026-03-13T10:01:00Z"

    def test_updates_status_with_error(self, repo, mock_session):
        repo.update_mission_status("mission-1", "aborted", error="Battery critical")
        params = mock_session.run.call_args[1]
        assert params["error"] == "Battery critical"


class TestGetMission:
    def test_returns_dict_when_found(self, repo, mock_session):
        record = MagicMock()
        record.data.return_value = {
            "mission": {
                "id": "mission-1",
                "goal": "Survey the living room",
                "status": "planned",
            },
        }
        mock_session.run.return_value.single.return_value = record
        result = repo.get_mission("mission-1")
        assert result["id"] == "mission-1"
        assert result["goal"] == "Survey the living room"

    def test_returns_none_when_not_found(self, repo, mock_session):
        mock_session.run.return_value.single.return_value = None
        result = repo.get_mission("nonexistent")
        assert result is None


class TestListMissions:
    def test_returns_list_of_dicts(self, repo, mock_session):
        record1 = MagicMock()
        record1.data.return_value = {"mission": {"id": "mission-1"}}
        record2 = MagicMock()
        record2.data.return_value = {"mission": {"id": "mission-2"}}
        mock_session.run.return_value = [record1, record2]
        result = repo.list_missions(limit=10)
        assert len(result) == 2
        assert result[0]["id"] == "mission-1"

    def test_filters_by_status(self, repo, mock_session):
        record = MagicMock()
        record.data.return_value = {"mission": {"id": "mission-1", "status": "planned"}}
        mock_session.run.return_value = [record]
        result = repo.list_missions(status="planned")
        assert len(result) == 1
        cypher = mock_session.run.call_args[0][0]
        assert "status: $status" in cypher


class TestGetMissionWaypoints:
    def test_returns_ordered_waypoints(self, repo, mock_session):
        record = MagicMock()
        record.data.return_value = {
            "waypoint": {"id": "wp-1", "sequence": 0, "action": "takeoff"},
        }
        mock_session.run.return_value = [record]
        result = repo.get_mission_waypoints("mission-1")
        assert len(result) == 1
        assert result[0]["action"] == "takeoff"
        cypher = mock_session.run.call_args[0][0]
        assert "ORDER BY w.sequence" in cypher


class TestRoomGraphQueries:
    def test_get_rooms(self, repo, mock_session):
        record = MagicMock()
        record.data.return_value = {
            "room": {"id": "living_room", "name": "Living Room", "width_cm": 500},
        }
        mock_session.run.return_value = [record]
        result = repo.get_rooms(["living_room"])
        assert len(result) == 1
        assert result[0]["id"] == "living_room"

    def test_get_room_pads(self, repo, mock_session):
        record = MagicMock()
        record.data.return_value = {
            "pad": {"id": 1, "room_id": "living_room", "x_cm": 100, "y_cm": 200},
        }
        mock_session.run.return_value = [record]
        result = repo.get_room_pads(["living_room"])
        assert len(result) == 1
        assert result[0]["id"] == 1


class TestSeedRoomGraph:
    def test_seeds_rooms_pads_and_connections(self, repo, mock_session):
        rooms = [
            {
                "id": "living_room",
                "name": "Living Room",
                "width_cm": 500,
                "depth_cm": 400,
                "height_cm": 270,
            },
        ]
        pads = [
            {"id": 1, "room_id": "living_room", "x_cm": 100, "y_cm": 200},
        ]
        connections = [
            {
                "from_room": "living_room",
                "to_room": "kitchen",
                "via_pad": 2,
                "direction": "north",
                "passage_type": "doorway",
            },
        ]
        repo.seed_room_graph(rooms, pads, connections)
        # 1 room + 1 pad + 1 connection = 3 calls
        assert mock_session.run.call_count == 3
        # Verify MERGE used (idempotent)
        for call_obj in mock_session.run.call_args_list:
            cypher = call_obj[0][0]
            assert "MERGE" in cypher
