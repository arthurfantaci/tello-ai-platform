"""Async command queue for serializing all hardware calls.

Only one command executes at a time. Tools enqueue; a single consumer
dispatches to the drone sequentially. Prevents "takeoff while landing" conflicts.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

import structlog

logger = structlog.get_logger("tello_mcp.queue")


class CommandQueue:
    """Serializes drone commands through an asyncio.Queue.

    Enforces inter-command delays to prevent "Not joystick" errors.
    Normal commands get ``post_delay_s`` (default 0.5s); heavy commands
    like takeoff get ``heavy_delay_s`` (default 3.0s).
    """

    def __init__(
        self,
        maxsize: int = 100,
        post_delay_s: float = 0.5,
        heavy_delay_s: float = 3.0,
    ) -> None:
        self._queue: asyncio.Queue[tuple[Callable, asyncio.Future, bool]] = asyncio.Queue(
            maxsize=maxsize
        )
        self._running = False
        self.post_delay_s = post_delay_s
        self.heavy_delay_s = heavy_delay_s

    async def enqueue(self, command: Callable[[], Any], *, heavy: bool = False) -> dict:
        """Add a command to the queue and wait for its result.

        Args:
            command: A callable (sync) that returns a result dict.
            heavy: If True, use longer post-command delay (e.g. takeoff).

        Returns:
            The command's return value, or an error dict if it raised.
        """
        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        await self._queue.put((command, future, heavy))
        return await future

    async def start(self) -> None:
        """Start the command consumer loop."""
        self._running = True
        logger.info("Command queue consumer started")
        while self._running:
            try:
                command, future, heavy = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0,
                )
            except TimeoutError:
                continue

            try:
                result = command()
                future.set_result(result)
            except Exception as e:
                logger.exception("Command execution failed")
                future.set_result({"error": "COMMAND_FAILED", "detail": str(e)})
            finally:
                self._queue.task_done()

            delay = self.heavy_delay_s if heavy else self.post_delay_s
            await asyncio.sleep(delay)

    async def stop(self) -> None:
        """Stop the command consumer loop."""
        self._running = False
        logger.info("Command queue consumer stopped")
