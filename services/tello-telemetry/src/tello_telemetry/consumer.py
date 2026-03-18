"""Redis Stream consumer -- XREADGROUP loop.

The StreamConsumer is the "Imperative Shell" in the Pure Core /
Imperative Shell architecture. It handles all I/O (Redis reads,
Neo4j writes via asyncio.to_thread) and delegates logic to:
- AnomalyDetector (pure core) for threshold checks
- SessionRepository for Neo4j persistence

Consumer lifecycle:
1. ensure_consumer_group() -- idempotent XGROUP CREATE
2. Process pending messages (PEL recovery, ID=0)
3. Read new messages (ID=>) in a loop
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import structlog
from pydantic import ValidationError as PydanticValidationError

from tello_core.models import FlightSession, TelemetryFrame, TelemetrySample

if TYPE_CHECKING:
    import redis.asyncio as aioredis

    from tello_telemetry.config import TelloTelemetryConfig
    from tello_telemetry.detector import AnomalyDetector
    from tello_telemetry.session_repo import SessionRepository

logger = structlog.get_logger("tello_telemetry.consumer")


class StreamConsumer:
    """Reads from the tello:events Redis Stream and processes telemetry.

    Handles flight telemetry, lifecycle events, and anomalies.

    Args:
        redis: Async Redis client.
        config: Service configuration.
        detector: Anomaly detection engine.
        session_repo: Neo4j persistence layer.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        config: TelloTelemetryConfig,
        detector: AnomalyDetector,
        session_repo: SessionRepository,
    ) -> None:
        self._redis = redis
        self._config = config
        self._detector = detector
        self._repo = session_repo
        self._current_session: FlightSession | None = None
        self._last_sample_time: float = 0.0

    async def ensure_consumer_group(self) -> None:
        """Create consumer group if it doesn't exist.

        Uses XGROUP CREATE with MKSTREAM. Catches BUSYGROUP
        error (group already exists) gracefully.
        """
        try:
            await self._redis.xgroup_create(
                self._config.stream_name,
                self._config.consumer_group,
                id="0",
                mkstream=True,
            )
            logger.info(
                "Created consumer group %s",
                self._config.consumer_group,
            )
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                logger.info(
                    "Consumer group %s already exists",
                    self._config.consumer_group,
                )
            else:
                raise

    async def run(self) -> None:
        """Main consumer loop.

        1. Ensure consumer group exists
        2. Process pending messages (PEL recovery)
        3. Read new messages in a loop
        """
        await self.ensure_consumer_group()

        # Phase 1: Process pending entries (crash recovery)
        await self._read_and_process(message_id="0")

        # Phase 2: Read new messages
        while True:
            await self._read_and_process(message_id=">")

    async def _read_and_process(self, *, message_id: str) -> None:
        """Read a batch of messages and process each one.

        Args:
            message_id: "0" for pending, ">" for new messages.
        """
        messages = await self._redis.xreadgroup(
            groupname=self._config.consumer_group,
            consumername=self._config.consumer_name,
            streams={self._config.stream_name: message_id},
            count=self._config.batch_size,
            block=self._config.block_ms,
        )

        if not messages:
            return

        for _stream_name, entries in messages:
            for msg_id, fields in entries:
                await self._process_message(msg_id, fields)
                await self._redis.xack(
                    self._config.stream_name,
                    self._config.consumer_group,
                    msg_id,
                )

    async def _process_message(
        self,
        _msg_id: str,
        fields: dict,
    ) -> None:
        """Route a single stream message by event_type.

        Args:
            _msg_id: Redis Stream message ID (used upstream for XACK).
            fields: Message fields dict.
        """
        event_type = fields.get("event_type", "unknown")

        if event_type == "takeoff":
            await self._handle_takeoff(fields)
        elif event_type == "land":
            await self._handle_land()
        elif event_type == "telemetry":
            await self._handle_telemetry(fields)
        elif event_type == "obstacle_danger":
            await self._handle_obstacle(fields)
        else:
            logger.warning("Unknown event type: %s", event_type)

    async def _handle_takeoff(self, fields: dict) -> None:
        """Start a new flight session."""
        session = FlightSession(
            id=str(uuid4()),
            start_time=datetime.now(UTC),
            room_id=fields.get("room_id", "unknown"),
        )
        self._current_session = session
        self._last_sample_time = 0.0
        await asyncio.to_thread(self._repo.create_session, session)
        logger.info(
            "Flight session started",
            session_id=session.id,
            room_id=session.room_id,
        )

    async def _handle_land(self) -> None:
        """End the current flight session."""
        if self._current_session is None:
            logger.warning("Land event without active session")
            return
        end_time = datetime.now(UTC)
        await asyncio.to_thread(
            self._repo.end_session,
            self._current_session.id,
            end_time,
        )
        logger.info(
            "Flight session ended",
            session_id=self._current_session.id,
        )
        self._current_session = None

    async def _handle_telemetry(self, fields: dict) -> None:
        """Parse telemetry frame, detect anomalies, sample."""
        if self._current_session is None:
            return

        try:
            frame = TelemetryFrame.model_validate_json(fields["data"])
        except (PydanticValidationError, KeyError):
            logger.exception(
                "Failed to parse telemetry data",
                raw_fields=fields,
            )
            return

        # Anomaly detection (pure core -- no I/O)
        anomalies = self._detector.check(frame)
        for anomaly in anomalies:
            await asyncio.to_thread(
                self._repo.add_anomaly,
                self._current_session.id,
                anomaly,
            )
            logger.warning(
                "Anomaly detected",
                type=anomaly.type,
                severity=anomaly.severity,
            )

        # Sampling -- persist every neo4j_sample_interval_s
        now = time.monotonic()
        if now - self._last_sample_time >= self._config.neo4j_sample_interval_s:
            sample = TelemetrySample(
                battery_pct=frame.battery_pct,
                height_cm=frame.height_cm,
                tof_cm=frame.tof_cm,
                temp_c=frame.temp_c,
                timestamp=frame.timestamp,
            )
            await asyncio.to_thread(
                self._repo.add_sample,
                self._current_session.id,
                sample,
            )
            self._last_sample_time = now

    async def _handle_obstacle(self, fields: dict) -> None:
        """Record an obstacle incident for the current session."""
        if self._current_session is None:
            logger.warning("Obstacle event without active session")
            return

        from tello_core.models import ObstacleIncident

        incident = ObstacleIncident(
            id=str(uuid4()),
            timestamp=datetime.now(UTC),
            forward_distance_mm=int(fields.get("forward_distance_mm", 0)),
            forward_distance_in=float(fields.get("forward_distance_in", 0.0)),
            height_cm=int(fields.get("height_cm", 0)),
            zone=fields.get("zone", "DANGER"),
            response=fields.get("response", "unknown"),
            outcome=fields.get("outcome", "unknown"),
            mission_id=fields.get("mission_id") or None,
            room_id=fields.get("room_id") or None,
            reversed_direction=fields.get("reversed_direction") or None,
        )
        await asyncio.to_thread(
            self._repo.add_obstacle_incident,
            self._current_session.id,
            incident,
        )
        logger.info(
            "Obstacle incident recorded",
            session_id=self._current_session.id,
            distance_mm=incident.forward_distance_mm,
            response=incident.response,
        )
