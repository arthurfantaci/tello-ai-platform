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
    Dwelling,
    FlightCommand,
    FlightSession,
    Mission,
    MissionPad,
    MissionStatus,
    ObstacleIncident,
    ObstacleReading,
    ObstacleZone,
    RoomNode,
    TelemetryFrame,
    TelemetrySample,
    VisualEntity,
    Waypoint,
)
from tello_core.neo4j_client import create_neo4j_driver, neo4j_lifespan
from tello_core.redis_client import create_redis_client, redis_health_check

__all__ = [
    "Anomaly",
    "BaseServiceConfig",
    "CommandError",
    "ConfigurationError",
    "ConnectionError",
    "Dwelling",
    "FlightCommand",
    "FlightSession",
    "Mission",
    "MissionPad",
    "MissionStatus",
    "ObstacleIncident",
    "ObstacleReading",
    "ObstacleZone",
    "RoomNode",
    "TelemetryFrame",
    "TelemetrySample",
    "TelloError",
    "ValidationError",
    "VisualEntity",
    "Waypoint",
    "configure_structlog",
    "create_neo4j_driver",
    "create_redis_client",
    "neo4j_lifespan",
    "redis_health_check",
]
