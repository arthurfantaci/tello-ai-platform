"""Obstacle detection and safety enforcement.

ObstacleConfig: configurable thresholds for tiered zone detection.
ObstacleMonitor: continuous forward ToF polling with safety stops.
ObstacleResponseHandler: options menu when obstacle forces a stop.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

import structlog

from tello_core.models import ObstacleReading, ObstacleZone

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from tello_mcp.drone import DroneAdapter

logger = structlog.get_logger("tello_mcp.obstacle")


@dataclass(frozen=True, slots=True)
class ObstacleConfig:
    """Configuration for obstacle detection thresholds.

    Overridable via environment variables:
        OBSTACLE_CAUTION_MM, OBSTACLE_WARNING_MM, OBSTACLE_DANGER_MM,
        OBSTACLE_OUT_OF_RANGE, OBSTACLE_POLL_INTERVAL_MS
    """

    caution_mm: int = 1500
    warning_mm: int = 800
    danger_mm: int = 400
    out_of_range: int = 8192
    poll_interval_ms: int = 200

    @classmethod
    def from_env(cls) -> ObstacleConfig:
        """Load config from environment, falling back to defaults."""
        env_map = {
            "caution_mm": "OBSTACLE_CAUTION_MM",
            "warning_mm": "OBSTACLE_WARNING_MM",
            "danger_mm": "OBSTACLE_DANGER_MM",
            "out_of_range": "OBSTACLE_OUT_OF_RANGE",
            "poll_interval_ms": "OBSTACLE_POLL_INTERVAL_MS",
        }
        kwargs: dict[str, int] = {}
        for field, env_var in env_map.items():
            val = os.environ.get(env_var)
            if val is not None:
                kwargs[field] = int(val)
        return cls(**kwargs)


class ObstacleMonitor:
    """Continuous forward ToF monitoring with tiered zone enforcement.

    Polls the forward-facing ToF sensor at a configurable interval,
    classifies distance into zones (CLEAR/CAUTION/WARNING/DANGER),
    and enforces a forced stop in the DANGER zone.
    """

    def __init__(self, drone: DroneAdapter, config: ObstacleConfig | None = None) -> None:
        self._drone = drone
        self._config = config or ObstacleConfig()
        self._latest: ObstacleReading | None = None
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._callbacks: list[Callable[[ObstacleReading], None | Awaitable[None]]] = []

    def classify_zone(self, distance_mm: int) -> ObstacleZone:
        """Classify a distance reading into an obstacle zone.

        Pure function — no I/O, no side effects.
        """
        if distance_mm >= self._config.out_of_range:
            return ObstacleZone.CLEAR
        if distance_mm < self._config.danger_mm:
            return ObstacleZone.DANGER
        if distance_mm < self._config.warning_mm:
            return ObstacleZone.WARNING
        if distance_mm < self._config.caution_mm:
            return ObstacleZone.CAUTION
        return ObstacleZone.CLEAR

    @property
    def latest(self) -> ObstacleReading | None:
        """Most recent obstacle reading, or None if not yet polled."""
        return self._latest

    @property
    def config(self) -> ObstacleConfig:
        """Current obstacle configuration."""
        return self._config

    @property
    def is_running(self) -> bool:
        """Whether the monitor is actively polling."""
        return self._running

    def on_reading(self, callback: Callable[[ObstacleReading], None | Awaitable[None]]) -> None:
        """Subscribe to obstacle readings."""
        self._callbacks.append(callback)

    async def start(self) -> None:
        """Start the background polling loop. Idempotent."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("obstacle_monitor.started", poll_interval_ms=self._config.poll_interval_ms)

    async def stop(self) -> None:
        """Stop the background polling loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("obstacle_monitor.stopped")

    async def _poll_loop(self) -> None:
        """Background task: poll forward ToF and enforce safety zones."""
        while self._running:
            result = await asyncio.to_thread(self._drone.get_forward_distance)
            if result.get("status") == "ok":
                distance_mm = result["distance_mm"]
                zone = self.classify_zone(distance_mm)
                reading = ObstacleReading(
                    distance_mm=distance_mm,
                    zone=zone,
                    timestamp=datetime.now(UTC),
                )
                self._latest = reading

                if zone == ObstacleZone.DANGER:
                    logger.warning("obstacle.danger", distance_mm=distance_mm)
                    await asyncio.to_thread(self._drone.stop)

                for cb in self._callbacks:
                    cb_result = cb(reading)
                    if asyncio.iscoroutine(cb_result):
                        await cb_result

            await asyncio.sleep(self._config.poll_interval_ms / 1000)


class ObstacleResponse(StrEnum):
    """Available responses when an obstacle forces a stop."""

    EMERGENCY_LAND = "emergency_land"
    RETURN_TO_HOME = "return_to_home"
    AVOID_AND_CONTINUE = "avoid_and_continue"
    MANUAL_OVERRIDE = "manual_override"


class ObstacleResponseHandler:
    """Executes obstacle response actions.

    Phase 4a: emergency_land + manual_override working.
    Phase 4b: return_to_home + avoid_and_continue (navigator integration).
    """

    def __init__(self, drone: DroneAdapter) -> None:
        self._drone = drone

    async def execute(self, choice: ObstacleResponse) -> dict:
        """Execute the chosen obstacle response."""
        match choice:
            case ObstacleResponse.EMERGENCY_LAND:
                return await asyncio.to_thread(self._drone.safe_land)
            case ObstacleResponse.RETURN_TO_HOME:
                return {
                    "error": "NOT_IMPLEMENTED",
                    "detail": "Phase 4b -- requires navigator integration",
                }
            case ObstacleResponse.AVOID_AND_CONTINUE:
                return {
                    "error": "NOT_IMPLEMENTED",
                    "detail": "Phase 4b -- requires navigator integration",
                }
            case ObstacleResponse.MANUAL_OVERRIDE:
                logger.info("obstacle.manual_override")
                return {"status": "ok", "detail": "Manual control resumed"}


@runtime_checkable
class ResponseProvider(Protocol):
    """How obstacle options are presented to the caller.

    Phase 4a: CLIResponseProvider (fly.py).
    Phase 6: VoiceResponseProvider (verbal options).
    """

    async def present_options(self, reading: ObstacleReading) -> ObstacleResponse:
        """Present obstacle response options and return the user's choice."""
        ...


class CLIResponseProvider:
    """Present obstacle response options in a terminal/CLI."""

    _OPTIONS: ClassVar[list[tuple[ObstacleResponse, str]]] = [
        (ObstacleResponse.EMERGENCY_LAND, "Emergency Landing -- land immediately"),
        (
            ObstacleResponse.RETURN_TO_HOME,
            "Return to Home -- navigate back to launch pad (Phase 4b)",
        ),
        (
            ObstacleResponse.AVOID_AND_CONTINUE,
            "Avoid & Continue -- dodge obstacle, resume mission (Phase 4b)",
        ),
        (ObstacleResponse.MANUAL_OVERRIDE, "Manual Override -- resume manual control"),
    ]

    async def present_options(self, reading: ObstacleReading) -> ObstacleResponse:
        """Print options and read user choice from stdin."""
        print(f"\nOBSTACLE DETECTED: {reading.distance_mm}mm ({reading.zone.value})")
        print("Drone has been stopped. Choose a response:\n")
        for i, (_, label) in enumerate(self._OPTIONS, 1):
            print(f"  {i}. {label}")
        print()

        while True:
            try:
                raw = input("Select (1-4): ").strip()
                idx = int(raw) - 1
                if 0 <= idx < len(self._OPTIONS):
                    return self._OPTIONS[idx][0]
            except (ValueError, EOFError):
                pass
            print("Invalid selection. Enter 1-4.")
