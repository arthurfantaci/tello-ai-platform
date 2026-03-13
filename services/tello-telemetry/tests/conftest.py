"""Shared test fixtures for tello-telemetry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tello_telemetry.config import TelloTelemetryConfig


@pytest.fixture()
def mock_config():
    """Test configuration with defaults."""
    return TelloTelemetryConfig(
        neo4j_uri="bolt://localhost:7687",
        neo4j_username="neo4j",
        neo4j_password="test",
        redis_url="redis://localhost:6379",
        service_name="tello-telemetry-test",
    )


@pytest.fixture()
def mock_redis():
    """Mock async Redis client."""
    client = AsyncMock()
    client.xreadgroup = AsyncMock(return_value=[])
    client.xack = AsyncMock(return_value=1)
    client.xgroup_create = AsyncMock()
    client.aclose = AsyncMock()
    return client


@pytest.fixture()
def mock_neo4j_driver():
    """Mock Neo4j driver with session support."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(
        return_value=session,
    )
    driver.session.return_value.__exit__ = MagicMock(
        return_value=False,
    )
    session.run = MagicMock()
    return driver
