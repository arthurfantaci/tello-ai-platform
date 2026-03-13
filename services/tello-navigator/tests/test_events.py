"""Tests for MissionEventPublisher."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tello_navigator.events import MissionEventPublisher


@pytest.fixture
def publisher():
    redis = AsyncMock()
    return MissionEventPublisher(redis, stream="tello:missions"), redis


class TestMissionEventPublisher:
    async def test_publish_event_calls_xadd(self, publisher):
        pub, redis = publisher
        await pub.publish_event("mission_created", {"mission_id": "m_001", "goal": "Patrol"})
        redis.xadd.assert_called_once()
        call_args = redis.xadd.call_args
        assert call_args[0][0] == "tello:missions"
        fields = call_args[0][1]
        assert fields["event_type"] == "mission_created"
        assert fields["mission_id"] == "m_001"

    async def test_publish_event_stringifies_values(self, publisher):
        pub, redis = publisher
        await pub.publish_event("waypoint_reached", {"sequence": 3, "mission_id": "m_001"})
        fields = redis.xadd.call_args[0][1]
        assert fields["sequence"] == "3"

    async def test_mission_created_event(self, publisher):
        pub, redis = publisher
        await pub.mission_created("m_001", "Patrol rooms", ["living", "kitchen"])
        redis.xadd.assert_called_once()
        fields = redis.xadd.call_args[0][1]
        assert fields["event_type"] == "mission_created"

    async def test_mission_started_event(self, publisher):
        pub, redis = publisher
        await pub.mission_started("m_001")
        fields = redis.xadd.call_args[0][1]
        assert fields["event_type"] == "mission_started"

    async def test_waypoint_reached_event(self, publisher):
        pub, redis = publisher
        await pub.waypoint_reached("m_001", "wp_2", 2)
        fields = redis.xadd.call_args[0][1]
        assert fields["event_type"] == "waypoint_reached"
        assert fields["waypoint_id"] == "wp_2"

    async def test_mission_completed_event(self, publisher):
        pub, redis = publisher
        await pub.mission_completed("m_001", 120.5)
        fields = redis.xadd.call_args[0][1]
        assert fields["event_type"] == "mission_completed"
        assert fields["duration_s"] == "120.5"

    async def test_mission_aborted_event(self, publisher):
        pub, redis = publisher
        await pub.mission_aborted("m_001", "Low battery")
        fields = redis.xadd.call_args[0][1]
        assert fields["event_type"] == "mission_aborted"
        assert fields["reason"] == "Low battery"
