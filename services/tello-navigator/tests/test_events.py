"""Tests for MissionEventPublisher."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tello_navigator.events import MissionEventPublisher


class TestMissionEventPublisher:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.redis = AsyncMock()
        self.redis.xadd = AsyncMock(return_value="1234-0")
        self.publisher = MissionEventPublisher(self.redis, stream="tello:missions")

    async def test_publish_event(self):
        await self.publisher.publish_event("test_event", {"key": "value"})
        self.redis.xadd.assert_called_once()
        call_args = self.redis.xadd.call_args
        assert call_args[0][0] == "tello:missions"
        fields = call_args[0][1]
        assert fields["event_type"] == "test_event"
        assert fields["key"] == "value"

    async def test_mission_created(self):
        await self.publisher.mission_created("m1", "patrol", ["room_a", "room_b"])
        self.redis.xadd.assert_called_once()
        fields = self.redis.xadd.call_args[0][1]
        assert fields["event_type"] == "mission_created"
        assert fields["mission_id"] == "m1"
        assert fields["goal"] == "patrol"
        assert fields["room_ids"] == "['room_a', 'room_b']"  # stringified

    async def test_mission_started(self):
        await self.publisher.mission_started("m1")
        fields = self.redis.xadd.call_args[0][1]
        assert fields["event_type"] == "mission_started"
        assert fields["mission_id"] == "m1"

    async def test_waypoint_reached(self):
        await self.publisher.waypoint_reached("m1", "wp1", 2)
        fields = self.redis.xadd.call_args[0][1]
        assert fields["event_type"] == "waypoint_reached"
        assert fields["waypoint_id"] == "wp1"
        assert fields["sequence"] == "2"  # stringified int

    async def test_mission_completed(self):
        await self.publisher.mission_completed("m1", 120.5)
        fields = self.redis.xadd.call_args[0][1]
        assert fields["event_type"] == "mission_completed"
        assert fields["duration_s"] == "120.5"  # stringified float

    async def test_mission_aborted(self):
        await self.publisher.mission_aborted("m1", "low battery")
        fields = self.redis.xadd.call_args[0][1]
        assert fields["event_type"] == "mission_aborted"
        assert fields["reason"] == "low battery"

    async def test_all_values_stringified(self):
        await self.publisher.publish_event("test", {"count": 42, "flag": True})
        fields = self.redis.xadd.call_args[0][1]
        for v in fields.values():
            assert isinstance(v, str), f"Value {v!r} is not a string"
