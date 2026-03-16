# Forward ToF Sensor Integration — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the Dot-Matrix Module's forward-facing ToF sensor end-to-end: raw sensor method, background obstacle monitoring with tiered zones, MCP tools, CLI commands, and active safety (forced stop + response options menu).

**Architecture:** DroneAdapter provides raw `get_forward_distance()` I/O. A new ObstacleMonitor class runs continuous background polling, classifies distance into tiered zones (CLEAR/CAUTION/WARNING/DANGER), and enforces forced stops in the DANGER zone. An ObstacleResponseHandler presents response options (Emergency Landing, Return to Home, Avoid & Continue, Manual Override) via a pluggable ResponseProvider protocol. This follows the Pure Core pattern: raw sensor data separated from business logic interpretation.

**Tech Stack:** Python 3.13, FastMCP 3.x, djitellopy, Pydantic v2, pytest + pytest-asyncio, structlog

**Spec:** `docs/superpowers/specs/2026-03-16-forward-tof-design.md`

**Chunk dependencies:** Chunk 1 → Chunk 2 → Chunk 3 → Chunk 4. Each chunk depends on the previous.

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `packages/tello-core/src/tello_core/models.py` | Add `forward_tof_mm` to TelemetryFrame, new ObstacleZone enum, ObstacleReading model | Modify |
| `packages/tello-core/src/tello_core/__init__.py` | Re-export ObstacleZone, ObstacleReading | Modify |
| `packages/tello-core/tests/test_models.py` | Tests for new/updated models | Modify |
| `services/tello-mcp/src/tello_mcp/drone.py` | Add `get_forward_distance()`, update `get_telemetry()` | Modify |
| `services/tello-mcp/src/tello_mcp/obstacle.py` | New: ObstacleConfig, ObstacleMonitor, ObstacleResponseHandler, ResponseProvider, providers | Create |
| `services/tello-mcp/src/tello_mcp/tools/sensors.py` | Add `get_forward_distance` + `get_obstacle_status` tools, update `get_tof_distance` docstring | Modify |
| `services/tello-mcp/src/tello_mcp/server.py` | Create ObstacleMonitor in lifespan, pass to context | Modify |
| `scripts/fly.py` | Add `tof` + `monitor` commands, DANGER options menu | Modify |
| `services/tello-mcp/tests/test_drone.py` | Tests for `get_forward_distance()` and updated `get_telemetry()` | Modify |
| `services/tello-mcp/tests/test_obstacle.py` | New: Tests for ObstacleMonitor, ObstacleConfig, ObstacleResponseHandler | Create |
| `services/tello-mcp/tests/test_tools/test_sensors.py` | Tests for new sensor tools | Modify |

---

## Chunk 1: Data Models + DroneAdapter Raw Sensor

### Task 1: Add ObstacleZone and ObstacleReading to tello-core models

**Files:**
- Modify: `packages/tello-core/src/tello_core/models.py:7-9` (imports), after line 35 (new models)
- Modify: `packages/tello-core/tests/test_models.py`

- [ ] **Step 1: Write failing tests for new models**

Add to imports at top of `packages/tello-core/tests/test_models.py`:

```python
from tello_core.models import ObstacleReading, ObstacleZone
```

Add new test classes at end of file:

```python
class TestObstacleZone:
    def test_zone_values(self):
        assert ObstacleZone.CLEAR == "clear"
        assert ObstacleZone.CAUTION == "caution"
        assert ObstacleZone.WARNING == "warning"
        assert ObstacleZone.DANGER == "danger"

    def test_zone_is_str_enum(self):
        assert isinstance(ObstacleZone.DANGER, str)


class TestObstacleReading:
    def test_valid_reading(self):
        reading = ObstacleReading(
            distance_mm=450,
            zone=ObstacleZone.WARNING,
            timestamp=datetime(2026, 3, 16, 14, 0, 0),
        )
        assert reading.distance_mm == 450
        assert reading.zone == ObstacleZone.WARNING
        assert reading.classification is None
        assert reading.confidence is None

    def test_with_classification(self):
        reading = ObstacleReading(
            distance_mm=300,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 16, 14, 0, 0),
            classification="person",
            confidence=0.92,
        )
        assert reading.classification == "person"
        assert reading.confidence == 0.92

    def test_serialization_roundtrip(self):
        reading = ObstacleReading(
            distance_mm=1200,
            zone=ObstacleZone.CAUTION,
            timestamp=datetime(2026, 3, 16, 14, 0, 0),
        )
        data = reading.model_dump()
        assert data["zone"] == "caution"
        assert data["distance_mm"] == 1200
        restored = ObstacleReading.model_validate(data)
        assert restored == reading
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package tello-core pytest packages/tello-core/tests/test_models.py::TestObstacleZone -v`
Expected: FAIL — `ImportError: cannot import name 'ObstacleZone'`

- [ ] **Step 3: Add ObstacleZone and ObstacleReading to models.py**

In `packages/tello-core/src/tello_core/models.py`, add after the `TelemetryFrame` class (after line 35). Add an `# -- Obstacle Detection --` section comment for consistency with existing section headers:

```python
# ── Obstacle Detection ───────────────────────────────────────────────


class ObstacleZone(StrEnum):
    """Tiered obstacle detection zones."""

    CLEAR = "clear"
    CAUTION = "caution"
    WARNING = "warning"
    DANGER = "danger"


class ObstacleReading(BaseModel):
    """Interpreted forward ToF sensor reading with zone classification.

    Phase 5 extension: classification and confidence fields
    allow vision enrichment without model changes.
    """

    distance_mm: int
    zone: ObstacleZone
    timestamp: datetime
    classification: str | None = None
    confidence: float | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package tello-core pytest packages/tello-core/tests/test_models.py::TestObstacleZone packages/tello-core/tests/test_models.py::TestObstacleReading -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add packages/tello-core/src/tello_core/models.py packages/tello-core/tests/test_models.py
git commit -m "feat(tello-core): add ObstacleZone enum and ObstacleReading model"
```

---

### Task 2: Add forward_tof_mm to TelemetryFrame

**Files:**
- Modify: `packages/tello-core/src/tello_core/models.py:24-35` (TelemetryFrame)
- Modify: `packages/tello-core/tests/test_models.py` (TestTelemetryFrame)

- [ ] **Step 1: Write failing test for forward_tof_mm field**

Add to `TestTelemetryFrame` class in `packages/tello-core/tests/test_models.py`:

```python
    def test_forward_tof_mm_defaults_to_none(self):
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
        assert frame.forward_tof_mm is None

    def test_forward_tof_mm_with_value(self):
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
            forward_tof_mm=1250,
        )
        assert frame.forward_tof_mm == 1250

    def test_forward_tof_mm_out_of_range_value(self):
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
            forward_tof_mm=8192,
        )
        assert frame.forward_tof_mm == 8192
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package tello-core pytest packages/tello-core/tests/test_models.py::TestTelemetryFrame::test_forward_tof_mm_defaults_to_none -v`
Expected: FAIL — `TypeError: unexpected keyword argument 'forward_tof_mm'` or the `None` assertion fails

- [ ] **Step 3: Add forward_tof_mm to TelemetryFrame**

In `packages/tello-core/src/tello_core/models.py`, add after line 35 (`timestamp: datetime`):

```python
    forward_tof_mm: int | None = None
```

- [ ] **Step 4: Run all TelemetryFrame tests**

Run: `uv run --package tello-core pytest packages/tello-core/tests/test_models.py::TestTelemetryFrame -v`
Expected: All PASSED (existing tests still pass because `forward_tof_mm` defaults to `None`)

- [ ] **Step 5: Commit**

```bash
git add packages/tello-core/src/tello_core/models.py packages/tello-core/tests/test_models.py
git commit -m "feat(tello-core): add forward_tof_mm field to TelemetryFrame"
```

---

### Task 3: Re-export new models from tello_core __init__.py

**Files:**
- Modify: `packages/tello-core/src/tello_core/__init__.py:15-28` (imports), `32-56` (__all__)

- [ ] **Step 1: Update __init__.py re-exports**

In `packages/tello-core/src/tello_core/__init__.py`, add to the imports from `tello_core.models` (keep alphabetically sorted):

```python
    ObstacleReading,
    ObstacleZone,
```

And add to `__all__` (keep alphabetically sorted):

```python
    "ObstacleReading",
    "ObstacleZone",
```

- [ ] **Step 2: Verify import works**

Run: `uv run --package tello-core python -c "from tello_core import ObstacleZone, ObstacleReading; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Run all tello-core tests to confirm nothing broke**

Run: `uv run --package tello-core pytest packages/tello-core/tests/ -v`
Expected: All PASSED (57+ tests)

- [ ] **Step 4: Commit**

```bash
git add packages/tello-core/src/tello_core/__init__.py
git commit -m "feat(tello-core): re-export ObstacleZone and ObstacleReading"
```

---

### Task 4: Add DroneAdapter.get_forward_distance()

**Files:**
- Modify: `services/tello-mcp/src/tello_mcp/drone.py` (add method after line 255, before `set_led` at line 257)
- Modify: `services/tello-mcp/tests/test_drone.py`

- [ ] **Step 1: Write failing tests for get_forward_distance**

Add to `TestDroneAdapter` class in `services/tello-mcp/tests/test_drone.py`:

```python
    def test_get_forward_distance_success(self, mock_drone):
        mock_drone.send_expansion_command.return_value = "1245"
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            # Reset mock from connect() expansion calls
            mock_drone.send_expansion_command.reset_mock()
            result = adapter.get_forward_distance()
            mock_drone.send_expansion_command.assert_called_once_with("tof?")
            assert result["status"] == "ok"
            assert result["distance_mm"] == 1245

    def test_get_forward_distance_out_of_range(self, mock_drone):
        mock_drone.send_expansion_command.return_value = "8192"
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            mock_drone.send_expansion_command.reset_mock()
            result = adapter.get_forward_distance()
            assert result["status"] == "ok"
            assert result["distance_mm"] == 8192

    def test_get_forward_distance_parse_error(self, mock_drone):
        mock_drone.send_expansion_command.return_value = "error"
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.get_forward_distance()
            assert result["error"] == "PARSE_ERROR"

    def test_get_forward_distance_command_failed(self, mock_drone):
        mock_drone.send_expansion_command.side_effect = Exception("timeout")
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            result = adapter.get_forward_distance()
            assert result["error"] == "COMMAND_FAILED"

    def test_get_forward_distance_when_not_connected(self):
        with patch("tello_mcp.drone.Tello"):
            adapter = DroneAdapter()
            result = adapter.get_forward_distance()
            assert result["error"] == "DRONE_NOT_CONNECTED"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_drone.py::TestDroneAdapter::test_get_forward_distance_success -v`
Expected: FAIL — `AttributeError: 'DroneAdapter' object has no attribute 'get_forward_distance'`

- [ ] **Step 3: Implement get_forward_distance in DroneAdapter**

In `services/tello-mcp/src/tello_mcp/drone.py`, add after the `go_xyz_speed_mid` method (after line 255) and before `set_led` (line 257):

```python
    def get_forward_distance(self) -> dict:
        """Query the forward-facing ToF sensor on the Dot-Matrix Module.

        Returns distance in mm, or 8192 if out of range.
        Uses EXT tof? command via the Open-Source Controller (ESP32).
        """
        if err := self._require_connection():
            return err
        try:
            response = self._tello.send_expansion_command("tof?")
            distance_mm = int(response)
            return {"status": "ok", "distance_mm": distance_mm}
        except (ValueError, TypeError):
            logger.exception("forward_tof.parse_failed", response=response)
            return {"error": "PARSE_ERROR", "detail": f"Unexpected response: {response}"}
        except Exception as e:
            logger.exception("forward_tof.query_failed")
            return {"error": "COMMAND_FAILED", "detail": str(e)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_drone.py -k "forward_distance" -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/drone.py services/tello-mcp/tests/test_drone.py
git commit -m "feat(tello-mcp): add DroneAdapter.get_forward_distance()"
```

---

### Task 5: Update DroneAdapter.get_telemetry() to include forward_tof_mm

**Files:**
- Modify: `services/tello-mcp/src/tello_mcp/drone.py:192-214` (get_telemetry)
- Modify: `services/tello-mcp/tests/test_drone.py`

- [ ] **Step 1: Write failing tests for updated get_telemetry**

Add to `TestDroneAdapter` class in `services/tello-mcp/tests/test_drone.py`:

```python
    def test_get_telemetry_includes_forward_tof(self, mock_drone):
        mock_drone.send_expansion_command.return_value = "750"
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            frame = adapter.get_telemetry()
            assert frame.forward_tof_mm == 750

    def test_get_telemetry_forward_tof_none_on_failure(self, mock_drone):
        mock_drone.send_expansion_command.return_value = "error"
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            frame = adapter.get_telemetry()
            assert frame.forward_tof_mm is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_drone.py::TestDroneAdapter::test_get_telemetry_includes_forward_tof -v`
Expected: FAIL — `forward_tof_mm` is `None` because `get_telemetry()` doesn't call `get_forward_distance()` yet

- [ ] **Step 3: Update get_telemetry to include forward distance**

In `services/tello-mcp/src/tello_mcp/drone.py`, replace the try block inside `get_telemetry` (lines 200-211):

```python
        try:
            forward_result = self.get_forward_distance()
            forward_mm = (
                forward_result["distance_mm"]
                if forward_result.get("status") == "ok"
                else None
            )
            return TelemetryFrame(
                battery_pct=self._tello.get_battery(),
                height_cm=self._tello.get_height(),
                tof_cm=self._tello.get_distance_tof(),
                temp_c=float(self._tello.get_temperature()),
                pitch=float(self._tello.get_pitch()),
                roll=float(self._tello.get_roll()),
                yaw=float(self._tello.get_yaw()),
                flight_time_s=self._tello.get_flight_time(),
                timestamp=datetime.now(tz=UTC),
                forward_tof_mm=forward_mm,
            )
        except Exception as e:
            logger.exception("get_telemetry failed")
            return {"error": "TELEMETRY_FAILED", "detail": str(e)}
```

- [ ] **Step 4: Run all drone tests to verify nothing broke**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_drone.py -v`
Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/drone.py services/tello-mcp/tests/test_drone.py
git commit -m "feat(tello-mcp): include forward_tof_mm in telemetry"
```

---

## Chunk 2: ObstacleMonitor + ObstacleConfig

**Depends on:** Chunk 1 (ObstacleZone and ObstacleReading must exist in tello-core)

### Task 6: Create ObstacleConfig with from_env

**Files:**
- Create: `services/tello-mcp/src/tello_mcp/obstacle.py`
- Create: `services/tello-mcp/tests/test_obstacle.py`

- [ ] **Step 1: Write failing tests for ObstacleConfig**

Create `services/tello-mcp/tests/test_obstacle.py`:

```python
"""Tests for ObstacleMonitor, ObstacleConfig, and ObstacleResponseHandler."""

from __future__ import annotations

import pytest

from tello_mcp.obstacle import ObstacleConfig


class TestObstacleConfig:
    def test_default_values(self):
        config = ObstacleConfig()
        assert config.caution_mm == 1500
        assert config.warning_mm == 800
        assert config.danger_mm == 400
        assert config.out_of_range == 8192
        assert config.poll_interval_ms == 200

    def test_custom_values(self):
        config = ObstacleConfig(danger_mm=500, poll_interval_ms=100)
        assert config.danger_mm == 500
        assert config.poll_interval_ms == 100
        assert config.caution_mm == 1500  # unchanged default

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("OBSTACLE_DANGER_MM", "500")
        monkeypatch.setenv("OBSTACLE_POLL_INTERVAL_MS", "100")
        config = ObstacleConfig.from_env()
        assert config.danger_mm == 500
        assert config.poll_interval_ms == 100
        assert config.caution_mm == 1500  # default

    def test_from_env_no_vars(self):
        config = ObstacleConfig.from_env()
        assert config.danger_mm == 400  # default

    def test_frozen(self):
        config = ObstacleConfig()
        with pytest.raises(AttributeError):
            config.danger_mm = 999
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestObstacleConfig -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tello_mcp.obstacle'`

- [ ] **Step 3: Create obstacle.py with ObstacleConfig**

Create `services/tello-mcp/src/tello_mcp/obstacle.py`:

```python
"""Obstacle detection and safety enforcement.

ObstacleConfig: configurable thresholds for tiered zone detection.
ObstacleMonitor: continuous forward ToF polling with safety stops.
ObstacleResponseHandler: options menu when obstacle forces a stop.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

import structlog

from tello_core.models import ObstacleReading, ObstacleZone
from tello_mcp.drone import DroneAdapter

logger = structlog.get_logger("tello_mcp.obstacle")


@dataclass(frozen=True, slots=True)
class ObstacleConfig:
    """Configuration for obstacle detection thresholds.

    Overridable via environment variables:
        OBSTACLE_CAUTION_MM, OBSTACLE_WARNING_MM, OBSTACLE_DANGER_MM,
        OBSTACLE_OUT_OF_RANGE, OBSTACLE_POLL_INTERVAL_MS
    """

    caution_mm: int = 1500
    warning_mm: int = 800
    danger_mm: int = 400
    out_of_range: int = 8192
    poll_interval_ms: int = 200

    @classmethod
    def from_env(cls) -> ObstacleConfig:
        """Load config from environment, falling back to defaults."""
        env_map = {
            "caution_mm": "OBSTACLE_CAUTION_MM",
            "warning_mm": "OBSTACLE_WARNING_MM",
            "danger_mm": "OBSTACLE_DANGER_MM",
            "out_of_range": "OBSTACLE_OUT_OF_RANGE",
            "poll_interval_ms": "OBSTACLE_POLL_INTERVAL_MS",
        }
        kwargs: dict[str, int] = {}
        for field, env_var in env_map.items():
            val = os.environ.get(env_var)
            if val is not None:
                kwargs[field] = int(val)
        return cls(**kwargs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestObstacleConfig -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/obstacle.py services/tello-mcp/tests/test_obstacle.py
git commit -m "feat(tello-mcp): add ObstacleConfig with env var overrides"
```

---

### Task 7: Implement ObstacleMonitor.classify_zone (pure function)

**Files:**
- Modify: `services/tello-mcp/src/tello_mcp/obstacle.py`
- Modify: `services/tello-mcp/tests/test_obstacle.py`

- [ ] **Step 1: Write failing tests for classify_zone**

Add to `services/tello-mcp/tests/test_obstacle.py`:

```python
from unittest.mock import MagicMock

from tello_core.models import ObstacleZone

from tello_mcp.obstacle import ObstacleConfig, ObstacleMonitor


class TestClassifyZone:
    """Tests for the pure zone classification function."""

    def setup_method(self):
        self.config = ObstacleConfig()
        self.monitor = ObstacleMonitor(MagicMock(), self.config)

    def test_out_of_range_is_clear(self):
        assert self.monitor.classify_zone(8192) == ObstacleZone.CLEAR

    def test_above_caution_is_clear(self):
        assert self.monitor.classify_zone(2000) == ObstacleZone.CLEAR

    def test_at_caution_boundary_is_clear(self):
        assert self.monitor.classify_zone(1500) == ObstacleZone.CLEAR

    def test_below_caution_is_caution(self):
        assert self.monitor.classify_zone(1499) == ObstacleZone.CAUTION

    def test_at_warning_boundary_is_caution(self):
        assert self.monitor.classify_zone(800) == ObstacleZone.CAUTION

    def test_below_warning_is_warning(self):
        assert self.monitor.classify_zone(799) == ObstacleZone.WARNING

    def test_at_danger_boundary_is_warning(self):
        assert self.monitor.classify_zone(400) == ObstacleZone.WARNING

    def test_below_danger_is_danger(self):
        assert self.monitor.classify_zone(399) == ObstacleZone.DANGER

    def test_zero_is_danger(self):
        assert self.monitor.classify_zone(0) == ObstacleZone.DANGER

    def test_custom_thresholds(self):
        config = ObstacleConfig(caution_mm=1000, warning_mm=500, danger_mm=200)
        monitor = ObstacleMonitor(MagicMock(), config)
        assert monitor.classify_zone(999) == ObstacleZone.CAUTION
        assert monitor.classify_zone(499) == ObstacleZone.WARNING
        assert monitor.classify_zone(199) == ObstacleZone.DANGER
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestClassifyZone -v`
Expected: FAIL — `ImportError: cannot import name 'ObstacleMonitor'`

- [ ] **Step 3: Add ObstacleMonitor class with classify_zone**

Add to `services/tello-mcp/src/tello_mcp/obstacle.py` after `ObstacleConfig`:

```python
class ObstacleMonitor:
    """Continuous forward ToF monitoring with tiered zone enforcement.

    Polls the forward-facing ToF sensor at a configurable interval,
    classifies distance into zones (CLEAR/CAUTION/WARNING/DANGER),
    and enforces a forced stop in the DANGER zone.
    """

    def __init__(self, drone: DroneAdapter, config: ObstacleConfig | None = None) -> None:
        self._drone = drone
        self._config = config or ObstacleConfig()
        self._latest: ObstacleReading | None = None
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._callbacks: list[Callable[[ObstacleReading], None | Awaitable[None]]] = []

    def classify_zone(self, distance_mm: int) -> ObstacleZone:
        """Classify a distance reading into an obstacle zone.

        Pure function — no I/O, no side effects.
        """
        if distance_mm >= self._config.out_of_range:
            return ObstacleZone.CLEAR
        if distance_mm < self._config.danger_mm:
            return ObstacleZone.DANGER
        if distance_mm < self._config.warning_mm:
            return ObstacleZone.WARNING
        if distance_mm < self._config.caution_mm:
            return ObstacleZone.CAUTION
        return ObstacleZone.CLEAR

    @property
    def latest(self) -> ObstacleReading | None:
        """Most recent obstacle reading, or None if not yet polled."""
        return self._latest

    @property
    def config(self) -> ObstacleConfig:
        """Current obstacle configuration."""
        return self._config

    @property
    def is_running(self) -> bool:
        """Whether the monitor is actively polling."""
        return self._running

    def on_reading(self, callback: Callable[[ObstacleReading], None | Awaitable[None]]) -> None:
        """Subscribe to obstacle readings."""
        self._callbacks.append(callback)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestClassifyZone -v`
Expected: 11 PASSED

- [ ] **Step 5: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/obstacle.py services/tello-mcp/tests/test_obstacle.py
git commit -m "feat(tello-mcp): add ObstacleMonitor with classify_zone"
```

---

### Task 8: Implement ObstacleMonitor poll loop and lifecycle

**Files:**
- Modify: `services/tello-mcp/src/tello_mcp/obstacle.py`
- Modify: `services/tello-mcp/tests/test_obstacle.py`

- [ ] **Step 1: Write failing tests for poll loop**

Add to `services/tello-mcp/tests/test_obstacle.py`:

```python
import asyncio
from unittest.mock import AsyncMock


class TestObstacleMonitorLifecycle:
    async def test_start_is_idempotent(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 8192}
        monitor = ObstacleMonitor(drone, ObstacleConfig(poll_interval_ms=50))
        await monitor.start()
        task1 = monitor._task
        await monitor.start()  # second call
        assert monitor._task is task1  # same task
        await monitor.stop()

    async def test_stop_when_not_started(self):
        drone = MagicMock()
        monitor = ObstacleMonitor(drone)
        await monitor.stop()  # should not raise


class TestObstacleMonitorPolling:
    async def test_poll_caches_latest_reading(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 1200}
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)
        await monitor.start()
        await asyncio.sleep(0.15)  # allow a few polls
        await monitor.stop()
        assert monitor.latest is not None
        assert monitor.latest.distance_mm == 1200
        assert monitor.latest.zone == ObstacleZone.CAUTION

    async def test_danger_zone_calls_stop(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 200}
        drone.stop = MagicMock(return_value={"status": "ok"})
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)
        await monitor.start()
        await asyncio.sleep(0.15)
        await monitor.stop()
        drone.stop.assert_called()

    async def test_clear_zone_does_not_call_stop(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 8192}
        drone.stop = MagicMock()
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)
        await monitor.start()
        await asyncio.sleep(0.15)
        await monitor.stop()
        drone.stop.assert_not_called()

    async def test_sensor_error_skips_reading(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"error": "COMMAND_FAILED", "detail": "timeout"}
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)
        await monitor.start()
        await asyncio.sleep(0.15)
        await monitor.stop()
        assert monitor.latest is None

    async def test_sync_callback_invoked(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 500}
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)
        readings: list = []
        monitor.on_reading(lambda r: readings.append(r))
        await monitor.start()
        await asyncio.sleep(0.15)
        await monitor.stop()
        assert len(readings) > 0
        assert readings[0].distance_mm == 500

    async def test_async_callback_invoked(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 600}
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)
        readings: list = []

        async def async_cb(r):
            readings.append(r)

        monitor.on_reading(async_cb)
        await monitor.start()
        await asyncio.sleep(0.15)
        await monitor.stop()
        assert len(readings) > 0
        assert readings[0].distance_mm == 600
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestObstacleMonitorPolling services/tello-mcp/tests/test_obstacle.py::TestObstacleMonitorLifecycle -v`
Expected: FAIL — `AttributeError: 'ObstacleMonitor' object has no attribute 'start'`

- [ ] **Step 3: Implement start, stop, and _poll_loop**

Add to the `ObstacleMonitor` class in `services/tello-mcp/src/tello_mcp/obstacle.py`:

```python
    async def start(self) -> None:
        """Start the background polling loop. Idempotent."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("obstacle_monitor.started", poll_interval_ms=self._config.poll_interval_ms)

    async def stop(self) -> None:
        """Stop the background polling loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("obstacle_monitor.stopped")

    async def _poll_loop(self) -> None:
        """Background task: poll forward ToF and enforce safety zones."""
        while self._running:
            result = await asyncio.to_thread(self._drone.get_forward_distance)
            if result.get("status") == "ok":
                distance_mm = result["distance_mm"]
                zone = self.classify_zone(distance_mm)
                reading = ObstacleReading(
                    distance_mm=distance_mm,
                    zone=zone,
                    timestamp=datetime.now(UTC),
                )
                self._latest = reading

                if zone == ObstacleZone.DANGER:
                    logger.warning("obstacle.danger", distance_mm=distance_mm)
                    await asyncio.to_thread(self._drone.stop)

                for cb in self._callbacks:
                    cb_result = cb(reading)
                    if asyncio.iscoroutine(cb_result):
                        await cb_result

            await asyncio.sleep(self._config.poll_interval_ms / 1000)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py -v`
Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/obstacle.py services/tello-mcp/tests/test_obstacle.py
git commit -m "feat(tello-mcp): implement ObstacleMonitor poll loop and lifecycle"
```

---

## Chunk 3: MCP Tools + Server Integration + fly.py CLI

**Depends on:** Chunk 2 (ObstacleMonitor must exist)

### Task 9: Add MCP sensor tools and update existing docstring

**Files:**
- Modify: `services/tello-mcp/src/tello_mcp/tools/sensors.py`
- Modify: `services/tello-mcp/tests/test_tools/test_sensors.py`

- [ ] **Step 1: Write failing tests for new tools**

Add to `TestSensorTools` class in `services/tello-mcp/tests/test_tools/test_sensors.py`:

```python
    def test_get_forward_distance_registered(self):
        assert "get_forward_distance" in self.registered_tools

    def test_get_obstacle_status_registered(self):
        assert "get_obstacle_status" in self.registered_tools

    async def test_get_forward_distance_returns_reading(self):
        from datetime import datetime
        from unittest.mock import MagicMock

        from tello_core.models import ObstacleReading, ObstacleZone

        mock_monitor = MagicMock()
        mock_monitor.latest = ObstacleReading(
            distance_mm=750,
            zone=ObstacleZone.WARNING,
            timestamp=datetime(2026, 3, 16, 14, 0, 0),
        )
        ctx = MagicMock()
        ctx.lifespan_context = {"monitor": mock_monitor, "drone": MagicMock()}
        tool_fn = self.registered_tools["get_forward_distance"]
        result = await tool_fn(ctx)
        assert result["distance_mm"] == 750
        assert result["zone"] == "warning"

    async def test_get_forward_distance_no_reading(self):
        from unittest.mock import MagicMock

        mock_monitor = MagicMock()
        mock_monitor.latest = None
        ctx = MagicMock()
        ctx.lifespan_context = {"monitor": mock_monitor}
        tool_fn = self.registered_tools["get_forward_distance"]
        result = await tool_fn(ctx)
        assert result["error"] == "NO_READING"

    async def test_get_obstacle_status_safe(self):
        from datetime import datetime
        from unittest.mock import MagicMock

        from tello_core.models import ObstacleReading, ObstacleZone

        mock_monitor = MagicMock()
        mock_monitor.latest = ObstacleReading(
            distance_mm=2000,
            zone=ObstacleZone.CLEAR,
            timestamp=datetime(2026, 3, 16, 14, 0, 0),
        )
        ctx = MagicMock()
        ctx.lifespan_context = {"monitor": mock_monitor}
        tool_fn = self.registered_tools["get_obstacle_status"]
        result = await tool_fn(ctx)
        assert result["zone"] == "clear"
        assert result["is_safe"] is True

    async def test_get_obstacle_status_danger(self):
        from datetime import datetime
        from unittest.mock import MagicMock

        from tello_core.models import ObstacleReading, ObstacleZone

        mock_monitor = MagicMock()
        mock_monitor.latest = ObstacleReading(
            distance_mm=300,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 16, 14, 0, 0),
        )
        ctx = MagicMock()
        ctx.lifespan_context = {"monitor": mock_monitor}
        tool_fn = self.registered_tools["get_obstacle_status"]
        result = await tool_fn(ctx)
        assert result["zone"] == "danger"
        assert result["is_safe"] is False

    async def test_get_obstacle_status_no_sensor(self):
        from unittest.mock import MagicMock

        mock_monitor = MagicMock()
        mock_monitor.latest = None
        ctx = MagicMock()
        ctx.lifespan_context = {"monitor": mock_monitor}
        tool_fn = self.registered_tools["get_obstacle_status"]
        result = await tool_fn(ctx)
        assert result["zone"] == "unknown"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_tools/test_sensors.py -v`
Expected: Registration tests FAIL, behavioral tests FAIL

- [ ] **Step 3: Add new tools and update docstring**

Update `services/tello-mcp/src/tello_mcp/tools/sensors.py` to match the following (adds `ObstacleZone` import, two new tool functions, updates `get_tof_distance` docstring — existing tools unchanged):

```python
"""Sensor and state MCP tools (read-only)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import Context
from mcp.types import ToolAnnotations

from tello_core.models import ObstacleZone

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register sensor tools on the MCP server."""

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_telemetry(ctx: Context) -> dict:
        """Get current telemetry: battery, height, ToF, attitude, temp, flight time."""
        drone = ctx.lifespan_context["drone"]
        result = drone.get_telemetry()
        if isinstance(result, dict):
            return result
        return result.model_dump()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_tof_distance(ctx: Context) -> dict:
        """Get DOWNWARD Time-of-Flight distance in cm (built-in Vision Positioning System).

        This is the drone's built-in downward-facing sensor for altitude/ground distance.
        For forward obstacle detection, use get_forward_distance instead.
        """
        drone = ctx.lifespan_context["drone"]
        result = drone.get_telemetry()
        if isinstance(result, dict):
            return result
        return {"tof_cm": result.tof_cm}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def detect_mission_pad(ctx: Context) -> dict:
        """Scan for the nearest mission pad. Returns pad ID or -1 if none detected."""
        drone = ctx.lifespan_context["drone"]
        return drone.detect_mission_pad()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_forward_distance(ctx: Context) -> dict:
        """Get forward-facing ToF distance in mm (Dot-Matrix Module sensor).

        Returns distance to nearest obstacle ahead. 8192 means nothing detected.
        Includes obstacle zone classification (CLEAR/CAUTION/WARNING/DANGER).
        """
        monitor = ctx.lifespan_context["monitor"]
        latest = monitor.latest
        if latest is None:
            return {"error": "NO_READING", "detail": "Forward ToF not yet polled or sensor unavailable"}
        return latest.model_dump()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_obstacle_status(ctx: Context) -> dict:
        """Check if the path ahead is clear. Returns zone and distance.

        Zones: CLEAR (safe), CAUTION (<150cm), WARNING (<80cm), DANGER (<40cm).
        In DANGER zone, the drone has already been stopped automatically.
        """
        monitor = ctx.lifespan_context["monitor"]
        latest = monitor.latest
        if latest is None:
            return {"zone": "unknown", "detail": "Sensor unavailable"}
        return {
            "zone": latest.zone.value,
            "distance_mm": latest.distance_mm,
            "is_safe": latest.zone in (ObstacleZone.CLEAR, ObstacleZone.CAUTION),
            "timestamp": latest.timestamp.isoformat(),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_tools/test_sensors.py -v`
Expected: All PASSED (3 existing + 7 new = 10 tests)

- [ ] **Step 5: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/tools/sensors.py services/tello-mcp/tests/test_tools/test_sensors.py
git commit -m "feat(tello-mcp): add forward distance and obstacle status MCP tools"
```

---

### Task 10: Integrate ObstacleMonitor into server lifespan

**Files:**
- Modify: `services/tello-mcp/src/tello_mcp/server.py:19-20` (imports), `46-85` (lifespan)

- [ ] **Step 1: Update server.py imports**

In `services/tello-mcp/src/tello_mcp/server.py`, add after line 20 (`from tello_mcp.queue import CommandQueue`):

```python
from tello_mcp.obstacle import ObstacleConfig, ObstacleMonitor
```

- [ ] **Step 2: Create ObstacleMonitor in lifespan**

In the `lifespan` function, after `queue = CommandQueue()` (line 47) add:

```python
    obstacle_config = ObstacleConfig.from_env()
    monitor = ObstacleMonitor(drone, obstacle_config)
```

After `keepalive_task = asyncio.create_task(_keepalive_loop(drone))` (line 67) add:

```python
    await monitor.start()
```

Update the `yield` dict (lines 69-75) to include `monitor`:

```python
        yield {
            "drone": drone,
            "queue": queue,
            "redis": redis,
            "telemetry": telemetry,
            "config": config,
            "monitor": monitor,
        }
```

In the `finally` block, add before `keepalive_task.cancel()` (line 77):

```python
        await monitor.stop()
```

- [ ] **Step 3: Run all tello-mcp tests**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/ -v`
Expected: All PASSED

- [ ] **Step 4: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/server.py
git commit -m "feat(tello-mcp): integrate ObstacleMonitor into server lifespan"
```

---

### Task 11: Add tof and monitor commands to fly.py

**Files:**
- Modify: `scripts/fly.py:42-128` (run_command), `132-136` (repl help text), `1-24` (docstring)

- [ ] **Step 1: Add imports at top of fly.py**

Add after the existing imports (after line 32 `from tello_mcp.drone import DroneAdapter`):

```python
from tello_mcp.obstacle import ObstacleConfig, ObstacleMonitor
```

- [ ] **Step 2: Add tof and monitor commands to run_command**

In `scripts/fly.py`, add new cases after the `battery` case (after line 119, before `case "quit"`):

```python
        case "tof":
            result = drone.get_forward_distance()
            if result.get("status") == "ok":
                mm = result["distance_mm"]
                config = ObstacleConfig.from_env()
                monitor = ObstacleMonitor(drone, config)
                zone = monitor.classify_zone(mm)
                suffix = " -- drone stopped" if zone.value == "danger" else ""
                print(f"Forward ToF: {mm}mm ({zone.value.upper()}){suffix}")
            else:
                print(f"Forward ToF error: {result}")

        case "monitor":
            config = ObstacleConfig.from_env()
            print("Obstacle monitor config:")
            print(f"  Thresholds: CAUTION <{config.caution_mm}mm, WARNING <{config.warning_mm}mm, DANGER <{config.danger_mm}mm")
            print(f"  Out of range: {config.out_of_range}mm")
            print(f"  Poll interval: {config.poll_interval_ms}ms")
            print("  Note: Continuous monitoring runs inside the MCP server.")
            print("  Use 'tof' for a one-shot forward distance reading.")
```

- [ ] **Step 3: Update help text**

Update the help text in `run_command` default case (lines 126-127) and `repl` function (lines 135-136):

```python
            print("Commands: connect, telemetry, takeoff, land, emergency, move, rotate,")
            print("          led, text, pad, goto, battery, tof, monitor, quit")
```

Update the docstring at the top of the file to add these lines:

```
    tof                   Forward ToF sensor reading (mm)
    monitor               Obstacle monitor config and status
```

- [ ] **Step 4: Test fly.py parses without errors**

Run: `uv run python scripts/fly.py --help`
Expected: Shows help with new commands listed

- [ ] **Step 5: Commit**

```bash
git add scripts/fly.py
git commit -m "feat(fly.py): add tof and monitor CLI commands"
```

---

## Chunk 4: Phase 4a — Obstacle Response System

**Depends on:** Chunk 3 (ObstacleMonitor integrated, MCP tools exist)

### Task 12: Add ObstacleResponse enum and ObstacleResponseHandler

**Files:**
- Modify: `services/tello-mcp/src/tello_mcp/obstacle.py`
- Modify: `services/tello-mcp/tests/test_obstacle.py`

- [ ] **Step 1: Write failing tests for ObstacleResponseHandler**

Add to `services/tello-mcp/tests/test_obstacle.py`:

```python
from tello_mcp.obstacle import ObstacleResponse, ObstacleResponseHandler


class TestObstacleResponse:
    def test_response_values(self):
        assert ObstacleResponse.EMERGENCY_LAND == "emergency_land"
        assert ObstacleResponse.RETURN_TO_HOME == "return_to_home"
        assert ObstacleResponse.AVOID_AND_CONTINUE == "avoid_and_continue"
        assert ObstacleResponse.MANUAL_OVERRIDE == "manual_override"


class TestObstacleResponseHandler:
    async def test_execute_emergency_land(self):
        drone = MagicMock()
        drone.safe_land.return_value = {"status": "ok"}
        handler = ObstacleResponseHandler(drone)
        result = await handler.execute(ObstacleResponse.EMERGENCY_LAND)
        drone.safe_land.assert_called_once()
        assert result["status"] == "ok"

    async def test_execute_manual_override(self):
        drone = MagicMock()
        handler = ObstacleResponseHandler(drone)
        result = await handler.execute(ObstacleResponse.MANUAL_OVERRIDE)
        assert result["status"] == "ok"

    async def test_execute_return_to_home_not_implemented(self):
        drone = MagicMock()
        handler = ObstacleResponseHandler(drone)
        result = await handler.execute(ObstacleResponse.RETURN_TO_HOME)
        assert result["error"] == "NOT_IMPLEMENTED"

    async def test_execute_avoid_and_continue_not_implemented(self):
        drone = MagicMock()
        handler = ObstacleResponseHandler(drone)
        result = await handler.execute(ObstacleResponse.AVOID_AND_CONTINUE)
        assert result["error"] == "NOT_IMPLEMENTED"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestObstacleResponseHandler -v`
Expected: FAIL — `ImportError: cannot import name 'ObstacleResponse'`

- [ ] **Step 3: Implement ObstacleResponse and ObstacleResponseHandler**

Add to `services/tello-mcp/src/tello_mcp/obstacle.py` after the `ObstacleMonitor` class:

```python
class ObstacleResponse(StrEnum):
    """Available responses when an obstacle forces a stop."""

    EMERGENCY_LAND = "emergency_land"
    RETURN_TO_HOME = "return_to_home"
    AVOID_AND_CONTINUE = "avoid_and_continue"
    MANUAL_OVERRIDE = "manual_override"


class ObstacleResponseHandler:
    """Executes obstacle response actions.

    Phase 4a: emergency_land + manual_override working.
    Phase 4b: return_to_home + avoid_and_continue (navigator integration).
    """

    def __init__(self, drone: DroneAdapter) -> None:
        self._drone = drone

    async def execute(self, choice: ObstacleResponse) -> dict:
        """Execute the chosen obstacle response."""
        match choice:
            case ObstacleResponse.EMERGENCY_LAND:
                return await asyncio.to_thread(self._drone.safe_land)
            case ObstacleResponse.RETURN_TO_HOME:
                return {"error": "NOT_IMPLEMENTED", "detail": "Phase 4b -- requires navigator integration"}
            case ObstacleResponse.AVOID_AND_CONTINUE:
                return {"error": "NOT_IMPLEMENTED", "detail": "Phase 4b -- requires navigator integration"}
            case ObstacleResponse.MANUAL_OVERRIDE:
                logger.info("obstacle.manual_override")
                return {"status": "ok", "detail": "Manual control resumed"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestObstacleResponseHandler services/tello-mcp/tests/test_obstacle.py::TestObstacleResponse -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/obstacle.py services/tello-mcp/tests/test_obstacle.py
git commit -m "feat(tello-mcp): add ObstacleResponseHandler with emergency_land and manual_override"
```

---

### Task 13: Add ResponseProvider protocol and CLIResponseProvider

**Files:**
- Modify: `services/tello-mcp/src/tello_mcp/obstacle.py`
- Modify: `services/tello-mcp/tests/test_obstacle.py`

- [ ] **Step 1: Write failing tests for CLIResponseProvider**

Add to `services/tello-mcp/tests/test_obstacle.py`:

```python
from datetime import datetime

from tello_core.models import ObstacleReading

from tello_mcp.obstacle import CLIResponseProvider


class TestCLIResponseProvider:
    async def test_present_options_emergency_land(self, monkeypatch):
        provider = CLIResponseProvider()
        reading = ObstacleReading(
            distance_mm=350,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 16, 14, 0, 0),
        )
        monkeypatch.setattr("builtins.input", lambda _: "1")
        choice = await provider.present_options(reading)
        assert choice == ObstacleResponse.EMERGENCY_LAND

    async def test_present_options_manual_override(self, monkeypatch):
        provider = CLIResponseProvider()
        reading = ObstacleReading(
            distance_mm=350,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 16, 14, 0, 0),
        )
        monkeypatch.setattr("builtins.input", lambda _: "4")
        choice = await provider.present_options(reading)
        assert choice == ObstacleResponse.MANUAL_OVERRIDE

    async def test_present_options_invalid_then_valid(self, monkeypatch):
        provider = CLIResponseProvider()
        reading = ObstacleReading(
            distance_mm=350,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 16, 14, 0, 0),
        )
        inputs = iter(["invalid", "0", "5", "2"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        choice = await provider.present_options(reading)
        assert choice == ObstacleResponse.RETURN_TO_HOME
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestCLIResponseProvider -v`
Expected: FAIL — `ImportError: cannot import name 'CLIResponseProvider'`

- [ ] **Step 3: Implement ResponseProvider protocol and CLIResponseProvider**

Add to `services/tello-mcp/src/tello_mcp/obstacle.py` after `ObstacleResponseHandler`:

```python
@runtime_checkable
class ResponseProvider(Protocol):
    """How obstacle options are presented to the caller.

    Phase 4a: CLIResponseProvider (fly.py).
    Phase 6: VoiceResponseProvider (verbal options).
    """

    async def present_options(self, reading: ObstacleReading) -> ObstacleResponse: ...


class CLIResponseProvider:
    """Present obstacle response options in a terminal/CLI."""

    _OPTIONS = [
        (ObstacleResponse.EMERGENCY_LAND, "Emergency Landing -- land immediately"),
        (ObstacleResponse.RETURN_TO_HOME, "Return to Home -- navigate back to launch pad (Phase 4b)"),
        (ObstacleResponse.AVOID_AND_CONTINUE, "Avoid & Continue -- dodge obstacle, resume mission (Phase 4b)"),
        (ObstacleResponse.MANUAL_OVERRIDE, "Manual Override -- resume manual control"),
    ]

    async def present_options(self, reading: ObstacleReading) -> ObstacleResponse:
        """Print options and read user choice from stdin."""
        print(f"\nOBSTACLE DETECTED: {reading.distance_mm}mm ({reading.zone.value})")
        print("Drone has been stopped. Choose a response:\n")
        for i, (_, label) in enumerate(self._OPTIONS, 1):
            print(f"  {i}. {label}")
        print()

        while True:
            try:
                raw = input("Select (1-4): ").strip()
                idx = int(raw) - 1
                if 0 <= idx < len(self._OPTIONS):
                    return self._OPTIONS[idx][0]
            except (ValueError, EOFError):
                pass
            print("Invalid selection. Enter 1-4.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestCLIResponseProvider -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/obstacle.py services/tello-mcp/tests/test_obstacle.py
git commit -m "feat(tello-mcp): add ResponseProvider protocol and CLIResponseProvider"
```

---

### Task 14: Wire ObstacleMonitor DANGER callback to fly.py options menu

This task connects the safety pipeline end-to-end: when the monitor detects DANGER during a fly.py session, it presents the options menu.

**Note:** This task **replaces** the `tof` case added in Task 11 with an enhanced version that includes DANGER handling.

**Files:**
- Modify: `scripts/fly.py`

- [ ] **Step 1: Add additional imports at top of fly.py**

Add to the imports section at top of `scripts/fly.py` (alongside the Task 11 imports):

```python
import asyncio
from datetime import UTC, datetime

from tello_core.models import ObstacleReading
from tello_mcp.obstacle import CLIResponseProvider, ObstacleResponseHandler
```

- [ ] **Step 2: Replace the `tof` case with DANGER-aware version**

Replace the `tof` case (added in Task 11) with this enhanced version:

```python
        case "tof":
            result = drone.get_forward_distance()
            if result.get("status") == "ok":
                mm = result["distance_mm"]
                config = ObstacleConfig.from_env()
                temp_monitor = ObstacleMonitor(drone, config)
                zone = temp_monitor.classify_zone(mm)
                print(f"Forward ToF: {mm}mm ({zone.value.upper()})")
                if zone.value == "danger":
                    print("DANGER -- drone stopped.")
                    reading = ObstacleReading(
                        distance_mm=mm,
                        zone=zone,
                        timestamp=datetime.now(UTC),
                    )
                    provider = CLIResponseProvider()
                    choice = asyncio.run(provider.present_options(reading))
                    handler = ObstacleResponseHandler(drone)
                    action_result = asyncio.run(handler.execute(choice))
                    print(f"Action result: {action_result}")
            else:
                print(f"Forward ToF error: {result}")
```

- [ ] **Step 2: Test fly.py still parses without errors**

Run: `uv run python scripts/fly.py --help`
Expected: Shows help without errors

- [ ] **Step 3: Commit**

```bash
git add scripts/fly.py
git commit -m "feat(fly.py): wire DANGER detection to obstacle response menu"
```

---

### Task 15: Full test suite verification and lint

**Files:** All modified files

- [ ] **Step 1: Run full tello-core test suite**

Run: `uv run --package tello-core pytest packages/tello-core/tests/ -v`
Expected: All PASSED (57+ tests + new model tests)

- [ ] **Step 2: Run full tello-mcp test suite**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/ -v`
Expected: All PASSED (79+ existing + new obstacle + new sensor tool tests)

- [ ] **Step 3: Run lint and format**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: No errors

- [ ] **Step 4: Fix any lint/format issues**

Run: `uv run ruff check --fix . && uv run ruff format .`

- [ ] **Step 5: Run all project tests**

Run: `uv run pytest packages/ services/ -v`
Expected: All PASSED (235+ existing + new tests)

- [ ] **Step 6: Commit any lint fixes**

```bash
git add packages/tello-core/src/ packages/tello-core/tests/ services/tello-mcp/src/ services/tello-mcp/tests/ scripts/fly.py
git commit -m "style: lint and format fixes"
```
