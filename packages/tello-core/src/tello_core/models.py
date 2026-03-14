"""Shared Pydantic models for the tello-ai-platform.

These models are the data contracts that flow between services via Redis
pub/sub and Streams. Defined once in tello-core, used by all services.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

# ── Hardware Layer ────────────────────────────────────────────────────


class FlightCommand(BaseModel):
    """A single drone flight command."""

    direction: Literal["up", "down", "left", "right", "forward", "back"]
    distance_cm: int = Field(ge=20, le=500)
    speed: int | None = None  # cm/s


class TelemetryFrame(BaseModel):
    """Real-time telemetry snapshot from the drone."""

    battery_pct: int
    height_cm: int
    tof_cm: int
    temp_c: float
    pitch: float
    roll: float
    yaw: float
    flight_time_s: int
    timestamp: datetime


# ── Navigation Layer ──────────────────────────────────────────────────


class RoomNode(BaseModel):
    """A room in the physical environment."""

    id: str
    name: str
    width_cm: int
    depth_cm: int
    height_cm: int


class MissionPad(BaseModel):
    """A Tello TT mission pad placed in a room."""

    id: int = Field(ge=1, le=8)
    room_id: str
    x_cm: int
    y_cm: int
    last_tof_approach_cm: int | None = None
    last_visited: datetime | None = None


class Waypoint(BaseModel):
    """A single step in a mission plan."""

    id: str
    sequence: int = Field(ge=0)
    room_id: str
    pad_id: int | None = None
    action: Literal["takeoff", "move", "rotate", "land", "hover", "goto_pad"]
    direction: Literal["up", "down", "left", "right", "forward", "back"] | None = None
    distance_cm: int | None = Field(default=None, ge=20, le=500)
    degrees: int | None = Field(default=None, ge=-360, le=360)
    speed_cm_s: int | None = Field(default=None, ge=10, le=100)


class MissionStatus(StrEnum):
    """Mission lifecycle states."""

    PLANNED = "planned"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ABORTED = "aborted"


class Mission(BaseModel):
    """A multi-step flight mission."""

    id: str
    goal: str
    status: MissionStatus = MissionStatus.PLANNED
    room_ids: list[str]
    waypoints: list[Waypoint] = []
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class Dwelling(BaseModel):
    """A physical dwelling that groups rooms."""

    id: str
    name: str
    address: str | None = None


# ── Vision Layer ──────────────────────────────────────────────────────


class VisualEntity(BaseModel):
    """An object observed by the drone's camera."""

    name: str
    type: str
    confidence: float = Field(ge=0.0, le=1.0)
    position: str | None = None
    room_id: str
    last_seen: datetime


# ── Telemetry Layer ───────────────────────────────────────────────────


class FlightSession(BaseModel):
    """A recorded flight session."""

    id: str
    start_time: datetime
    end_time: datetime | None = None
    room_id: str = "unknown"
    mission_id: str | None = None


class TelemetrySample(BaseModel):
    """A single telemetry measurement within a session."""

    battery_pct: int
    height_cm: int
    tof_cm: int
    temp_c: float
    timestamp: datetime


class Anomaly(BaseModel):
    """A detected flight anomaly."""

    type: str
    severity: Literal["warning", "critical"]
    detail: str
    timestamp: datetime
