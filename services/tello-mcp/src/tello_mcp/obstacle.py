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
from tello_mcp.strategies import ObstacleContext, ReturnToHomeStrategy

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from tello_mcp.drone import DroneAdapter
    from tello_mcp.telemetry import TelemetryPublisher

logger = structlog.get_logger("tello_mcp.obstacle")


@dataclass(frozen=True, slots=True)
class ObstacleConfig:
    """Configuration for obstacle detection thresholds.

    Thresholds calibrated for the VL53L0X forward ToF sensor (~500mm reliable range).

    Overridable via environment variables:
        OBSTACLE_CAUTION_MM, OBSTACLE_WARNING_MM, OBSTACLE_DANGER_MM,
        OBSTACLE_OUT_OF_RANGE_MIN, OBSTACLE_REQUIRED_CLEAR_READINGS,
        OBSTACLE_POLL_INTERVAL_MS
    """

    caution_mm: int = 500
    warning_mm: int = 300
    danger_mm: int = 200
    out_of_range_min: int = 8000
    required_clear_readings: int = 3
    poll_interval_ms: int = 200

    @classmethod
    def from_env(cls) -> ObstacleConfig:
        """Load config from environment, falling back to defaults."""
        env_map = {
            "caution_mm": "OBSTACLE_CAUTION_MM",
            "warning_mm": "OBSTACLE_WARNING_MM",
            "danger_mm": "OBSTACLE_DANGER_MM",
            "out_of_range_min": "OBSTACLE_OUT_OF_RANGE_MIN",
            "required_clear_readings": "OBSTACLE_REQUIRED_CLEAR_READINGS",
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
        self._in_danger = False
        self._danger_clear_count = 0

    def classify_zone(self, distance_mm: int) -> ObstacleZone:
        """Classify a distance reading into an obstacle zone.

        Pure function — no I/O, no side effects.
        """
        if distance_mm >= self._config.out_of_range_min:
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

    def is_safe_for_movement(self) -> bool:
        """Check whether it is safe to execute the next movement chunk.

        Uses the *raw* sensor reading (undebounced) so that movement can
        resume immediately after a DANGER event clears, without waiting
        for the debounce counter (required_clear_readings).

        Safe zones: CLEAR, CAUTION.
        Unsafe zones: WARNING, DANGER.

        Returns True when no reading exists yet (no obstacle evidence).
        """
        if self._latest is None:
            return True
        raw_zone = self.classify_zone(self._latest.distance_mm)
        return raw_zone in (ObstacleZone.CLEAR, ObstacleZone.CAUTION)

    @property
    def config(self) -> ObstacleConfig:
        """Current obstacle configuration."""
        return self._config

    @property
    def is_running(self) -> bool:
        """Whether the monitor is actively polling."""
        return self._running

    def status(self) -> dict:
        """Current monitor state for diagnostics."""
        return {
            "running": self._running,
            "in_danger": self._in_danger,
            "danger_clear_count": self._danger_clear_count,
            "latest_reading_mm": self._latest.distance_mm if self._latest else None,
            "latest_zone": self._latest.zone.value if self._latest else None,
        }

    def on_reading(self, callback: Callable[[ObstacleReading], None | Awaitable[None]]) -> None:
        """Subscribe to obstacle readings."""
        self._callbacks.append(callback)

    async def start(self) -> None:
        """Start the background polling loop. Idempotent."""
        if self._running:
            return
        self._in_danger = False
        self._danger_clear_count = 0
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
                raw_zone = self.classify_zone(distance_mm)

                # Debounce DANGER exit
                if self._in_danger:
                    if raw_zone != ObstacleZone.DANGER:
                        self._danger_clear_count += 1
                        if self._danger_clear_count >= self._config.required_clear_readings:
                            self._in_danger = False
                            reported_zone = raw_zone
                        else:
                            reported_zone = ObstacleZone.DANGER
                    else:
                        self._danger_clear_count = 0
                        reported_zone = ObstacleZone.DANGER
                elif raw_zone == ObstacleZone.DANGER:
                    self._in_danger = True
                    self._danger_clear_count = 0
                    logger.warning("obstacle.danger", distance_mm=distance_mm)
                    await asyncio.to_thread(self._drone.stop)
                    reported_zone = ObstacleZone.DANGER
                else:
                    reported_zone = raw_zone

                reading = ObstacleReading(
                    distance_mm=distance_mm,
                    zone=reported_zone,
                    timestamp=datetime.now(UTC),
                )
                self._latest = reading

                for cb in self._callbacks:
                    try:
                        cb_result = cb(reading)
                        if asyncio.iscoroutine(cb_result):
                            await cb_result
                    except Exception:
                        logger.exception(
                            "obstacle.callback_failed",
                            distance_mm=reading.distance_mm,
                            zone=reading.zone.value,
                        )

            await asyncio.sleep(self._config.poll_interval_ms / 1000)


class ObstacleResponse(StrEnum):
    """Available responses when an obstacle forces a stop."""

    EMERGENCY_LAND = "emergency_land"
    RETURN_TO_HOME = "return_to_home"
    AVOID_AND_CONTINUE = "avoid_and_continue"
    MANUAL_OVERRIDE = "manual_override"


class ObstacleResponseHandler:
    """Executes obstacle response actions.

    Receives a ReturnToHomeStrategy via DI. Handles event publishing
    after the strategy executes (strategies stay pure — drone commands only).
    """

    def __init__(
        self,
        drone: DroneAdapter,
        rth_strategy: ReturnToHomeStrategy | None = None,
        telemetry: TelemetryPublisher | None = None,
        last_command: dict | None = None,
    ) -> None:
        self._drone = drone
        self._rth = rth_strategy
        self._telemetry = telemetry
        self._last_command = last_command
        self._rth_active = False

    def status(self) -> dict:
        """Current handler state for diagnostics."""
        return {"rth_active": self._rth_active}

    async def execute(
        self,
        choice: ObstacleResponse,
        context: ObstacleContext | None = None,
    ) -> dict:
        """Execute the chosen obstacle response."""
        match choice:
            case ObstacleResponse.EMERGENCY_LAND:
                return await asyncio.to_thread(self._drone.safe_land)
            case ObstacleResponse.RETURN_TO_HOME:
                if self._rth is None or context is None:
                    return {
                        "error": "NOT_CONFIGURED",
                        "detail": "RTH strategy or context not provided",
                    }
                result = await asyncio.to_thread(self._rth.return_to_home, self._drone, context)
                if self._telemetry is not None:
                    await self._telemetry.publish_event(
                        "obstacle_danger",
                        {
                            "forward_distance_mm": str(context.forward_distance_mm),
                            "forward_distance_in": str(
                                round(context.forward_distance_mm / 25.4, 1)
                            ),
                            "height_cm": str(context.height_cm),
                            "zone": "DANGER",
                            "response": "RETURN_TO_HOME",
                            "outcome": result.get("status", "unknown"),
                            "mission_id": context.mission_id or "",
                            "room_id": context.room_id or "",
                            "reversed_direction": result.get("reversed_direction", ""),
                        },
                    )
                    await self._telemetry.publish_event("land", {})
                return result
            case ObstacleResponse.AVOID_AND_CONTINUE:
                return {
                    "error": "NOT_IMPLEMENTED",
                    "detail": "Deferred to Phase 5+",
                }
            case ObstacleResponse.MANUAL_OVERRIDE:
                logger.info("obstacle.manual_override")
                return {"status": "ok", "detail": "Manual control resumed"}

    async def on_obstacle_reading(self, reading: ObstacleReading) -> None:
        """Callback for ObstacleMonitor — auto-triggers RTH on DANGER.

        Guards:
        - Ignores non-DANGER readings
        - Skips if RTH is already in progress (_rth_active flag)
        - Skips if drone is confirmed on the ground (height_cm == 0)
        - Does NOT skip if get_height fails (drone may be airborne)
        """
        if reading.zone != ObstacleZone.DANGER:
            return

        if self._rth_active:
            logger.debug("obstacle.rth_skipped_active", distance_mm=reading.distance_mm)
            return

        last_cmd = self._last_command or {}
        height_result = await asyncio.to_thread(self._drone.get_height)
        height_cm = height_result.get("height_cm", 0) if height_result.get("status") == "ok" else 0

        if height_result.get("status") == "ok" and height_cm == 0:
            logger.debug(
                "obstacle.rth_skipped_grounded",
                height_cm=height_cm,
                distance_mm=reading.distance_mm,
            )
            return

        self._rth_active = True
        try:
            logger.info(
                "obstacle.rth_started",
                distance_mm=reading.distance_mm,
                height_cm=height_cm,
                last_direction=last_cmd.get("direction", ""),
            )
            context = ObstacleContext(
                last_direction=last_cmd.get("direction", ""),
                last_distance_cm=int(last_cmd.get("distance_cm", 0)),
                height_cm=height_cm,
                forward_distance_mm=reading.distance_mm,
                mission_id=last_cmd.get("mission_id"),
                room_id=last_cmd.get("room_id"),
            )
            result = await self.execute(ObstacleResponse.RETURN_TO_HOME, context)
            logger.info(
                "obstacle.rth_completed",
                outcome=result.get("status", "unknown"),
                reversed_direction=result.get("reversed_direction"),
            )
        finally:
            self._rth_active = False


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
