"""Tests for tello-navigator configuration."""

from __future__ import annotations

import pytest

from tello_core.exceptions import ConfigurationError
from tello_navigator.config import TelloNavigatorConfig

_ENV = {
    "NEO4J_URI": "bolt://localhost:7687",
    "NEO4J_USERNAME": "neo4j",
    "NEO4J_PASSWORD": "password",
    "REDIS_URL": "redis://localhost:6379",
}


class TestTelloNavigatorConfig:
    def test_defaults(self, monkeypatch):
        for k, v in _ENV.items():
            monkeypatch.setenv(k, v)
        config = TelloNavigatorConfig.from_env(service_name="tello-navigator")
        assert config.service_name == "tello-navigator"
        assert config.missions_stream == "tello:missions"
        assert config.max_waypoints_per_mission == 20
        assert config.default_move_distance_cm == 100
        assert config.planning_timeout_s == 30.0
        assert config.checkpoint_ttl_hours == 24

    def test_override_defaults(self, monkeypatch):
        for k, v in _ENV.items():
            monkeypatch.setenv(k, v)
        config = TelloNavigatorConfig.from_env(
            service_name="tello-navigator",
            max_waypoints_per_mission=10,
        )
        assert config.max_waypoints_per_mission == 10

    def test_missing_env_raises(self, monkeypatch):
        monkeypatch.delenv("NEO4J_URI", raising=False)
        monkeypatch.delenv("NEO4J_USERNAME", raising=False)
        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        with pytest.raises(ConfigurationError):
            TelloNavigatorConfig.from_env(service_name="tello-navigator")

    def test_frozen(self, monkeypatch):
        for k, v in _ENV.items():
            monkeypatch.setenv(k, v)
        config = TelloNavigatorConfig.from_env(service_name="tello-navigator")
        with pytest.raises(AttributeError):
            config.missions_stream = "other"
