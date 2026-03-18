"""Obstacle response strategies — Strategy Pattern via Protocol.

ObstacleContext captures flight state at the moment of detection.
ReturnToHomeStrategy defines the contract for RTH implementations.
SimpleReverseRTH is the Phase 4b strategy: stop, reverse, land.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import structlog

if TYPE_CHECKING:
    from tello_mcp.drone import DroneAdapter

logger = structlog.get_logger("tello_mcp.strategies")

_OPPOSITES: dict[str, str] = {
    "forward": "back",
    "back": "forward",
    "left": "right",
    "right": "left",
    "up": "down",
    "down": "up",
}


def _opposite_direction(direction: str) -> str:
    """Return the opposite movement direction."""
    return _OPPOSITES[direction]


@dataclass(frozen=True)
class ObstacleContext:
    """Flight state captured at the moment of obstacle detection."""

    last_direction: str
    last_distance_cm: int
    height_cm: int
    forward_distance_mm: int
    mission_id: str | None = None
    room_id: str | None = None


class ReturnToHomeStrategy(Protocol):
    """Contract for return-to-home implementations.

    Phase 4b: SimpleReverseRTH (stop, reverse, land).
    Phase 5+: VisionGuidedRTH, VoiceConfirmedRTH.
    """

    def return_to_home(self, drone: DroneAdapter, context: ObstacleContext) -> dict:
        """Execute return-to-home sequence."""
        ...


class SimpleReverseRTH:
    """Phase 4b: stop, reverse last movement, land.

    Focuses on drone commands only. Event publishing is handled
    by ObstacleResponseHandler after this strategy returns.
    """

    def return_to_home(self, drone: DroneAdapter, context: ObstacleContext) -> dict:
        """Stop, reverse last movement, and land."""
        reversed_direction: str | None = None

        if context.last_direction and context.last_distance_cm > 0:
            reversed_direction = _opposite_direction(context.last_direction)
            move_result = drone.move(reversed_direction, context.last_distance_cm)
            if "error" in move_result:
                logger.warning(
                    "RTH reverse failed: %s — proceeding to land",
                    move_result,
                )

        drone.land()

        return {
            "status": "returned",
            "method": "simple_reverse",
            "reversed_direction": reversed_direction,
            "height_cm": context.height_cm,
            "forward_distance_mm": context.forward_distance_mm,
            "landed": True,
        }
