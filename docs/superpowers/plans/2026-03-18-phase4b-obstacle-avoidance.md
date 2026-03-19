# Phase 4b: Navigator Obstacle Avoidance — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development
> (if subagents available) or superpowers:executing-plans to implement this plan.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add autonomous obstacle avoidance safety — the drone stops, reverses,
and lands when the forward ToF sensor detects an imminent collision. Persist
obstacle incidents to Neo4j.

**Architecture:** threading.RLock in DroneAdapter serializes all SDK calls.
Strategy Pattern (Python Protocol) for RETURN_TO_HOME with SimpleReverseRTH.
Obstacle events flow through existing Redis stream to tello-telemetry for
Neo4j persistence.

**Tech Stack:** Python 3.13, threading.RLock, Pydantic, FastMCP 3.x,
Redis Streams, Neo4j, pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-18-phase4b-navigator-obstacle-avoidance-design.md`

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `services/tello-mcp/src/tello_mcp/strategies.py` | ObstacleContext, ReturnToHomeStrategy Protocol, SimpleReverseRTH |
| `services/tello-mcp/tests/test_strategies.py` | Unit tests for RTH strategies |
| `services/tello-mcp/tests/test_drone_lock.py` | Unit tests for RLock and new methods |
| `services/tello-telemetry/tests/test_integration.py` | Integration tests (real Redis + Neo4j) |
| `testing/test_phase4b.py` | Physical test script (3 stages) |

### Modified Files

| File | Changes |
|------|---------|
| `services/tello-mcp/src/tello_mcp/drone.py` | Add RLock, `stop()`, `get_height()` |
| `services/tello-mcp/src/tello_mcp/obstacle.py` | Update handler for DI, event publishing, `on_obstacle_reading` callback |
| `services/tello-mcp/src/tello_mcp/tools/flight.py` | `last_command` tracking, land event |
| `services/tello-mcp/src/tello_mcp/server.py` | Wire strategy + handler + monitor callback + last_command |
| `packages/tello-core/src/tello_core/__init__.py` | Re-export `ObstacleIncident` |
| `services/tello-telemetry/src/tello_telemetry/consumer.py` | `obstacle_danger` route |
| `services/tello-telemetry/src/tello_telemetry/session_repo.py` | `add_obstacle_incident()` |
| `packages/tello-core/src/tello_core/models.py` | `ObstacleIncident` model |
| `services/tello-mcp/tests/test_obstacle.py` | Update handler tests for new constructor |

---

## Task 1: DroneAdapter — RLock + `stop()` + `get_height()`

**Files:**
- Modify: `services/tello-mcp/src/tello_mcp/drone.py`
- Create: `services/tello-mcp/tests/test_drone_lock.py`

- [ ] **Step 1: Write failing test for `stop()` method**

```python
# services/tello-mcp/tests/test_drone_lock.py
"""Tests for DroneAdapter command lock, stop(), and get_height()."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tello_mcp.drone import DroneAdapter


class TestDroneStop:
    def test_stop_sends_control_command(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter._connected = True
            mock_drone.send_control_command = MagicMock()
            result = adapter.stop()
            mock_drone.send_control_command.assert_called_once_with("stop")
            assert result["status"] == "ok"

    def test_stop_requires_connection(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter._connected = False
            result = adapter.stop()
            assert result["error"] == "DRONE_NOT_CONNECTED"

    def test_stop_handles_exception(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter._connected = True
            mock_drone.send_control_command.side_effect = Exception("fail")
            result = adapter.stop()
            assert result["error"] == "STOP_FAILED"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_drone_lock.py::TestDroneStop -v
```

Expected: FAIL — `DroneAdapter` has no `stop()` method.

- [ ] **Step 3: Implement `stop()` and add RLock to DroneAdapter**

In `services/tello-mcp/src/tello_mcp/drone.py`:

Add `import threading` at the top (after `from datetime import ...`).

Add `self._command_lock = threading.RLock()` to `__init__` (after `self._connected = False`).

Wrap every method body that touches `self._tello` with `with self._command_lock:`.
The methods to wrap: `connect`, `disconnect`, `keepalive`, `set_pad_detection_direction`,
`takeoff`, `land`, `safe_land`, `emergency`, `move`, `rotate`, `get_telemetry`,
`detect_mission_pad`, `go_xyz_speed_mid`, `get_forward_distance`, `set_led`,
`display_scroll_text`, `display_static_char`, `display_pattern`.

Add `stop()` method after `emergency()`:

```python
def stop(self) -> dict:
    """Stop all motors and hover in place."""
    with self._command_lock:
        if err := self._require_connection():
            return err
        try:
            self._tello.send_control_command("stop")
            return {"status": "ok"}
        except Exception as exc:
            logger.exception("stop failed")
            return {"error": "STOP_FAILED", "detail": str(exc)}
```

Add `get_height()` method after `get_forward_distance()`:

```python
def get_height(self) -> dict:
    """Get current altitude from the downward ToF sensor.

    Lightweight alternative to get_telemetry() — reads only height,
    avoiding the internal get_forward_distance() call.
    """
    with self._command_lock:
        if err := self._require_connection():
            return err
        try:
            height = self._tello.get_distance_tof()
            return {"status": "ok", "height_cm": height}
        except Exception as exc:
            logger.exception("get_height failed")
            return {"error": "HEIGHT_FAILED", "detail": str(exc)}
```

- [ ] **Step 4: Write test for `get_height()`**

Add to `test_drone_lock.py`:

```python
class TestDroneGetHeight:
    def test_get_height_returns_distance(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter._connected = True
            mock_drone.get_distance_tof.return_value = 80
            result = adapter.get_height()
            assert result == {"status": "ok", "height_cm": 80}

    def test_get_height_requires_connection(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter._connected = False
            result = adapter.get_height()
            assert result["error"] == "DRONE_NOT_CONNECTED"
```

- [ ] **Step 5: Write test for RLock reentrance (get_telemetry → get_forward_distance)**

Add to `test_drone_lock.py`:

```python
class TestDroneRLock:
    def test_get_telemetry_does_not_deadlock(self, mock_drone):
        """get_telemetry calls get_forward_distance internally.

        With threading.Lock this would deadlock. RLock allows reentrance.
        """
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter._connected = True
            # Should complete without deadlock
            result = adapter.get_telemetry()
            assert hasattr(result, "battery_pct")  # TelemetryFrame

    def test_lock_is_rlock(self, mock_drone):
        """Verify we use RLock, not Lock."""
        import threading

        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            assert isinstance(adapter._command_lock, threading.RLock)
```

- [ ] **Step 6: Run all tests**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_drone_lock.py -v
```

Expected: All PASS.

- [ ] **Step 7: Run full tello-mcp test suite to check for regressions**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/ -v
```

Expected: All 129+ tests PASS.

- [ ] **Step 8: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/drone.py \
       services/tello-mcp/tests/test_drone_lock.py
git commit -m "feat(tello-mcp): add RLock command serialization + stop() + get_height()

Adds threading.RLock to DroneAdapter to prevent UDP response crossing
when ObstacleMonitor polls concurrently with flight commands. Adds
missing stop() method and lightweight get_height() for obstacle context.

Closes #TBD"
```

---

## Task 2: ObstacleIncident Model + ObstacleContext

**Files:**
- Modify: `packages/tello-core/src/tello_core/models.py`
- Create: `services/tello-mcp/src/tello_mcp/strategies.py`
- Create: `services/tello-mcp/tests/test_strategies.py`

- [ ] **Step 1: Write failing test for ObstacleIncident model**

```python
# services/tello-mcp/tests/test_strategies.py
"""Tests for RTH strategies and ObstacleContext."""

from __future__ import annotations

from datetime import UTC, datetime

from tello_core.models import ObstacleIncident


class TestObstacleIncidentModel:
    def test_create_incident(self):
        incident = ObstacleIncident(
            id="inc-1",
            timestamp=datetime(2026, 3, 18, tzinfo=UTC),
            forward_distance_mm=185,
            forward_distance_in=7.3,
            height_cm=80,
            zone="DANGER",
            response="RETURN_TO_HOME",
            outcome="landed",
        )
        assert incident.forward_distance_mm == 185
        assert incident.mission_id is None

    def test_incident_with_optional_fields(self):
        incident = ObstacleIncident(
            id="inc-2",
            timestamp=datetime(2026, 3, 18, tzinfo=UTC),
            forward_distance_mm=185,
            forward_distance_in=7.3,
            height_cm=80,
            zone="DANGER",
            response="RETURN_TO_HOME",
            outcome="landed",
            mission_id="mission-1",
            room_id="living-room",
            reversed_direction="back",
        )
        assert incident.mission_id == "mission-1"
        assert incident.reversed_direction == "back"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_strategies.py::TestObstacleIncidentModel -v
```

Expected: FAIL — `ObstacleIncident` not found in `tello_core.models`.

- [ ] **Step 3: Add ObstacleIncident to models.py**

In `packages/tello-core/src/tello_core/models.py`, add after the `Anomaly` class
(end of Telemetry Layer section):

```python
class ObstacleIncident(BaseModel):
    """A recorded obstacle detection incident during flight."""

    id: str
    timestamp: datetime
    forward_distance_mm: int
    forward_distance_in: float
    height_cm: int
    zone: str
    response: str
    outcome: str
    mission_id: str | None = None
    room_id: str | None = None
    reversed_direction: str | None = None
```

- [ ] **Step 4: Update `tello_core/__init__.py` re-exports**

Add `ObstacleIncident` to the import list and `__all__` in
`packages/tello-core/src/tello_core/__init__.py`:

```python
from tello_core.models import (
    ...
    ObstacleIncident,
    ObstacleReading,
    ...
)

__all__ = [
    ...
    "ObstacleIncident",
    "ObstacleReading",
    ...
]
```

- [ ] **Step 5: Write failing tests for ObstacleContext and SimpleReverseRTH**

Add to `test_strategies.py`:

```python
from unittest.mock import MagicMock

import pytest

from tello_mcp.strategies import ObstacleContext, SimpleReverseRTH


class TestObstacleContext:
    def test_create_context(self):
        ctx = ObstacleContext(
            last_direction="forward",
            last_distance_cm=100,
            height_cm=80,
            forward_distance_mm=185,
        )
        assert ctx.last_direction == "forward"
        assert ctx.mission_id is None

    def test_context_is_frozen(self):
        ctx = ObstacleContext(
            last_direction="forward",
            last_distance_cm=100,
            height_cm=80,
            forward_distance_mm=185,
        )
        with pytest.raises(AttributeError):
            ctx.last_direction = "back"


class TestSimpleReverseRTH:
    def test_reverses_and_lands(self):
        drone = MagicMock()
        drone.move.return_value = {"status": "ok"}
        drone.land.return_value = {"status": "ok"}
        ctx = ObstacleContext(
            last_direction="forward",
            last_distance_cm=100,
            height_cm=80,
            forward_distance_mm=185,
        )
        rth = SimpleReverseRTH()
        result = rth.return_to_home(drone, ctx)
        drone.move.assert_called_once_with("back", 100)
        drone.land.assert_called_once()
        assert result["status"] == "returned"
        assert result["reversed_direction"] == "back"
        assert result["height_cm"] == 80
        assert result["landed"] is True

    def test_skips_reverse_when_no_last_direction(self):
        drone = MagicMock()
        drone.land.return_value = {"status": "ok"}
        ctx = ObstacleContext(
            last_direction="",
            last_distance_cm=0,
            height_cm=80,
            forward_distance_mm=185,
        )
        rth = SimpleReverseRTH()
        result = rth.return_to_home(drone, ctx)
        drone.move.assert_not_called()
        drone.land.assert_called_once()
        assert result["reversed_direction"] is None

    def test_lands_even_if_reverse_fails(self):
        drone = MagicMock()
        drone.move.return_value = {"error": "COMMAND_FAILED", "detail": "timeout"}
        drone.land.return_value = {"status": "ok"}
        ctx = ObstacleContext(
            last_direction="forward",
            last_distance_cm=100,
            height_cm=80,
            forward_distance_mm=185,
        )
        rth = SimpleReverseRTH()
        result = rth.return_to_home(drone, ctx)
        drone.move.assert_called_once()
        drone.land.assert_called_once()
        assert result["landed"] is True

    def test_all_directions_reverse_correctly(self):
        pairs = [
            ("forward", "back"),
            ("back", "forward"),
            ("left", "right"),
            ("right", "left"),
            ("up", "down"),
            ("down", "up"),
        ]
        for direction, expected_opposite in pairs:
            drone = MagicMock()
            drone.move.return_value = {"status": "ok"}
            drone.land.return_value = {"status": "ok"}
            ctx = ObstacleContext(
                last_direction=direction,
                last_distance_cm=50,
                height_cm=80,
                forward_distance_mm=185,
            )
            rth = SimpleReverseRTH()
            result = rth.return_to_home(drone, ctx)
            drone.move.assert_called_once_with(expected_opposite, 50)
            assert result["reversed_direction"] == expected_opposite
```

- [ ] **Step 5: Run test to verify it fails**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_strategies.py -v
```

Expected: FAIL — `tello_mcp.strategies` module not found.

- [ ] **Step 7: Implement strategies.py**

```python
# services/tello-mcp/src/tello_mcp/strategies.py
"""Obstacle response strategies — Strategy Pattern via Protocol.

ObstacleContext captures flight state at the moment of detection.
ReturnToHomeStrategy defines the contract for RTH implementations.
SimpleReverseRTH is the Phase 4b strategy: stop, reverse, land.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import structlog

if TYPE_CHECKING:
    from tello_mcp.drone import DroneAdapter

logger = structlog.get_logger("tello_mcp.strategies")

_OPPOSITES: dict[str, str] = {
    "forward": "back",
    "back": "forward",
    "left": "right",
    "right": "left",
    "up": "down",
    "down": "up",
}


def _opposite_direction(direction: str) -> str:
    """Return the opposite movement direction."""
    return _OPPOSITES[direction]


@dataclass(frozen=True)
class ObstacleContext:
    """Flight state captured at the moment of obstacle detection."""

    last_direction: str
    last_distance_cm: int
    height_cm: int
    forward_distance_mm: int
    mission_id: str | None = None
    room_id: str | None = None


class ReturnToHomeStrategy(Protocol):
    """Contract for return-to-home implementations.

    Phase 4b: SimpleReverseRTH (stop, reverse, land).
    Phase 5+: VisionGuidedRTH, VoiceConfirmedRTH.
    """

    def return_to_home(
        self, drone: DroneAdapter, context: ObstacleContext
    ) -> dict: ...


class SimpleReverseRTH:
    """Phase 4b: stop, reverse last movement, land.

    Focuses on drone commands only. Event publishing is handled
    by ObstacleResponseHandler after this strategy returns.
    """

    def return_to_home(
        self, drone: DroneAdapter, context: ObstacleContext
    ) -> dict:
        reversed_direction: str | None = None

        if context.last_direction and context.last_distance_cm > 0:
            reversed_direction = _opposite_direction(context.last_direction)
            move_result = drone.move(reversed_direction, context.last_distance_cm)
            if "error" in move_result:
                logger.warning(
                    "RTH reverse failed: %s — proceeding to land",
                    move_result,
                )

        drone.land()

        return {
            "status": "returned",
            "method": "simple_reverse",
            "reversed_direction": reversed_direction,
            "height_cm": context.height_cm,
            "forward_distance_mm": context.forward_distance_mm,
            "landed": True,
        }
```

- [ ] **Step 8: Run tests**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_strategies.py -v
```

Expected: All PASS.

- [ ] **Step 9: Run full test suites for both packages**

```bash
uv run --package tello-core pytest packages/tello-core/tests/ -v
uv run --package tello-mcp pytest services/tello-mcp/tests/ -v
```

Expected: All PASS (65+ core, 129+ mcp).

- [ ] **Step 10: Commit**

```bash
git add packages/tello-core/src/tello_core/models.py \
       packages/tello-core/src/tello_core/__init__.py \
       services/tello-mcp/src/tello_mcp/strategies.py \
       services/tello-mcp/tests/test_strategies.py
git commit -m "feat(tello-mcp): add ObstacleContext, ReturnToHomeStrategy, SimpleReverseRTH

Strategy Pattern with Protocol for DI. SimpleReverseRTH stops, reverses
last movement, and lands. ObstacleContext captures height_cm and
forward_distance_mm at detection time. ObstacleIncident model added to
tello-core for Neo4j persistence."
```

---

## Task 3: Update ObstacleResponseHandler for DI + Event Publishing

**Files:**
- Modify: `services/tello-mcp/src/tello_mcp/obstacle.py`
- Modify: `services/tello-mcp/tests/test_obstacle.py`

- [ ] **Step 1: Write failing tests for updated handler**

Add to `services/tello-mcp/tests/test_obstacle.py`, replacing the existing
`TestObstacleResponseHandler` class:

```python
from unittest.mock import AsyncMock

from tello_mcp.strategies import ObstacleContext


class TestObstacleResponseHandlerDI:
    """Tests for the updated handler with DI and event publishing."""

    def _make_handler(self):
        drone = MagicMock()
        drone.safe_land.return_value = {"status": "ok"}
        strategy = MagicMock()
        strategy.return_to_home.return_value = {
            "status": "returned",
            "method": "simple_reverse",
            "reversed_direction": "back",
            "height_cm": 80,
            "forward_distance_mm": 185,
            "landed": True,
        }
        telemetry = AsyncMock()
        telemetry.publish_event = AsyncMock()
        handler = ObstacleResponseHandler(
            drone=drone,
            rth_strategy=strategy,
            telemetry=telemetry,
        )
        return handler, drone, strategy, telemetry

    async def test_return_to_home_calls_strategy(self):
        handler, drone, strategy, _tel = self._make_handler()
        ctx = ObstacleContext(
            last_direction="forward",
            last_distance_cm=100,
            height_cm=80,
            forward_distance_mm=185,
        )
        result = await handler.execute(ObstacleResponse.RETURN_TO_HOME, ctx)
        strategy.return_to_home.assert_called_once_with(drone, ctx)
        assert result["status"] == "returned"

    async def test_return_to_home_publishes_obstacle_event(self):
        handler, _drone, _strategy, telemetry = self._make_handler()
        ctx = ObstacleContext(
            last_direction="forward",
            last_distance_cm=100,
            height_cm=80,
            forward_distance_mm=185,
            mission_id="m1",
            room_id="living-room",
        )
        await handler.execute(ObstacleResponse.RETURN_TO_HOME, ctx)
        calls = telemetry.publish_event.call_args_list
        event_types = [c[0][0] for c in calls]
        assert "obstacle_danger" in event_types
        assert "land" in event_types

    async def test_emergency_land_still_works(self):
        handler, drone, _strategy, _tel = self._make_handler()
        result = await handler.execute(ObstacleResponse.EMERGENCY_LAND)
        drone.safe_land.assert_called_once()
        assert result["status"] == "ok"

    async def test_manual_override_still_works(self):
        handler, _drone, _strategy, _tel = self._make_handler()
        result = await handler.execute(ObstacleResponse.MANUAL_OVERRIDE)
        assert result["status"] == "ok"

    async def test_on_obstacle_reading_triggers_rth_on_danger(self):
        handler, drone, strategy, _tel = self._make_handler()
        # Set last_command so RTH has context
        handler._last_command = {"direction": "forward", "distance_cm": 100}
        drone.get_height.return_value = {"status": "ok", "height_cm": 80}

        reading = ObstacleReading(
            distance_mm=185,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 18),
        )
        await handler.on_obstacle_reading(reading)
        strategy.return_to_home.assert_called_once()

    async def test_on_obstacle_reading_ignores_non_danger(self):
        handler, _drone, strategy, _tel = self._make_handler()
        reading = ObstacleReading(
            distance_mm=400,
            zone=ObstacleZone.CAUTION,
            timestamp=datetime(2026, 3, 18),
        )
        await handler.on_obstacle_reading(reading)
        strategy.return_to_home.assert_not_called()
```

Add imports at the top of the new test class:

```python
from datetime import datetime
from tello_core.models import ObstacleReading, ObstacleZone
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestObstacleResponseHandlerDI -v
```

Expected: FAIL — `ObstacleResponseHandler.__init__` doesn't accept `rth_strategy`
or `telemetry` yet.

- [ ] **Step 3: Update ObstacleResponseHandler in obstacle.py**

Replace the existing `ObstacleResponseHandler` class (lines 191-218).
Key additions: `rth_strategy` + `telemetry` DI params, `on_obstacle_reading`
callback method for auto-trigger RTH, and event publishing after response.

```python
class ObstacleResponseHandler:
    """Executes obstacle response actions.

    Receives a ReturnToHomeStrategy via DI. Handles event publishing
    after the strategy executes (strategies stay pure — drone commands only).
    """

    def __init__(
        self,
        drone: DroneAdapter,
        rth_strategy: ReturnToHomeStrategy | None = None,
        telemetry: TelemetryPublisher | None = None,
    ) -> None:
        self._drone = drone
        self._rth = rth_strategy
        self._telemetry = telemetry

    async def execute(
        self,
        choice: ObstacleResponse,
        context: ObstacleContext | None = None,
    ) -> dict:
        """Execute the chosen obstacle response."""
        match choice:
            case ObstacleResponse.EMERGENCY_LAND:
                return await asyncio.to_thread(self._drone.safe_land)
            case ObstacleResponse.RETURN_TO_HOME:
                if self._rth is None or context is None:
                    return {
                        "error": "NOT_CONFIGURED",
                        "detail": "RTH strategy or context not provided",
                    }
                result = await asyncio.to_thread(
                    self._rth.return_to_home, self._drone, context
                )
                if self._telemetry is not None:
                    await self._telemetry.publish_event(
                        "obstacle_danger",
                        {
                            "forward_distance_mm": str(context.forward_distance_mm),
                            "forward_distance_in": str(
                                round(context.forward_distance_mm / 25.4, 1)
                            ),
                            "height_cm": str(context.height_cm),
                            "zone": "DANGER",
                            "response": "RETURN_TO_HOME",
                            "outcome": result.get("status", "unknown"),
                            "mission_id": context.mission_id or "",
                            "room_id": context.room_id or "",
                            "reversed_direction": result.get(
                                "reversed_direction", ""
                            ),
                        },
                    )
                    await self._telemetry.publish_event("land", {})
                return result
            case ObstacleResponse.AVOID_AND_CONTINUE:
                return {
                    "error": "NOT_IMPLEMENTED",
                    "detail": "Deferred to Phase 5+",
                }
            case ObstacleResponse.MANUAL_OVERRIDE:
                logger.info("obstacle.manual_override")
                return {"status": "ok", "detail": "Manual control resumed"}

    async def on_obstacle_reading(self, reading: ObstacleReading) -> None:
        """Callback for ObstacleMonitor — auto-triggers RTH on DANGER.

        Registered via monitor.on_reading(handler.on_obstacle_reading).
        Builds ObstacleContext from lifespan state and dispatches to execute().
        """
        if reading.zone != ObstacleZone.DANGER:
            return

        # Build context from lifespan state
        last_cmd = self._last_command or {}
        height_result = await asyncio.to_thread(self._drone.get_height)
        height_cm = height_result.get("height_cm", 0) if height_result.get("status") == "ok" else 0

        context = ObstacleContext(
            last_direction=last_cmd.get("direction", ""),
            last_distance_cm=int(last_cmd.get("distance_cm", 0)),
            height_cm=height_cm,
            forward_distance_mm=reading.distance_mm,
            mission_id=last_cmd.get("mission_id"),
            room_id=last_cmd.get("room_id"),
        )
        await self.execute(ObstacleResponse.RETURN_TO_HOME, context)
```

Update the `__init__` to also accept `last_command` dict:

```python
def __init__(
    self,
    drone: DroneAdapter,
    rth_strategy: ReturnToHomeStrategy | None = None,
    telemetry: TelemetryPublisher | None = None,
    last_command: dict | None = None,
) -> None:
    self._drone = drone
    self._rth = rth_strategy
    self._telemetry = telemetry
    self._last_command = last_command
```

Add necessary imports at the top of obstacle.py:

```python
from tello_mcp.strategies import ObstacleContext, ReturnToHomeStrategy
```

And add `TelemetryPublisher` to the TYPE_CHECKING block:

```python
if TYPE_CHECKING:
    from tello_mcp.drone import DroneAdapter
    from tello_mcp.telemetry import TelemetryPublisher
```

- [ ] **Step 4: Run updated handler tests**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py -v
```

Expected: New DI tests PASS. Old handler tests that used the single-arg
constructor will fail — update them.

- [ ] **Step 5: Fix old handler tests to use new constructor**

In `test_obstacle.py`, the existing `TestObstacleResponseHandler` tests use
positional `ObstacleResponseHandler(drone)` — this still works since new
params default to `None`.

Update `test_execute_return_to_home_not_implemented` (line 220):

```python
async def test_execute_return_to_home_not_configured(self):
    drone = MagicMock()
    handler = ObstacleResponseHandler(drone)
    result = await handler.execute(ObstacleResponse.RETURN_TO_HOME)
    assert result["error"] == "NOT_CONFIGURED"
```

Note: `rotate` does not update `last_command` — this is intentional.
Rotate has no meaningful "reverse" direction. If DANGER triggers after
a rotate, `last_command` still holds the previous movement's data (or
is empty), and RTH behaves correctly in both cases.

- [ ] **Step 6: Run full test suite**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/ -v
```

Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/obstacle.py \
       services/tello-mcp/tests/test_obstacle.py
git commit -m "feat(tello-mcp): update ObstacleResponseHandler for DI + event publishing

Handler now accepts ReturnToHomeStrategy and TelemetryPublisher via DI.
RETURN_TO_HOME delegates to injected strategy, then publishes
obstacle_danger and land events. Backward compatible — old constructor
still works with defaults."
```

---

## Task 4: Flight Tools — `last_command` Tracking + Land Event

**Files:**
- Modify: `services/tello-mcp/src/tello_mcp/tools/flight.py`
- Modify: `services/tello-mcp/src/tello_mcp/server.py`

- [ ] **Step 1: Update `land()` tool to publish land event**

Note: Flight tools are hard to unit-test in isolation because they use
`ctx.lifespan_context`. The land event is validated by the integration test
in Task 6 (`test_obstacle_event_reaches_neo4j` publishes a land event and
verifies the session is closed in Neo4j).

In `services/tello-mcp/src/tello_mcp/tools/flight.py`, update the `land` function:

```python
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
async def land(ctx: Context) -> dict:
    """Land the drone safely."""
    drone = ctx.lifespan_context["drone"]
    queue = ctx.lifespan_context["queue"]
    telemetry = ctx.lifespan_context["telemetry"]
    result = await queue.enqueue(drone.safe_land)
    await telemetry.publish_event("land", {})
    return result
```

- [ ] **Step 2: Add `last_command` tracking to `move` and `go_to_mission_pad`**

Update the `move` tool:

```python
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
async def move(ctx: Context, direction: str, distance_cm: int) -> dict:
    """Move the drone in a direction.

    Args:
        direction: One of forward, back, left, right, up, down.
        distance_cm: Distance in centimeters (20-500).
    """
    drone = ctx.lifespan_context["drone"]
    queue = ctx.lifespan_context["queue"]
    last_command = ctx.lifespan_context["last_command"]
    result = await queue.enqueue(lambda: drone.move(direction, distance_cm))
    if result.get("status") == "ok":
        last_command["direction"] = direction
        last_command["distance_cm"] = distance_cm
    return result
```

Update `go_to_mission_pad` — set `last_command["direction"] = ""` (empty string)
since pad navigation has no simple reverse. If DANGER triggers after a
`go_to_mission_pad`, RTH will skip the reverse and just land:

```python
if result.get("status") == "ok":
    last_command["direction"] = ""
    last_command["distance_cm"] = 0
```

- [ ] **Step 3: Wire strategy + handler + monitor callback in server.py**

In `services/tello-mcp/src/tello_mcp/server.py`, wire the strategy, handler,
and monitor→handler callback inside the `lifespan` function (after
`monitor = ObstacleMonitor(...)`):

```python
from tello_mcp.strategies import SimpleReverseRTH

# After monitor creation:
last_command: dict[str, str | int] = {}
strategy = SimpleReverseRTH()
handler = ObstacleResponseHandler(
    drone=drone,
    rth_strategy=strategy,
    telemetry=telemetry,
    last_command=last_command,
)
monitor.on_reading(handler.on_obstacle_reading)
```

Add `"handler": handler` and `"last_command": last_command` to the yielded dict.

This is the critical wiring that connects the ObstacleMonitor's DANGER
detection to the automatic RTH response. When the monitor detects DANGER,
it fires `handler.on_obstacle_reading(reading)`, which builds an
`ObstacleContext` and calls `handler.execute(RETURN_TO_HOME, context)`.

Update imports:

```python
from tello_mcp.obstacle import ObstacleConfig, ObstacleMonitor, ObstacleResponseHandler
```

- [ ] **Step 4: Run full test suite**

```bash
uv run --package tello-mcp pytest services/tello-mcp/tests/ -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/tools/flight.py \
       services/tello-mcp/src/tello_mcp/server.py
git commit -m "feat(tello-mcp): add last_command tracking + land event + handler wiring

Flight tools now track last movement in lifespan context for RTH.
Land tool publishes land event to close FlightSessions. Server wires
SimpleReverseRTH strategy into ObstacleResponseHandler."
```

---

## Task 5: Telemetry Consumer — Obstacle Event Route + Neo4j Persistence

**Files:**
- Modify: `services/tello-telemetry/src/tello_telemetry/consumer.py`
- Modify: `services/tello-telemetry/src/tello_telemetry/session_repo.py`
- Modify: `services/tello-telemetry/tests/test_consumer.py`
- Modify: `services/tello-telemetry/tests/test_session_repo.py`

- [ ] **Step 1: Write failing test for obstacle event routing in consumer**

Add to `services/tello-telemetry/tests/test_consumer.py`:

```python
class TestObstacleEventRouting:
    async def test_obstacle_danger_creates_incident(self):
        config = _make_config()
        redis = AsyncMock()
        detector = AnomalyDetector(config)
        session_repo = MagicMock()
        session_repo.add_obstacle_incident = MagicMock()

        consumer = StreamConsumer(redis, config, detector, session_repo)
        # Simulate active session
        consumer._current_session = MagicMock()
        consumer._current_session.id = "session-1"

        fields = {
            "event_type": "obstacle_danger",
            "forward_distance_mm": "185",
            "forward_distance_in": "7.3",
            "height_cm": "80",
            "zone": "DANGER",
            "response": "RETURN_TO_HOME",
            "outcome": "returned",
            "mission_id": "m1",
            "room_id": "living-room",
            "reversed_direction": "back",
        }
        await consumer._process_message("msg-1", fields)
        session_repo.add_obstacle_incident.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_consumer.py::TestObstacleEventRouting -v
```

Expected: FAIL — no `obstacle_danger` route in `_process_message`.

- [ ] **Step 3: Add obstacle route to consumer.py**

In `_process_message`, add before the `else` branch (after line 150):

```python
elif event_type == "obstacle_danger":
    await self._handle_obstacle(fields)
```

Add the handler method:

```python
async def _handle_obstacle(self, fields: dict) -> None:
    """Record an obstacle incident for the current session."""
    if self._current_session is None:
        logger.warning("Obstacle event without active session")
        return
    from tello_core.models import ObstacleIncident

    incident = ObstacleIncident(
        id=str(uuid4()),
        timestamp=datetime.now(UTC),
        forward_distance_mm=int(fields.get("forward_distance_mm", 0)),
        forward_distance_in=float(fields.get("forward_distance_in", 0.0)),
        height_cm=int(fields.get("height_cm", 0)),
        zone=fields.get("zone", "DANGER"),
        response=fields.get("response", "unknown"),
        outcome=fields.get("outcome", "unknown"),
        mission_id=fields.get("mission_id") or None,
        room_id=fields.get("room_id") or None,
        reversed_direction=fields.get("reversed_direction") or None,
    )
    await asyncio.to_thread(
        self._repo.add_obstacle_incident,
        self._current_session.id,
        incident,
    )
    logger.info(
        "Obstacle incident recorded",
        session_id=self._current_session.id,
        distance_mm=incident.forward_distance_mm,
        response=incident.response,
    )
```

- [ ] **Step 4: Write failing test for `add_obstacle_incident` in session_repo**

Add to `services/tello-telemetry/tests/test_session_repo.py`:

```python
class TestAddObstacleIncident:
    def test_creates_incident_node_with_relationship(self):
        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        repo = SessionRepository(mock_driver)
        incident = ObstacleIncident(
            id="inc-1",
            timestamp=datetime(2026, 3, 18, tzinfo=UTC),
            forward_distance_mm=185,
            forward_distance_in=7.3,
            height_cm=80,
            zone="DANGER",
            response="RETURN_TO_HOME",
            outcome="landed",
        )
        repo.add_obstacle_incident("session-1", incident)
        mock_session.run.assert_called_once()
        cypher = mock_session.run.call_args[0][0]
        assert "ObstacleIncident" in cypher
        assert "TRIGGERED_DURING" in cypher
```

- [ ] **Step 5: Implement `add_obstacle_incident` in session_repo.py**

Add to `SessionRepository` class (after `add_anomaly`):

```python
def add_obstacle_incident(
    self, session_id: str, incident: ObstacleIncident
) -> None:
    """Create an ObstacleIncident node linked to a session.

    Args:
        session_id: Parent flight session.
        incident: Obstacle incident to persist.
    """
    with self._driver.session() as s:
        s.run(
            """
            MATCH (fs:FlightSession {id: $session_id})
            CREATE (oi:ObstacleIncident {
                id: $id,
                timestamp: datetime($timestamp),
                forward_distance_mm: $forward_distance_mm,
                forward_distance_in: $forward_distance_in,
                height_cm: $height_cm,
                zone: $zone,
                response: $response,
                outcome: $outcome,
                mission_id: $mission_id,
                room_id: $room_id,
                reversed_direction: $reversed_direction
            })-[:TRIGGERED_DURING]->(fs)
            """,
            session_id=session_id,
            id=incident.id,
            timestamp=incident.timestamp.isoformat(),
            forward_distance_mm=incident.forward_distance_mm,
            forward_distance_in=incident.forward_distance_in,
            height_cm=incident.height_cm,
            zone=incident.zone,
            response=incident.response,
            outcome=incident.outcome,
            mission_id=incident.mission_id,
            room_id=incident.room_id,
            reversed_direction=incident.reversed_direction,
        )
    logger.info(
        "Obstacle incident persisted",
        session_id=session_id,
        incident_id=incident.id,
    )
```

Add `ObstacleIncident` to the TYPE_CHECKING imports:

```python
from tello_core.models import Anomaly, FlightSession, ObstacleIncident, TelemetrySample
```

- [ ] **Step 6: Run all telemetry tests**

```bash
uv run --package tello-telemetry pytest services/tello-telemetry/tests/ -v
```

Expected: All PASS (45+ existing + new obstacle tests).

- [ ] **Step 7: Commit**

```bash
git add services/tello-telemetry/src/tello_telemetry/consumer.py \
       services/tello-telemetry/src/tello_telemetry/session_repo.py \
       services/tello-telemetry/tests/test_consumer.py \
       services/tello-telemetry/tests/test_session_repo.py
git commit -m "feat(tello-telemetry): add obstacle_danger event consumption + Neo4j persistence

StreamConsumer routes obstacle_danger events to new _handle_obstacle().
SessionRepository.add_obstacle_incident() creates ObstacleIncident
nodes linked to FlightSession via TRIGGERED_DURING relationship."
```

---

## Task 6: Integration Tests (Real Redis + Real Neo4j)

**Files:**
- Create: `services/tello-telemetry/tests/test_integration.py`

**Prerequisites:** `docker compose up -d` (Redis + Neo4j healthy).

- [ ] **Step 1: Write integration test for obstacle pipeline**

```python
# services/tello-telemetry/tests/test_integration.py
"""Integration tests — real Redis + real Neo4j.

Requires: docker compose up -d (Redis + Neo4j healthy).
Run: uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_integration.py -v
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest
import redis.asyncio as aioredis
from neo4j import GraphDatabase

from tello_telemetry.config import TelloTelemetryConfig
from tello_telemetry.consumer import StreamConsumer
from tello_telemetry.detector import AnomalyDetector
from tello_telemetry.session_repo import SessionRepository

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7689")
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "claude-code-memory")

# Use a unique stream name to avoid collisions
TEST_STREAM = "tello:events:integration-test"


@pytest.fixture()
async def setup_integration():
    """Set up real Redis + Neo4j for integration testing."""
    r = aioredis.from_url(REDIS_URL)
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    # Clean up test data
    await r.delete(TEST_STREAM)
    with driver.session() as s:
        s.run("""
            MATCH (n)-[r]->(fs:FlightSession)
            WHERE fs.room_id = 'integration-test-room'
            DELETE r, n
        """)
        s.run("MATCH (fs:FlightSession {room_id: 'integration-test-room'}) DELETE fs")

    yield r, driver

    # Cleanup
    await r.delete(TEST_STREAM)
    with driver.session() as s:
        s.run("""
            MATCH (n)-[r]->(fs:FlightSession)
            WHERE fs.room_id = 'integration-test-room'
            DELETE r, n
        """)
        s.run("MATCH (fs:FlightSession {room_id: 'integration-test-room'}) DELETE fs")
    await r.aclose()
    driver.close()


def _make_config() -> TelloTelemetryConfig:
    return TelloTelemetryConfig(
        neo4j_uri=NEO4J_URI,
        neo4j_username=NEO4J_USER,
        neo4j_password=NEO4J_PASS,
        redis_url=REDIS_URL,
        service_name="integration-test",
        stream_name=TEST_STREAM,
        consumer_group="test-group",
        consumer_name="test-worker",
    )


class TestObstaclePipelineEndToEnd:
    @pytest.mark.skipif(
        os.environ.get("SKIP_INTEGRATION") == "1",
        reason="Integration tests disabled",
    )
    async def test_obstacle_event_reaches_neo4j(self, setup_integration):
        r, driver = setup_integration
        config = _make_config()
        repo = SessionRepository(driver)
        detector = AnomalyDetector(config)
        consumer = StreamConsumer(r, config, detector, repo)

        # Publish takeoff → obstacle → land
        await r.xadd(TEST_STREAM, {"event_type": "takeoff", "room_id": "integration-test-room"})
        await r.xadd(
            TEST_STREAM,
            {
                "event_type": "obstacle_danger",
                "forward_distance_mm": "185",
                "forward_distance_in": "7.3",
                "height_cm": "80",
                "zone": "DANGER",
                "response": "RETURN_TO_HOME",
                "outcome": "returned",
                "mission_id": "",
                "room_id": "integration-test-room",
                "reversed_direction": "back",
            },
        )
        await r.xadd(TEST_STREAM, {"event_type": "land"})

        # Process all messages
        await consumer.ensure_consumer_group()
        await consumer._read_and_process(message_id="0")

        # Verify in Neo4j
        with driver.session() as s:
            result = s.run(
                """
                MATCH (oi:ObstacleIncident)-[:TRIGGERED_DURING]->(fs:FlightSession)
                WHERE fs.room_id = 'integration-test-room'
                RETURN oi.forward_distance_mm AS distance,
                       oi.height_cm AS height,
                       oi.response AS response,
                       fs.end_time IS NOT NULL AS session_closed
                """
            ).single()
            assert result is not None
            assert result["distance"] == 185
            assert result["height"] == 80
            assert result["response"] == "RETURN_TO_HOME"
            assert result["session_closed"] is True
```

- [ ] **Step 2: Run integration test**

```bash
uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_integration.py -v
```

Expected: PASS (requires Docker containers running).

- [ ] **Step 3: Commit**

```bash
git add services/tello-telemetry/tests/test_integration.py
git commit -m "test(tello-telemetry): add integration tests for obstacle pipeline

End-to-end test: publish takeoff → obstacle_danger → land to real Redis,
consume via StreamConsumer, verify FlightSession + ObstacleIncident in
real Neo4j with TRIGGERED_DURING relationship."
```

---

## Task 7: Physical Test Script

**Files:**
- Create: `testing/test_phase4b.py`

- [ ] **Step 1: Write the physical test script**

Create `testing/test_phase4b.py` with three stages:
- Stage 1: Lock verification (concurrent monitor + movements)
- Stage 2: RETURN_TO_HOME trigger (fly toward wall)
- Stage 3: Pipeline verification (query Neo4j)

This is a manual test script (not pytest) — similar to `testing/test_tof.py`.

- [ ] **Step 2: Commit**

```bash
git add testing/test_phase4b.py
git commit -m "test: Phase 4b physical test script (3 stages)

Stage 1: Lock verification — concurrent monitor + movements.
Stage 2: RETURN_TO_HOME trigger — fly toward wall, verify reverse + land.
Stage 3: Pipeline verification — confirm Neo4j ObstacleIncident."
```

---

## Task 8: Lint, Format, Final Verification

- [ ] **Step 1: Run linter and formatter**

```bash
uv run ruff check .
uv run ruff format --check .
```

Fix any issues.

- [ ] **Step 2: Run all test suites**

```bash
uv run --package tello-core pytest packages/tello-core/tests/ -v
uv run --package tello-mcp pytest services/tello-mcp/tests/ -v
uv run --package tello-navigator pytest services/tello-navigator/tests/ -v
uv run --package tello-telemetry pytest services/tello-telemetry/tests/ -v
```

Expected: All 293+ tests PASS + new tests.

- [ ] **Step 3: Run integration tests**

```bash
uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_integration.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit any lint/format fixes**

```bash
git add -A
git commit -m "style: lint and format fixes for Phase 4b"
```

---

## Post-Implementation

After all tasks pass:
1. Physical testing (Task 7) — requires drone powered on
2. Push branch and create PR: `gh pr create --title "feat: Phase 4b obstacle avoidance"`
3. Update MEMORY.md with Phase 4b completion status
