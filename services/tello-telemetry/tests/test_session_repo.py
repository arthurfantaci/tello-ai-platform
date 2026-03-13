"""Tests for Neo4j session repository.

All tests mock the Neo4j driver -- no real database connections.
Tests verify that correct Cypher queries are executed with the
right parameters.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from tello_core.models import Anomaly, FlightSession, TelemetrySample
from tello_telemetry.session_repo import SessionRepository


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
    return SessionRepository(mock_driver)


class TestCreateSession:
    def test_creates_session_node(self, repo, mock_session):
        session = FlightSession(
            id="sess-1",
            start_time=datetime(2026, 3, 12, 10, 0, 0, tzinfo=UTC),
            room_id="living_room",
        )
        repo.create_session(session)
        mock_session.run.assert_called_once()
        cypher = mock_session.run.call_args[0][0]
        params = mock_session.run.call_args[1]
        assert "CREATE" in cypher
        assert ":FlightSession" in cypher
        assert params["session_id"] == "sess-1"
        assert params["room_id"] == "living_room"


class TestEndSession:
    def test_sets_end_time_and_duration(self, repo, mock_session):
        end = datetime(2026, 3, 12, 10, 5, 0, tzinfo=UTC)
        repo.end_session("sess-1", end)
        mock_session.run.assert_called_once()
        cypher = mock_session.run.call_args[0][0]
        params = mock_session.run.call_args[1]
        assert "MATCH" in cypher
        assert "end_time" in cypher
        assert params["session_id"] == "sess-1"


class TestAddSample:
    def test_creates_sample_linked_to_session(self, repo, mock_session):
        sample = TelemetrySample(
            battery_pct=75,
            height_cm=100,
            tof_cm=95,
            temp_c=42.0,
            timestamp=datetime(2026, 3, 12, 10, 1, 0, tzinfo=UTC),
        )
        repo.add_sample("sess-1", sample)
        mock_session.run.assert_called_once()
        cypher = mock_session.run.call_args[0][0]
        assert ":BELONGS_TO" in cypher
        assert ":TelemetrySample" in cypher


class TestAddAnomaly:
    def test_creates_anomaly_linked_to_session(self, repo, mock_session):
        anomaly = Anomaly(
            type="battery_low",
            severity="warning",
            detail="Battery at 18%",
            timestamp=datetime(2026, 3, 12, 10, 2, 0, tzinfo=UTC),
        )
        repo.add_anomaly("sess-1", anomaly)
        mock_session.run.assert_called_once()
        cypher = mock_session.run.call_args[0][0]
        assert ":OCCURRED_DURING" in cypher
        assert ":Anomaly" in cypher


class TestGetSession:
    def test_returns_dict_when_found(self, repo, mock_session):
        record = MagicMock()
        record.data.return_value = {
            "session": {
                "id": "sess-1",
                "start_time": "2026-03-12T10:00:00Z",
                "room_id": "living_room",
            },
        }
        mock_session.run.return_value.single.return_value = record
        result = repo.get_session("sess-1")
        assert result["id"] == "sess-1"
        assert result["room_id"] == "living_room"

    def test_returns_none_when_not_found(self, repo, mock_session):
        mock_session.run.return_value.single.return_value = None
        result = repo.get_session("nonexistent")
        assert result is None


class TestListSessions:
    def test_returns_list_of_dicts(self, repo, mock_session):
        record1 = MagicMock()
        record1.data.return_value = {"session": {"id": "sess-1"}}
        record2 = MagicMock()
        record2.data.return_value = {"session": {"id": "sess-2"}}
        mock_session.run.return_value = [record1, record2]
        result = repo.list_sessions(limit=10)
        assert len(result) == 2
        assert result[0]["id"] == "sess-1"


class TestGetSessionSamples:
    def test_returns_sample_list(self, repo, mock_session):
        record = MagicMock()
        record.data.return_value = {
            "sample": {
                "battery_pct": 75,
                "timestamp": "2026-03-12T10:01:00Z",
            },
        }
        mock_session.run.return_value = [record]
        result = repo.get_session_samples("sess-1")
        assert len(result) == 1
        assert result[0]["battery_pct"] == 75


class TestGetSessionAnomalies:
    def test_returns_anomaly_list(self, repo, mock_session):
        record = MagicMock()
        record.data.return_value = {
            "anomaly": {
                "type": "battery_low",
                "severity": "warning",
            },
        }
        mock_session.run.return_value = [record]
        result = repo.get_session_anomalies("sess-1")
        assert len(result) == 1
        assert result[0]["type"] == "battery_low"


class TestGetAnomalySummary:
    def test_returns_aggregated_counts(self, repo, mock_session):
        record = MagicMock()
        record.data.return_value = {
            "type": "battery_low",
            "count": 5,
        }
        mock_session.run.return_value = [record]
        result = repo.get_anomaly_summary()
        assert len(result) == 1
        assert result[0]["count"] == 5
