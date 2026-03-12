"""Tests for tello_core configuration."""

import pytest

from tello_core.config import BaseServiceConfig, configure_structlog
from tello_core.exceptions import ConfigurationError


class TestBaseServiceConfig:
    def test_from_env_loads_values(self, env_vars):
        config = BaseServiceConfig.from_env(service_name="test-service")
        assert config.neo4j_uri == "bolt://localhost:7687"
        assert config.neo4j_username == "neo4j"
        assert config.neo4j_password == "test-password"
        assert config.redis_url == "redis://localhost:6379"
        assert config.service_name == "test-service"

    def test_from_env_missing_required_var_raises(self, monkeypatch):
        monkeypatch.delenv("NEO4J_URI", raising=False)
        with pytest.raises(ConfigurationError, match="NEO4J_URI"):
            BaseServiceConfig.from_env(service_name="test")

    def test_invalid_neo4j_uri_scheme_raises(self):
        with pytest.raises(ConfigurationError, match="Neo4j URI"):
            BaseServiceConfig(
                neo4j_uri="http://localhost:7687",
                neo4j_username="neo4j",
                neo4j_password="pw",
                redis_url="redis://localhost:6379",
                service_name="test",
            )

    def test_invalid_redis_url_scheme_raises(self):
        with pytest.raises(ConfigurationError, match="Redis URL"):
            BaseServiceConfig(
                neo4j_uri="bolt://localhost:7687",
                neo4j_username="neo4j",
                neo4j_password="pw",
                redis_url="http://localhost:6379",
                service_name="test",
            )

    def test_valid_neo4j_schemes_accepted(self):
        for scheme in ["bolt://", "bolt+s://", "neo4j://", "neo4j+s://"]:
            config = BaseServiceConfig(
                neo4j_uri=f"{scheme}localhost:7687",
                neo4j_username="neo4j",
                neo4j_password="pw",
                redis_url="redis://localhost:6379",
                service_name="test",
            )
            assert config.neo4j_uri.startswith(scheme)

    def test_frozen_dataclass(self):
        config = BaseServiceConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_username="neo4j",
            neo4j_password="pw",
            redis_url="redis://localhost:6379",
            service_name="test",
        )
        with pytest.raises(AttributeError):
            config.neo4j_uri = "bolt://other:7687"

    def test_defaults(self):
        config = BaseServiceConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_username="neo4j",
            neo4j_password="pw",
            redis_url="redis://localhost:6379",
            service_name="test",
        )
        assert config.neo4j_max_connection_pool_size == 5
        assert config.neo4j_connection_acquisition_timeout == 30.0


class TestConfigureStructlog:
    def test_configure_structlog_sets_up_logging(self):
        import structlog

        configure_structlog("test-service")
        logger = structlog.get_logger()
        assert logger is not None
