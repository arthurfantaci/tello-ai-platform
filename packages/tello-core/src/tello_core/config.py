"""Base configuration for all tello-ai-platform services.

Each service subclasses BaseServiceConfig with its own fields.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, ClassVar, Self

import structlog

from tello_core.exceptions import ConfigurationError

VALID_NEO4J_SCHEMES = ("bolt://", "bolt+s://", "neo4j://", "neo4j+s://")
VALID_REDIS_SCHEMES = ("redis://", "rediss://")


@dataclass(frozen=True, slots=True)
class BaseServiceConfig:
    """Base configuration shared by all platform services.

    Subclass and add service-specific fields:
        @dataclass(frozen=True, slots=True)
        class TelloMcpConfig(BaseServiceConfig):
            tello_wifi_ssid: str = ""

    Set require_neo4j = False on subclasses that don't use Neo4j:
        @dataclass(frozen=True, slots=True)
        class NoNeo4jService(BaseServiceConfig):
            require_neo4j: ClassVar[bool] = False
    """

    require_neo4j: ClassVar[bool] = True

    redis_url: str
    service_name: str
    neo4j_uri: str | None = None
    neo4j_username: str | None = None
    neo4j_password: str | None = None
    neo4j_max_connection_pool_size: int = 5
    neo4j_connection_acquisition_timeout: float = 30.0

    @classmethod
    def from_env(cls, **overrides: str | int | float | bool) -> Self:
        """Load configuration from environment variables.

        Reads: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, REDIS_URL.
        Raises ConfigurationError for missing required vars (Neo4j only if require_neo4j=True).

        Args:
            **overrides: Values that override environment variables.
        """
        values: dict[str, Any] = {}

        # Redis is always required
        if "redis_url" in overrides:
            values["redis_url"] = overrides.pop("redis_url")  # type: ignore[assignment]
        else:
            val = os.environ.get("REDIS_URL")
            if val is None:
                msg = "Required environment variable REDIS_URL is not set"
                raise ConfigurationError(msg)
            values["redis_url"] = val

        # Neo4j is conditional on require_neo4j
        neo4j_fields = {
            "neo4j_uri": "NEO4J_URI",
            "neo4j_username": "NEO4J_USERNAME",
            "neo4j_password": "NEO4J_PASSWORD",
        }
        for field, env_var in neo4j_fields.items():
            if field in overrides:
                values[field] = overrides.pop(field)  # type: ignore[assignment]
            else:
                val = os.environ.get(env_var)
                if val is None and cls.require_neo4j:
                    msg = f"Required environment variable {env_var} is not set"
                    raise ConfigurationError(msg)
                values[field] = val

        return cls(**values, **overrides)

    def __post_init__(self) -> None:
        """Fail-fast validation."""
        if self.neo4j_uri is not None and not any(
            self.neo4j_uri.startswith(s) for s in VALID_NEO4J_SCHEMES
        ):
            msg = f"Neo4j URI must start with one of {VALID_NEO4J_SCHEMES}, got: {self.neo4j_uri}"
            raise ConfigurationError(msg)
        if not any(self.redis_url.startswith(s) for s in VALID_REDIS_SCHEMES):
            msg = f"Redis URL must start with one of {VALID_REDIS_SCHEMES}, got: {self.redis_url}"
            raise ConfigurationError(msg)
        if not self.service_name:
            msg = "service_name must be non-empty"
            raise ConfigurationError(msg)


def configure_structlog(service_name: str) -> None:
    """Configure structlog with consistent JSON processing for all services.

    Args:
        service_name: Injected into every log entry as 'service' key.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.EventRenamer("msg"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(0),
        cache_logger_on_first_use=True,
    )
    # Bind service name globally
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(service=service_name)
