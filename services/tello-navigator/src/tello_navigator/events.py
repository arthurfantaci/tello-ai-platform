"""Mission event publisher — Redis Stream lifecycle events."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = structlog.get_logger("tello_navigator.events")


class MissionEventPublisher:
    """Publishes mission lifecycle events to a Redis Stream."""

    def __init__(self, redis_client: Redis, stream: str = "tello:missions") -> None:
        self._redis = redis_client
        self._stream = stream

    async def publish_event(self, event_type: str, data: dict) -> None:
        """Publish an event to the missions stream."""
        fields = {"event_type": event_type}
        for k, v in data.items():
            fields[k] = str(v)
        await self._redis.xadd(self._stream, fields)
        logger.info("Published %s event", event_type, mission_stream=self._stream)

    async def mission_created(self, mission_id: str, goal: str, room_ids: list[str]) -> None:
        """Publish a mission_created event."""
        await self.publish_event(
            "mission_created",
            {
                "mission_id": mission_id,
                "goal": goal,
                "room_ids": room_ids,
            },
        )

    async def mission_started(self, mission_id: str) -> None:
        """Publish a mission_started event."""
        await self.publish_event("mission_started", {"mission_id": mission_id})

    async def waypoint_reached(self, mission_id: str, waypoint_id: str, sequence: int) -> None:
        """Publish a waypoint_reached event."""
        await self.publish_event(
            "waypoint_reached",
            {
                "mission_id": mission_id,
                "waypoint_id": waypoint_id,
                "sequence": sequence,
            },
        )

    async def mission_completed(self, mission_id: str, duration_s: float) -> None:
        """Publish a mission_completed event."""
        await self.publish_event(
            "mission_completed",
            {
                "mission_id": mission_id,
                "duration_s": duration_s,
            },
        )

    async def mission_aborted(self, mission_id: str, reason: str) -> None:
        """Publish a mission_aborted event."""
        await self.publish_event(
            "mission_aborted",
            {
                "mission_id": mission_id,
                "reason": reason,
            },
        )
