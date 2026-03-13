"""MissionPlanner — LangGraph StateGraph for deterministic mission planning.

The planner is a deterministic graph (no LLM calls in v1). It uses
LangGraph for structured state management, checkpointing, and future
extensibility (LLM-powered planning in v2).

Graph flow:
    START → fetch_rooms → validate_rooms → generate_waypoints
          → validate_plan → finalize → END
    (validate_rooms/validate_plan can short-circuit to END on error)
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from tello_navigator.config import TelloNavigatorConfig
    from tello_navigator.repository import MissionRepository

logger = structlog.get_logger("tello_navigator.planner")


class PlannerState(TypedDict):
    """State flowing through the planning graph."""

    mission_id: str
    goal: str
    room_ids: list[str]
    rooms: list[dict]
    mission_pads: list[dict]
    waypoints: list[dict]
    current_waypoint_idx: int
    status: str  # planning | planned | error
    error: str | None


class MissionPlanner:
    """Deterministic mission planner using LangGraph StateGraph.

    Args:
        repo: MissionRepository for room graph queries.
        config: Navigator configuration.
        checkpointer: Optional LangGraph checkpointer for state persistence.
    """

    def __init__(
        self,
        repo: MissionRepository,
        config: TelloNavigatorConfig,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        self._repo = repo
        self._config = config
        self._graph = self._build_graph(checkpointer)

    def _build_graph(self, checkpointer: BaseCheckpointSaver | None = None) -> StateGraph:
        """Build and compile the planning StateGraph."""
        builder = StateGraph(PlannerState)

        builder.add_node("fetch_rooms", self.fetch_rooms)
        builder.add_node("validate_rooms", self.validate_rooms)
        builder.add_node("generate_waypoints", self.generate_waypoints)
        builder.add_node("validate_plan", self.validate_plan)
        builder.add_node("finalize", self.finalize)

        builder.add_edge(START, "fetch_rooms")
        builder.add_edge("fetch_rooms", "validate_rooms")
        builder.add_conditional_edges(
            "validate_rooms",
            self._route_after_validation,
            {"continue": "generate_waypoints", "error": END},
        )
        builder.add_edge("generate_waypoints", "validate_plan")
        builder.add_conditional_edges(
            "validate_plan",
            self._route_after_validation,
            {"continue": "finalize", "error": END},
        )
        builder.add_edge("finalize", END)

        return builder.compile(checkpointer=checkpointer)

    # -- Graph Nodes -------------------------------------------------

    def fetch_rooms(self, state: PlannerState) -> dict:
        """Query Neo4j for room data and mission pads."""
        rooms = self._repo.get_rooms(state["room_ids"])
        pads = self._repo.get_room_pads(state["room_ids"])
        return {"rooms": rooms, "mission_pads": pads}

    def validate_rooms(self, state: PlannerState) -> dict:
        """Check all requested rooms exist in the graph."""
        found_ids = {r["id"] for r in state["rooms"]}
        missing = [rid for rid in state["room_ids"] if rid not in found_ids]
        if missing:
            return {
                "error": f"Unknown rooms: {', '.join(missing)}",
                "status": "error",
            }
        return {}

    def generate_waypoints(self, state: PlannerState) -> dict:
        """Generate ordered waypoint sequence for the mission."""
        waypoints: list[dict] = []
        seq = 0
        first_room = state["room_ids"][0]

        # Takeoff in the first room
        waypoints.append(
            {
                "id": f"wp_{uuid.uuid4().hex[:8]}",
                "sequence": seq,
                "room_id": first_room,
                "action": "takeoff",
            }
        )
        seq += 1

        # Visit each room's pads
        for room_id in state["room_ids"]:
            room_pads = [p for p in state["mission_pads"] if p["room_id"] == room_id]
            room_data = next((r for r in state["rooms"] if r["id"] == room_id), None)

            if room_pads:
                for pad in room_pads:
                    waypoints.append(
                        {
                            "id": f"wp_{uuid.uuid4().hex[:8]}",
                            "sequence": seq,
                            "room_id": room_id,
                            "action": "goto_pad",
                            "pad_id": pad["id"],
                        }
                    )
                    seq += 1
            else:
                # No pads — do a simple forward move through the room
                distance = self._config.default_move_distance_cm
                if room_data and room_data.get("depth_cm"):
                    distance = min(room_data["depth_cm"] // 2, 500)
                    distance = max(distance, 20)
                waypoints.append(
                    {
                        "id": f"wp_{uuid.uuid4().hex[:8]}",
                        "sequence": seq,
                        "room_id": room_id,
                        "action": "move",
                        "direction": "forward",
                        "distance_cm": distance,
                    }
                )
                seq += 1

        # Land in the last room
        last_room = state["room_ids"][-1]
        waypoints.append(
            {
                "id": f"wp_{uuid.uuid4().hex[:8]}",
                "sequence": seq,
                "room_id": last_room,
                "action": "land",
            }
        )

        return {"waypoints": waypoints}

    def validate_plan(self, state: PlannerState) -> dict:
        """Safety checks on the generated plan."""
        waypoints = state["waypoints"]
        max_wp = self._config.max_waypoints_per_mission

        if len(waypoints) > max_wp:
            return {
                "error": f"Plan has {len(waypoints)} waypoints, max is {max_wp}",
                "status": "error",
            }
        return {}

    def finalize(self, state: PlannerState) -> dict:  # noqa: ARG002
        """Mark plan as ready."""
        return {"status": "planned"}

    # -- Routing Functions -------------------------------------------

    @staticmethod
    def _route_after_validation(state: PlannerState) -> str:
        """Route to error end or continue based on state."""
        if state.get("error"):
            return "error"
        return "continue"

    # -- Public API --------------------------------------------------

    async def plan(
        self,
        mission_id: str,
        goal: str,
        room_ids: list[str],
    ) -> PlannerState:
        """Run the planning graph and return final state."""
        initial_state: PlannerState = {
            "mission_id": mission_id,
            "goal": goal,
            "room_ids": room_ids,
            "rooms": [],
            "mission_pads": [],
            "waypoints": [],
            "current_waypoint_idx": 0,
            "status": "planning",
            "error": None,
        }
        config = {"configurable": {"thread_id": mission_id}}
        result = await self._graph.ainvoke(initial_state, config)
        return result
