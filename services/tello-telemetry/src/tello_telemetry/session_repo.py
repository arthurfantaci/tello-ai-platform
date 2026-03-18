"""Neo4j session repository -- read/write flight session data.

All methods use the sync Neo4j driver. The consumer calls these
via asyncio.to_thread() to avoid blocking the event loop.

Graph schema:
    (:FlightSession)-[:BELONGS_TO]->(:TelemetrySample)
    (:FlightSession)-[:OCCURRED_DURING]->(:Anomaly)

Note: relationship direction is Sample/Anomaly -> Session
(BELONGS_TO / OCCURRED_DURING) to model "a sample belongs to a
session" and "an anomaly occurred during a session".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from datetime import datetime

    from neo4j import Driver

    from tello_core.models import Anomaly, FlightSession, ObstacleIncident, TelemetrySample

logger = structlog.get_logger("tello_telemetry.session_repo")


class SessionRepository:
    """Neo4j read/write operations for flight sessions.

    Args:
        driver: Neo4j sync driver instance.
    """

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    # -- Writes --------------------------------------------------

    def create_session(self, session: FlightSession) -> None:
        """Create a FlightSession node in Neo4j.

        Args:
            session: Flight session to persist.
        """
        with self._driver.session() as s:
            s.run(
                """
                CREATE (fs:FlightSession {
                    id: $session_id,
                    start_time: datetime($start_time),
                    room_id: $room_id,
                    mission_id: $mission_id,
                    anomaly_count: 0
                })
                """,
                session_id=session.id,
                start_time=session.start_time.isoformat(),
                room_id=session.room_id,
                mission_id=session.mission_id,
            )
        logger.info(
            "Created flight session %s",
            session.id,
            room_id=session.room_id,
        )

    def end_session(self, session_id: str, end_time: datetime) -> None:
        """Set end_time and compute duration on a FlightSession.

        Args:
            session_id: Session to end.
            end_time: When the session ended.
        """
        with self._driver.session() as s:
            s.run(
                """
                MATCH (fs:FlightSession {id: $session_id})
                SET fs.end_time = datetime($end_time),
                    fs.duration_s = duration.between(
                        fs.start_time, datetime($end_time)
                    ).seconds
                """,
                session_id=session_id,
                end_time=end_time.isoformat(),
            )
        logger.info("Ended flight session %s", session_id)

    def add_sample(self, session_id: str, sample: TelemetrySample) -> None:
        """Create a TelemetrySample node linked to a session.

        Args:
            session_id: Parent session.
            sample: Telemetry sample to persist.
        """
        with self._driver.session() as s:
            s.run(
                """
                MATCH (fs:FlightSession {id: $session_id})
                CREATE (ts:TelemetrySample {
                    battery_pct: $battery_pct,
                    height_cm: $height_cm,
                    tof_cm: $tof_cm,
                    temp_c: $temp_c,
                    timestamp: datetime($timestamp)
                })-[:BELONGS_TO]->(fs)
                SET fs.min_battery_pct = CASE
                    WHEN fs.min_battery_pct IS NULL
                        THEN $battery_pct
                    WHEN $battery_pct < fs.min_battery_pct
                        THEN $battery_pct
                    ELSE fs.min_battery_pct
                END,
                fs.max_temp_c = CASE
                    WHEN fs.max_temp_c IS NULL
                        THEN $temp_c
                    WHEN $temp_c > fs.max_temp_c
                        THEN $temp_c
                    ELSE fs.max_temp_c
                END
                """,
                session_id=session_id,
                battery_pct=sample.battery_pct,
                height_cm=sample.height_cm,
                tof_cm=sample.tof_cm,
                temp_c=sample.temp_c,
                timestamp=sample.timestamp.isoformat(),
            )

    def add_anomaly(self, session_id: str, anomaly: Anomaly) -> None:
        """Create an Anomaly node linked to a session.

        Args:
            session_id: Parent session.
            anomaly: Detected anomaly to persist.
        """
        with self._driver.session() as s:
            s.run(
                """
                MATCH (fs:FlightSession {id: $session_id})
                CREATE (a:Anomaly {
                    type: $type,
                    severity: $severity,
                    detail: $detail,
                    timestamp: datetime($timestamp)
                })-[:OCCURRED_DURING]->(fs)
                SET fs.anomaly_count = fs.anomaly_count + 1
                """,
                session_id=session_id,
                type=anomaly.type,
                severity=anomaly.severity,
                detail=anomaly.detail,
                timestamp=anomaly.timestamp.isoformat(),
            )

    def add_obstacle_incident(self, session_id: str, incident: ObstacleIncident) -> None:
        """Create an ObstacleIncident node linked to a session.

        Args:
            session_id: Parent flight session.
            incident: Obstacle incident to persist.
        """
        with self._driver.session() as s:
            s.run(
                """
                MATCH (fs:FlightSession {id: $session_id})
                CREATE (oi:ObstacleIncident {
                    id: $id,
                    timestamp: datetime($timestamp),
                    forward_distance_mm: $forward_distance_mm,
                    forward_distance_in: $forward_distance_in,
                    height_cm: $height_cm,
                    zone: $zone,
                    response: $response,
                    outcome: $outcome,
                    mission_id: $mission_id,
                    room_id: $room_id,
                    reversed_direction: $reversed_direction
                })-[:TRIGGERED_DURING]->(fs)
                """,
                session_id=session_id,
                id=incident.id,
                timestamp=incident.timestamp.isoformat(),
                forward_distance_mm=incident.forward_distance_mm,
                forward_distance_in=incident.forward_distance_in,
                height_cm=incident.height_cm,
                zone=incident.zone,
                response=incident.response,
                outcome=incident.outcome,
                mission_id=incident.mission_id,
                room_id=incident.room_id,
                reversed_direction=incident.reversed_direction,
            )
        logger.info(
            "Obstacle incident persisted",
            session_id=session_id,
            incident_id=incident.id,
        )

    # -- Reads ---------------------------------------------------

    def get_session(self, session_id: str) -> dict | None:
        """Get a single flight session by ID.

        Args:
            session_id: Session to retrieve.

        Returns:
            Session data dict, or None if not found.
        """
        with self._driver.session() as s:
            record = s.run(
                """
                MATCH (fs:FlightSession {id: $session_id})
                RETURN fs {.*} AS session
                """,
                session_id=session_id,
            ).single()
            if record is None:
                return None
            return record.data()["session"]

    def list_sessions(self, limit: int = 10) -> list[dict]:
        """List recent flight sessions, newest first.

        Args:
            limit: Maximum number of sessions to return.
        """
        with self._driver.session() as s:
            records = s.run(
                """
                MATCH (fs:FlightSession)
                RETURN fs {.*} AS session
                ORDER BY fs.start_time DESC
                LIMIT $limit
                """,
                limit=limit,
            )
            return [r.data()["session"] for r in records]

    def get_session_samples(self, session_id: str) -> list[dict]:
        """Get telemetry samples for a session, ordered by time.

        Args:
            session_id: Session whose samples to retrieve.
        """
        with self._driver.session() as s:
            records = s.run(
                """
                MATCH (ts:TelemetrySample)-[:BELONGS_TO]->
                      (fs:FlightSession {id: $session_id})
                RETURN ts {.*} AS sample
                ORDER BY ts.timestamp
                """,
                session_id=session_id,
            )
            return [r.data()["sample"] for r in records]

    def get_session_anomalies(self, session_id: str) -> list[dict]:
        """Get anomalies for a session, ordered by time.

        Args:
            session_id: Session whose anomalies to retrieve.
        """
        with self._driver.session() as s:
            records = s.run(
                """
                MATCH (a:Anomaly)-[:OCCURRED_DURING]->
                      (fs:FlightSession {id: $session_id})
                RETURN a {.*} AS anomaly
                ORDER BY a.timestamp
                """,
                session_id=session_id,
            )
            return [r.data()["anomaly"] for r in records]

    def get_anomaly_summary(self) -> list[dict]:
        """Get anomaly counts by type across all sessions."""
        with self._driver.session() as s:
            records = s.run(
                """
                MATCH (a:Anomaly)
                RETURN a.type AS type,
                       a.severity AS severity,
                       count(a) AS count
                ORDER BY count DESC
                """,
            )
            return [r.data() for r in records]
