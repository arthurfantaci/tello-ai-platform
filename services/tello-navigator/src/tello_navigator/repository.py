"""Neo4j mission repository -- read/write mission and room graph data.

All methods use the sync Neo4j driver. Tools call these via
asyncio.to_thread() to avoid blocking the event loop.

Graph schema:
    (:Mission)-[:CONTAINS_WAYPOINT {sequence}]->(:Waypoint)
    (:RoomNode)-[:HAS_PAD]->(:MissionPad)
    (:RoomNode)-[:CONNECTS_TO {via_pad, direction, passage_type}]->(:RoomNode)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from neo4j import Driver

    from tello_core.models import Waypoint

logger = structlog.get_logger("tello_navigator.repository")


class MissionRepository:
    """Neo4j read/write operations for missions and room graphs.

    Args:
        driver: Neo4j sync driver instance.
    """

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    # -- Writes --------------------------------------------------

    def create_mission(
        self,
        mission_id: str,
        goal: str,
        room_ids: list[str],
        status: str,
        created_at: str,
    ) -> None:
        """Create a Mission node.

        Args:
            mission_id: Unique mission identifier.
            goal: Human-readable goal description.
            room_ids: Rooms involved in the mission.
            status: Initial mission status.
            created_at: ISO-8601 creation timestamp.
        """
        with self._driver.session() as s:
            s.run(
                """
                CREATE (m:Mission {
                    id: $mission_id,
                    goal: $goal,
                    room_ids: $room_ids,
                    status: $status,
                    created_at: datetime($created_at)
                })
                """,
                mission_id=mission_id,
                goal=goal,
                room_ids=room_ids,
                status=status,
                created_at=created_at,
            )
        logger.info(
            "Created mission %s",
            mission_id,
            goal=goal,
            rooms=room_ids,
        )

    def save_waypoints(self, mission_id: str, waypoints: list[Waypoint]) -> None:
        """Create Waypoint nodes linked to a Mission.

        Args:
            mission_id: Parent mission ID.
            waypoints: Ordered list of waypoints to persist.
        """
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
                        degrees: $degrees,
                        speed_cm_s: $speed_cm_s
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
                    speed_cm_s=wp.speed_cm_s,
                )
        logger.info(
            "Saved %d waypoints for mission %s",
            len(waypoints),
            mission_id,
        )

    def update_mission_status(
        self,
        mission_id: str,
        status: str,
        *,
        started_at: str | None = None,
        completed_at: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update mission status and optional timestamps.

        Args:
            mission_id: Mission to update.
            status: New status value.
            started_at: ISO-8601 start timestamp (optional).
            completed_at: ISO-8601 completion timestamp (optional).
            error: Error message if aborted (optional).
        """
        with self._driver.session() as s:
            params: dict[str, str | int] = {
                "mission_id": mission_id,
                "status": status,
            }
            set_clauses = ["m.status = $status"]
            if started_at:
                set_clauses.append("m.started_at = datetime($started_at)")
                params["started_at"] = started_at
            if completed_at:
                set_clauses.append("m.completed_at = datetime($completed_at)")
                params["completed_at"] = completed_at
            if error:
                set_clauses.append("m.error = $error")
                params["error"] = error
            s.run(
                f"MATCH (m:Mission {{id: $mission_id}}) SET {', '.join(set_clauses)}",
                **params,
            )
        logger.info(
            "Updated mission %s to %s",
            mission_id,
            status,
        )

    # -- Reads ---------------------------------------------------

    def get_mission(self, mission_id: str) -> dict | None:
        """Get a single mission by ID.

        Args:
            mission_id: Mission to retrieve.

        Returns:
            Mission data dict, or None if not found.
        """
        with self._driver.session() as s:
            record = s.run(
                "MATCH (m:Mission {id: $mission_id}) RETURN m {.*} AS mission",
                mission_id=mission_id,
            ).single()
            if record is None:
                return None
            return record.data()["mission"]

    def list_missions(self, limit: int = 10, status: str | None = None) -> list[dict]:
        """List missions, optionally filtered by status.

        Args:
            limit: Maximum number of missions to return.
            status: Filter by this status (optional).
        """
        with self._driver.session() as s:
            if status:
                records = s.run(
                    """
                    MATCH (m:Mission {status: $status})
                    RETURN m {.*} AS mission
                    ORDER BY m.created_at DESC
                    LIMIT $limit
                    """,
                    status=status,
                    limit=limit,
                )
            else:
                records = s.run(
                    """
                    MATCH (m:Mission)
                    RETURN m {.*} AS mission
                    ORDER BY m.created_at DESC
                    LIMIT $limit
                    """,
                    limit=limit,
                )
            return [r.data()["mission"] for r in records]

    def get_mission_waypoints(self, mission_id: str) -> list[dict]:
        """Get waypoints for a mission, ordered by sequence.

        Args:
            mission_id: Mission whose waypoints to retrieve.
        """
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

    def get_rooms(self, room_ids: list[str]) -> list[dict]:
        """Get room nodes by IDs.

        Args:
            room_ids: Room IDs to retrieve.
        """
        with self._driver.session() as s:
            records = s.run(
                "MATCH (r:RoomNode) WHERE r.id IN $room_ids RETURN r {.*} AS room",
                room_ids=room_ids,
            )
            return [r.data()["room"] for r in records]

    def get_room_pads(self, room_ids: list[str]) -> list[dict]:
        """Get mission pads in rooms.

        Args:
            room_ids: Room IDs whose pads to retrieve.
        """
        with self._driver.session() as s:
            records = s.run(
                """
                MATCH (r:RoomNode)-[:HAS_PAD]->(p:MissionPad)
                WHERE r.id IN $room_ids
                RETURN p {.*, room_id: r.id} AS pad
                ORDER BY p.id
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
        """Seed room graph with rooms, pads, and connections using MERGE (idempotent).

        Args:
            rooms: List of room dicts with id, name, dimensions.
            pads: List of pad dicts with id, room_id, coordinates.
            connections: List of connection dicts with from_room, to_room, metadata.
        """
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
                    MERGE (a)-[c:CONNECTS_TO]->(b)
                    SET c.via_pad = $via_pad,
                        c.direction = $direction,
                        c.passage_type = $passage_type
                    """,
                    from_room=conn["from_room"],
                    to_room=conn["to_room"],
                    via_pad=conn.get("via_pad"),
                    direction=conn.get("direction"),
                    passage_type=conn.get("passage_type"),
                )
        logger.info(
            "Seeded room graph: %d rooms, %d pads, %d connections",
            len(rooms),
            len(pads),
            len(connections),
        )
