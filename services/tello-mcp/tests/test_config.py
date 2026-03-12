"""Tests for tello-mcp configuration."""

import pytest

from tello_core.exceptions import ConfigurationError
from tello_mcp.config import TelloMcpConfig


class TestTelloMcpConfig:
    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
        monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "pw")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        monkeypatch.setenv("TELLO_WIFI_SSID", "RMTT-TEST")

        config = TelloMcpConfig.from_env(service_name="tello-mcp")
        assert config.tello_wifi_ssid == "RMTT-TEST"
        assert config.service_name == "tello-mcp"

    def test_inherits_base_validation(self):
        with pytest.raises(ConfigurationError, match="Neo4j URI"):
            TelloMcpConfig(
                neo4j_uri="http://bad",
                neo4j_username="neo4j",
                neo4j_password="pw",
                redis_url="redis://localhost:6379",
                service_name="test",
            )

    def test_telemetry_defaults(self):
        config = TelloMcpConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_username="neo4j",
            neo4j_password="pw",
            redis_url="redis://localhost:6379",
            service_name="test",
        )
        assert config.telemetry_publish_hz == 10
        assert config.telemetry_channel == "tello:telemetry"
        assert config.events_stream == "tello:events"
