"""Configuration for tello-mcp service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Self

from tello_core.config import BaseServiceConfig


@dataclass(frozen=True, slots=True)
class TelloMcpConfig(BaseServiceConfig):
    """tello-mcp specific configuration."""

    tello_wifi_ssid: str = ""
    tello_host: str = "192.168.10.1"
    telemetry_publish_hz: int = 10
    telemetry_channel: str = "tello:telemetry"
    events_stream: str = "tello:events"

    @classmethod
    def from_env(cls, **overrides: str | int | float | bool) -> Self:
        """Load tello-mcp config from environment."""
        overrides.setdefault("tello_wifi_ssid", os.environ.get("TELLO_WIFI_SSID", ""))
        overrides.setdefault("tello_host", os.environ.get("TELLO_HOST", "192.168.10.1"))
        return BaseServiceConfig.from_env.__func__(cls, **overrides)  # type: ignore[attr-defined]
