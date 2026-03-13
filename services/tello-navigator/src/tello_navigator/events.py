"""Mission event publisher — Redis Stream for mission lifecycle events.

Publishes structured events to the tello:missions stream for
observability and cross-service coordination.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = structlog.get_logger("tello_navigator.events")


class MissionEventPublisher:
    """Publishes mission lifecycle events to a Redis Stream."""

    def __init__(self, redis_client: aioredis.Redis, stream: str = "tello:missions") -> None:
        self._redis = redis_client
        self._stream = stream

    async def publish_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish a mission event to the Redis Stream."""
        fields = {"event_type": event_type, **{k: str(v) for k, v in data.items()}}
        await self._redis.xadd(self._stream, fields)
        logger.info("Published mission event %s", event_type)

    async def mission_created(self, mission_id: str, goal: str, room_ids: list[str]) -> None:
        """Publish mission_created event."""
        await self.publish_event(
            "mission_created",
            {
                "mission_id": mission_id,
                "goal": goal,
                "room_ids": ",".join(room_ids),
            },
        )

    async def mission_started(self, mission_id: str) -> None:
        """Publish mission_started event."""
        await self.publish_event("mission_started", {"mission_id": mission_id})

    async def waypoint_reached(self, mission_id: str, waypoint_id: str, sequence: int) -> None:
        """Publish waypoint_reached event."""
        await self.publish_event(
            "waypoint_reached",
            {
                "mission_id": mission_id,
                "waypoint_id": waypoint_id,
                "sequence": sequence,
            },
        )

    async def mission_completed(self, mission_id: str, duration_s: float) -> None:
        """Publish mission_completed event."""
        await self.publish_event(
            "mission_completed",
            {
                "mission_id": mission_id,
                "duration_s": duration_s,
            },
        )

    async def mission_aborted(self, mission_id: str, reason: str) -> None:
        """Publish mission_aborted event."""
        await self.publish_event(
            "mission_aborted",
            {
                "mission_id": mission_id,
                "reason": reason,
            },
        )
