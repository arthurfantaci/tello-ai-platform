"""Tests for query MCP tools.

Tests verify that tools call SessionRepository methods and
return correctly shaped responses, including error cases.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tello_telemetry.tools.queries import register


class TestQueryTools:
    @pytest.fixture(autouse=True)
    def setup_mcp(self):
        """Create a mock FastMCP server and register tools."""
        self.mcp = MagicMock()
        self.registered_tools = {}

        self.mock_repo = MagicMock()
        self.mock_ctx = MagicMock()
        self.mock_ctx.lifespan_context = {"session_repo": self.mock_repo}

        def mock_tool(*args, **kwargs):
            if args and callable(args[0]):
                fn = args[0]
                self.registered_tools[fn.__name__] = fn
                return fn

            def decorator(fn):
                self.registered_tools[fn.__name__] = fn
                return fn

            return decorator

        self.mcp.tool = mock_tool
        register(self.mcp)

    def test_all_tools_registered(self):
        expected = {
            "list_flight_sessions",
            "get_flight_session",
            "get_session_telemetry",
            "get_session_anomalies",
            "get_anomaly_summary",
        }
        assert set(self.registered_tools.keys()) == expected

    async def test_list_flight_sessions(self):
        self.mock_repo.list_sessions.return_value = [
            {"id": "s1"},
            {"id": "s2"},
        ]
        result = await self.registered_tools["list_flight_sessions"](
            self.mock_ctx,
            limit=10,
        )
        assert result["sessions"][0]["id"] == "s1"
        assert len(result["sessions"]) == 2

    async def test_get_flight_session_found(self):
        self.mock_repo.get_session.return_value = {
            "id": "s1",
            "room_id": "kitchen",
        }
        result = await self.registered_tools["get_flight_session"](
            self.mock_ctx,
            session_id="s1",
        )
        assert result["session"]["id"] == "s1"

    async def test_get_flight_session_not_found(self):
        self.mock_repo.get_session.return_value = None
        result = await self.registered_tools["get_flight_session"](
            self.mock_ctx,
            session_id="nonexistent",
        )
        assert "error" in result

    async def test_get_session_telemetry(self):
        self.mock_repo.get_session_samples.return_value = [
            {"battery_pct": 75},
        ]
        result = await self.registered_tools["get_session_telemetry"](
            self.mock_ctx,
            session_id="s1",
        )
        assert len(result["samples"]) == 1

    async def test_get_session_anomalies(self):
        self.mock_repo.get_session_anomalies.return_value = [
            {"type": "battery_low"},
        ]
        result = await self.registered_tools["get_session_anomalies"](
            self.mock_ctx,
            session_id="s1",
        )
        assert len(result["anomalies"]) == 1

    async def test_get_anomaly_summary(self):
        self.mock_repo.get_anomaly_summary.return_value = [
            {"type": "battery_low", "count": 3},
        ]
        result = await self.registered_tools["get_anomaly_summary"](
            self.mock_ctx,
        )
        assert result["summary"][0]["count"] == 3
