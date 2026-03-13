"""Neo4j mission repository — CRUD for missions, waypoints, and room graph.

All methods use the sync Neo4j driver. MCP tools call these
via asyncio.to_thread() to avoid blocking the event loop.

Graph schema:
    (:Mission)-[:CONTAINS_WAYPOINT {sequence}]->(:Waypoint)
    (:Mission)-[:TARGETS_ROOM]->(:RoomNode)
    (:RoomNode)-[:HAS_PAD]->(:MissionPad)
    (:RoomNode)-[:CONNECTS_TO {via_pad, direction}]->(:RoomNode)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from datetime import datetime

    from neo4j import Driver

    from tello_core.models import MissionStatus, Waypoint

logger = structlog.get_logger("tello_navigator.repository")


class MissionRepository:
    """Neo4j read/write operations for missions and room graph.

    Args:
        driver: Neo4j sync driver instance.
    """

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    # -- Mission Writes ------------------------------------------

    def create_mission(
        self,
        mission_id: str,
        goal: str,
        room_ids: list[str],
        status: MissionStatus,
        created_at: datetime,
    ) -> None:
        """Create a Mission node and link to target rooms."""
        with self._driver.session() as s:
            s.run(
                """
                CREATE (m:Mission {
                    id: $mission_id,
                    goal: $goal,
                    status: $status,
                    room_ids: $room_ids,
                    created_at: datetime($created_at)
                })
                """,
                mission_id=mission_id,
                goal=goal,
                status=str(status),
                room_ids=room_ids,
                created_at=created_at.isoformat(),
            )
        logger.info("Created mission %s", mission_id, goal=goal)

    def save_waypoints(self, mission_id: str, waypoints: list[Waypoint]) -> None:
        """Create Waypoint nodes linked to a mission."""
        with self._driver.session() as s:
            for wp in waypoints:
                s.run(
                    """
                    MATCH (m:Mission {id: $mission_id})
                    CREATE (w:Waypoint {
                        id: $wp_id,
                        sequence: $sequence,
                        room_id: $room_id,
                        pad_id: $pad_id,
                        action: $action,
                        direction: $direction,
                        distance_cm: $distance_cm,
                        degrees: $degrees
                    })<-[:CONTAINS_WAYPOINT {sequence: $sequence}]-(m)
                    """,
                    mission_id=mission_id,
                    wp_id=wp.id,
                    sequence=wp.sequence,
                    room_id=wp.room_id,
                    pad_id=wp.pad_id,
                    action=wp.action,
                    direction=wp.direction,
                    distance_cm=wp.distance_cm,
                    degrees=wp.degrees,
                )

    def update_mission_status(
        self,
        mission_id: str,
        status: MissionStatus,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        """Update a mission's status and optional timestamps."""
        with self._driver.session() as s:
            s.run(
                """
                MATCH (m:Mission {id: $mission_id})
                SET m.status = $status,
                    m.started_at = CASE WHEN $started_at IS NOT NULL
                        THEN datetime($started_at) ELSE m.started_at END,
                    m.completed_at = CASE WHEN $completed_at IS NOT NULL
                        THEN datetime($completed_at) ELSE m.completed_at END,
                    m.error = CASE WHEN $error IS NOT NULL
                        THEN $error ELSE m.error END
                """,
                mission_id=mission_id,
                status=str(status),
                started_at=started_at.isoformat() if started_at else None,
                completed_at=completed_at.isoformat() if completed_at else None,
                error=error,
            )
        logger.info("Updated mission %s → %s", mission_id, status)

    # -- Mission Reads -------------------------------------------

    def get_mission(self, mission_id: str) -> dict | None:
        """Get a single mission by ID."""
        with self._driver.session() as s:
            record = s.run(
                """
                MATCH (m:Mission {id: $mission_id})
                RETURN m {.*} AS mission
                """,
                mission_id=mission_id,
            ).single()
            if record is None:
                return None
            return record.data()["mission"]

    def list_missions(
        self,
        limit: int = 10,
        status: str | None = None,
    ) -> list[dict]:
        """List missions, optionally filtered by status."""
        if status:
            query = """
                MATCH (m:Mission)
                WHERE m.status = $status
                RETURN m {.*} AS mission
                ORDER BY m.created_at DESC
                LIMIT $limit
            """
        else:
            query = """
                MATCH (m:Mission)
                RETURN m {.*} AS mission
                ORDER BY m.created_at DESC
                LIMIT $limit
            """
        with self._driver.session() as s:
            records = s.run(query, limit=limit, status=status)
            return [r.data()["mission"] for r in records]

    def get_mission_waypoints(self, mission_id: str) -> list[dict]:
        """Get waypoints for a mission, ordered by sequence."""
        with self._driver.session() as s:
            records = s.run(
                """
                MATCH (m:Mission {id: $mission_id})-[:CONTAINS_WAYPOINT]->(w:Waypoint)
                RETURN w {.*} AS waypoint
                ORDER BY w.sequence
                """,
                mission_id=mission_id,
            )
            return [r.data()["waypoint"] for r in records]

    # -- Room Graph Reads ----------------------------------------

    def get_rooms(self, room_ids: list[str]) -> list[dict]:
        """Get room data for the given room IDs."""
        with self._driver.session() as s:
            records = s.run(
                """
                MATCH (r:RoomNode)
                WHERE r.id IN $room_ids
                RETURN r {.*} AS room
                """,
                room_ids=room_ids,
            )
            return [r.data()["room"] for r in records]

    def get_room_pads(self, room_ids: list[str]) -> list[dict]:
        """Get mission pads in the given rooms."""
        with self._driver.session() as s:
            records = s.run(
                """
                MATCH (r:RoomNode)-[:HAS_PAD]->(p:MissionPad)
                WHERE r.id IN $room_ids
                RETURN p {.*} AS pad
                """,
                room_ids=room_ids,
            )
            return [r.data()["pad"] for r in records]

    # -- Room Graph Seeding --------------------------------------

    def seed_room_graph(
        self,
        rooms: list[dict],
        pads: list[dict],
        connections: list[dict],
    ) -> None:
        """Seed rooms, pads, and connections into Neo4j."""
        with self._driver.session() as s:
            for room in rooms:
                s.run(
                    """
                    MERGE (r:RoomNode {id: $id})
                    SET r.name = $name,
                        r.width_cm = $width_cm,
                        r.depth_cm = $depth_cm,
                        r.height_cm = $height_cm
                    """,
                    **room,
                )
            for pad in pads:
                s.run(
                    """
                    MATCH (r:RoomNode {id: $room_id})
                    MERGE (p:MissionPad {id: $id})
                    SET p.room_id = $room_id,
                        p.x_cm = $x_cm,
                        p.y_cm = $y_cm
                    MERGE (r)-[:HAS_PAD]->(p)
                    """,
                    **pad,
                )
            for conn in connections:
                s.run(
                    """
                    MATCH (a:RoomNode {id: $from_room})
                    MATCH (b:RoomNode {id: $to_room})
                    MERGE (a)-[:CONNECTS_TO {via_pad: $via_pad, direction: $direction}]->(b)
                    """,
                    **conn,
                )
        logger.info(
            "Seeded room graph",
            rooms=len(rooms),
            pads=len(pads),
            connections=len(connections),
        )
