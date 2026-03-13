"""LangGraph mission planner -- builds waypoint sequences from room graphs.

The planning pipeline is a 5-node StateGraph:

    fetch_rooms → validate_rooms → generate_waypoints → validate_plan → finalize
                        ↓ (error)                           ↓ (error)
                       END                                 END

Each node receives the full ``PlannerState`` and returns a *partial* dict
that LangGraph merges back into the state.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, TypedDict

import structlog
from langgraph.graph import END, StateGraph

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from tello_navigator.config import TelloNavigatorConfig
    from tello_navigator.repository import MissionRepository

logger = structlog.get_logger("tello_navigator.planner")


class PlannerState(TypedDict):
    """State flowing through the mission planning graph."""

    mission_id: str
    goal: str
    room_ids: list[str]
    rooms: list[dict]
    mission_pads: list[dict]
    waypoints: list[dict]
    current_waypoint_idx: int
    status: str  # "planning" | "planned" | "error"
    error: str | None


class MissionPlanner:
    """LangGraph-based mission planner.

    Builds a waypoint sequence by fetching room data from Neo4j,
    validating rooms, generating waypoints, and validating the plan.

    Args:
        repo: Neo4j mission repository.
        config: Navigator service configuration.
        checkpointer: Optional LangGraph checkpointer (Redis-backed).
    """

    def __init__(
        self,
        repo: MissionRepository,
        config: TelloNavigatorConfig,
        checkpointer: object | None = None,
    ) -> None:
        self._repo = repo
        self._config = config
        self._graph = self._build_graph(checkpointer)

    def _build_graph(self, checkpointer: object | None) -> CompiledStateGraph:
        """Build and compile the 5-node planning StateGraph."""
        graph: StateGraph = StateGraph(PlannerState)

        graph.add_node("fetch_rooms", self._fetch_rooms)
        graph.add_node("validate_rooms", self._validate_rooms)
        graph.add_node("generate_waypoints", self._generate_waypoints)
        graph.add_node("validate_plan", self._validate_plan)
        graph.add_node("finalize", self._finalize)

        graph.set_entry_point("fetch_rooms")
        graph.add_edge("fetch_rooms", "validate_rooms")
        graph.add_conditional_edges(
            "validate_rooms",
            self._check_error,
            {True: END, False: "generate_waypoints"},
        )
        graph.add_edge("generate_waypoints", "validate_plan")
        graph.add_conditional_edges(
            "validate_plan",
            self._check_error,
            {True: END, False: "finalize"},
        )
        graph.add_edge("finalize", END)

        return graph.compile(checkpointer=checkpointer)

    # -- Routing --------------------------------------------------

    @staticmethod
    def _check_error(state: PlannerState) -> bool:
        """Return True when the state contains an error (routes to END)."""
        return state.get("error") is not None

    # -- Nodes ----------------------------------------------------

    def _fetch_rooms(self, state: PlannerState) -> dict:
        """Fetch room and pad data from the repository."""
        rooms = self._repo.get_rooms(state["room_ids"])
        pads = self._repo.get_room_pads(state["room_ids"])
        return {"rooms": rooms, "mission_pads": pads}

    def _validate_rooms(self, state: PlannerState) -> dict:
        """Ensure all requested rooms were found in the graph."""
        found_ids = {r["id"] for r in state["rooms"]}
        missing = [rid for rid in state["room_ids"] if rid not in found_ids]
        if missing:
            return {"status": "error", "error": f"Unknown rooms: {missing}"}
        return {}

    def _generate_waypoints(self, state: PlannerState) -> dict:
        """Generate waypoint sequence from room/pad data.

        Visit rooms in ``room_ids`` order. Within each room: if pads exist,
        ``goto_pad`` for each. If no pads, ``move`` forward by half the room
        depth (clamped 20..500 cm). First room gets ``takeoff``, last room
        gets ``land``.
        """
        waypoints: list[dict] = []
        room_ids = state["room_ids"]

        pads_by_room: dict[str, list[dict]] = {}
        for pad in state["mission_pads"]:
            rid = pad["room_id"]
            pads_by_room.setdefault(rid, []).append(pad)

        seq = 0
        for i, room_id in enumerate(room_ids):
            # Takeoff in first room
            if i == 0:
                waypoints.append(
                    {
                        "id": f"{state['mission_id']}_wp_{seq}",
                        "sequence": seq,
                        "room_id": room_id,
                        "action": "takeoff",
                    }
                )
                seq += 1

            room_pads = pads_by_room.get(room_id, [])
            if room_pads:
                for pad in room_pads:
                    waypoints.append(
                        {
                            "id": f"{state['mission_id']}_wp_{seq}",
                            "sequence": seq,
                            "room_id": room_id,
                            "pad_id": pad["id"],
                            "action": "goto_pad",
                        }
                    )
                    seq += 1
            else:
                # Fallback: forward move
                room_data = next((r for r in state["rooms"] if r["id"] == room_id), None)
                depth = room_data["depth_cm"] if room_data else 200
                distance = min(max(depth // 2, 20), 500)
                waypoints.append(
                    {
                        "id": f"{state['mission_id']}_wp_{seq}",
                        "sequence": seq,
                        "room_id": room_id,
                        "action": "move",
                        "direction": "forward",
                        "distance_cm": distance,
                    }
                )
                seq += 1

            # Land in last room
            if i == len(room_ids) - 1:
                waypoints.append(
                    {
                        "id": f"{state['mission_id']}_wp_{seq}",
                        "sequence": seq,
                        "room_id": room_id,
                        "action": "land",
                    }
                )
                seq += 1

        return {"waypoints": waypoints, "current_waypoint_idx": 0}

    def _validate_plan(self, state: PlannerState) -> dict:
        """Reject plans that exceed the maximum waypoint count."""
        if len(state["waypoints"]) > self._config.max_waypoints_per_mission:
            return {
                "status": "error",
                "error": (
                    f"Plan exceeds max waypoints "
                    f"({len(state['waypoints'])} > "
                    f"{self._config.max_waypoints_per_mission})"
                ),
            }
        return {}

    def _finalize(self, state: PlannerState) -> dict:  # noqa: ARG002
        """Mark the plan as complete."""
        return {"status": "planned"}

    # -- Public API -----------------------------------------------

    async def plan(self, mission_id: str, goal: str, room_ids: list[str]) -> PlannerState:
        """Run the planning graph and return final state.

        Args:
            mission_id: Unique mission identifier.
            goal: Human-readable mission goal.
            room_ids: Ordered list of rooms to visit.

        Returns:
            Final planner state with waypoints (or error).
        """
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
        try:
            result = await asyncio.wait_for(
                self._graph.ainvoke(initial_state),
                timeout=self._config.planning_timeout_s,
            )
        except TimeoutError:
            return {**initial_state, "status": "error", "error": "Planning timed out"}
        return result
