"""Telemetry publisher — Redis pub/sub and Streams.

Publishes TelemetryFrame to pub/sub at ~10Hz for real-time consumers.
Appends flight events to a Redis Stream for durable, ordered replay.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    import redis.asyncio as aioredis

    from tello_core.models import TelemetryFrame

logger = structlog.get_logger("tello_mcp.telemetry")


class TelemetryPublisher:
    """Publishes drone telemetry to Redis."""

    def __init__(
        self,
        redis_client: aioredis.Redis,
        channel: str = "tello:telemetry",
        stream: str = "tello:events",
    ) -> None:
        self._redis = redis_client
        self._channel = channel
        self._stream = stream

    async def publish_frame(self, frame: TelemetryFrame) -> None:
        """Publish a telemetry frame to pub/sub and append to stream.

        Args:
            frame: Current telemetry snapshot.
        """
        data = frame.model_dump_json()
        await self._redis.publish(self._channel, data)
        await self._redis.xadd(
            self._stream,
            {"event_type": "telemetry", "data": data},
        )

    async def publish_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish a flight event to the Redis Stream.

        Args:
            event_type: Event type (e.g., "takeoff", "land", "move").
            data: Event payload.
        """
        fields = {"event_type": event_type, **{k: str(v) for k, v in data.items()}}
        try:
            await self._redis.xadd(self._stream, fields)
            logger.info("event.published", event_type=event_type)
        except Exception:
            logger.exception("event.publish_failed", event_type=event_type)
