"""Tests for the async command queue."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tello_mcp.queue import CommandQueue


class TestCommandQueue:
    @pytest.fixture()
    def queue(self):
        # Zero delays for fast tests
        return CommandQueue(post_delay_s=0.0, heavy_delay_s=0.0)

    async def test_enqueue_and_execute(self, queue):
        called = False

        def command():
            nonlocal called
            called = True
            return {"status": "ok"}

        consumer_task = asyncio.create_task(queue.start())
        try:
            result = await queue.enqueue(command)
            assert result == {"status": "ok"}
            assert called
        finally:
            await queue.stop()
            consumer_task.cancel()

    async def test_commands_execute_sequentially(self, queue):
        execution_order = []

        def make_command(n):
            def cmd():
                execution_order.append(n)
                return {"status": "ok", "n": n}

            return cmd

        consumer_task = asyncio.create_task(queue.start())
        try:
            results = await asyncio.gather(
                queue.enqueue(make_command(1)),
                queue.enqueue(make_command(2)),
                queue.enqueue(make_command(3)),
            )
            assert len(results) == 3
            assert execution_order == [1, 2, 3]
        finally:
            await queue.stop()
            consumer_task.cancel()

    async def test_command_exception_returns_error(self, queue):
        def failing_command():
            raise RuntimeError("hardware fault")

        consumer_task = asyncio.create_task(queue.start())
        try:
            result = await queue.enqueue(failing_command)
            assert result["error"] == "COMMAND_FAILED"
            assert "hardware fault" in result["detail"]
        finally:
            await queue.stop()
            consumer_task.cancel()

    async def test_post_delay_applied(self):
        queue = CommandQueue(post_delay_s=0.5, heavy_delay_s=3.0)
        mock_sleep = AsyncMock()
        consumer_task = asyncio.create_task(queue.start())
        try:
            with patch("tello_mcp.queue.asyncio.sleep", mock_sleep):
                await queue.enqueue(lambda: {"status": "ok"})
            mock_sleep.assert_called_once_with(0.5)
        finally:
            await queue.stop()
            consumer_task.cancel()

    async def test_heavy_delay_applied(self):
        queue = CommandQueue(post_delay_s=0.5, heavy_delay_s=3.0)
        mock_sleep = AsyncMock()
        consumer_task = asyncio.create_task(queue.start())
        try:
            with patch("tello_mcp.queue.asyncio.sleep", mock_sleep):
                await queue.enqueue(lambda: {"status": "ok"}, heavy=True)
            mock_sleep.assert_called_once_with(3.0)
        finally:
            await queue.stop()
            consumer_task.cancel()

    async def test_default_delays(self):
        queue = CommandQueue()
        assert queue.post_delay_s == 0.5
        assert queue.heavy_delay_s == 3.0
