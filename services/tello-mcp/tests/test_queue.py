"""Tests for the async command queue."""

import asyncio

import pytest

from tello_mcp.queue import CommandQueue


class TestCommandQueue:
    @pytest.fixture()
    def queue(self):
        return CommandQueue()

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
