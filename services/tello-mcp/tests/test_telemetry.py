"""Tests for the telemetry publisher."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tello_core.models import TelemetryFrame
from tello_mcp.telemetry import TelemetryPublisher


@pytest.fixture()
def sample_frame():
    return TelemetryFrame(
        battery_pct=85,
        height_cm=120,
        tof_cm=95,
        temp_c=42.0,
        pitch=1.0,
        roll=0.0,
        yaw=180.0,
        flight_time_s=45,
        timestamp=datetime(2026, 3, 12, 10, 0, 0, tzinfo=timezone.utc),
    )


class TestTelemetryPublisher:
    async def test_publish_frame_to_pubsub(self, mock_redis, sample_frame):
        publisher = TelemetryPublisher(
            redis_client=mock_redis,
            channel="tello:telemetry",
            stream="tello:events",
        )
        await publisher.publish_frame(sample_frame)
        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == "tello:telemetry"

    async def test_publish_frame_to_stream(self, mock_redis, sample_frame):
        publisher = TelemetryPublisher(
            redis_client=mock_redis,
            channel="tello:telemetry",
            stream="tello:events",
        )
        await publisher.publish_frame(sample_frame)
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "tello:events"

    async def test_publish_event(self, mock_redis):
        publisher = TelemetryPublisher(
            redis_client=mock_redis,
            channel="tello:telemetry",
            stream="tello:events",
        )
        await publisher.publish_event("takeoff", {"height_cm": 50})
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        fields = call_args[0][1]
        assert fields["event_type"] == "takeoff"
