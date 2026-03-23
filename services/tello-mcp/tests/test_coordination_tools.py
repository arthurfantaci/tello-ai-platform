"""Tests for coordination MCP tools (acquire_control, release_control, get_control_owner)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from tello_mcp.tools.coordination import register


def _make_mcp():
    """Create a mock FastMCP with tool registration capture."""
    mcp = MagicMock()
    tools: dict[str, callable] = {}

    def tool_decorator(**kwargs):
        def wrapper(fn):
            tools[fn.__name__] = fn
            return fn

        return wrapper

    mcp.tool = tool_decorator
    return mcp, tools


def _make_context(coordinator=None):
    """Create a mock FastMCP Context."""
    ctx = MagicMock()
    ctx.lifespan_context = {"coordinator": coordinator or MagicMock()}
    return ctx


class TestAcquireControl:
    def setup_method(self):
        self.mcp, self.tools = _make_mcp()
        register(self.mcp)

    async def test_acquire_success(self):
        coordinator = AsyncMock()
        coordinator.acquire_control = AsyncMock(return_value={"status": "ok", "owner": "navigator"})
        ctx = _make_context(coordinator)
        result = await self.tools["acquire_control"](ctx, actor="navigator")
        assert result["status"] == "ok"
        assert result["owner"] == "navigator"
        coordinator.acquire_control.assert_called_once_with("navigator")

    async def test_acquire_conflict(self):
        coordinator = AsyncMock()
        coordinator.acquire_control = AsyncMock(
            return_value={"error": "OWNERSHIP_CONFLICT", "owner": "vision"}
        )
        ctx = _make_context(coordinator)
        result = await self.tools["acquire_control"](ctx, actor="vision")
        assert result["error"] == "OWNERSHIP_CONFLICT"


class TestReleaseControl:
    def setup_method(self):
        self.mcp, self.tools = _make_mcp()
        register(self.mcp)

    async def test_release_success(self):
        coordinator = AsyncMock()
        coordinator.release_control = AsyncMock(
            return_value={"status": "ok", "owner": "mcp", "previous_owner": "navigator"}
        )
        ctx = _make_context(coordinator)
        result = await self.tools["release_control"](ctx, actor="navigator")
        assert result["status"] == "ok"
        coordinator.release_control.assert_called_once_with("navigator")

    async def test_release_not_owner(self):
        coordinator = AsyncMock()
        coordinator.release_control = AsyncMock(
            return_value={"error": "NOT_OWNER", "detail": "Cannot release"}
        )
        ctx = _make_context(coordinator)
        result = await self.tools["release_control"](ctx, actor="vision")
        assert result["error"] == "NOT_OWNER"


class TestGetControlOwner:
    def setup_method(self):
        self.mcp, self.tools = _make_mcp()
        register(self.mcp)

    async def test_get_owner(self):
        coordinator = MagicMock()
        coordinator.get_control_info.return_value = {"owner": "mcp", "executing": False}
        ctx = _make_context(coordinator)
        result = await self.tools["get_control_owner"](ctx)
        assert result["owner"] == "mcp"
        assert result["executing"] is False
