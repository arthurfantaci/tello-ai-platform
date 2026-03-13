"""Configuration for tello-telemetry service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from tello_core.config import BaseServiceConfig


@dataclass(frozen=True, slots=True)
class TelloTelemetryConfig(BaseServiceConfig):
    """tello-telemetry specific configuration.

    Anomaly thresholds, sampling interval, and Redis Stream
    consumer settings. All fields have sensible defaults;
    override via environment variables.
    """

    # Anomaly thresholds
    battery_warning_pct: int = 20
    battery_critical_pct: int = 10
    temp_warning_c: float = 85.0
    temp_critical_c: float = 90.0
    altitude_max_cm: int = 300

    # Sampling
    neo4j_sample_interval_s: float = 5.0

    # Consumer
    stream_name: str = "tello:events"
    consumer_group: str = "telemetry-service"
    consumer_name: str = "worker-1"
    batch_size: int = 10
    block_ms: int = 2000

    @classmethod
    def from_env(cls, **overrides: str | int | float | bool) -> Self:
        """Load tello-telemetry config from environment."""
        return BaseServiceConfig.from_env.__func__(cls, **overrides)  # type: ignore[attr-defined]
