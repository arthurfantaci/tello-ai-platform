"""Async command queue for serializing all hardware calls.

Only one command executes at a time. Tools enqueue; a single consumer
dispatches to the drone sequentially. Prevents "takeoff while landing" conflicts.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

import structlog

logger = structlog.get_logger("tello_mcp.queue")


class CommandQueue:
    """Serializes drone commands through an asyncio.Queue."""

    def __init__(self, maxsize: int = 100) -> None:
        self._queue: asyncio.Queue[tuple[Callable, asyncio.Future]] = asyncio.Queue(
            maxsize=maxsize,
        )
        self._running = False

    async def enqueue(self, command: Callable[[], Any]) -> dict:
        """Add a command to the queue and wait for its result.

        Args:
            command: A callable (sync) that returns a result dict.

        Returns:
            The command's return value, or an error dict if it raised.
        """
        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        await self._queue.put((command, future))
        return await future

    async def start(self) -> None:
        """Start the command consumer loop."""
        self._running = True
        logger.info("Command queue consumer started")
        while self._running:
            try:
                command, future = await asyncio.wait_for(
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

    async def stop(self) -> None:
        """Stop the command consumer loop."""
        self._running = False
        logger.info("Command queue consumer stopped")
