"""Tests for tello-mcp configuration."""

import pytest

from tello_core.exceptions import ConfigurationError
from tello_mcp.config import TelloMcpConfig


class TestTelloMcpConfig:
    def test_from_env_without_neo4j(self, monkeypatch):
        """TelloMcpConfig.from_env works without NEO4J_* env vars."""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        monkeypatch.setenv("TELLO_WIFI_SSID", "RMTT-TEST")
        monkeypatch.delenv("NEO4J_URI", raising=False)
        monkeypatch.delenv("NEO4J_USERNAME", raising=False)
        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

        config = TelloMcpConfig.from_env(service_name="tello-mcp")
        assert config.tello_wifi_ssid == "RMTT-TEST"
        assert config.service_name == "tello-mcp"
        assert config.neo4j_uri is None

    def test_require_neo4j_is_false(self):
        """TelloMcpConfig opts out of Neo4j requirement."""
        assert TelloMcpConfig.require_neo4j is False

    def test_inherits_base_validation(self):
        with pytest.raises(ConfigurationError, match="Neo4j URI"):
            TelloMcpConfig(
                neo4j_uri="http://bad",
                redis_url="redis://localhost:6379",
                service_name="test",
            )

    def test_telemetry_defaults(self):
        config = TelloMcpConfig(
            redis_url="redis://localhost:6379",
            service_name="test",
        )
        assert config.telemetry_publish_hz == 10
        assert config.telemetry_channel == "tello:telemetry"
        assert config.events_stream == "tello:events"

    def test_tello_host_default(self):
        config = TelloMcpConfig(
            redis_url="redis://localhost:6379",
            service_name="test",
        )
        assert config.tello_host == "192.168.10.1"

    def test_tello_host_from_env(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        monkeypatch.setenv("TELLO_HOST", "192.168.68.102")
        monkeypatch.delenv("NEO4J_URI", raising=False)
        monkeypatch.delenv("NEO4J_USERNAME", raising=False)
        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

        config = TelloMcpConfig.from_env(service_name="tello-mcp")
        assert config.tello_host == "192.168.68.102"
