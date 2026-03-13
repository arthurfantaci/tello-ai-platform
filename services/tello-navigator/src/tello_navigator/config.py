"""Configuration for tello-navigator service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from tello_core.config import BaseServiceConfig


@dataclass(frozen=True, slots=True)
class TelloNavigatorConfig(BaseServiceConfig):
    """tello-navigator specific configuration.

    Mission planning parameters, waypoint limits, and Redis Stream
    settings. All fields have sensible defaults;
    override via constructor kwargs.
    """

    missions_stream: str = "tello:missions"
    max_waypoints_per_mission: int = 20
    default_move_distance_cm: int = 100
    planning_timeout_s: float = 30.0
    checkpoint_ttl_hours: int = 24

    @classmethod
    def from_env(cls, **overrides: str | int | float | bool) -> Self:
        """Load tello-navigator config from environment."""
        return BaseServiceConfig.from_env.__func__(cls, **overrides)  # type: ignore[attr-defined]
