"""tello-core: shared library for the tello-ai-platform.

Public API re-exports for convenient imports:
    from tello_core import FlightCommand, BaseServiceConfig, TelloError
"""

from tello_core.config import BaseServiceConfig, configure_structlog
from tello_core.exceptions import (
    CommandError,
    ConfigurationError,
    ConnectionError,
    TelloError,
    ValidationError,
)
from tello_core.models import (
    Anomaly,
    FlightCommand,
    FlightSession,
    MissionPad,
    RoomNode,
    TelemetryFrame,
    TelemetrySample,
    VisualEntity,
)
from tello_core.neo4j_client import create_neo4j_driver, neo4j_lifespan
from tello_core.redis_client import create_redis_client, redis_health_check

__all__ = [
    # Config
    "BaseServiceConfig",
    "configure_structlog",
    # Exceptions
    "CommandError",
    "ConfigurationError",
    "ConnectionError",
    "TelloError",
    "ValidationError",
    # Models
    "Anomaly",
    "FlightCommand",
    "FlightSession",
    "MissionPad",
    "RoomNode",
    "TelemetryFrame",
    "TelemetrySample",
    "VisualEntity",
    # Infrastructure
    "create_neo4j_driver",
    "create_redis_client",
    "neo4j_lifespan",
    "redis_health_check",
]
