"""FlightCoordinator — unified command execution with chunked moves.

Replaces CommandQueue. Single entry point for all drone commands.
Decomposes long moves into 20cm chunks with safety checkpoint inspection
between each chunk. Enforces single-owner coordination model.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

    from tello_mcp.drone import DroneAdapter
    from tello_mcp.obstacle import ObstacleMonitor
    from tello_mcp.telemetry import TelemetryPublisher

logger = structlog.get_logger("tello_mcp.coordinator")

CHUNK_SIZE_CM = 20
"""Minimum SDK movement distance — each chunk is this size."""


class FlightCoordinator:
    """Unified coordination layer for drone command execution.

    Single Owner + Safety Veto pattern:
    - One actor owns the drone at a time (default: "mcp" for MCP tool callers)
    - Safety veto (ObstacleMonitor) can block commands regardless of ownership
    - Movement commands are decomposed into chunks with checkpoint inspection
    """

    def __init__(
        self,
        drone: DroneAdapter,
        monitor: ObstacleMonitor,
        telemetry: TelemetryPublisher | None = None,
        last_command: dict | None = None,
        inter_chunk_delay_s: float = 0.1,
        post_delay_s: float = 0.5,
        heavy_delay_s: float = 3.0,
    ) -> None:
        self._drone = drone
        self._monitor = monitor
        self._telemetry = telemetry
        self._last_command = last_command if last_command is not None else {}
        self._inter_chunk_delay_s = inter_chunk_delay_s
        self._post_delay_s = post_delay_s
        self._heavy_delay_s = heavy_delay_s
        self._owner = "mcp"
        self._owner_lock = asyncio.Lock()
        self._executing = False

    @property
    def owner(self) -> str:
        """Current control owner."""
        return self._owner

    @property
    def monitor(self) -> ObstacleMonitor:
        """Obstacle monitor reference (for server.py wiring)."""
        return self._monitor

    def get_control_info(self) -> dict:
        """Current ownership state for diagnostics."""
        return {"owner": self._owner, "executing": self._executing}

    # ── Ownership ────────────────────────────────────────────────

    async def acquire_control(self, actor: str) -> dict:
        """Acquire exclusive control of the drone.

        Idempotent for the current owner. Returns error if another actor holds it.
        """
        async with self._owner_lock:
            if self._owner == actor:
                return {"status": "ok", "owner": actor}
            if self._owner != "mcp" and self._owner != actor:
                return {
                    "error": "OWNERSHIP_CONFLICT",
                    "detail": f"Currently owned by '{self._owner}'",
                    "owner": self._owner,
                }
            previous = self._owner
            self._owner = actor
            logger.info("control.acquired", actor=actor, previous_owner=previous)

        if self._telemetry:
            await self._telemetry.publish_event(
                "control_acquired",
                {"actor": actor, "previous_owner": previous},
            )
        return {"status": "ok", "owner": actor}

    async def release_control(self, actor: str) -> dict:
        """Release control back to the default owner (mcp).

        Only the current owner can release. Rejected during execution.
        """
        async with self._owner_lock:
            if self._executing:
                return {
                    "error": "EXECUTING",
                    "detail": "Cannot release control while a command is executing",
                }
            if self._owner != actor:
                return {
                    "error": "NOT_OWNER",
                    "detail": f"Cannot release — owned by '{self._owner}'",
                }
            previous = self._owner
            self._owner = "mcp"
            logger.info("control.released", actor=actor, returned_to="mcp")

        if self._telemetry:
            await self._telemetry.publish_event(
                "control_released",
                {"actor": actor, "returned_to": "mcp"},
            )
        return {"status": "ok", "owner": "mcp", "previous_owner": previous}

    # ── Chunk decomposition ──────────────────────────────────────

    def _decompose_chunks(self, distance_cm: int) -> list[int]:
        """Break a distance into CHUNK_SIZE_CM chunks.

        Remainder goes in the first chunk so the last chunk is always
        exactly CHUNK_SIZE_CM (the minimum safe checkpoint distance).

        If distance < 2 * CHUNK_SIZE_CM, returns a single chunk (indivisible).
        """
        if distance_cm < 2 * CHUNK_SIZE_CM:
            return [distance_cm]
        full_chunks = distance_cm // CHUNK_SIZE_CM
        remainder = distance_cm % CHUNK_SIZE_CM
        if remainder == 0:
            return [CHUNK_SIZE_CM] * full_chunks
        # Remainder-first: first chunk = CHUNK_SIZE_CM + remainder
        return [CHUNK_SIZE_CM + remainder] + [CHUNK_SIZE_CM] * (full_chunks - 1)

    # ── Checkpoint inspection ────────────────────────────────────

    async def _poll_forward_distance(self) -> bool:
        """Actively poll the forward ToF sensor and check if movement is safe.

        Unlike monitor.is_safe_for_movement() which reads cached _latest
        (stale during chunked moves because the RLock blocks background
        polling), this method performs a fresh sensor read between chunks.

        Returns True if safe to continue (CLEAR or CAUTION zone).
        Returns True if the sensor read fails (no obstacle evidence).
        """
        result = await asyncio.to_thread(self._drone.get_forward_distance)
        if result.get("status") != "ok":
            logger.warning("checkpoint.sensor_read_failed", result=result)
            return True  # No obstacle evidence — continue

        distance_mm = result["distance_mm"]
        zone = self._monitor.classify_zone(distance_mm)
        logger.debug(
            "checkpoint.polled",
            distance_mm=distance_mm,
            zone=zone.value,
        )
        return zone.value in ("clear", "caution")

    # ── Command execution ────────────────────────────────────────

    async def execute_move(
        self,
        direction: str,
        distance_cm: int,
        *,
        actor: str = "mcp",
    ) -> dict:
        """Execute a movement command with chunking and checkpoint inspection.

        Returns a result dict with distance_completed_cm and chunk info.
        """
        if self._owner != actor:
            return {
                "error": "NOT_OWNER",
                "detail": f"Control owned by '{self._owner}', not '{actor}'",
            }

        chunks = self._decompose_chunks(distance_cm)
        total_chunks = len(chunks)
        completed_chunks = 0
        distance_completed = 0

        self._executing = True
        try:
            for i, chunk_cm in enumerate(chunks):
                # Checkpoint: actively poll ToF sensor (not cached — cache
                # goes stale during chunked moves due to RLock contention)
                if not await self._poll_forward_distance():
                    logger.warning(
                        "move.aborted_obstacle",
                        direction=direction,
                        chunk=i,
                        distance_completed_cm=distance_completed,
                    )
                    self._last_command["direction"] = direction
                    self._last_command["distance_cm"] = distance_completed
                    return {
                        "status": "ok",
                        "distance_requested_cm": distance_cm,
                        "distance_completed_cm": distance_completed,
                        "chunks_completed": completed_chunks,
                        "chunks_total": total_chunks,
                        "stopped_reason": "obstacle_warning",
                    }

                # Execute chunk via thread (blocking SDK call)
                result = await asyncio.to_thread(self._drone.move, direction, chunk_cm)
                if result.get("error"):
                    logger.error(
                        "move.chunk_failed",
                        direction=direction,
                        chunk=i,
                        chunk_cm=chunk_cm,
                        error=result["error"],
                    )
                    result["distance_completed_cm"] = distance_completed
                    return result

                completed_chunks += 1
                distance_completed += chunk_cm

                # Inter-chunk delay (not after last chunk)
                if i < len(chunks) - 1 and self._inter_chunk_delay_s > 0:
                    await asyncio.sleep(self._inter_chunk_delay_s)
        finally:
            self._executing = False

        # Post-move delay
        if self._post_delay_s > 0:
            await asyncio.sleep(self._post_delay_s)

        self._last_command["direction"] = direction
        self._last_command["distance_cm"] = distance_completed

        return {
            "status": "ok",
            "distance_requested_cm": distance_cm,
            "distance_completed_cm": distance_completed,
            "chunks_completed": completed_chunks,
            "chunks_total": total_chunks,
            "stopped_reason": None,
        }

    async def execute(
        self,
        command: Callable[[], Any],
        *,
        heavy: bool = False,
        actor: str = "mcp",
    ) -> dict:
        """Execute a non-chunked command (takeoff, land, rotate, go_to_pad).

        Enforces ownership. Uses post_delay_s or heavy_delay_s after execution.
        """
        if self._owner != actor:
            return {
                "error": "NOT_OWNER",
                "detail": f"Control owned by '{self._owner}', not '{actor}'",
            }

        self._executing = True
        try:
            result = await asyncio.to_thread(command)
        except Exception as e:
            logger.exception("command.failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}
        finally:
            self._executing = False

        delay = self._heavy_delay_s if heavy else self._post_delay_s
        if delay > 0:
            await asyncio.sleep(delay)

        return result
