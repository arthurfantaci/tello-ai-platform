"""Tests for tello-telemetry configuration."""

from __future__ import annotations

import pytest

from tello_core.exceptions import ConfigurationError
from tello_telemetry.config import TelloTelemetryConfig


class TestTelloTelemetryConfig:
    def test_defaults(self, mock_config):
        assert mock_config.battery_warning_pct == 20
        assert mock_config.battery_critical_pct == 10
        assert mock_config.temp_warning_c == 85.0
        assert mock_config.temp_critical_c == 90.0
        assert mock_config.altitude_max_cm == 300
        assert mock_config.neo4j_sample_interval_s == 5.0
        assert mock_config.stream_name == "tello:events"
        assert mock_config.consumer_group == "telemetry-service"
        assert mock_config.consumer_name == "worker-1"
        assert mock_config.batch_size == 10
        assert mock_config.block_ms == 2000

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
        monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "pw")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        config = TelloTelemetryConfig.from_env(
            service_name="tello-telemetry",
        )
        assert config.service_name == "tello-telemetry"
        assert config.battery_warning_pct == 20

    def test_custom_thresholds(self):
        config = TelloTelemetryConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_username="neo4j",
            neo4j_password="test",
            redis_url="redis://localhost:6379",
            service_name="test",
            battery_warning_pct=30,
            temp_critical_c=95.0,
        )
        assert config.battery_warning_pct == 30
        assert config.temp_critical_c == 95.0

    def test_inherits_base_validation(self):
        with pytest.raises(ConfigurationError, match="Neo4j URI"):
            TelloTelemetryConfig(
                neo4j_uri="http://bad",
                neo4j_username="neo4j",
                neo4j_password="pw",
                redis_url="redis://localhost:6379",
                service_name="test",
            )
