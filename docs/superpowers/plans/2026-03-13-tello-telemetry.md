# Tello Telemetry Service Implementation Plan

> **For agentic workers:** REQUIRED: Use
> superpowers:subagent-driven-development (if subagents available)
> or superpowers:executing-plans to implement this plan.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build tello-telemetry — a FastMCP service that consumes
the Redis Stream written by tello-mcp, detects anomalies via
config-driven thresholds, persists flight session data to Neo4j,
and exposes template query tools for Claude to interrogate
session history.

**Architecture:** Monolithic FastMCP service with four internal
components: StreamConsumer (XREADGROUP loop), AnomalyDetector
(stateless threshold checks), SessionRepository (sync Neo4j
driver via asyncio.to\_thread), and query tools (read-only MCP
tools). Consumer runs as a background asyncio task inside the
FastMCP lifespan. Shared models from tello-core — no model
duplication.

**Tech Stack:** Python 3.13, FastMCP 3.x, redis-py (async),
neo4j 5.x (sync driver), Pydantic 2.x (via tello-core),
structlog, pytest + pytest-asyncio

**Spec:**
`docs/superpowers/specs/2026-03-12-tello-telemetry-design.md`

---

## File Map

### services/tello-telemetry/ (create unless noted)

- `pyproject.toml` — update existing placeholder with full deps
- `src/tello_telemetry/__init__.py` — package init
- `src/tello_telemetry/config.py` — TelloTelemetryConfig
- `src/tello_telemetry/detector.py` — AnomalyDetector
- `src/tello_telemetry/session_repo.py` — SessionRepository
- `src/tello_telemetry/consumer.py` — StreamConsumer
- `src/tello_telemetry/server.py` — FastMCP server + lifespan
- `src/tello_telemetry/__main__.py` — CLI entry point
- `src/tello_telemetry/tools/__init__.py` — tools package init
- `src/tello_telemetry/tools/queries.py` — query MCP tools
- `tests/__init__.py` — test package init
- `tests/conftest.py` — shared fixtures
- `tests/test_config.py` — config tests
- `tests/test_detector.py` — anomaly detector tests
- `tests/test_session_repo.py` — session repository tests
- `tests/test_consumer.py` — stream consumer tests
- `tests/test_tools/__init__.py` — tools test package init
- `tests/test_tools/test_queries.py` — query tools tests

### Bundled changes (modify existing files)

- `packages/tello-core/src/tello_core/models.py` — add
  `room_id: str = "unknown"` default on FlightSession
- `services/tello-mcp/src/tello_mcp/config.py` — add
  `tello_host` field
- `services/tello-mcp/src/tello_mcp/tools/flight.py` — add
  `room_id` param to takeoff, publish event
- `services/tello-mcp/tests/test_config.py` — test tello\_host
- `services/tello-mcp/tests/test_tools/test_flight.py` — test
  room\_id
- `scripts/find_drone.py` — auto-update .env with discovered IP
- `.env.example` — add TELLO\_HOST
- `.github/workflows/ci.yml` — add tello-telemetry to test matrix
- `pyproject.toml` (root) — add coverage source + pythonpath

---

## Chunk 1: Foundation — Config, Detector, Package Setup

### Task 1: Package Setup and Config

**Files:**

- Update: `services/tello-telemetry/pyproject.toml`
- Create: `services/tello-telemetry/src/tello_telemetry/__init__.py`
- Create: `services/tello-telemetry/src/tello_telemetry/config.py`
- Create: `services/tello-telemetry/tests/__init__.py`
- Create: `services/tello-telemetry/tests/conftest.py`
- Create: `services/tello-telemetry/tests/test_config.py`

#### Step-by-step

- [ ] **Step 1: Update pyproject.toml with full dependencies**

Update the existing placeholder `services/tello-telemetry/pyproject.toml`:

```toml
[project]
name = "tello-telemetry"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "tello-core",
    "fastmcp>=3.0.0",
    "redis>=5.0.0",
    "neo4j>=5.15.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tello_telemetry"]

[tool.uv.sources]
tello-core = { workspace = true }
```

- [ ] **Step 2: Create package init**

Create `services/tello-telemetry/src/tello_telemetry/__init__.py`:

```python
"""tello-telemetry: flight session intelligence service."""
```

- [ ] **Step 3: Write the failing config test**

Create `services/tello-telemetry/tests/__init__.py` (empty).

Create `services/tello-telemetry/tests/conftest.py`:

```python
"""Shared test fixtures for tello-telemetry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tello_telemetry.config import TelloTelemetryConfig


@pytest.fixture()
def mock_config():
    """Test configuration with defaults."""
    return TelloTelemetryConfig(
        neo4j_uri="bolt://localhost:7687",
        neo4j_username="neo4j",
        neo4j_password="test",
        redis_url="redis://localhost:6379",
        service_name="tello-telemetry-test",
    )


@pytest.fixture()
def mock_redis():
    """Mock async Redis client."""
    client = AsyncMock()
    client.xreadgroup = AsyncMock(return_value=[])
    client.xack = AsyncMock(return_value=1)
    client.xgroup_create = AsyncMock()
    client.aclose = AsyncMock()
    return client


@pytest.fixture()
def mock_neo4j_driver():
    """Mock Neo4j driver with session support."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(
        return_value=session,
    )
    driver.session.return_value.__exit__ = MagicMock(
        return_value=False,
    )
    session.run = MagicMock()
    return driver
```

Create `services/tello-telemetry/tests/test_config.py`:

```python
"""Tests for tello-telemetry configuration."""

from __future__ import annotations

import pytest

from tello_core.exceptions import ConfigurationError
from tello_telemetry.config import TelloTelemetryConfig


class TestTelloTelemetryConfig:
    def test_defaults(self, mock_config):
        assert mock_config.battery_warning_pct == 20
        assert mock_config.battery_critical_pct == 10
        assert mock_config.temp_warning_c == 85.0
        assert mock_config.temp_critical_c == 90.0
        assert mock_config.altitude_max_cm == 300
        assert mock_config.neo4j_sample_interval_s == 5.0
        assert mock_config.stream_name == "tello:events"
        assert mock_config.consumer_group == "telemetry-service"
        assert mock_config.consumer_name == "worker-1"
        assert mock_config.batch_size == 10
        assert mock_config.block_ms == 2000

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
        monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "pw")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

        config = TelloTelemetryConfig.from_env(
            service_name="tello-telemetry",
        )
        assert config.service_name == "tello-telemetry"
        assert config.battery_warning_pct == 20

    def test_custom_thresholds(self):
        config = TelloTelemetryConfig(
            neo4j_uri="bolt://localhost:7687",
            neo4j_username="neo4j",
            neo4j_password="test",
            redis_url="redis://localhost:6379",
            service_name="test",
            battery_warning_pct=30,
            temp_critical_c=95.0,
        )
        assert config.battery_warning_pct == 30
        assert config.temp_critical_c == 95.0

    def test_inherits_base_validation(self):
        with pytest.raises(ConfigurationError, match="Neo4j URI"):
            TelloTelemetryConfig(
                neo4j_uri="http://bad",
                neo4j_username="neo4j",
                neo4j_password="pw",
                redis_url="redis://localhost:6379",
                service_name="test",
            )
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tello_telemetry.config'`

- [ ] **Step 5: Write the config implementation**

Create `services/tello-telemetry/src/tello_telemetry/config.py`:

```python
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
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_config.py -v`
Expected: 4 passed

- [ ] **Step 7: Run uv sync to resolve new dependencies**

Run: `uv sync`
Expected: Resolves and installs fastmcp, neo4j deps for
tello-telemetry

- [ ] **Step 8: Lint check**

Run: `uv run ruff check services/tello-telemetry/ --fix && uv run ruff format services/tello-telemetry/`
Expected: Clean

- [ ] **Step 9: Commit**

```bash
git add services/tello-telemetry/
git commit -m "feat(telemetry): add package setup and config

TelloTelemetryConfig extends BaseServiceConfig with anomaly
thresholds, sampling interval, and Redis Stream consumer
settings. 4 tests passing."
```

---

### Task 2: Anomaly Detector (Pure Core)

**Files:**

- Create: `services/tello-telemetry/src/tello_telemetry/detector.py`
- Create: `services/tello-telemetry/tests/test_detector.py`

The AnomalyDetector is a **stateless, pure function** — it takes
a TelemetryFrame and config, returns a list of Anomaly objects.
No I/O, no mocks needed. This is the "Pure Core" in the Pure
Core / Imperative Shell pattern.

#### Step-by-step

- [ ] **Step 1: Write the failing detector tests**

Create `services/tello-telemetry/tests/test_detector.py`:

```python
"""Tests for anomaly detection.

AnomalyDetector is a pure function — no mocks needed.
Input: TelemetryFrame + config thresholds → Output: list[Anomaly]
"""

from __future__ import annotations

from datetime import UTC, datetime

from tello_core.models import Anomaly, TelemetryFrame
from tello_telemetry.config import TelloTelemetryConfig
from tello_telemetry.detector import AnomalyDetector


def _make_frame(**overrides) -> TelemetryFrame:
    """Create a TelemetryFrame with sensible defaults."""
    defaults = {
        "battery_pct": 80,
        "height_cm": 100,
        "tof_cm": 95,
        "temp_c": 40.0,
        "pitch": 0.0,
        "roll": 0.0,
        "yaw": 0.0,
        "flight_time_s": 30,
        "timestamp": datetime(2026, 3, 12, 10, 0, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    return TelemetryFrame(**defaults)


def _make_config(**overrides) -> TelloTelemetryConfig:
    """Create a TelloTelemetryConfig with test defaults."""
    defaults = {
        "neo4j_uri": "bolt://localhost:7687",
        "neo4j_username": "neo4j",
        "neo4j_password": "test",
        "redis_url": "redis://localhost:6379",
        "service_name": "test",
    }
    defaults.update(overrides)
    return TelloTelemetryConfig(**defaults)


class TestAnomalyDetector:
    def setup_method(self):
        self.config = _make_config()
        self.detector = AnomalyDetector(self.config)

    # ── Nominal (no anomalies) ──────────────────────────

    def test_nominal_frame_returns_empty(self):
        frame = _make_frame()
        assert self.detector.check(frame) == []

    # ── Battery ─────────────────────────────────────────

    def test_battery_warning(self):
        frame = _make_frame(battery_pct=18)
        anomalies = self.detector.check(frame)
        assert len(anomalies) == 1
        assert anomalies[0].type == "battery_low"
        assert anomalies[0].severity == "warning"
        assert "18%" in anomalies[0].detail

    def test_battery_critical(self):
        frame = _make_frame(battery_pct=8)
        anomalies = self.detector.check(frame)
        assert len(anomalies) == 1
        assert anomalies[0].type == "battery_low"
        assert anomalies[0].severity == "critical"

    def test_battery_at_exact_warning_threshold_is_nominal(self):
        frame = _make_frame(battery_pct=20)
        assert self.detector.check(frame) == []

    def test_battery_at_exact_critical_threshold_is_warning(self):
        """At exactly critical threshold (10%), it's still
        warning level (< 20 but not < 10)."""
        frame = _make_frame(battery_pct=10)
        anomalies = self.detector.check(frame)
        assert len(anomalies) == 1
        assert anomalies[0].severity == "warning"

    # ── Temperature ─────────────────────────────────────

    def test_temp_warning(self):
        frame = _make_frame(temp_c=87.0)
        anomalies = self.detector.check(frame)
        assert len(anomalies) == 1
        assert anomalies[0].type == "high_temperature"
        assert anomalies[0].severity == "warning"

    def test_temp_critical(self):
        frame = _make_frame(temp_c=92.0)
        anomalies = self.detector.check(frame)
        assert len(anomalies) == 1
        assert anomalies[0].type == "high_temperature"
        assert anomalies[0].severity == "critical"

    def test_temp_at_exact_warning_threshold_is_nominal(self):
        frame = _make_frame(temp_c=85.0)
        assert self.detector.check(frame) == []

    # ── Altitude ────────────────────────────────────────

    def test_altitude_critical(self):
        frame = _make_frame(height_cm=350)
        anomalies = self.detector.check(frame)
        assert len(anomalies) == 1
        assert anomalies[0].type == "altitude_exceeded"
        assert anomalies[0].severity == "critical"

    def test_altitude_at_exact_max_is_nominal(self):
        frame = _make_frame(height_cm=300)
        assert self.detector.check(frame) == []

    # ── Multiple simultaneous anomalies ─────────────────

    def test_multiple_anomalies(self):
        frame = _make_frame(battery_pct=5, temp_c=92.0, height_cm=400)
        anomalies = self.detector.check(frame)
        types = {a.type for a in anomalies}
        assert types == {"battery_low", "high_temperature", "altitude_exceeded"}

    # ── Custom thresholds ───────────────────────────────

    def test_custom_battery_threshold(self):
        config = _make_config(battery_warning_pct=30)
        detector = AnomalyDetector(config)
        frame = _make_frame(battery_pct=25)
        anomalies = detector.check(frame)
        assert len(anomalies) == 1
        assert anomalies[0].severity == "warning"

    # ── Timestamp propagation ───────────────────────────

    def test_anomaly_uses_frame_timestamp(self):
        ts = datetime(2026, 3, 12, 15, 30, 0, tzinfo=UTC)
        frame = _make_frame(battery_pct=5, timestamp=ts)
        anomalies = self.detector.check(frame)
        assert anomalies[0].timestamp == ts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_detector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tello_telemetry.detector'`

- [ ] **Step 3: Write the detector implementation**

Create `services/tello-telemetry/src/tello_telemetry/detector.py`:

```python
"""Anomaly detection — config-driven threshold checks.

The AnomalyDetector is stateless: a pure function from
(TelemetryFrame, config) → list[Anomaly]. No I/O, no side
effects. This is the "Pure Core" in the Pure Core / Imperative
Shell architecture. The consumer (imperative shell) handles
I/O; the detector (pure core) handles logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tello_core.models import Anomaly

if TYPE_CHECKING:
    from tello_core.models import TelemetryFrame
    from tello_telemetry.config import TelloTelemetryConfig


class AnomalyDetector:
    """Runs threshold checks against telemetry frames.

    Args:
        config: Service config containing threshold values.
    """

    def __init__(self, config: TelloTelemetryConfig) -> None:
        self._config = config

    def check(self, frame: TelemetryFrame) -> list[Anomaly]:
        """Run all threshold checks on a telemetry frame.

        Returns an empty list if all values are nominal.

        Args:
            frame: Current telemetry snapshot.
        """
        anomalies: list[Anomaly] = []
        self._check_battery(frame, anomalies)
        self._check_temperature(frame, anomalies)
        self._check_altitude(frame, anomalies)
        return anomalies

    def _check_battery(
        self,
        frame: TelemetryFrame,
        anomalies: list[Anomaly],
    ) -> None:
        if frame.battery_pct < self._config.battery_critical_pct:
            anomalies.append(
                Anomaly(
                    type="battery_low",
                    severity="critical",
                    detail=f"Battery at {frame.battery_pct}%",
                    timestamp=frame.timestamp,
                ),
            )
        elif frame.battery_pct < self._config.battery_warning_pct:
            anomalies.append(
                Anomaly(
                    type="battery_low",
                    severity="warning",
                    detail=f"Battery at {frame.battery_pct}%",
                    timestamp=frame.timestamp,
                ),
            )

    def _check_temperature(
        self,
        frame: TelemetryFrame,
        anomalies: list[Anomaly],
    ) -> None:
        if frame.temp_c > self._config.temp_critical_c:
            anomalies.append(
                Anomaly(
                    type="high_temperature",
                    severity="critical",
                    detail=f"Temperature at {frame.temp_c}°C",
                    timestamp=frame.timestamp,
                ),
            )
        elif frame.temp_c > self._config.temp_warning_c:
            anomalies.append(
                Anomaly(
                    type="high_temperature",
                    severity="warning",
                    detail=f"Temperature at {frame.temp_c}°C",
                    timestamp=frame.timestamp,
                ),
            )

    def _check_altitude(
        self,
        frame: TelemetryFrame,
        anomalies: list[Anomaly],
    ) -> None:
        if frame.height_cm > self._config.altitude_max_cm:
            anomalies.append(
                Anomaly(
                    type="altitude_exceeded",
                    severity="critical",
                    detail=f"Altitude {frame.height_cm}cm exceeds max {self._config.altitude_max_cm}cm",
                    timestamp=frame.timestamp,
                ),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_detector.py -v`
Expected: 14 passed

- [ ] **Step 5: Lint check**

Run: `uv run ruff check services/tello-telemetry/ --fix && uv run ruff format services/tello-telemetry/`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
git add services/tello-telemetry/src/tello_telemetry/detector.py \
      services/tello-telemetry/tests/test_detector.py
git commit -m "feat(telemetry): add anomaly detector

Stateless threshold checks for battery, temperature, altitude.
Pure Core pattern — no I/O, no mocks needed. 14 tests."
```

---

## Chunk 2: Session Repository (Neo4j)

### Task 3: Session Repository

**Files:**

- Create: `services/tello-telemetry/src/tello_telemetry/session_repo.py`
- Create: `services/tello-telemetry/tests/test_session_repo.py`

The SessionRepository wraps the sync Neo4j driver. Each method
runs a Cypher query inside `driver.session()`. The consumer
calls these methods via `asyncio.to_thread()` — the repo itself
is synchronous and simple.

#### Step-by-step

- [ ] **Step 1: Write the failing session repo tests**

Create `services/tello-telemetry/tests/test_session_repo.py`:

```python
"""Tests for Neo4j session repository.

All tests mock the Neo4j driver — no real database connections.
Tests verify that correct Cypher queries are executed with the
right parameters.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, call

import pytest

from tello_core.models import Anomaly, FlightSession, TelemetrySample
from tello_telemetry.session_repo import SessionRepository


@pytest.fixture()
def mock_session():
    """Mock Neo4j session with run() method."""
    session = MagicMock()
    session.run = MagicMock()
    return session


@pytest.fixture()
def mock_driver(mock_session):
    """Mock Neo4j driver that yields mock_session."""
    driver = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(
        return_value=mock_session,
    )
    driver.session.return_value.__exit__ = MagicMock(
        return_value=False,
    )
    return driver


@pytest.fixture()
def repo(mock_driver):
    return SessionRepository(mock_driver)


class TestCreateSession:
    def test_creates_session_node(self, repo, mock_session):
        session = FlightSession(
            id="sess-1",
            start_time=datetime(2026, 3, 12, 10, 0, 0, tzinfo=UTC),
            room_id="living_room",
        )
        repo.create_session(session)
        mock_session.run.assert_called_once()
        cypher = mock_session.run.call_args[0][0]
        params = mock_session.run.call_args[1]
        assert "CREATE" in cypher
        assert ":FlightSession" in cypher
        assert params["session_id"] == "sess-1"
        assert params["room_id"] == "living_room"


class TestEndSession:
    def test_sets_end_time_and_duration(self, repo, mock_session):
        end = datetime(2026, 3, 12, 10, 5, 0, tzinfo=UTC)
        repo.end_session("sess-1", end)
        mock_session.run.assert_called_once()
        cypher = mock_session.run.call_args[0][0]
        params = mock_session.run.call_args[1]
        assert "MATCH" in cypher
        assert "end_time" in cypher
        assert params["session_id"] == "sess-1"


class TestAddSample:
    def test_creates_sample_linked_to_session(self, repo, mock_session):
        sample = TelemetrySample(
            battery_pct=75,
            height_cm=100,
            tof_cm=95,
            temp_c=42.0,
            timestamp=datetime(2026, 3, 12, 10, 1, 0, tzinfo=UTC),
        )
        repo.add_sample("sess-1", sample)
        mock_session.run.assert_called_once()
        cypher = mock_session.run.call_args[0][0]
        assert ":BELONGS_TO" in cypher
        assert ":TelemetrySample" in cypher


class TestAddAnomaly:
    def test_creates_anomaly_linked_to_session(self, repo, mock_session):
        anomaly = Anomaly(
            type="battery_low",
            severity="warning",
            detail="Battery at 18%",
            timestamp=datetime(2026, 3, 12, 10, 2, 0, tzinfo=UTC),
        )
        repo.add_anomaly("sess-1", anomaly)
        mock_session.run.assert_called_once()
        cypher = mock_session.run.call_args[0][0]
        assert ":OCCURRED_DURING" in cypher
        assert ":Anomaly" in cypher


class TestGetSession:
    def test_returns_dict_when_found(self, repo, mock_session):
        record = MagicMock()
        record.data.return_value = {
            "session": {
                "id": "sess-1",
                "start_time": "2026-03-12T10:00:00Z",
                "room_id": "living_room",
            },
        }
        mock_session.run.return_value.single.return_value = record
        result = repo.get_session("sess-1")
        assert result["id"] == "sess-1"
        assert result["room_id"] == "living_room"

    def test_returns_none_when_not_found(self, repo, mock_session):
        mock_session.run.return_value.single.return_value = None
        result = repo.get_session("nonexistent")
        assert result is None


class TestListSessions:
    def test_returns_list_of_dicts(self, repo, mock_session):
        record1 = MagicMock()
        record1.data.return_value = {"session": {"id": "sess-1"}}
        record2 = MagicMock()
        record2.data.return_value = {"session": {"id": "sess-2"}}
        mock_session.run.return_value = [record1, record2]
        result = repo.list_sessions(limit=10)
        assert len(result) == 2
        assert result[0]["id"] == "sess-1"


class TestGetSessionSamples:
    def test_returns_sample_list(self, repo, mock_session):
        record = MagicMock()
        record.data.return_value = {
            "sample": {
                "battery_pct": 75,
                "timestamp": "2026-03-12T10:01:00Z",
            },
        }
        mock_session.run.return_value = [record]
        result = repo.get_session_samples("sess-1")
        assert len(result) == 1
        assert result[0]["battery_pct"] == 75


class TestGetSessionAnomalies:
    def test_returns_anomaly_list(self, repo, mock_session):
        record = MagicMock()
        record.data.return_value = {
            "anomaly": {
                "type": "battery_low",
                "severity": "warning",
            },
        }
        mock_session.run.return_value = [record]
        result = repo.get_session_anomalies("sess-1")
        assert len(result) == 1
        assert result[0]["type"] == "battery_low"


class TestGetAnomalySummary:
    def test_returns_aggregated_counts(self, repo, mock_session):
        record = MagicMock()
        record.data.return_value = {
            "type": "battery_low",
            "count": 5,
        }
        mock_session.run.return_value = [record]
        result = repo.get_anomaly_summary()
        assert len(result) == 1
        assert result[0]["count"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_session_repo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tello_telemetry.session_repo'`

- [ ] **Step 3: Write the session repository implementation**

Create `services/tello-telemetry/src/tello_telemetry/session_repo.py`:

```python
"""Neo4j session repository — read/write flight session data.

All methods use the sync Neo4j driver. The consumer calls these
via asyncio.to_thread() to avoid blocking the event loop.

Graph schema:
    (:FlightSession)-[:BELONGS_TO]->(:TelemetrySample)
    (:FlightSession)-[:OCCURRED_DURING]->(:Anomaly)

Note: relationship direction is Sample/Anomaly → Session
(BELONGS_TO / OCCURRED_DURING) to model "a sample belongs to a
session" and "an anomaly occurred during a session".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from datetime import datetime

    from neo4j import Driver

    from tello_core.models import Anomaly, FlightSession, TelemetrySample

logger = structlog.get_logger("tello_telemetry.session_repo")


class SessionRepository:
    """Neo4j read/write operations for flight sessions.

    Args:
        driver: Neo4j sync driver instance.
    """

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    # ── Writes ──────────────────────────────────────────

    def create_session(self, session: FlightSession) -> None:
        """Create a FlightSession node in Neo4j.

        Args:
            session: Flight session to persist.
        """
        with self._driver.session() as s:
            s.run(
                """
                CREATE (fs:FlightSession {
                    id: $session_id,
                    start_time: datetime($start_time),
                    room_id: $room_id,
                    mission_id: $mission_id,
                    anomaly_count: 0
                })
                """,
                session_id=session.id,
                start_time=session.start_time.isoformat(),
                room_id=session.room_id,
                mission_id=session.mission_id,
            )
        logger.info(
            "Created flight session %s",
            session.id,
            room_id=session.room_id,
        )

    def end_session(self, session_id: str, end_time: datetime) -> None:
        """Set end_time and compute duration on a FlightSession.

        Args:
            session_id: Session to end.
            end_time: When the session ended.
        """
        with self._driver.session() as s:
            s.run(
                """
                MATCH (fs:FlightSession {id: $session_id})
                SET fs.end_time = datetime($end_time),
                    fs.duration_s = duration.between(
                        fs.start_time, datetime($end_time)
                    ).seconds
                """,
                session_id=session_id,
                end_time=end_time.isoformat(),
            )
        logger.info("Ended flight session %s", session_id)

    def add_sample(self, session_id: str, sample: TelemetrySample) -> None:
        """Create a TelemetrySample node linked to a session.

        Args:
            session_id: Parent session.
            sample: Telemetry sample to persist.
        """
        with self._driver.session() as s:
            s.run(
                """
                MATCH (fs:FlightSession {id: $session_id})
                CREATE (ts:TelemetrySample {
                    battery_pct: $battery_pct,
                    height_cm: $height_cm,
                    tof_cm: $tof_cm,
                    temp_c: $temp_c,
                    timestamp: datetime($timestamp)
                })-[:BELONGS_TO]->(fs)
                SET fs.min_battery_pct = CASE
                    WHEN fs.min_battery_pct IS NULL
                        THEN $battery_pct
                    WHEN $battery_pct < fs.min_battery_pct
                        THEN $battery_pct
                    ELSE fs.min_battery_pct
                END,
                fs.max_temp_c = CASE
                    WHEN fs.max_temp_c IS NULL
                        THEN $temp_c
                    WHEN $temp_c > fs.max_temp_c
                        THEN $temp_c
                    ELSE fs.max_temp_c
                END
                """,
                session_id=session_id,
                battery_pct=sample.battery_pct,
                height_cm=sample.height_cm,
                tof_cm=sample.tof_cm,
                temp_c=sample.temp_c,
                timestamp=sample.timestamp.isoformat(),
            )

    def add_anomaly(self, session_id: str, anomaly: Anomaly) -> None:
        """Create an Anomaly node linked to a session.

        Args:
            session_id: Parent session.
            anomaly: Detected anomaly to persist.
        """
        with self._driver.session() as s:
            s.run(
                """
                MATCH (fs:FlightSession {id: $session_id})
                CREATE (a:Anomaly {
                    type: $type,
                    severity: $severity,
                    detail: $detail,
                    timestamp: datetime($timestamp)
                })-[:OCCURRED_DURING]->(fs)
                SET fs.anomaly_count = fs.anomaly_count + 1
                """,
                session_id=session_id,
                type=anomaly.type,
                severity=anomaly.severity,
                detail=anomaly.detail,
                timestamp=anomaly.timestamp.isoformat(),
            )

    # ── Reads ───────────────────────────────────────────

    def get_session(self, session_id: str) -> dict | None:
        """Get a single flight session by ID.

        Args:
            session_id: Session to retrieve.

        Returns:
            Session data dict, or None if not found.
        """
        with self._driver.session() as s:
            record = s.run(
                """
                MATCH (fs:FlightSession {id: $session_id})
                RETURN fs {.*} AS session
                """,
                session_id=session_id,
            ).single()
            if record is None:
                return None
            return record.data()["session"]

    def list_sessions(self, limit: int = 10) -> list[dict]:
        """List recent flight sessions, newest first.

        Args:
            limit: Maximum number of sessions to return.
        """
        with self._driver.session() as s:
            records = s.run(
                """
                MATCH (fs:FlightSession)
                RETURN fs {.*} AS session
                ORDER BY fs.start_time DESC
                LIMIT $limit
                """,
                limit=limit,
            )
            return [r.data()["session"] for r in records]

    def get_session_samples(self, session_id: str) -> list[dict]:
        """Get telemetry samples for a session, ordered by time.

        Args:
            session_id: Session whose samples to retrieve.
        """
        with self._driver.session() as s:
            records = s.run(
                """
                MATCH (ts:TelemetrySample)-[:BELONGS_TO]->
                      (fs:FlightSession {id: $session_id})
                RETURN ts {.*} AS sample
                ORDER BY ts.timestamp
                """,
                session_id=session_id,
            )
            return [r.data()["sample"] for r in records]

    def get_session_anomalies(self, session_id: str) -> list[dict]:
        """Get anomalies for a session, ordered by time.

        Args:
            session_id: Session whose anomalies to retrieve.
        """
        with self._driver.session() as s:
            records = s.run(
                """
                MATCH (a:Anomaly)-[:OCCURRED_DURING]->
                      (fs:FlightSession {id: $session_id})
                RETURN a {.*} AS anomaly
                ORDER BY a.timestamp
                """,
                session_id=session_id,
            )
            return [r.data()["anomaly"] for r in records]

    def get_anomaly_summary(self) -> list[dict]:
        """Get anomaly counts by type across all sessions."""
        with self._driver.session() as s:
            records = s.run(
                """
                MATCH (a:Anomaly)
                RETURN a.type AS type,
                       a.severity AS severity,
                       count(a) AS count
                ORDER BY count DESC
                """,
            )
            return [r.data() for r in records]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_session_repo.py -v`
Expected: 9 passed

- [ ] **Step 5: Lint check**

Run: `uv run ruff check services/tello-telemetry/ --fix && uv run ruff format services/tello-telemetry/`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
git add services/tello-telemetry/src/tello_telemetry/session_repo.py \
      services/tello-telemetry/tests/test_session_repo.py
git commit -m "feat(telemetry): add session repository

Neo4j CRUD for FlightSession, TelemetrySample, Anomaly nodes.
Sync driver — consumer calls via asyncio.to_thread(). 9 tests."
```

---

## Chunk 3: Stream Consumer

### Task 4: Stream Consumer

**Files:**

- Create: `services/tello-telemetry/src/tello_telemetry/consumer.py`
- Create: `services/tello-telemetry/tests/test_consumer.py`

The StreamConsumer is the "Imperative Shell" — it reads from
Redis, routes messages, calls the detector and repository, and
acknowledges processed messages. All I/O happens here; all logic
is delegated to the pure detector and the repository.

**Important Redis Stream concepts for the tests:**

- `XREADGROUP` returns a list of `[stream_name, [(msg_id, fields), ...]]`
- `XACK` acknowledges a message so it leaves the Pending Entries List
- `XGROUP CREATE` with MKSTREAM is idempotent (catch BUSYGROUP)
- PEL recovery: first read with ID `0` to get pending, then `>` for new

#### Step-by-step

- [ ] **Step 1: Write the failing consumer tests**

Create `services/tello-telemetry/tests/test_consumer.py`:

```python
"""Tests for Redis Stream consumer.

Tests verify message routing, XACK behavior, PEL recovery,
and consumer group auto-creation. Redis is mocked throughout.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ResponseError

from tello_core.models import TelemetryFrame
from tello_telemetry.config import TelloTelemetryConfig
from tello_telemetry.consumer import StreamConsumer
from tello_telemetry.detector import AnomalyDetector
from tello_telemetry.session_repo import SessionRepository


def _make_config(**overrides) -> TelloTelemetryConfig:
    defaults = {
        "neo4j_uri": "bolt://localhost:7687",
        "neo4j_username": "neo4j",
        "neo4j_password": "test",
        "redis_url": "redis://localhost:6379",
        "service_name": "test",
    }
    defaults.update(overrides)
    return TelloTelemetryConfig(**defaults)


def _make_telemetry_fields(**overrides) -> dict:
    """Create stream fields for a telemetry event."""
    frame_data = {
        "battery_pct": 80,
        "height_cm": 100,
        "tof_cm": 95,
        "temp_c": 40.0,
        "pitch": 0.0,
        "roll": 0.0,
        "yaw": 0.0,
        "flight_time_s": 30,
        "timestamp": "2026-03-12T10:00:00Z",
    }
    frame_data.update(overrides)
    return {
        "event_type": "telemetry",
        "data": json.dumps(frame_data),
    }


@pytest.fixture()
def config():
    return _make_config()


@pytest.fixture()
def detector(config):
    return AnomalyDetector(config)


@pytest.fixture()
def session_repo():
    repo = MagicMock(spec=SessionRepository)
    repo.create_session = MagicMock()
    repo.end_session = MagicMock()
    repo.add_sample = MagicMock()
    repo.add_anomaly = MagicMock()
    return repo


@pytest.fixture()
def consumer(mock_redis, config, detector, session_repo):
    return StreamConsumer(
        redis=mock_redis,
        config=config,
        detector=detector,
        session_repo=session_repo,
    )


class TestEnsureConsumerGroup:
    async def test_creates_group(self, consumer, mock_redis):
        await consumer.ensure_consumer_group()
        mock_redis.xgroup_create.assert_called_once_with(
            "tello:events",
            "telemetry-service",
            id="0",
            mkstream=True,
        )

    async def test_ignores_busygroup_error(self, consumer, mock_redis):
        mock_redis.xgroup_create = AsyncMock(
            side_effect=ResponseError("BUSYGROUP"),
        )
        await consumer.ensure_consumer_group()
        # Should not raise


class TestProcessTakeoff:
    async def test_takeoff_creates_session(self, consumer, session_repo):
        fields = {"event_type": "takeoff", "room_id": "living_room"}
        await consumer._process_message("1-0", fields)
        session_repo.create_session.assert_called_once()
        session = session_repo.create_session.call_args[0][0]
        assert session.room_id == "living_room"

    async def test_takeoff_default_room_id(self, consumer, session_repo):
        fields = {"event_type": "takeoff"}
        await consumer._process_message("1-0", fields)
        session = session_repo.create_session.call_args[0][0]
        assert session.room_id == "unknown"


class TestProcessLand:
    async def test_land_ends_session(self, consumer, session_repo):
        # First start a session
        await consumer._process_message(
            "1-0", {"event_type": "takeoff"},
        )
        await consumer._process_message(
            "2-0", {"event_type": "land"},
        )
        session_repo.end_session.assert_called_once()


class TestProcessTelemetry:
    async def test_telemetry_with_anomaly_persists(
        self, consumer, session_repo,
    ):
        # Start session
        await consumer._process_message(
            "1-0", {"event_type": "takeoff"},
        )
        # Send telemetry with low battery
        fields = _make_telemetry_fields(battery_pct=5)
        await consumer._process_message("2-0", fields)
        session_repo.add_anomaly.assert_called()

    async def test_nominal_telemetry_no_anomaly(
        self, consumer, session_repo,
    ):
        await consumer._process_message(
            "1-0", {"event_type": "takeoff"},
        )
        fields = _make_telemetry_fields()  # all nominal
        await consumer._process_message("2-0", fields)
        session_repo.add_anomaly.assert_not_called()

    async def test_sampling_interval_respected(
        self, consumer, session_repo,
    ):
        """Only samples to Neo4j when interval has elapsed."""
        await consumer._process_message(
            "1-0", {"event_type": "takeoff"},
        )
        # First telemetry — should sample (first frame always samples)
        fields = _make_telemetry_fields()
        await consumer._process_message("2-0", fields)
        assert session_repo.add_sample.call_count == 1

        # Second telemetry immediately — should NOT sample
        await consumer._process_message("3-0", fields)
        assert session_repo.add_sample.call_count == 1


class TestRunLoop:
    async def test_run_processes_pending_then_new(
        self, consumer, mock_redis,
    ):
        """Run should process pending (ID=0) then new (ID=>)."""
        call_count = 0

        async def mock_xreadgroup(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # Return empty for both pending and new reads
                return []
            raise asyncio.CancelledError

        mock_redis.xreadgroup = AsyncMock(
            side_effect=mock_xreadgroup,
        )
        with pytest.raises(asyncio.CancelledError):
            await consumer.run()
        # Should have called ensure_consumer_group
        mock_redis.xgroup_create.assert_called_once()

    async def test_xack_after_processing(self, consumer, mock_redis):
        """Messages are ACKed after successful processing."""
        msg_id = "1-0"
        fields = {"event_type": "takeoff"}
        # Simulate one message then stop
        call_count = 0

        async def mock_xreadgroup(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Pending read returns empty
                return []
            if call_count == 2:
                return [["tello:events", [(msg_id, fields)]]]
            raise asyncio.CancelledError

        mock_redis.xreadgroup = AsyncMock(
            side_effect=mock_xreadgroup,
        )
        with pytest.raises(asyncio.CancelledError):
            await consumer.run()
        mock_redis.xack.assert_called_with(
            "tello:events", "telemetry-service", msg_id,
        )


class TestMalformedMessage:
    async def test_invalid_json_skipped_and_acked(
        self, consumer, session_repo, mock_redis,
    ):
        """Malformed telemetry data is logged, skipped, not retried."""
        await consumer._process_message(
            "1-0", {"event_type": "takeoff"},
        )
        fields = {"event_type": "telemetry", "data": "not-json"}
        # Should not raise
        await consumer._process_message("2-0", fields)
        session_repo.add_sample.assert_not_called()
        session_repo.add_anomaly.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_consumer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tello_telemetry.consumer'`

- [ ] **Step 3: Write the consumer implementation**

Create `services/tello-telemetry/src/tello_telemetry/consumer.py`:

```python
"""Redis Stream consumer — XREADGROUP loop.

The StreamConsumer is the "Imperative Shell" in the Pure Core /
Imperative Shell architecture. It handles all I/O (Redis reads,
Neo4j writes via asyncio.to_thread) and delegates logic to:
- AnomalyDetector (pure core) for threshold checks
- SessionRepository for Neo4j persistence

Consumer lifecycle:
1. ensure_consumer_group() — idempotent XGROUP CREATE
2. Process pending messages (PEL recovery, ID=0)
3. Read new messages (ID=>) in a loop
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import structlog
from pydantic import ValidationError as PydanticValidationError

from tello_core.models import FlightSession, TelemetryFrame, TelemetrySample

if TYPE_CHECKING:
    import redis.asyncio as aioredis

    from tello_telemetry.config import TelloTelemetryConfig
    from tello_telemetry.detector import AnomalyDetector
    from tello_telemetry.session_repo import SessionRepository

logger = structlog.get_logger("tello_telemetry.consumer")


class StreamConsumer:
    """Reads from the tello:events Redis Stream and processes
    flight telemetry, lifecycle events, and anomalies.

    Args:
        redis: Async Redis client.
        config: Service configuration.
        detector: Anomaly detection engine.
        session_repo: Neo4j persistence layer.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        config: TelloTelemetryConfig,
        detector: AnomalyDetector,
        session_repo: SessionRepository,
    ) -> None:
        self._redis = redis
        self._config = config
        self._detector = detector
        self._repo = session_repo
        self._current_session: FlightSession | None = None
        self._last_sample_time: float = 0.0

    async def ensure_consumer_group(self) -> None:
        """Create consumer group if it doesn't exist.

        Uses XGROUP CREATE with MKSTREAM. Catches BUSYGROUP
        error (group already exists) gracefully. This makes
        startup idempotent — no external setup required.
        """
        try:
            await self._redis.xgroup_create(
                self._config.stream_name,
                self._config.consumer_group,
                id="0",
                mkstream=True,
            )
            logger.info(
                "Created consumer group %s",
                self._config.consumer_group,
            )
        except Exception as exc:  # noqa: BLE001
            if "BUSYGROUP" in str(exc):
                logger.info(
                    "Consumer group %s already exists",
                    self._config.consumer_group,
                )
            else:
                raise

    async def run(self) -> None:
        """Main consumer loop.

        1. Ensure consumer group exists
        2. Process pending messages (PEL recovery)
        3. Read new messages in a loop
        """
        await self.ensure_consumer_group()

        # Phase 1: Process pending entries (crash recovery)
        await self._read_and_process(message_id="0")

        # Phase 2: Read new messages
        while True:
            await self._read_and_process(message_id=">")

    async def _read_and_process(self, *, message_id: str) -> None:
        """Read a batch of messages and process each one.

        Args:
            message_id: "0" for pending, ">" for new messages.
        """
        messages = await self._redis.xreadgroup(
            groupname=self._config.consumer_group,
            consumername=self._config.consumer_name,
            streams={self._config.stream_name: message_id},
            count=self._config.batch_size,
            block=self._config.block_ms,
        )

        if not messages:
            return

        for _stream_name, entries in messages:
            for msg_id, fields in entries:
                await self._process_message(msg_id, fields)
                await self._redis.xack(
                    self._config.stream_name,
                    self._config.consumer_group,
                    msg_id,
                )

    async def _process_message(
        self,
        msg_id: str,
        fields: dict,
    ) -> None:
        """Route a single stream message by event_type.

        Args:
            msg_id: Redis Stream message ID.
            fields: Message fields dict.
        """
        event_type = fields.get("event_type", "unknown")

        if event_type == "takeoff":
            await self._handle_takeoff(fields)
        elif event_type == "land":
            await self._handle_land()
        elif event_type == "telemetry":
            await self._handle_telemetry(fields)
        else:
            logger.warning("Unknown event type: %s", event_type)

    async def _handle_takeoff(self, fields: dict) -> None:
        """Start a new flight session."""
        session = FlightSession(
            id=str(uuid4()),
            start_time=datetime.now(UTC),
            room_id=fields.get("room_id", "unknown"),
        )
        self._current_session = session
        self._last_sample_time = 0.0
        await asyncio.to_thread(self._repo.create_session, session)
        logger.info(
            "Flight session started",
            session_id=session.id,
            room_id=session.room_id,
        )

    async def _handle_land(self) -> None:
        """End the current flight session."""
        if self._current_session is None:
            logger.warning("Land event without active session")
            return
        end_time = datetime.now(UTC)
        await asyncio.to_thread(
            self._repo.end_session,
            self._current_session.id,
            end_time,
        )
        logger.info(
            "Flight session ended",
            session_id=self._current_session.id,
        )
        self._current_session = None

    async def _handle_telemetry(self, fields: dict) -> None:
        """Parse telemetry frame, detect anomalies, sample."""
        if self._current_session is None:
            return

        try:
            frame = TelemetryFrame.model_validate_json(fields["data"])
        except (PydanticValidationError, KeyError):
            logger.exception(
                "Failed to parse telemetry data",
                raw_fields=fields,
            )
            return

        # Anomaly detection (pure core — no I/O)
        anomalies = self._detector.check(frame)
        for anomaly in anomalies:
            await asyncio.to_thread(
                self._repo.add_anomaly,
                self._current_session.id,
                anomaly,
            )
            logger.warning(
                "Anomaly detected",
                type=anomaly.type,
                severity=anomaly.severity,
            )

        # Sampling — persist every neo4j_sample_interval_s
        now = time.monotonic()
        if (
            now - self._last_sample_time
            >= self._config.neo4j_sample_interval_s
        ):
            sample = TelemetrySample(
                battery_pct=frame.battery_pct,
                height_cm=frame.height_cm,
                tof_cm=frame.tof_cm,
                temp_c=frame.temp_c,
                timestamp=frame.timestamp,
            )
            await asyncio.to_thread(
                self._repo.add_sample,
                self._current_session.id,
                sample,
            )
            self._last_sample_time = now
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_consumer.py -v`
Expected: 10 passed

- [ ] **Step 5: Lint check**

Run: `uv run ruff check services/tello-telemetry/ --fix && uv run ruff format services/tello-telemetry/`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
git add services/tello-telemetry/src/tello_telemetry/consumer.py \
      services/tello-telemetry/tests/test_consumer.py
git commit -m "feat(telemetry): add stream consumer

XREADGROUP loop with PEL recovery, message routing for
takeoff/land/telemetry events, sampling interval, anomaly
detection delegation. 10 tests."
```

---

## Chunk 4: Query Tools, Server, Entry Point

### Task 5: Query Tools

**Files:**

- Create: `services/tello-telemetry/src/tello_telemetry/tools/__init__.py`
- Create: `services/tello-telemetry/src/tello_telemetry/tools/queries.py`
- Create: `services/tello-telemetry/tests/test_tools/__init__.py`
- Create: `services/tello-telemetry/tests/test_tools/test_queries.py`

Query tools are read-only FastMCP tools that call
SessionRepository methods via asyncio.to\_thread(). They follow
the `register(mcp)` pattern established in tello-mcp.

#### Step-by-step

- [ ] **Step 1: Write the failing query tools tests**

Create `services/tello-telemetry/tests/test_tools/__init__.py` (empty).

Create `services/tello-telemetry/tests/test_tools/test_queries.py`:

```python
"""Tests for query MCP tools.

Tests verify that tools call SessionRepository methods and
return correctly shaped responses, including error cases.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tello_telemetry.tools.queries import register


class TestQueryTools:
    @pytest.fixture(autouse=True)
    def setup_mcp(self):
        """Create a mock FastMCP server and register tools."""
        self.mcp = MagicMock()
        self.registered_tools = {}

        self.mock_repo = MagicMock()
        self.mcp.state = {"session_repo": self.mock_repo}

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

    def test_all_tools_registered(self):
        expected = {
            "list_flight_sessions",
            "get_flight_session",
            "get_session_telemetry",
            "get_session_anomalies",
            "get_anomaly_summary",
        }
        assert set(self.registered_tools.keys()) == expected

    async def test_list_flight_sessions(self):
        self.mock_repo.list_sessions.return_value = [
            {"id": "s1"}, {"id": "s2"},
        ]
        result = await self.registered_tools["list_flight_sessions"](
            limit=10,
        )
        assert result["sessions"][0]["id"] == "s1"
        assert len(result["sessions"]) == 2

    async def test_get_flight_session_found(self):
        self.mock_repo.get_session.return_value = {
            "id": "s1", "room_id": "kitchen",
        }
        result = await self.registered_tools["get_flight_session"](
            session_id="s1",
        )
        assert result["session"]["id"] == "s1"

    async def test_get_flight_session_not_found(self):
        self.mock_repo.get_session.return_value = None
        result = await self.registered_tools["get_flight_session"](
            session_id="nonexistent",
        )
        assert "error" in result

    async def test_get_session_telemetry(self):
        self.mock_repo.get_session_samples.return_value = [
            {"battery_pct": 75},
        ]
        result = await self.registered_tools["get_session_telemetry"](
            session_id="s1",
        )
        assert len(result["samples"]) == 1

    async def test_get_session_anomalies(self):
        self.mock_repo.get_session_anomalies.return_value = [
            {"type": "battery_low"},
        ]
        result = await self.registered_tools["get_session_anomalies"](
            session_id="s1",
        )
        assert len(result["anomalies"]) == 1

    async def test_get_anomaly_summary(self):
        self.mock_repo.get_anomaly_summary.return_value = [
            {"type": "battery_low", "count": 3},
        ]
        result = await self.registered_tools["get_anomaly_summary"]()
        assert result["summary"][0]["count"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_tools/test_queries.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the query tools implementation**

Create `services/tello-telemetry/src/tello_telemetry/tools/__init__.py` (empty):

```python
"""tello-telemetry MCP tools."""
```

Create `services/tello-telemetry/src/tello_telemetry/tools/queries.py`:

```python
"""Query tools — read-only FastMCP tools for flight session data.

Template queries that call SessionRepository methods. Each tool
wraps sync Neo4j calls with asyncio.to_thread() to keep the
event loop responsive.

Tools follow the register(mcp) pattern. The SessionRepository
is accessed from mcp.state["session_repo"].
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register query tools on the MCP server.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def list_flight_sessions(limit: int = 10) -> dict:
        """List recent flight sessions with summary stats.

        Args:
            limit: Maximum number of sessions to return (default 10).
        """
        repo = mcp.state["session_repo"]
        sessions = await asyncio.to_thread(repo.list_sessions, limit)
        return {"sessions": sessions, "count": len(sessions)}

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def get_flight_session(session_id: str) -> dict:
        """Get detailed info for one flight session.

        Args:
            session_id: The session ID to look up.
        """
        repo = mcp.state["session_repo"]
        session = await asyncio.to_thread(repo.get_session, session_id)
        if session is None:
            return {
                "error": "NOT_FOUND",
                "detail": f"No session with ID {session_id}",
            }
        return {"session": session}

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def get_session_telemetry(session_id: str) -> dict:
        """Get sampled telemetry curve for a session.

        Returns battery, altitude, temperature over time.

        Args:
            session_id: The session to get telemetry for.
        """
        repo = mcp.state["session_repo"]
        samples = await asyncio.to_thread(
            repo.get_session_samples, session_id,
        )
        return {"samples": samples, "count": len(samples)}

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def get_session_anomalies(session_id: str) -> dict:
        """Get anomalies detected during a flight session.

        Args:
            session_id: The session to get anomalies for.
        """
        repo = mcp.state["session_repo"]
        anomalies = await asyncio.to_thread(
            repo.get_session_anomalies, session_id,
        )
        return {"anomalies": anomalies, "count": len(anomalies)}

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def get_anomaly_summary() -> dict:
        """Get anomaly counts by type across all sessions."""
        repo = mcp.state["session_repo"]
        summary = await asyncio.to_thread(repo.get_anomaly_summary)
        return {"summary": summary}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_tools/test_queries.py -v`
Expected: 7 passed

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check services/tello-telemetry/ --fix && \
uv run ruff format services/tello-telemetry/
git add services/tello-telemetry/src/tello_telemetry/tools/ \
      services/tello-telemetry/tests/test_tools/
git commit -m "feat(telemetry): add query tools

5 read-only MCP tools wrapping SessionRepository via
asyncio.to_thread(). Uses register(mcp) pattern. 7 tests."
```

---

### Task 6: Server and Entry Point

**Files:**

- Create: `services/tello-telemetry/src/tello_telemetry/server.py`
- Create: `services/tello-telemetry/src/tello_telemetry/__main__.py`

The server wires everything together in the FastMCP lifespan:
Config → structlog → Redis → Neo4j → domain objects → background
consumer task. The `__main__.py` provides the CLI entry point.

No dedicated tests for server.py — it's thin wiring code. The
integration between components is already tested in the consumer
and tools tests. Smoke-testing the server would require real
Redis + Neo4j, which is out of scope for unit tests.

#### Step-by-step

- [ ] **Step 1: Write the server module**

Create `services/tello-telemetry/src/tello_telemetry/server.py`:

```python
"""tello-telemetry — FastMCP flight session intelligence server.

Run:
    stdio:            python -m tello_telemetry.server
    streamable-http:  python -m tello_telemetry.server --transport streamable-http --port 8200
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

from fastmcp import FastMCP

from tello_core.config import configure_structlog
from tello_core.neo4j_client import neo4j_lifespan
from tello_core.redis_client import create_redis_client
from tello_telemetry.config import TelloTelemetryConfig
from tello_telemetry.consumer import StreamConsumer
from tello_telemetry.detector import AnomalyDetector
from tello_telemetry.session_repo import SessionRepository
from tello_telemetry.tools import queries

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Manage service lifecycle.

    Startup: Config → structlog → Redis → Neo4j → domain objects →
        background consumer task
    Shutdown: Cancel consumer → close Neo4j (via lifespan) → close Redis
    """
    config = TelloTelemetryConfig.from_env(
        service_name="tello-telemetry",
    )
    configure_structlog(config.service_name)

    redis = create_redis_client(config.redis_url)
    async with neo4j_lifespan(config) as neo4j_driver:
        detector = AnomalyDetector(config)
        session_repo = SessionRepository(neo4j_driver)
        consumer = StreamConsumer(redis, config, detector, session_repo)

        server.state["session_repo"] = session_repo

        task = asyncio.create_task(consumer.run())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await redis.aclose()


mcp = FastMCP(
    name="tello-telemetry",
    instructions=(
        "Flight session intelligence service. "
        "Query flight sessions, telemetry curves, and anomaly history. "
        "All query tools are read-only."
    ),
    lifespan=lifespan,
)

queries.register(mcp)


def main() -> None:
    """Entry point for tello-telemetry server."""
    import argparse

    parser = argparse.ArgumentParser(description="tello-telemetry server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "streamable-http", "sse"],
    )
    parser.add_argument("--port", type=int, default=8200)
    parsed = parser.parse_args()

    mcp.run(
        transport=parsed.transport,
        host="0.0.0.0",
        port=parsed.port,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the \_\_main\_\_ entry point**

Create `services/tello-telemetry/src/tello_telemetry/__main__.py`:

```python
"""Allow running as `python -m tello_telemetry`."""

from tello_telemetry.server import main

main()
```

- [ ] **Step 3: Run all tello-telemetry tests to verify nothing broke**

Run: `uv run --package tello-telemetry pytest services/tello-telemetry/tests/ -v`
Expected: All tests pass (config + detector + session\_repo + consumer + queries)

- [ ] **Step 4: Lint check**

Run: `uv run ruff check services/tello-telemetry/ --fix && uv run ruff format services/tello-telemetry/`
Expected: Clean

- [ ] **Step 5: Commit**

```bash
git add services/tello-telemetry/src/tello_telemetry/server.py \
      services/tello-telemetry/src/tello_telemetry/__main__.py
git commit -m "feat(telemetry): add server and entry point

FastMCP lifespan wires config, Redis, Neo4j, consumer, detector,
and session_repo. Background consumer task with graceful shutdown."
```

---

## Chunk 5: Bundled Changes

### Task 7: tello-mcp Updates (tello\_host + room\_id)

**Files:**

- Modify: `services/tello-mcp/src/tello_mcp/config.py`
- Modify: `services/tello-mcp/src/tello_mcp/tools/flight.py`
- Modify: `services/tello-mcp/tests/test_config.py`
- Modify: `services/tello-mcp/tests/test_tools/test_flight.py`

Two changes to tello-mcp:

1. **`tello_host` config field** — Add `tello_host: str = "192.168.10.1"`
   to `TelloMcpConfig`. Read from `TELLO_HOST` env var. Default is
   Direct Mode IP.
2. **`room_id` on takeoff tool** — Add optional `room_id: str = "unknown"`
   parameter. Publish `room_id` in the takeoff event to the Redis Stream.

#### Step-by-step

- [ ] **Step 0: Add default room\_id to FlightSession model**

Edit `packages/tello-core/src/tello_core/models.py`. Change:

```python
room_id: str
```

to:

```python
room_id: str = "unknown"
```

This makes `room_id` optional at the model level (defaults to
`"unknown"` if not provided), matching the spec's intent that
sessions are tagged `"unknown"` when the caller doesn't specify
a room.

- [ ] **Step 1: Write the failing config test for tello\_host**

Add to `services/tello-mcp/tests/test_config.py`:

```python
def test_tello_host_default(self):
    config = TelloMcpConfig(
        neo4j_uri="bolt://localhost:7687",
        neo4j_username="neo4j",
        neo4j_password="pw",
        redis_url="redis://localhost:6379",
        service_name="test",
    )
    assert config.tello_host == "192.168.10.1"

def test_tello_host_from_env(self, monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "pw")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("TELLO_HOST", "192.168.68.102")

    config = TelloMcpConfig.from_env(service_name="tello-mcp")
    assert config.tello_host == "192.168.68.102"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_config.py -v`
Expected: FAIL — `TypeError: unexpected keyword argument 'tello_host'` or `AttributeError`

- [ ] **Step 3: Add tello\_host to TelloMcpConfig**

Edit `services/tello-mcp/src/tello_mcp/config.py`:

Add `tello_host: str = "192.168.10.1"` field to the dataclass.

Update `from_env` to read `TELLO_HOST`:

```python
@classmethod
def from_env(cls, **overrides: str | int | float | bool) -> Self:
    """Load tello-mcp config from environment."""
    overrides.setdefault("tello_wifi_ssid", os.environ.get("TELLO_WIFI_SSID", ""))
    overrides.setdefault("tello_host", os.environ.get("TELLO_HOST", "192.168.10.1"))
    return BaseServiceConfig.from_env.__func__(cls, **overrides)  # type: ignore[attr-defined]
```

- [ ] **Step 4: Run config test to verify it passes**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_config.py -v`
Expected: 5 passed (3 existing + 2 new)

- [ ] **Step 5: Write the failing takeoff room\_id test**

**Note:** The existing `test_flight.py` uses a `TestFlightTools`
class with an `autouse` `setup_mcp` fixture that creates
`self.mcp` and `self.registered_tools`. Match this pattern —
add the new test as a method inside the existing class.

Add to `services/tello-mcp/tests/test_tools/test_flight.py`:

```python
async def test_takeoff_publishes_room_id(self):
    """Takeoff tool publishes room_id in the stream event."""
    mock_queue = AsyncMock()
    mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
    mock_telemetry = AsyncMock()
    self.mcp.state = {
        "drone": MagicMock(),
        "queue": mock_queue,
        "telemetry": mock_telemetry,
    }
    takeoff = self.registered_tools["takeoff"]
    await takeoff(room_id="living_room")
    mock_telemetry.publish_event.assert_called_once()
    call_args = mock_telemetry.publish_event.call_args
    assert call_args[0][0] == "takeoff"
    assert call_args[0][1]["room_id"] == "living_room"
```

Add this import at the top of the test file:

```python
from unittest.mock import AsyncMock
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_tools/test_flight.py::TestFlightTools::test_takeoff_publishes_room_id -v`
Expected: FAIL — takeoff doesn't accept `room_id`

- [ ] **Step 7: Update takeoff tool with room\_id parameter**

Edit `services/tello-mcp/src/tello_mcp/tools/flight.py`. Update
the takeoff function:

```python
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
async def takeoff(room_id: str = "unknown") -> dict:
    """Take off and hover at ~50cm.

    Args:
        room_id: Room identifier for session tracking (default "unknown").
    """
    drone = mcp.state["drone"]
    queue = mcp.state["queue"]
    telemetry = mcp.state["telemetry"]
    result = await queue.enqueue(drone.takeoff)
    await telemetry.publish_event("takeoff", {"room_id": room_id})
    return result
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_tools/test_flight.py -v`
Expected: All passed

- [ ] **Step 9: Run all tello-mcp tests to verify nothing broke**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/ -v`
Expected: All 27+ tests pass

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff check services/tello-mcp/ --fix && \
uv run ruff format services/tello-mcp/
git add services/tello-mcp/
git commit -m "feat(mcp): add tello_host config and room_id on takeoff

- TelloMcpConfig.tello_host field (default 192.168.10.1, env TELLO_HOST)
- takeoff tool gains optional room_id param, publishes to stream
- Enables tello-telemetry to tag sessions with originating room"
```

---

### Task 8: find\_drone.py Auto-Update .env

**Files:**

- Modify: `scripts/find_drone.py`
- Commit as-is: `scripts/setup_router_mode.py`

Enhance `find_drone.py` to automatically write the discovered IP
to `.env`. If `.env` doesn't exist, create from `.env.example`.
If `TELLO_HOST` already exists, update its value.

#### Step-by-step

- [ ] **Step 1: Update find\_drone.py**

Edit `scripts/find_drone.py`. Replace the `main()` function:

```python
import re
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


def update_env_file(ip: str) -> None:
    """Write or update TELLO_HOST in .env file.

    If .env doesn't exist, copies from .env.example first.
    If TELLO_HOST exists, updates it. Otherwise appends it.
    """
    if not ENV_FILE.exists():
        if ENV_EXAMPLE.exists():
            ENV_FILE.write_text(ENV_EXAMPLE.read_text())
            print(f"Created .env from .env.example")
        else:
            ENV_FILE.write_text("")
            print(f"Created empty .env")

    content = ENV_FILE.read_text()
    new_line = f"TELLO_HOST={ip}"

    if re.search(r"^TELLO_HOST=.*$", content, re.MULTILINE):
        content = re.sub(
            r"^TELLO_HOST=.*$",
            new_line,
            content,
            flags=re.MULTILINE,
        )
        print(f"Updated TELLO_HOST={ip} in .env")
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += f"\n# Tello drone IP (auto-discovered)\n{new_line}\n"
        print(f"Added TELLO_HOST={ip} to .env")

    ENV_FILE.write_text(content)


def main() -> None:
    print("Tello TT Network Scanner")
    print("=" * 40)

    subnet = get_local_subnet()
    if not subnet:
        print("Could not determine local subnet. Check your WiFi connection.")
        sys.exit(1)

    print(f"Local subnet: {subnet}.0/24")
    print()

    drone_ip = scan_for_tello(subnet)
    if drone_ip:
        print(f"\nFound Tello TT at: {drone_ip}")
        update_env_file(drone_ip)
    else:
        print("\nTello TT not found on the network.")
        print("Make sure:")
        print("  - The drone is powered on")
        print("  - The expansion board switch is on ROUTER MODE")
        print("  - The drone has successfully connected to your WiFi")
        print("  - You're on the same network as the drone")
```

- [ ] **Step 2: Lint check**

Run: `uv run ruff check scripts/ --fix && uv run ruff format scripts/`
Expected: Clean

- [ ] **Step 3: Commit scripts**

```bash
git add scripts/
git commit -m "feat(scripts): auto-update .env with discovered drone IP

find_drone.py now writes TELLO_HOST to .env automatically.
Creates .env from .env.example if it doesn't exist.
Also commits setup_router_mode.py (previously uncommitted)."
```

---

### Task 9: .env.example, CI, Coverage, Root Config

**Files:**

- Modify: `.env.example`
- Modify: `.github/workflows/ci.yml`
- Modify: `pyproject.toml` (root)

#### Step-by-step

- [ ] **Step 1: Update .env.example**

Add after the `TELLO_WIFI_SSID` line:

```
# Drone IP — Direct Mode default (192.168.10.1)
# For Router Mode, run: uv run python scripts/find_drone.py
TELLO_HOST=192.168.10.1
```

- [ ] **Step 2: Update CI matrix**

Add to the `matrix.include` array in `.github/workflows/ci.yml`:

```yaml
          - package: tello-telemetry
            test-path: services/tello-telemetry/tests/
            cov-source: services/tello-telemetry/src
```

- [ ] **Step 3: Update root pyproject.toml**

Add `"services/tello-telemetry/src"` to both:

- `[tool.coverage.run].source` array
- `[tool.pytest.ini_options].pythonpath` array

- [ ] **Step 4: Run all tests to verify everything still works**

Run: `uv run pytest packages/ services/ -v`
Expected: All tests pass (62 existing + ~40 new tello-telemetry)

- [ ] **Step 5: Lint full project**

Run: `uv run ruff check . --fix && uv run ruff format .`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
git add .env.example .github/workflows/ci.yml pyproject.toml
git commit -m "chore: add tello-telemetry to CI, coverage, and env config

- .env.example: add TELLO_HOST with Direct/Router Mode docs
- CI: add tello-telemetry to test matrix
- Root pyproject.toml: add coverage source and pythonpath"
```

---

### Task 10: Docs and Uncommitted Files

**Files:**

- Existing: `docs/superpowers/` (specs, plans)
- Existing: `.markdownlint.json`

Commit the previously uncommitted documentation and config files
that have been building up during the brainstorming and planning
phases.

#### Step-by-step

- [ ] **Step 1: Commit docs and markdownlint config**

```bash
git add docs/superpowers/ .markdownlint.json
git commit -m "docs: add Phase 2 spec, plans, and markdownlint config

- Phase 1 scaffold spec and plan (executed)
- Phase 2 telemetry spec (approved) and implementation plan
- .markdownlint.json for consistent markdown formatting"
```

- [ ] **Step 2: Run final full test suite**

Run: `uv run pytest packages/ services/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 3: Run lint one final time**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: Clean

---

## Summary

| Task | Component | Tests | Key Pattern |
| ---- | --------- | ----- | ----------- |
| 1 | Config + package setup | 4 | BaseServiceConfig subclass, frozen dataclass |
| 2 | AnomalyDetector | 14 | Pure Core (no I/O, no mocks) |
| 3 | SessionRepository | 9 | Sync Neo4j driver, Cypher queries |
| 4 | StreamConsumer | 10 | XREADGROUP, PEL recovery, Imperative Shell |
| 5 | Query Tools | 7 | register(mcp) pattern, asyncio.to\_thread |
| 6 | Server + entry point | 0 | Lifespan wiring, background task |
| 7 | tello-mcp updates | 3 | tello\_host config, room\_id on takeoff |
| 8 | find\_drone.py | 0 | Auto-update .env |
| 9 | CI + coverage + env | 0 | CI matrix, coverage source |
| 10 | Docs commit | 0 | Specs, plans, markdownlint |
| **Total** | | **~47** | |
