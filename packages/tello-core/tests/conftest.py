"""Shared test fixtures for tello-core."""

import pytest


@pytest.fixture()
def env_vars(monkeypatch):
    """Set standard environment variables for testing."""
    values = {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "test-password",
        "REDIS_URL": "redis://localhost:6379",
    }
    for key, val in values.items():
        monkeypatch.setenv(key, val)
    return values
