"""Tests for tello-navigator configuration."""

from dataclasses import FrozenInstanceError

import pytest

from tello_core.exceptions import ConfigurationError
from tello_navigator.config import TelloNavigatorConfig


class TestTelloNavigatorConfig:
    ENV = {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "test",
        "REDIS_URL": "redis://localhost:6379",
    }

    def test_defaults(self, monkeypatch):
        for k, v in self.ENV.items():
            monkeypatch.setenv(k, v)
        config = TelloNavigatorConfig.from_env(service_name="tello-navigator")
        assert config.missions_stream == "tello:missions"
        assert config.max_waypoints_per_mission == 20
        assert config.default_move_distance_cm == 100
        assert config.planning_timeout_s == 30.0
        assert config.checkpoint_ttl_hours == 24

    def test_env_overrides(self, monkeypatch):
        for k, v in self.ENV.items():
            monkeypatch.setenv(k, v)
        config = TelloNavigatorConfig.from_env(
            service_name="test",
            max_waypoints_per_mission=50,
        )
        assert config.max_waypoints_per_mission == 50

    def test_missing_env_raises(self, monkeypatch):
        for k in self.ENV:
            monkeypatch.delenv(k, raising=False)
        with pytest.raises(ConfigurationError):
            TelloNavigatorConfig.from_env(service_name="test")

    def test_frozen_immutability(self, monkeypatch):
        for k, v in self.ENV.items():
            monkeypatch.setenv(k, v)
        config = TelloNavigatorConfig.from_env(service_name="test")
        with pytest.raises(FrozenInstanceError):
            config.missions_stream = "other"
