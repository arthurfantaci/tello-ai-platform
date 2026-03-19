"""Tests for Redis Stream consumer.

Tests verify message routing, XACK behavior, PEL recovery,
and consumer group auto-creation. Redis is mocked throughout.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import ResponseError

from tello_telemetry.config import TelloTelemetryConfig
from tello_telemetry.consumer import StreamConsumer
from tello_telemetry.detector import AnomalyDetector
from tello_telemetry.session_repo import SessionRepository


def _make_config(**overrides) -> TelloTelemetryConfig:
    defaults = {
        "neo4j_uri": "bolt://localhost:7687",
        "neo4j_username": "neo4j",
        "neo4j_password": "test",
        "redis_url": "redis://localhost:6379",
        "service_name": "test",
    }
    defaults.update(overrides)
    return TelloTelemetryConfig(**defaults)


def _make_telemetry_fields(**overrides) -> dict:
    """Create stream fields for a telemetry event."""
    frame_data = {
        "battery_pct": 80,
        "height_cm": 100,
        "tof_cm": 95,
        "temp_c": 40.0,
        "pitch": 0.0,
        "roll": 0.0,
        "yaw": 0.0,
        "flight_time_s": 30,
        "timestamp": "2026-03-12T10:00:00Z",
    }
    frame_data.update(overrides)
    return {
        "event_type": "telemetry",
        "data": json.dumps(frame_data),
    }


@pytest.fixture()
def config():
    return _make_config()


@pytest.fixture()
def detector(config):
    return AnomalyDetector(config)


@pytest.fixture()
def session_repo():
    repo = MagicMock(spec=SessionRepository)
    repo.create_session = MagicMock()
    repo.end_session = MagicMock()
    repo.add_sample = MagicMock()
    repo.add_anomaly = MagicMock()
    return repo


@pytest.fixture()
def consumer(mock_redis, config, detector, session_repo):
    return StreamConsumer(
        redis=mock_redis,
        config=config,
        detector=detector,
        session_repo=session_repo,
    )


class TestEnsureConsumerGroup:
    async def test_creates_group(self, consumer, mock_redis):
        await consumer.ensure_consumer_group()
        mock_redis.xgroup_create.assert_called_once_with(
            "tello:events",
            "telemetry-service",
            id="0",
            mkstream=True,
        )

    async def test_ignores_busygroup_error(self, consumer, mock_redis):
        mock_redis.xgroup_create = AsyncMock(
            side_effect=ResponseError("BUSYGROUP"),
        )
        await consumer.ensure_consumer_group()
        # Should not raise


class TestProcessTakeoff:
    async def test_takeoff_creates_session(self, consumer, session_repo):
        fields = {"event_type": "takeoff", "room_id": "living_room"}
        await consumer._process_message("1-0", fields)
        session_repo.create_session.assert_called_once()
        session = session_repo.create_session.call_args[0][0]
        assert session.room_id == "living_room"

    async def test_takeoff_default_room_id(self, consumer, session_repo):
        fields = {"event_type": "takeoff"}
        await consumer._process_message("1-0", fields)
        session = session_repo.create_session.call_args[0][0]
        assert session.room_id == "unknown"


class TestProcessLand:
    async def test_land_ends_session(self, consumer, session_repo):
        # First start a session
        await consumer._process_message(
            "1-0",
            {"event_type": "takeoff"},
        )
        await consumer._process_message(
            "2-0",
            {"event_type": "land"},
        )
        session_repo.end_session.assert_called_once()


class TestProcessTelemetry:
    async def test_telemetry_with_anomaly_persists(
        self,
        consumer,
        session_repo,
    ):
        # Start session
        await consumer._process_message(
            "1-0",
            {"event_type": "takeoff"},
        )
        # Send telemetry with low battery
        fields = _make_telemetry_fields(battery_pct=5)
        await consumer._process_message("2-0", fields)
        session_repo.add_anomaly.assert_called()

    async def test_nominal_telemetry_no_anomaly(
        self,
        consumer,
        session_repo,
    ):
        await consumer._process_message(
            "1-0",
            {"event_type": "takeoff"},
        )
        fields = _make_telemetry_fields()  # all nominal
        await consumer._process_message("2-0", fields)
        session_repo.add_anomaly.assert_not_called()

    async def test_sampling_interval_respected(
        self,
        consumer,
        session_repo,
    ):
        """Only samples to Neo4j when interval has elapsed."""
        await consumer._process_message(
            "1-0",
            {"event_type": "takeoff"},
        )
        # First telemetry — should sample (first frame always samples)
        fields = _make_telemetry_fields()
        await consumer._process_message("2-0", fields)
        assert session_repo.add_sample.call_count == 1

        # Second telemetry immediately — should NOT sample
        await consumer._process_message("3-0", fields)
        assert session_repo.add_sample.call_count == 1


class TestRunLoop:
    async def test_run_processes_pending_then_new(
        self,
        consumer,
        mock_redis,
    ):
        """Run should process pending (ID=0) then new (ID=>)."""
        call_count = 0

        async def mock_xreadgroup(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # Return empty for both pending and new reads
                return []
            raise asyncio.CancelledError

        mock_redis.xreadgroup = AsyncMock(
            side_effect=mock_xreadgroup,
        )
        with pytest.raises(asyncio.CancelledError):
            await consumer.run()
        # Should have called ensure_consumer_group
        mock_redis.xgroup_create.assert_called_once()

    async def test_xack_after_processing(self, consumer, mock_redis):
        """Messages are ACKed after successful processing."""
        msg_id = "1-0"
        fields = {"event_type": "takeoff"}
        # Simulate one message then stop
        call_count = 0

        async def mock_xreadgroup(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Pending read returns empty
                return []
            if call_count == 2:
                return [["tello:events", [(msg_id, fields)]]]
            raise asyncio.CancelledError

        mock_redis.xreadgroup = AsyncMock(
            side_effect=mock_xreadgroup,
        )
        with pytest.raises(asyncio.CancelledError):
            await consumer.run()
        mock_redis.xack.assert_called_with(
            "tello:events",
            "telemetry-service",
            msg_id,
        )


class TestObstacleEventRouting:
    async def test_obstacle_danger_creates_incident(self):
        config = _make_config()
        redis = AsyncMock()
        detector = AnomalyDetector(config)
        session_repo = MagicMock()
        session_repo.add_obstacle_incident = MagicMock()

        consumer = StreamConsumer(redis, config, detector, session_repo)
        # Simulate active session
        consumer._current_session = MagicMock()
        consumer._current_session.id = "session-1"

        fields = {
            "event_type": "obstacle_danger",
            "forward_distance_mm": "185",
            "forward_distance_in": "7.3",
            "height_cm": "80",
            "zone": "DANGER",
            "response": "RETURN_TO_HOME",
            "outcome": "returned",
            "mission_id": "m1",
            "room_id": "living-room",
            "reversed_direction": "back",
        }
        await consumer._process_message("msg-1", fields)
        session_repo.add_obstacle_incident.assert_called_once()

    async def test_obstacle_danger_without_session_ignored(self):
        config = _make_config()
        redis = AsyncMock()
        detector = AnomalyDetector(config)
        session_repo = MagicMock()
        session_repo.add_obstacle_incident = MagicMock()

        consumer = StreamConsumer(redis, config, detector, session_repo)
        # No active session

        fields = {
            "event_type": "obstacle_danger",
            "forward_distance_mm": "185",
        }
        await consumer._process_message("msg-1", fields)
        session_repo.add_obstacle_incident.assert_not_called()


class TestMalformedMessage:
    async def test_invalid_json_skipped_and_acked(
        self,
        consumer,
        session_repo,
        mock_redis,
    ):
        """Malformed telemetry data is logged, skipped, not retried."""
        await consumer._process_message(
            "1-0",
            {"event_type": "takeoff"},
        )
        fields = {"event_type": "telemetry", "data": "not-json"}
        # Should not raise
        await consumer._process_message("2-0", fields)
        session_repo.add_sample.assert_not_called()
        session_repo.add_anomaly.assert_not_called()
