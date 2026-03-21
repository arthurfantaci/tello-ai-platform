"""Tests for tello-telemetry health endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from tello_telemetry.server import mcp


class TestHealthEndpoint:
    @pytest.fixture()
    def client(self):
        """Create a Starlette test client from the FastMCP HTTP app."""
        app = mcp.http_app()
        return TestClient(app)

    def test_health_returns_200_when_healthy(self, client, monkeypatch):
        """Health endpoint returns 200 with redis=true, neo4j=true."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_neo4j = MagicMock()
        mock_neo4j.verify_connectivity = MagicMock(return_value=None)

        monkeypatch.setattr(
            "tello_telemetry.server._health_deps",
            lambda: (mock_redis, mock_neo4j),
        )

        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["redis"] is True
        assert data["neo4j"] is True

    def test_health_returns_503_when_redis_down(self, client, monkeypatch):
        """Health endpoint returns 503 when Redis is unreachable."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("refused"))
        mock_neo4j = MagicMock()
        mock_neo4j.verify_connectivity = MagicMock(return_value=None)

        monkeypatch.setattr(
            "tello_telemetry.server._health_deps",
            lambda: (mock_redis, mock_neo4j),
        )

        response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["redis"] is False
