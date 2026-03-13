# Tello AI Platform Scaffold Implementation Plan

> **For agentic workers:** REQUIRED: Use
> superpowers:subagent-driven-development (if subagents available)
> or superpowers:executing-plans to implement this plan.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the tello-ai-platform uv workspace monorepo
with tello-core shared library, tello-mcp service scaffold,
placeholder services, and full Claude Code + dev environment
configuration.

**Architecture:** uv workspace monorepo with `packages/tello-core`
(shared models, config, exceptions, Redis/Neo4j factories) and
`services/tello-mcp` (FastMCP hardware abstraction server).
Four placeholder services get minimal pyproject.toml only.
Root provides shared tooling config (Ruff, ty, pytest,
pre-commit, CI).

**Tech Stack:** Python 3.13, uv workspace, FastMCP 3.x,
Pydantic 2.x, structlog, Neo4j 5.x driver, redis-py,
pytest + pytest-asyncio, Ruff, ty, Docker Compose
(Neo4j + Redis)

**Spec:** `docs/superpowers/specs/2026-03-11-tello-platform-scaffold-design.md`

---

## File Map

### Root (create all)

- `pyproject.toml` — uv workspace root + Ruff/ty/pytest config
- `docker-compose.yml` — Neo4j 5 + Redis 8.0
- `.env.example` — environment variable template
- `.gitignore` — monorepo-adapted
- `.mcp.json` — MCP server configuration
- `.pre-commit-config.yaml` — Ruff + standard hooks
- `CLAUDE.md` — global behavioral conventions
- `MEMORY.md` — current working state

### .vscode/ (create all)

- `settings.json` — workspace Python + Ruff + pytest + ty
- `extensions.json` — recommended/unwanted extensions
- `launch.json` — per-service debug configs

### .claude/ (create all)

- `settings.json` — plugins + hooks
- `hooks/validate-workspace.sh` — workspace boundary validation
- `commands/implement.md` — TDD workflow
- `commands/plan.md` — feature planning
- `commands/review.md` — code review delegation
- `commands/test.md` — pytest guide
- `skills/drone-patterns/SKILL.md` — djitellopy conventions
- `skills/mcp-tool-patterns/SKILL.md` — FastMCP patterns
- `skills/pr-workflow/skill.md` — PR creation/merge

### .github/ (create all)

- `workflows/ci.yml` — lint + test matrix + type-check

### packages/tello-core/ (create all)

- `pyproject.toml` — package metadata + deps
- `src/tello_core/__init__.py` — public API re-exports
- `src/tello_core/models.py` — shared Pydantic models
- `src/tello_core/config.py` — BaseServiceConfig + configure_structlog()
- `src/tello_core/exceptions.py` — TelloError hierarchy
- `src/tello_core/redis_client.py` — AsyncRedis factory
- `src/tello_core/neo4j_client.py` — Neo4j driver factory + lifespan
- `tests/conftest.py` — shared test fixtures
- `tests/test_models.py` — model validation tests
- `tests/test_config.py` — config loading + validation tests
- `tests/test_exceptions.py` — exception hierarchy tests
- `tests/test_redis_client.py` — Redis factory + health check tests
- `tests/test_neo4j_client.py` — Neo4j factory + lifespan tests

### services/tello-mcp/ (create all)

- `pyproject.toml` — service metadata + deps
- `src/tello_mcp/__init__.py`
- `src/tello_mcp/server.py` — FastMCP server + tool registration
- `src/tello_mcp/config.py` — TelloMcpConfig(BaseServiceConfig)
- `src/tello_mcp/drone.py` — DroneAdapter wrapping djitellopy
- `src/tello_mcp/queue.py` — asyncio.Queue command serialization
- `src/tello_mcp/telemetry.py` — Redis PUBLISH + XADD publisher
- `src/tello_mcp/tools/__init__.py`
- `src/tello_mcp/tools/flight.py` — flight control tools
- `src/tello_mcp/tools/sensors.py` — sensor/state tools
- `src/tello_mcp/tools/expansion.py` — LED/matrix/ESP32 tools
- `tests/conftest.py` — mock_drone, mock_redis, mock_config
- `tests/test_config.py`
- `tests/test_drone.py`
- `tests/test_queue.py`
- `tests/test_telemetry.py`
- `tests/test_tools/test_flight.py`
- `tests/test_tools/test_sensors.py`
- `tests/test_tools/test_expansion.py`

### Placeholder services (create pyproject.toml only)

- `services/tello-navigator/pyproject.toml`
- `services/tello-vision/pyproject.toml`
- `services/tello-voice/pyproject.toml`
- `services/tello-telemetry/pyproject.toml`

### docs/ (create)

- `architecture.md` — platform overview from plan v2.0

---

## Chunk 1: Monorepo Root & Infrastructure

### Task 1: Initialize git repo and root workspace

**Files:**

- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `docker-compose.yml`
- Create: `.pre-commit-config.yaml`

- [ ] **Step 1: Initialize git repository**

```bash
cd /Users/arthurfantaci/Projects/tello-ai-platform
git init
```

- [ ] **Step 2: Create root pyproject.toml**

Create `pyproject.toml` with the full workspace definition,
Ruff config, ty config, pytest config, and coverage config
exactly as specified in spec Section 4.

- [ ] **Step 3: Create .gitignore**

Create `.gitignore` with contents from spec Section 15.
Includes: `.env`, `__pycache__/`, `.venv/`, `.ruff_cache/`,
`.ty_cache/`, `.superpowers/`, `.DS_Store`, `neo4j_data/`,
`redis_data/`, `.playwright-mcp/`.

- [ ] **Step 4: Create .env.example**

Create `.env.example` with contents from spec Section 13.
Infrastructure coords + drone SSID + commented-out future keys.

- [ ] **Step 5: Create docker-compose.yml**

Create `docker-compose.yml` with contents from spec Section 7.
Neo4j 5-community (LTS) + Redis 8.0-alpine, both with health
checks and named volumes.

- [ ] **Step 6: Create .pre-commit-config.yaml**

Create `.pre-commit-config.yaml` with contents from spec
Section 12. Workspace-aware Ruff hooks + standard
pre-commit-hooks.

- [ ] **Step 7: Create placeholder service pyproject.toml files**

Create minimal `pyproject.toml` for each placeholder service as specified in spec Section 14:

- `services/tello-navigator/pyproject.toml` (name: tello-navigator)
- `services/tello-vision/pyproject.toml` (name: tello-vision)
- `services/tello-voice/pyproject.toml` (name: tello-voice)
- `services/tello-telemetry/pyproject.toml` (name: tello-telemetry)

Each depends on `tello-core` via `[tool.uv.sources]` workspace reference.

- [ ] **Step 8: Create docs/architecture.md**

Create `docs/architecture.md` — platform overview summarizing
the 5 services, their roles, Neo4j schema domains, Redis
capabilities, and recommended build order. Sourced from
plan v2.0.

- [ ] **Step 9: Verify workspace resolves**

```bash
uv sync
```

Expected: Should resolve all workspace members (with warnings
about missing tello-core package, which is expected — we create
it in Task 2).

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml .gitignore .env.example docker-compose.yml .pre-commit-config.yaml services/ docs/
git commit -m "feat: initialize uv workspace monorepo with infrastructure config

Root pyproject.toml with workspace members, Ruff/ty/pytest config.
Docker Compose for Neo4j 5 + Redis 8.0 (infrastructure only).
Placeholder pyproject.toml for navigator, vision, voice, telemetry."
```

---

### Task 2: Create tello-core shared package

**Files:**

- Create: `packages/tello-core/pyproject.toml`
- Create: `packages/tello-core/src/tello_core/__init__.py`
- Create: `packages/tello-core/src/tello_core/exceptions.py`
- Create: `packages/tello-core/src/tello_core/models.py`
- Create: `packages/tello-core/src/tello_core/config.py`
- Create: `packages/tello-core/src/tello_core/redis_client.py`
- Create: `packages/tello-core/src/tello_core/neo4j_client.py`
- Test: `packages/tello-core/tests/conftest.py`
- Test: `packages/tello-core/tests/test_exceptions.py`
- Test: `packages/tello-core/tests/test_models.py`
- Test: `packages/tello-core/tests/test_config.py`

- [ ] **Step 1: Create tello-core pyproject.toml**

Create `packages/tello-core/pyproject.toml` as specified in
spec Section 5.1. Dependencies: pydantic>=2.0.0,
structlog>=24.0.0, neo4j>=5.15.0, redis>=5.0.0.
Build system: hatchling.

- [ ] **Step 2: Write the failing test for exceptions**

Create `packages/tello-core/tests/test_exceptions.py`:

```python
"""Tests for tello_core exception hierarchy."""

from tello_core.exceptions import (
    TelloError,
    ConfigurationError,
    ConnectionError as TelloConnectionError,
    CommandError,
    ValidationError as TelloValidationError,
)


def test_tello_error_is_base_exception():
    err = TelloError("base error")
    assert isinstance(err, Exception)
    assert str(err) == "base error"


def test_configuration_error_inherits_tello_error():
    err = ConfigurationError("bad config")
    assert isinstance(err, TelloError)


def test_connection_error_inherits_tello_error():
    err = TelloConnectionError("no connection")
    assert isinstance(err, TelloError)


def test_command_error_inherits_tello_error():
    err = CommandError("command failed")
    assert isinstance(err, TelloError)


def test_validation_error_inherits_tello_error():
    err = TelloValidationError("invalid input")
    assert isinstance(err, TelloError)


def test_all_exceptions_are_distinct():
    """Each exception type should be catchable independently."""
    with_config = ConfigurationError("x")
    with_conn = TelloConnectionError("x")
    with_cmd = CommandError("x")
    with_val = TelloValidationError("x")

    assert type(with_config) is not type(with_conn)
    assert type(with_conn) is not type(with_cmd)
    assert type(with_cmd) is not type(with_val)
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /Users/arthurfantaci/Projects/tello-ai-platform
uv run --package tello-core pytest packages/tello-core/tests/test_exceptions.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'tello_core'`

- [ ] **Step 4: Implement exceptions.py**

Create `packages/tello-core/src/tello_core/__init__.py` (empty) and `packages/tello-core/src/tello_core/exceptions.py`:

```python
"""Base exception hierarchy for the tello-ai-platform.

All platform exceptions inherit from TelloError.
Services extend these with domain-specific subclasses.
"""


class TelloError(Exception):
    """Root exception for all tello-ai-platform errors."""


class ConfigurationError(TelloError):
    """Invalid configuration or missing environment variables.

    Raised at startup (fail-fast). Should never be caught in normal flow.
    """


class ConnectionError(TelloError):
    """Neo4j, Redis, or drone connection failure."""


class CommandError(TelloError):
    """Failed to execute a drone command or tool call."""


class ValidationError(TelloError):
    """Invalid input data (distinct from Pydantic's ValidationError)."""
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run --package tello-core pytest packages/tello-core/tests/test_exceptions.py -v
```

Expected: All 6 tests PASS.

- [ ] **Step 6: Write the failing test for models**

Create `packages/tello-core/tests/test_models.py`:

```python
"""Tests for tello_core shared Pydantic models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

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


class TestFlightCommand:
    def test_valid_command(self):
        cmd = FlightCommand(direction="forward", distance_cm=100)
        assert cmd.direction == "forward"
        assert cmd.distance_cm == 100
        assert cmd.speed is None

    def test_with_speed(self):
        cmd = FlightCommand(direction="up", distance_cm=50, speed=30)
        assert cmd.speed == 30

    def test_invalid_direction_rejected(self):
        with pytest.raises(ValidationError):
            FlightCommand(direction="diagonal", distance_cm=100)

    def test_distance_bounds(self):
        with pytest.raises(ValidationError):
            FlightCommand(direction="forward", distance_cm=10)  # below 20

        with pytest.raises(ValidationError):
            FlightCommand(direction="forward", distance_cm=600)  # above 500


class TestTelemetryFrame:
    def test_valid_frame(self):
        frame = TelemetryFrame(
            battery_pct=85,
            height_cm=120,
            tof_cm=95,
            temp_c=42.5,
            pitch=1.2,
            roll=-0.5,
            yaw=180.0,
            flight_time_s=45,
            timestamp=datetime(2026, 3, 12, 10, 0, 0),
        )
        assert frame.battery_pct == 85

    def test_serialization_roundtrip(self):
        frame = TelemetryFrame(
            battery_pct=50,
            height_cm=100,
            tof_cm=80,
            temp_c=40.0,
            pitch=0.0,
            roll=0.0,
            yaw=0.0,
            flight_time_s=10,
            timestamp=datetime(2026, 3, 12, 10, 0, 0),
        )
        data = frame.model_dump()
        restored = TelemetryFrame.model_validate(data)
        assert restored == frame


class TestRoomNode:
    def test_valid_room(self):
        room = RoomNode(id="living_room", name="Living Room", width_cm=400, depth_cm=500, height_cm=270)
        assert room.id == "living_room"


class TestMissionPad:
    def test_valid_pad(self):
        pad = MissionPad(id=1, room_id="living_room", x_cm=200, y_cm=150)
        assert pad.last_visited is None

    def test_pad_id_range(self):
        with pytest.raises(ValidationError):
            MissionPad(id=0, room_id="r", x_cm=0, y_cm=0)
        with pytest.raises(ValidationError):
            MissionPad(id=9, room_id="r", x_cm=0, y_cm=0)


class TestVisualEntity:
    def test_valid_entity(self):
        entity = VisualEntity(
            name="couch",
            type="furniture",
            confidence=0.92,
            room_id="living_room",
            last_seen=datetime(2026, 3, 12, 10, 0, 0),
        )
        assert entity.position is None


class TestFlightSession:
    def test_valid_session(self):
        session = FlightSession(
            id="sess_001",
            start_time=datetime(2026, 3, 12, 10, 0, 0),
            room_id="living_room",
        )
        assert session.end_time is None
        assert session.mission_id is None


class TestTelemetrySample:
    def test_valid_sample(self):
        sample = TelemetrySample(
            battery_pct=75,
            height_cm=100,
            tof_cm=90,
            temp_c=41.0,
            timestamp=datetime(2026, 3, 12, 10, 0, 0),
        )
        assert sample.battery_pct == 75


class TestAnomaly:
    def test_valid_anomaly(self):
        anomaly = Anomaly(
            type="battery_drain",
            severity="warning",
            detail="Drain rate >5%/min",
            timestamp=datetime(2026, 3, 12, 10, 0, 0),
        )
        assert anomaly.severity == "warning"

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValidationError):
            Anomaly(
                type="battery_drain",
                severity="info",
                detail="x",
                timestamp=datetime(2026, 3, 12, 10, 0, 0),
            )
```

- [ ] **Step 7: Run test to verify it fails**

```bash
uv run --package tello-core pytest packages/tello-core/tests/test_models.py -v
```

Expected: FAIL — `ImportError: cannot import name 'FlightCommand' from 'tello_core.models'`

- [ ] **Step 8: Implement models.py**

Create `packages/tello-core/src/tello_core/models.py`:

```python
"""Shared Pydantic models for the tello-ai-platform.

These models are the data contracts that flow between services via Redis
pub/sub and Streams. Defined once in tello-core, used by all services.
"""

from datetime import datetime
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
    room_id: str
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
```

- [ ] **Step 9: Run test to verify it passes**

```bash
uv run --package tello-core pytest packages/tello-core/tests/test_models.py -v
```

Expected: All 12 tests PASS.

- [ ] **Step 10: Write the failing test for config**

Create `packages/tello-core/tests/conftest.py`:

```python
"""Shared test fixtures for tello-core."""

import pytest


@pytest.fixture()
def env_vars(monkeypatch):
    """Set standard environment variables for testing."""
    values = {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "test-password",
        "REDIS_URL": "redis://localhost:6379",
    }
    for key, val in values.items():
        monkeypatch.setenv(key, val)
    return values
```

Create `packages/tello-core/tests/test_config.py`:

```python
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
        # Should not raise — structlog is configured
        assert logger is not None
```

- [ ] **Step 11: Run test to verify it fails**

```bash
uv run --package tello-core pytest packages/tello-core/tests/test_config.py -v
```

Expected: FAIL — `ImportError: cannot import name 'BaseServiceConfig' from 'tello_core.config'`

- [ ] **Step 12: Implement config.py**

Create `packages/tello-core/src/tello_core/config.py`:

```python
"""Base configuration for all tello-ai-platform services.

Each service subclasses BaseServiceConfig with its own fields.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Self

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
    """

    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    redis_url: str
    service_name: str
    neo4j_max_connection_pool_size: int = 5
    neo4j_connection_acquisition_timeout: float = 30.0

    @classmethod
    def from_env(cls, **overrides) -> Self:
        """Load configuration from environment variables.

        Reads: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, REDIS_URL.
        Raises ConfigurationError for missing required vars.

        Args:
            **overrides: Values that override environment variables.
        """
        required = {
            "neo4j_uri": "NEO4J_URI",
            "neo4j_username": "NEO4J_USERNAME",
            "neo4j_password": "NEO4J_PASSWORD",
            "redis_url": "REDIS_URL",
        }
        values: dict[str, str] = {}
        for field, env_var in required.items():
            if field in overrides:
                values[field] = overrides.pop(field)
            else:
                val = os.environ.get(env_var)
                if val is None:
                    msg = f"Required environment variable {env_var} is not set"
                    raise ConfigurationError(msg)
                values[field] = val

        return cls(**values, **overrides)

    def __post_init__(self) -> None:
        """Fail-fast validation."""
        if not any(self.neo4j_uri.startswith(s) for s in VALID_NEO4J_SCHEMES):
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
```

- [ ] **Step 13: Run test to verify it passes**

```bash
uv run --package tello-core pytest packages/tello-core/tests/test_config.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 14: Implement redis_client.py and neo4j_client.py**

Create `packages/tello-core/src/tello_core/redis_client.py`:

```python
"""Shared Redis client factory for the tello-ai-platform."""

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger("tello_core.redis")


def create_redis_client(url: str) -> aioredis.Redis:
    """Create an async Redis client.

    Args:
        url: Redis connection URL (redis:// or rediss://).
    """
    logger.info("Creating Redis client for %s", url.split("@")[-1])
    return aioredis.from_url(url, decode_responses=True)


async def redis_health_check(client: aioredis.Redis) -> bool:
    """Check Redis connectivity.

    Returns:
        True if Redis responds to PING.
    """
    try:
        return await client.ping()
    except Exception:
        logger.exception("Redis health check failed")
        return False
```

Create `packages/tello-core/src/tello_core/neo4j_client.py`:

```python
"""Shared Neo4j driver factory for the tello-ai-platform."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

import structlog
from neo4j import GraphDatabase

if TYPE_CHECKING:
    from neo4j import Driver

    from tello_core.config import BaseServiceConfig

logger = structlog.get_logger("tello_core.neo4j")


def create_neo4j_driver(
    uri: str,
    username: str,
    password: str,
    *,
    max_connection_pool_size: int = 5,
    connection_acquisition_timeout: float = 30.0,
) -> Driver:
    """Create a Neo4j driver with connection pool settings.

    Uses the sync driver (neo4j-graphrag and most Neo4j operations are sync).

    Args:
        uri: Neo4j connection URI.
        username: Neo4j username.
        password: Neo4j password.
        max_connection_pool_size: Maximum connections in pool.
        connection_acquisition_timeout: Seconds to wait for a connection.
    """
    logger.info("Creating Neo4j driver for %s", uri)
    return GraphDatabase.driver(
        uri,
        auth=(username, password),
        max_connection_pool_size=max_connection_pool_size,
        connection_acquisition_timeout=connection_acquisition_timeout,
    )


@asynccontextmanager
async def neo4j_lifespan(config: BaseServiceConfig) -> AsyncIterator[Driver]:
    """Async context manager for Neo4j driver lifecycle.

    Usage in FastAPI/FastMCP lifespan:
        async with neo4j_lifespan(config) as driver:
            app.state.driver = driver
            yield
    """
    driver = create_neo4j_driver(
        config.neo4j_uri,
        config.neo4j_username,
        config.neo4j_password,
        max_connection_pool_size=config.neo4j_max_connection_pool_size,
        connection_acquisition_timeout=config.neo4j_connection_acquisition_timeout,
    )
    try:
        driver.verify_connectivity()
        logger.info("Neo4j connectivity verified")
        yield driver
    finally:
        driver.close()
        logger.info("Neo4j driver closed")
```

- [ ] **Step 15: Update **init**.py with public API exports**

Update `packages/tello-core/src/tello_core/__init__.py`:

```python
"""tello-core: shared models, config, and infrastructure for the tello-ai-platform."""

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

__all__ = [
    "Anomaly",
    "BaseServiceConfig",
    "CommandError",
    "ConfigurationError",
    "ConnectionError",
    "FlightCommand",
    "FlightSession",
    "MissionPad",
    "RoomNode",
    "TelemetryFrame",
    "TelemetrySample",
    "TelloError",
    "ValidationError",
    "VisualEntity",
    "configure_structlog",
]
```

- [ ] **Step 15b: Write tests for redis_client and neo4j_client**

Create `packages/tello-core/tests/test_redis_client.py`:

```python
"""Tests for Redis client factory."""

from unittest.mock import AsyncMock, patch

import pytest

from tello_core.redis_client import create_redis_client, redis_health_check


def test_create_redis_client_returns_client():
    with patch("tello_core.redis_client.aioredis.from_url") as mock_from_url:
        client = create_redis_client("redis://localhost:6379")
        mock_from_url.assert_called_once_with("redis://localhost:6379", decode_responses=True)


async def test_health_check_returns_true_when_connected():
    client = AsyncMock()
    client.ping = AsyncMock(return_value=True)
    assert await redis_health_check(client) is True


async def test_health_check_returns_false_on_error():
    client = AsyncMock()
    client.ping = AsyncMock(side_effect=ConnectionError("refused"))
    assert await redis_health_check(client) is False
```

Create `packages/tello-core/tests/test_neo4j_client.py`:

```python
"""Tests for Neo4j client factory."""

from unittest.mock import MagicMock, patch

import pytest

from tello_core.neo4j_client import create_neo4j_driver


def test_create_neo4j_driver():
    with patch("tello_core.neo4j_client.GraphDatabase.driver") as mock_driver:
        driver = create_neo4j_driver("bolt://localhost:7687", "neo4j", "pw")
        mock_driver.assert_called_once_with(
            "bolt://localhost:7687",
            auth=("neo4j", "pw"),
            max_connection_pool_size=5,
            connection_acquisition_timeout=30.0,
        )


def test_create_neo4j_driver_custom_pool():
    with patch("tello_core.neo4j_client.GraphDatabase.driver") as mock_driver:
        create_neo4j_driver("bolt://localhost:7687", "neo4j", "pw", max_connection_pool_size=10)
        call_kwargs = mock_driver.call_args[1]
        assert call_kwargs["max_connection_pool_size"] == 10
```

- [ ] **Step 16: Run full tello-core test suite**

```bash
uv run --package tello-core pytest packages/tello-core/tests/ -v --tb=short
```

Expected: All 26 tests PASS.

- [ ] **Step 17: Lint and type-check**

```bash
uv run ruff check packages/tello-core/ && uv run ruff format --check packages/tello-core/
uv run ty check packages/tello-core/src/
```

Expected: No lint errors. ty may show advisory warnings (acceptable).

- [ ] **Step 18: Commit**

```bash
git add packages/tello-core/
git commit -m "feat: add tello-core shared package

Pydantic models (FlightCommand, TelemetryFrame, RoomNode, etc.),
BaseServiceConfig with from_env() factory and fail-fast validation,
TelloError exception hierarchy, Redis/Neo4j client factories,
configure_structlog() helper. 26 tests passing."
```

---

## Chunk 2: tello-mcp Service Scaffold

### Task 3: Create tello-mcp config and drone adapter

**Files:**

- Create: `services/tello-mcp/pyproject.toml`
- Create: `services/tello-mcp/src/tello_mcp/__init__.py`
- Create: `services/tello-mcp/src/tello_mcp/config.py`
- Create: `services/tello-mcp/src/tello_mcp/drone.py`
- Test: `services/tello-mcp/tests/conftest.py`
- Test: `services/tello-mcp/tests/test_config.py`
- Test: `services/tello-mcp/tests/test_drone.py`

- [ ] **Step 1: Create tello-mcp pyproject.toml**

Create `services/tello-mcp/pyproject.toml` as specified in
spec Section 6.2. Dependencies: tello-core (workspace),
fastmcp>=3.0.0, djitellopy>=2.5.0, redis>=5.0.0.
No per-service dev deps (workspace root owns those).

- [ ] **Step 2: Create conftest.py with shared fixtures**

Create `services/tello-mcp/tests/conftest.py`:

```python
"""Shared test fixtures for tello-mcp."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tello_core.config import BaseServiceConfig


@pytest.fixture()
def mock_config():
    """Test configuration for tello-mcp."""
    return BaseServiceConfig(
        neo4j_uri="bolt://localhost:7687",
        neo4j_username="neo4j",
        neo4j_password="test",
        redis_url="redis://localhost:6379",
        service_name="tello-mcp-test",
    )


@pytest.fixture()
def mock_drone():
    """Mock djitellopy.Tello instance."""
    drone = MagicMock()
    drone.connect = MagicMock()
    drone.takeoff = MagicMock()
    drone.land = MagicMock()
    drone.emergency = MagicMock()
    drone.move_forward = MagicMock()
    drone.move_back = MagicMock()
    drone.move_left = MagicMock()
    drone.move_right = MagicMock()
    drone.move_up = MagicMock()
    drone.move_down = MagicMock()
    drone.rotate_clockwise = MagicMock()
    drone.rotate_counter_clockwise = MagicMock()
    drone.flip_forward = MagicMock()
    drone.get_battery = MagicMock(return_value=85)
    drone.get_height = MagicMock(return_value=120)
    drone.get_distance_tof = MagicMock(return_value=95)
    drone.get_temperature = MagicMock(return_value=42)
    drone.get_pitch = MagicMock(return_value=1)
    drone.get_roll = MagicMock(return_value=0)
    drone.get_yaw = MagicMock(return_value=180)
    drone.get_flight_time = MagicMock(return_value=45)
    drone.get_mission_pad_id = MagicMock(return_value=-1)
    return drone


@pytest.fixture()
def mock_redis():
    """Mock async Redis client."""
    client = AsyncMock()
    client.publish = AsyncMock(return_value=1)
    client.xadd = AsyncMock(return_value="1234-0")
    client.ping = AsyncMock(return_value=True)
    return client
```

- [ ] **Step 3: Write the failing test for config**

Create `services/tello-mcp/tests/test_config.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it fails**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'tello_mcp'`

- [ ] **Step 5: Implement tello-mcp config.py**

Create `services/tello-mcp/src/tello_mcp/__init__.py` (empty) and `services/tello-mcp/src/tello_mcp/config.py`:

```python
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
    telemetry_publish_hz: int = 10
    telemetry_channel: str = "tello:telemetry"
    events_stream: str = "tello:events"

    @classmethod
    def from_env(cls, **overrides) -> Self:
        """Load tello-mcp config from environment."""
        overrides.setdefault("tello_wifi_ssid", os.environ.get("TELLO_WIFI_SSID", ""))
        return super().from_env(**overrides)
```

- [ ] **Step 6: Run test to verify it passes**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_config.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 7: Write the failing test for drone adapter**

Create `services/tello-mcp/tests/test_drone.py`:

```python
"""Tests for the DroneAdapter — djitellopy abstraction layer."""

from unittest.mock import MagicMock, patch

import pytest

from tello_mcp.drone import DroneAdapter


class TestDroneAdapter:
    def test_connect(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            mock_drone.connect.assert_called_once()

    def test_disconnect_when_connected(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            adapter.disconnect()
            mock_drone.end.assert_called_once()

    def test_is_connected_property(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            assert not adapter.is_connected
            adapter.connect()
            assert adapter.is_connected

    def test_takeoff(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.takeoff()
            mock_drone.takeoff.assert_called_once()
            assert result["status"] == "ok"

    def test_land(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.land()
            mock_drone.land.assert_called_once()
            assert result["status"] == "ok"

    def test_command_when_not_connected_returns_error(self):
        with patch("tello_mcp.drone.Tello"):
            adapter = DroneAdapter()
            result = adapter.takeoff()
            assert result["error"] == "DRONE_NOT_CONNECTED"

    def test_get_telemetry(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            frame = adapter.get_telemetry()
            assert frame.battery_pct == 85
            assert frame.height_cm == 120

    def test_move(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.move("forward", 100)
            mock_drone.move_forward.assert_called_once_with(100)
            assert result["status"] == "ok"
```

- [ ] **Step 8: Run test to verify it fails**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_drone.py -v
```

Expected: FAIL — `ImportError: cannot import name 'DroneAdapter' from 'tello_mcp.drone'`

- [ ] **Step 9: Implement drone.py**

Create `services/tello-mcp/src/tello_mcp/drone.py`:

```python
"""DroneAdapter — single point of djitellopy dependency.

All other modules interact with the drone through this adapter.
If djitellopy ever needs a patch, this is the only file to change.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from djitellopy import Tello

from tello_core.models import TelemetryFrame

logger = structlog.get_logger("tello_mcp.drone")

MOVE_METHODS = {
    "forward": "move_forward",
    "back": "move_back",
    "left": "move_left",
    "right": "move_right",
    "up": "move_up",
    "down": "move_down",
}


class DroneAdapter:
    """Abstraction layer over djitellopy.Tello.

    Provides structured return values (never raw exceptions)
    and a consistent interface for the command queue.
    """

    def __init__(self) -> None:
        self._tello = Tello()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Whether the drone connection is active."""
        return self._connected

    def connect(self) -> dict:
        """Connect to the Tello drone over WiFi."""
        try:
            self._tello.connect()
            self._connected = True
            logger.info("Drone connected, battery=%d%%", self._tello.get_battery())
            return {"status": "ok"}
        except Exception as e:
            logger.exception("Failed to connect to drone")
            return {"error": "CONNECTION_FAILED", "detail": str(e)}

    def disconnect(self) -> None:
        """Disconnect from the drone."""
        if self._connected:
            self._tello.end()
            self._connected = False
            logger.info("Drone disconnected")

    def _require_connection(self) -> dict | None:
        """Return error dict if not connected, None if OK."""
        if not self._connected:
            return {"error": "DRONE_NOT_CONNECTED", "detail": "Call connect() first"}
        return None

    def takeoff(self) -> dict:
        """Take off and hover."""
        if err := self._require_connection():
            return err
        try:
            self._tello.takeoff()
            return {"status": "ok"}
        except Exception as e:
            logger.exception("Takeoff failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}

    def land(self) -> dict:
        """Land the drone."""
        if err := self._require_connection():
            return err
        try:
            self._tello.land()
            return {"status": "ok"}
        except Exception as e:
            logger.exception("Land failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}

    def emergency(self) -> dict:
        """Emergency motor stop."""
        if err := self._require_connection():
            return err
        try:
            self._tello.emergency()
            return {"status": "ok", "warning": "Motors killed"}
        except Exception as e:
            logger.exception("Emergency stop failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}

    def move(self, direction: str, distance_cm: int) -> dict:
        """Move in a direction.

        Args:
            direction: One of forward, back, left, right, up, down.
            distance_cm: Distance in centimeters (20-500).
        """
        if err := self._require_connection():
            return err
        method_name = MOVE_METHODS.get(direction)
        if not method_name:
            return {"error": "INVALID_DIRECTION", "detail": f"Unknown direction: {direction}"}
        try:
            getattr(self._tello, method_name)(distance_cm)
            return {"status": "ok"}
        except Exception as e:
            logger.exception("Move %s failed", direction)
            return {"error": "COMMAND_FAILED", "detail": str(e)}

    def rotate(self, degrees: int) -> dict:
        """Rotate clockwise (positive) or counter-clockwise (negative)."""
        if err := self._require_connection():
            return err
        try:
            if degrees >= 0:
                self._tello.rotate_clockwise(degrees)
            else:
                self._tello.rotate_counter_clockwise(abs(degrees))
            return {"status": "ok"}
        except Exception as e:
            logger.exception("Rotate failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}

    def get_telemetry(self) -> TelemetryFrame:
        """Get current telemetry snapshot."""
        return TelemetryFrame(
            battery_pct=self._tello.get_battery(),
            height_cm=self._tello.get_height(),
            tof_cm=self._tello.get_distance_tof(),
            temp_c=float(self._tello.get_temperature()),
            pitch=float(self._tello.get_pitch()),
            roll=float(self._tello.get_roll()),
            yaw=float(self._tello.get_yaw()),
            flight_time_s=self._tello.get_flight_time(),
            timestamp=datetime.now(tz=timezone.utc),
        )

    def detect_mission_pad(self) -> dict:
        """Scan for nearest mission pad.

        Returns:
            Dict with pad_id (int) or -1 if none detected.
        """
        if err := self._require_connection():
            return err
        pad_id = self._tello.get_mission_pad_id()
        return {"pad_id": pad_id, "detected": pad_id != -1}
```

- [ ] **Step 10: Run test to verify it passes**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_drone.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 11: Commit**

```bash
git add services/tello-mcp/
git commit -m "feat: add tello-mcp config and DroneAdapter

TelloMcpConfig extends BaseServiceConfig with drone-specific fields.
DroneAdapter wraps djitellopy.Tello as the single SDK dependency point.
Structured error returns, never raw exceptions. 11 tests passing."
```

---

### Task 4: Create command queue and telemetry publisher

**Files:**

- Create: `services/tello-mcp/src/tello_mcp/queue.py`
- Create: `services/tello-mcp/src/tello_mcp/telemetry.py`
- Test: `services/tello-mcp/tests/test_queue.py`
- Test: `services/tello-mcp/tests/test_telemetry.py`

- [ ] **Step 1: Write the failing test for command queue**

Create `services/tello-mcp/tests/test_queue.py`:

```python
"""Tests for the async command queue."""

import asyncio

import pytest

from tello_mcp.queue import CommandQueue


class TestCommandQueue:
    @pytest.fixture()
    def queue(self):
        return CommandQueue()

    async def test_enqueue_and_execute(self, queue):
        called = False

        def command():
            nonlocal called
            called = True
            return {"status": "ok"}

        # Start the consumer
        consumer_task = asyncio.create_task(queue.start())
        try:
            result = await queue.enqueue(command)
            assert result == {"status": "ok"}
            assert called
        finally:
            await queue.stop()
            consumer_task.cancel()

    async def test_commands_execute_sequentially(self, queue):
        execution_order = []

        def make_command(n):
            def cmd():
                execution_order.append(n)
                return {"status": "ok", "n": n}
            return cmd

        consumer_task = asyncio.create_task(queue.start())
        try:
            results = await asyncio.gather(
                queue.enqueue(make_command(1)),
                queue.enqueue(make_command(2)),
                queue.enqueue(make_command(3)),
            )
            assert len(results) == 3
            assert execution_order == [1, 2, 3]
        finally:
            await queue.stop()
            consumer_task.cancel()

    async def test_command_exception_returns_error(self, queue):
        def failing_command():
            raise RuntimeError("hardware fault")

        consumer_task = asyncio.create_task(queue.start())
        try:
            result = await queue.enqueue(failing_command)
            assert result["error"] == "COMMAND_FAILED"
            assert "hardware fault" in result["detail"]
        finally:
            await queue.stop()
            consumer_task.cancel()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_queue.py -v
```

Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement queue.py**

Create `services/tello-mcp/src/tello_mcp/queue.py`:

```python
"""Async command queue for serializing all hardware calls.

Only one command executes at a time. Tools enqueue; a single consumer
dispatches to the drone sequentially. Prevents "takeoff while landing" conflicts.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

import structlog

logger = structlog.get_logger("tello_mcp.queue")


class CommandQueue:
    """Serializes drone commands through an asyncio.Queue."""

    def __init__(self, maxsize: int = 100) -> None:
        self._queue: asyncio.Queue[tuple[Callable, asyncio.Future]] = asyncio.Queue(
            maxsize=maxsize,
        )
        self._running = False

    async def enqueue(self, command: Callable[[], Any]) -> dict:
        """Add a command to the queue and wait for its result.

        Args:
            command: A callable (sync) that returns a result dict.

        Returns:
            The command's return value, or an error dict if it raised.
        """
        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        await self._queue.put((command, future))
        return await future

    async def start(self) -> None:
        """Start the command consumer loop."""
        self._running = True
        logger.info("Command queue consumer started")
        while self._running:
            try:
                command, future = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0,
                )
            except TimeoutError:
                continue

            try:
                result = command()
                future.set_result(result)
            except Exception as e:
                logger.exception("Command execution failed")
                future.set_result({"error": "COMMAND_FAILED", "detail": str(e)})
            finally:
                self._queue.task_done()

    async def stop(self) -> None:
        """Stop the command consumer loop."""
        self._running = False
        logger.info("Command queue consumer stopped")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_queue.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 5: Write the failing test for telemetry publisher**

Create `services/tello-mcp/tests/test_telemetry.py`:

```python
"""Tests for the telemetry publisher."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tello_core.models import TelemetryFrame
from tello_mcp.telemetry import TelemetryPublisher


@pytest.fixture()
def sample_frame():
    return TelemetryFrame(
        battery_pct=85,
        height_cm=120,
        tof_cm=95,
        temp_c=42.0,
        pitch=1.0,
        roll=0.0,
        yaw=180.0,
        flight_time_s=45,
        timestamp=datetime(2026, 3, 12, 10, 0, 0, tzinfo=timezone.utc),
    )


class TestTelemetryPublisher:
    async def test_publish_frame_to_pubsub(self, mock_redis, sample_frame):
        publisher = TelemetryPublisher(
            redis_client=mock_redis,
            channel="tello:telemetry",
            stream="tello:events",
        )
        await publisher.publish_frame(sample_frame)
        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == "tello:telemetry"

    async def test_publish_frame_to_stream(self, mock_redis, sample_frame):
        publisher = TelemetryPublisher(
            redis_client=mock_redis,
            channel="tello:telemetry",
            stream="tello:events",
        )
        await publisher.publish_frame(sample_frame)
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "tello:events"

    async def test_publish_event(self, mock_redis):
        publisher = TelemetryPublisher(
            redis_client=mock_redis,
            channel="tello:telemetry",
            stream="tello:events",
        )
        await publisher.publish_event("takeoff", {"height_cm": 50})
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        fields = call_args[0][1]
        assert fields["event_type"] == "takeoff"
```

- [ ] **Step 6: Run test to verify it fails**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_telemetry.py -v
```

Expected: FAIL — `ImportError`

- [ ] **Step 7: Implement telemetry.py**

Create `services/tello-mcp/src/tello_mcp/telemetry.py`:

```python
"""Telemetry publisher — Redis pub/sub and Streams.

Publishes TelemetryFrame to pub/sub at ~10Hz for real-time consumers.
Appends flight events to a Redis Stream for durable, ordered replay.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    import redis.asyncio as aioredis

    from tello_core.models import TelemetryFrame

logger = structlog.get_logger("tello_mcp.telemetry")


class TelemetryPublisher:
    """Publishes drone telemetry to Redis."""

    def __init__(
        self,
        redis_client: aioredis.Redis,
        channel: str = "tello:telemetry",
        stream: str = "tello:events",
    ) -> None:
        self._redis = redis_client
        self._channel = channel
        self._stream = stream

    async def publish_frame(self, frame: TelemetryFrame) -> None:
        """Publish a telemetry frame to pub/sub and append to stream.

        Args:
            frame: Current telemetry snapshot.
        """
        data = frame.model_dump_json()
        await self._redis.publish(self._channel, data)
        await self._redis.xadd(
            self._stream,
            {"event_type": "telemetry", "data": data},
        )

    async def publish_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish a flight event to the Redis Stream.

        Args:
            event_type: Event type (e.g., "takeoff", "land", "move").
            data: Event payload.
        """
        fields = {"event_type": event_type, **{k: str(v) for k, v in data.items()}}
        await self._redis.xadd(self._stream, fields)
        logger.info("Published event %s", event_type)
```

- [ ] **Step 8: Run test to verify it passes**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_telemetry.py -v
```

Expected: All 3 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/queue.py services/tello-mcp/src/tello_mcp/telemetry.py services/tello-mcp/tests/test_queue.py services/tello-mcp/tests/test_telemetry.py
git commit -m "feat: add command queue and telemetry publisher

CommandQueue serializes all hardware calls via asyncio.Queue.
TelemetryPublisher sends frames to Redis pub/sub + Streams.
6 tests passing."
```

---

### Task 5: Create MCP tools and server entry point

**Files:**

- Create: `services/tello-mcp/src/tello_mcp/tools/__init__.py`
- Create: `services/tello-mcp/src/tello_mcp/tools/flight.py`
- Create: `services/tello-mcp/src/tello_mcp/tools/sensors.py`
- Create: `services/tello-mcp/src/tello_mcp/tools/expansion.py`
- Create: `services/tello-mcp/src/tello_mcp/server.py`
- Test: `services/tello-mcp/tests/test_tools/test_flight.py`
- Test: `services/tello-mcp/tests/test_tools/test_sensors.py`
- Test: `services/tello-mcp/tests/test_tools/test_expansion.py`

- [ ] **Step 1: Write the failing test for flight tools**

Create `services/tello-mcp/tests/test_tools/__init__.py` (empty) and `services/tello-mcp/tests/test_tools/test_flight.py`:

```python
"""Tests for flight control MCP tools."""

from unittest.mock import MagicMock

import pytest

from tello_mcp.tools.flight import register


class TestFlightTools:
    @pytest.fixture(autouse=True)
    def setup_mcp(self):
        """Create a mock FastMCP server and register tools."""
        self.mcp = MagicMock()
        self.registered_tools = {}

        def mock_tool(*args, **kwargs):
            """Capture tool registrations."""
            if args and callable(args[0]):
                # Direct @mcp.tool decorator
                fn = args[0]
                self.registered_tools[fn.__name__] = fn
                return fn

            def decorator(fn):
                self.registered_tools[fn.__name__] = fn
                return fn
            return decorator

        self.mcp.tool = mock_tool
        register(self.mcp)

    def test_takeoff_registered(self):
        assert "takeoff" in self.registered_tools

    def test_land_registered(self):
        assert "land" in self.registered_tools

    def test_emergency_stop_registered(self):
        assert "emergency_stop" in self.registered_tools

    def test_move_registered(self):
        assert "move" in self.registered_tools

    def test_rotate_registered(self):
        assert "rotate" in self.registered_tools
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_tools/test_flight.py -v
```

Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement flight.py, sensors.py, expansion.py**

Create `services/tello-mcp/src/tello_mcp/tools/__init__.py` (empty).

Create `services/tello-mcp/src/tello_mcp/tools/flight.py`:

```python
"""Flight control MCP tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register flight control tools on the MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def takeoff() -> dict:
        """Take off and hover at ~50cm."""
        drone = mcp.state["drone"]
        queue = mcp.state["queue"]
        return await queue.enqueue(drone.takeoff)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def land() -> dict:
        """Land the drone safely."""
        drone = mcp.state["drone"]
        queue = mcp.state["queue"]
        return await queue.enqueue(drone.land)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    async def emergency_stop() -> dict:
        """Kill motors immediately. DANGER: drone will fall."""
        drone = mcp.state["drone"]
        queue = mcp.state["queue"]
        return await queue.enqueue(drone.emergency)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def move(direction: str, distance_cm: int) -> dict:
        """Move the drone in a direction.

        Args:
            direction: One of forward, back, left, right, up, down.
            distance_cm: Distance in centimeters (20-500).
        """
        drone = mcp.state["drone"]
        queue = mcp.state["queue"]
        return await queue.enqueue(lambda: drone.move(direction, distance_cm))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def rotate(degrees: int) -> dict:
        """Rotate the drone. Positive = clockwise, negative = counter-clockwise.

        Args:
            degrees: Rotation angle (-360 to 360).
        """
        drone = mcp.state["drone"]
        queue = mcp.state["queue"]
        return await queue.enqueue(lambda: drone.rotate(degrees))
```

Create `services/tello-mcp/src/tello_mcp/tools/sensors.py`:

```python
"""Sensor and state MCP tools (read-only)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register sensor tools on the MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_telemetry() -> dict:
        """Get current telemetry: battery, height, ToF, attitude, temp, flight time."""
        drone = mcp.state["drone"]
        frame = drone.get_telemetry()
        return frame.model_dump()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_tof_distance() -> dict:
        """Get Time-of-Flight distance sensor reading in cm."""
        drone = mcp.state["drone"]
        frame = drone.get_telemetry()
        return {"tof_cm": frame.tof_cm}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def detect_mission_pad() -> dict:
        """Scan for the nearest mission pad. Returns pad ID or -1 if none detected."""
        drone = mcp.state["drone"]
        return drone.detect_mission_pad()
```

Create `services/tello-mcp/src/tello_mcp/tools/expansion.py`:

```python
"""Expansion board MCP tools (LED, matrix display, ESP32)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register expansion board tools on the MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def set_led_color(r: int, g: int, b: int) -> dict:
        """Set the LED color (RGB values 0-255)."""
        drone = mcp.state["drone"]
        queue = mcp.state["queue"]
        return await queue.enqueue(lambda: drone.set_led(r, g, b))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def display_matrix_text(text: str) -> dict:
        """Display scrolling text on the 8x8 LED matrix.

        Args:
            text: Text to display (will scroll if longer than 1 character).
        """
        drone = mcp.state["drone"]
        queue = mcp.state["queue"]
        return await queue.enqueue(lambda: drone.display_text(text))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_tools/test_flight.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Write the failing test for sensor tools**

Create `services/tello-mcp/tests/test_tools/test_sensors.py`:

```python
"""Tests for sensor MCP tools."""

from unittest.mock import MagicMock

import pytest

from tello_mcp.tools.sensors import register


class TestSensorTools:
    @pytest.fixture(autouse=True)
    def setup_mcp(self):
        self.mcp = MagicMock()
        self.registered_tools = {}

        def mock_tool(*args, **kwargs):
            if args and callable(args[0]):
                fn = args[0]
                self.registered_tools[fn.__name__] = fn
                return fn

            def decorator(fn):
                self.registered_tools[fn.__name__] = fn
                return fn
            return decorator

        self.mcp.tool = mock_tool
        register(self.mcp)

    def test_get_telemetry_registered(self):
        assert "get_telemetry" in self.registered_tools

    def test_get_tof_distance_registered(self):
        assert "get_tof_distance" in self.registered_tools

    def test_detect_mission_pad_registered(self):
        assert "detect_mission_pad" in self.registered_tools
```

- [ ] **Step 6: Run sensor test to verify it fails**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_tools/test_sensors.py -v
```

Expected: FAIL — `ImportError: cannot import name 'register' from 'tello_mcp.tools.sensors'`

(sensors.py was already created in Step 3 — this step confirms it passes)

- [ ] **Step 7: Write the failing test for expansion tools**

Create `services/tello-mcp/tests/test_tools/test_expansion.py`:

```python
"""Tests for expansion board MCP tools."""

from unittest.mock import MagicMock

import pytest

from tello_mcp.tools.expansion import register


class TestExpansionTools:
    @pytest.fixture(autouse=True)
    def setup_mcp(self):
        self.mcp = MagicMock()
        self.registered_tools = {}

        def mock_tool(*args, **kwargs):
            if args and callable(args[0]):
                fn = args[0]
                self.registered_tools[fn.__name__] = fn
                return fn

            def decorator(fn):
                self.registered_tools[fn.__name__] = fn
                return fn
            return decorator

        self.mcp.tool = mock_tool
        register(self.mcp)

    def test_set_led_color_registered(self):
        assert "set_led_color" in self.registered_tools

    def test_display_matrix_text_registered(self):
        assert "display_matrix_text" in self.registered_tools
```

- [ ] **Step 8: Run all tool tests**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_tools/ -v
```

Expected: All 10 tests PASS (5 flight + 3 sensors + 2 expansion).

- [ ] **Step 9: Implement server.py**

Create `services/tello-mcp/src/tello_mcp/server.py`:

```python
"""tello-mcp — FastMCP hardware abstraction server for DJI Tello TT.

Run:
    stdio:            python -m tello_mcp.server
    streamable-http:  python -m tello_mcp.server --transport streamable-http --port 8100
"""

from __future__ import annotations

import asyncio
import sys

from fastmcp import FastMCP

from tello_core.config import configure_structlog
from tello_core.redis_client import create_redis_client

from tello_mcp.config import TelloMcpConfig
from tello_mcp.drone import DroneAdapter
from tello_mcp.queue import CommandQueue
from tello_mcp.telemetry import TelemetryPublisher
from tello_mcp.tools import expansion, flight, sensors

mcp = FastMCP(
    name="tello-mcp",
    instructions=(
        "Hardware abstraction for DJI Tello TT drone. "
        "All flight commands are serialized through an async queue. "
        "Sensor tools are read-only and return current telemetry."
    ),
)

# Register tool modules
flight.register(mcp)
sensors.register(mcp)
expansion.register(mcp)


def main() -> None:
    """Entry point for tello-mcp server."""
    config = TelloMcpConfig.from_env(service_name="tello-mcp")
    configure_structlog(config.service_name)

    # Initialize components and store in server state
    mcp.state["drone"] = DroneAdapter()
    mcp.state["queue"] = CommandQueue()
    mcp.state["redis"] = create_redis_client(config.redis_url)
    mcp.state["telemetry"] = TelemetryPublisher(
        redis_client=mcp.state["redis"],
        channel=config.telemetry_channel,
        stream=config.events_stream,
    )
    mcp.state["config"] = config

    # Parse transport from CLI args
    import argparse

    parser = argparse.ArgumentParser(description="tello-mcp server")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http", "sse"])
    parser.add_argument("--port", type=int, default=8100)
    parsed = parser.parse_args()
    transport = parsed.transport
    port = parsed.port

    mcp.run(transport=transport, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
```

Create `services/tello-mcp/src/tello_mcp/__main__.py`:

```python
"""Allow running as: python -m tello_mcp.server."""

from tello_mcp.server import main

main()
```

- [ ] **Step 7: Run full tello-mcp test suite**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/ -v --tb=short
```

Expected: All tests PASS (config: 3, drone: 8, queue: 3, telemetry: 3, tools: ~10).

- [ ] **Step 8: Lint and type-check**

```bash
uv run ruff check services/tello-mcp/ && uv run ruff format --check services/tello-mcp/
uv run ty check services/tello-mcp/src/
```

- [ ] **Step 9: Commit**

```bash
git add services/tello-mcp/
git commit -m "feat: add MCP tools and server entry point

Flight, sensor, and expansion board tools registered via register(mcp) pattern.
server.py supports stdio and streamable-http transports.
Full test suite passing."
```

---

## Chunk 3: Claude Code Configuration & Dev Environment

### Task 6: Create Claude Code config, VS Code, CI, and docs

**Files:**

- Create: `CLAUDE.md`
- Create: `MEMORY.md`
- Create: `.mcp.json`
- Create: `.claude/settings.json`
- Create: `.claude/hooks/validate-workspace.sh`
- Create: `.claude/commands/implement.md`
- Create: `.claude/commands/plan.md`
- Create: `.claude/commands/review.md`
- Create: `.claude/commands/test.md`
- Create: `.claude/skills/drone-patterns/SKILL.md`
- Create: `.claude/skills/mcp-tool-patterns/SKILL.md`
- Create: `.claude/skills/pr-workflow/skill.md`
- Create: `.vscode/settings.json`
- Create: `.vscode/extensions.json`
- Create: `.vscode/launch.json`
- Create: `.github/workflows/ci.yml`
- Create: `docs/architecture.md`

- [ ] **Step 1: Create CLAUDE.md**

Create root `CLAUDE.md` with all sections from spec
Section 8.1: Project Layout, Commands, Conventions, Logging,
Error Handling, Testing, Shared Models. Include exact commands
for workspace operations.

- [ ] **Step 2: Create MEMORY.md**

Create root `MEMORY.md`:

```markdown
# Working State

## Current Phase
- Phase 1: tello-mcp (in progress)
- All 5 services scaffolded
- tello-core: complete (models, config, exceptions, factories)
- tello-mcp: complete (scaffold — tools, drone adapter, queue, telemetry, server)

## Active Branch
- main (initial scaffold)

## Next Steps
- Implementation plan for tello-mcp Phase 1 features
- Then: tello-telemetry (Phase 2)
```

- [ ] **Step 3: Create .mcp.json**

Create `.mcp.json` with contents from spec Section 8.3:
neo4j (direct command), memory (npx), tello-mcp (uv run).

- [ ] **Step 4: Create .claude/ directory**

Create `.claude/settings.json` from spec Section 8.4.

Create `.claude/hooks/validate-workspace.sh` — a script that
warns when Bash commands target wrong working directory or
attempt to modify files in other services.

Create `.claude/commands/implement.md`, `plan.md`, `review.md`,
`test.md` — adapted from reference implementation for
workspace-aware paths.
Reference: `~/Projects/requirements-graphrag-api/.claude/commands/`.

Create `.claude/skills/drone-patterns/SKILL.md` — djitellopy
conventions, DroneAdapter pattern, command queue usage,
telemetry frame handling, mission pad detection.

Create `.claude/skills/mcp-tool-patterns/SKILL.md` — FastMCP
tool registration, ToolAnnotations (readOnlyHint,
destructiveHint), structured error returns, Context usage
for logging/progress.

Create `.claude/skills/pr-workflow/skill.md` — adapted from
reference implementation.
Reference: `~/Projects/requirements-graphrag-api/.claude/skills/pr-workflow/skill.md`.

- [ ] **Step 5: Create .vscode/ configuration**

Create `.vscode/settings.json` from spec Section 9.1.
Key adaptations: workspace PYTHONPATH, Ruff config pointing
to root pyproject.toml, `typeCheckingMode: "off"` (ty handles
it), pytest workspace-wide.

Create `.vscode/extensions.json` from spec Section 9.2.

Create `.vscode/launch.json` from spec Section 9.3.
Four configs: tello-mcp (stdio), tello-mcp (HTTP),
Test: Current File, Test: tello-mcp.

- [ ] **Step 6: Create GitHub Actions CI**

Create `.github/workflows/ci.yml` from spec Section 10.
Matrix strategy: tello-core + tello-mcp. Lint job, test job,
type-check job (advisory).

- [ ] **Step 7: Create docs/architecture.md**

Create `docs/architecture.md` — platform overview from
plan v2.0. Service roles, Neo4j schema domains
(room/scene/session/memory graphs), Redis capabilities,
recommended build order.

- [ ] **Step 8: Install pre-commit hooks**

```bash
uv run pre-commit install
```

- [ ] **Step 9: Run full workspace verification**

```bash
uv run ruff check . && uv run ruff format --check .
uv run --package tello-core pytest packages/tello-core/tests/ -v --tb=short
uv run --package tello-mcp pytest services/tello-mcp/tests/ -v --tb=short
uv run ty check packages/ services/
```

Expected: All lint passes, all tests pass, ty advisory only.

- [ ] **Step 10: Commit**

```bash
git add CLAUDE.md MEMORY.md .mcp.json .claude/ .vscode/ .github/ docs/
git commit -m "feat: add Claude Code config, VS Code workspace, CI, and docs

CLAUDE.md with workspace conventions, .mcp.json (neo4j + memory + tello-mcp),
.claude/ skills (drone-patterns, mcp-tool-patterns, pr-workflow) and commands,
VS Code settings (Ruff, ty, pytest, per-service debug), GitHub Actions CI
(lint + test matrix + advisory type-check), docs/architecture.md."
```

- [ ] **Step 11: Verify Docker infrastructure starts**

```bash
docker compose up -d
docker compose ps
```

Expected: neo4j (healthy) and redis (healthy) containers running.

```bash
docker compose down
```

- [ ] **Step 12: Final commit message for the complete scaffold**

```bash
git log --oneline
```

Expected: 4-5 commits forming the complete scaffold:

1. `feat: initialize uv workspace monorepo with infrastructure config`
2. `feat: add tello-core shared package`
3. `feat: add tello-mcp config and DroneAdapter`
4. `feat: add command queue and telemetry publisher`
5. `feat: add MCP tools and server entry point`
6. `feat: add Claude Code config, VS Code workspace, CI, and docs`
