# Phase 4c: ObstacleMonitor Bug Fixes + Observability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three event-publishing bugs discovered during pipeline testing and add
structured logging so future failures are diagnosable in minutes, not hours.

**Architecture:** Surgical fixes at three points in the event-publishing chain:
(1) callback exception handling in `_poll_loop`, (2) RTH guards in
`ObstacleResponseHandler`, (3) publish-after-success in flight tools. Plus
structured log events at all decision points and status methods on monitor/handler.

**Tech Stack:** Python 3.13, pytest + pytest-asyncio, structlog, AsyncMock/MagicMock

**Spec:** `docs/superpowers/specs/2026-03-20-phase4c-obstacle-monitor-bugfixes-design.md`

**Session context recovery:** This plan references MEMORY.md for current state.
After each task, the implementer should update MEMORY.md with progress. Key files:
- `feedback_implementation_checklist.md` — mandatory workflow steps
- `feedback_always_run_telemetry.md` — tello-telemetry must run during physical tests
- `project_phase4b_physical_test_results.md` — test run data (Runs 1-3)

---

## File Structure

**Modified files (no new files created):**

| File | Responsibility | Changes |
|------|---------------|---------|
| `services/tello-mcp/src/tello_mcp/obstacle.py` | Obstacle detection + RTH | Callback try/except, RTH guards, status methods, state reset, logging |
| `services/tello-mcp/src/tello_mcp/telemetry.py` | Redis event publishing | Wrap xadd in try/except, structured log events |
| `services/tello-mcp/src/tello_mcp/tools/flight.py` | MCP flight tools | Publish-after-success for takeoff/land, add logger |
| `services/tello-mcp/tests/test_obstacle.py` | Obstacle tests | New tests for guards, callback resilience, status |
| `services/tello-mcp/tests/test_tools/test_flight.py` | Flight tool tests | New tests for publish-on-failure |
| `services/tello-mcp/tests/test_telemetry.py` | Telemetry tests | New test for xadd failure handling |

---

## Task 1: Callback Exception Handling in `_poll_loop` (Bug #1)

**Files:**
- Modify: `services/tello-mcp/tests/test_obstacle.py`
- Modify: `services/tello-mcp/src/tello_mcp/obstacle.py:176-179`

- [ ] **Step 1: Write the failing test — callback exception doesn't kill the monitor**

Add to `TestObstacleMonitorPolling` in `services/tello-mcp/tests/test_obstacle.py`:

```python
async def test_callback_exception_does_not_kill_monitor(self):
    """Poll loop survives a callback that raises an exception."""
    drone = MagicMock()
    drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 600}
    config = ObstacleConfig(poll_interval_ms=50)
    monitor = ObstacleMonitor(drone, config)

    call_count = 0

    def exploding_callback(reading):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            msg = "boom"
            raise RuntimeError(msg)

    monitor.on_reading(exploding_callback)
    await monitor.start()
    await asyncio.sleep(0.2)
    await monitor.stop()
    # The callback was called more than once — the loop survived the exception
    assert call_count >= 2

async def test_callback_exception_is_logged(self, caplog):
    """Callback exception is logged for diagnosis."""
    drone = MagicMock()
    drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 600}
    config = ObstacleConfig(poll_interval_ms=50)
    monitor = ObstacleMonitor(drone, config)

    def exploding_callback(reading):
        msg = "boom"
        raise RuntimeError(msg)

    monitor.on_reading(exploding_callback)
    await monitor.start()
    await asyncio.sleep(0.15)
    await monitor.stop()
    assert "callback_failed" in caplog.text or "boom" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestObstacleMonitorPolling::test_callback_exception_does_not_kill_monitor -v`

Expected: FAIL — `RuntimeError: boom` propagates and kills the poll loop, so
`call_count` stays at 1.

- [ ] **Step 3: Write the fix — wrap callbacks in try/except**

In `services/tello-mcp/src/tello_mcp/obstacle.py`, replace lines 176-179:

```python
# BEFORE:
                for cb in self._callbacks:
                    cb_result = cb(reading)
                    if asyncio.iscoroutine(cb_result):
                        await cb_result
```

With:

```python
# AFTER:
                for cb in self._callbacks:
                    try:
                        cb_result = cb(reading)
                        if asyncio.iscoroutine(cb_result):
                            await cb_result
                    except Exception:
                        logger.exception(
                            "obstacle.callback_failed",
                            distance_mm=reading.distance_mm,
                            zone=reading.zone.value,
                        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestObstacleMonitorPolling::test_callback_exception_does_not_kill_monitor -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/obstacle.py services/tello-mcp/tests/test_obstacle.py
git commit -m "fix: wrap poll loop callbacks in try/except (Bug #1)

Unhandled exceptions in ObstacleMonitor callbacks silently killed event
publishing. Now logged and the poll loop continues running."
```

---

## Task 2: RTH Guards — `_rth_active` flag + grounded check (Bug #2)

**Files:**
- Modify: `services/tello-mcp/tests/test_obstacle.py`
- Modify: `services/tello-mcp/src/tello_mcp/obstacle.py:200-277`

- [ ] **Step 1: Write the failing tests — RTH guards**

Add a new test class in `services/tello-mcp/tests/test_obstacle.py`:

```python
class TestRTHGuards:
    """Tests for on_obstacle_reading guards that prevent re-entry and grounded RTH."""

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
            last_command={"direction": "forward", "distance_cm": 50},
        )
        return handler, drone, strategy, telemetry

    async def test_rth_skipped_when_active(self):
        """on_obstacle_reading returns immediately if RTH is already in progress."""
        handler, _drone, strategy, _tel = self._make_handler()
        handler._rth_active = True

        reading = ObstacleReading(
            distance_mm=185,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 20),
        )
        await handler.on_obstacle_reading(reading)
        strategy.return_to_home.assert_not_called()

    async def test_rth_skipped_when_grounded(self):
        """on_obstacle_reading returns immediately if drone is on the ground."""
        handler, drone, strategy, _tel = self._make_handler()
        drone.get_height.return_value = {"status": "ok", "height_cm": 0}

        reading = ObstacleReading(
            distance_mm=185,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 20),
        )
        await handler.on_obstacle_reading(reading)
        strategy.return_to_home.assert_not_called()

    async def test_rth_not_skipped_when_height_query_fails(self):
        """A failed get_height must NOT suppress RTH — drone may be airborne."""
        handler, drone, strategy, _tel = self._make_handler()
        drone.get_height.return_value = {"error": "HEIGHT_FAILED", "detail": "timeout"}

        reading = ObstacleReading(
            distance_mm=185,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 20),
        )
        await handler.on_obstacle_reading(reading)
        strategy.return_to_home.assert_called_once()

    async def test_rth_active_flag_set_during_execution(self):
        """_rth_active is True while execute() is running, False after."""
        handler, drone, strategy, _tel = self._make_handler()
        drone.get_height.return_value = {"status": "ok", "height_cm": 80}

        observed_during: list[bool] = []
        original_execute = handler.execute

        async def spy_execute(*args, **kwargs):
            observed_during.append(handler._rth_active)
            return await original_execute(*args, **kwargs)

        handler.execute = spy_execute

        reading = ObstacleReading(
            distance_mm=185,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 20),
        )
        await handler.on_obstacle_reading(reading)
        assert observed_during == [True]
        assert handler._rth_active is False

    async def test_rth_active_flag_cleared_on_exception(self):
        """_rth_active is cleared even if execute() raises."""
        handler, drone, _strategy, _tel = self._make_handler()
        drone.get_height.return_value = {"status": "ok", "height_cm": 80}
        handler.execute = AsyncMock(side_effect=RuntimeError("execute failed"))

        reading = ObstacleReading(
            distance_mm=185,
            zone=ObstacleZone.DANGER,
            timestamp=datetime(2026, 3, 20),
        )
        # Should not propagate — the callback exception guard from Task 1
        # would catch this in production, but we test the flag cleanup here.
        with pytest.raises(RuntimeError, match="execute failed"):
            await handler.on_obstacle_reading(reading)
        assert handler._rth_active is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestRTHGuards -v`

Expected: FAIL — `_rth_active` attribute doesn't exist, grounded check not implemented.

- [ ] **Step 3: Write the fix — add `_rth_active` flag and grounded guard**

In `services/tello-mcp/src/tello_mcp/obstacle.py`, modify `ObstacleResponseHandler`:

Add `_rth_active` to `__init__` (after line 210):
```python
        self._last_command = last_command
        self._rth_active = False
```

Replace `on_obstacle_reading` method (lines 256-277) with:
```python
    async def on_obstacle_reading(self, reading: ObstacleReading) -> None:
        """Callback for ObstacleMonitor — auto-triggers RTH on DANGER.

        Guards:
        - Ignores non-DANGER readings
        - Skips if RTH is already in progress (_rth_active flag)
        - Skips if drone is confirmed on the ground (height_cm == 0)
        - Does NOT skip if get_height fails (drone may be airborne)
        """
        if reading.zone != ObstacleZone.DANGER:
            return

        if self._rth_active:
            logger.debug("obstacle.rth_skipped_active", distance_mm=reading.distance_mm)
            return

        last_cmd = self._last_command or {}
        height_result = await asyncio.to_thread(self._drone.get_height)
        height_cm = height_result.get("height_cm", 0) if height_result.get("status") == "ok" else 0

        if height_result.get("status") == "ok" and height_cm == 0:
            logger.debug(
                "obstacle.rth_skipped_grounded",
                height_cm=height_cm,
                distance_mm=reading.distance_mm,
            )
            return

        self._rth_active = True
        try:
            logger.info(
                "obstacle.rth_started",
                distance_mm=reading.distance_mm,
                height_cm=height_cm,
                last_direction=last_cmd.get("direction", ""),
            )
            context = ObstacleContext(
                last_direction=last_cmd.get("direction", ""),
                last_distance_cm=int(last_cmd.get("distance_cm", 0)),
                height_cm=height_cm,
                forward_distance_mm=reading.distance_mm,
                mission_id=last_cmd.get("mission_id"),
                room_id=last_cmd.get("room_id"),
            )
            result = await self.execute(ObstacleResponse.RETURN_TO_HOME, context)
            logger.info(
                "obstacle.rth_completed",
                outcome=result.get("status", "unknown"),
                reversed_direction=result.get("reversed_direction"),
            )
        finally:
            self._rth_active = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestRTHGuards -v`

Expected: PASS (all 5 tests)

- [ ] **Step 5: Run full obstacle test suite to verify no regressions**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py -v`

Expected: All tests PASS (existing + new)

- [ ] **Step 6: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/obstacle.py services/tello-mcp/tests/test_obstacle.py
git commit -m "fix: add RTH guards — rth_active flag + grounded check (Bug #2)

Prevents post-landing infinite DANGER loop and duplicate RTH execution.
Height guard only fires on confirmed ground reading — failed get_height
does not suppress RTH (safety-critical)."
```

---

## Task 3: Publish-After-Success in Flight Tools (Bug #3)

**Files:**
- Modify: `services/tello-mcp/tests/test_tools/test_flight.py`
- Modify: `services/tello-mcp/src/tello_mcp/tools/flight.py`

- [ ] **Step 1: Write the failing tests — events not published on SDK failure**

Add to `TestFlightTools` in `services/tello-mcp/tests/test_tools/test_flight.py`:

```python
async def test_takeoff_does_not_publish_on_failure(self):
    """Takeoff event is NOT published when SDK command fails."""
    mock_queue = AsyncMock()
    mock_queue.enqueue = AsyncMock(return_value={"error": "COMMAND_FAILED", "detail": "timeout"})
    mock_telemetry = AsyncMock()
    ctx = self._make_ctx(queue=mock_queue, telemetry=mock_telemetry)
    await self.registered_tools["takeoff"](ctx, room_id="living-room")
    mock_telemetry.publish_event.assert_not_called()

async def test_land_does_not_publish_on_failure(self):
    """Land event is NOT published when SDK command fails."""
    mock_queue = AsyncMock()
    mock_queue.enqueue = AsyncMock(return_value={"error": "LAND_FAILED", "detail": "timeout"})
    mock_telemetry = AsyncMock()
    ctx = self._make_ctx(queue=mock_queue, telemetry=mock_telemetry)
    await self.registered_tools["land"](ctx)
    mock_telemetry.publish_event.assert_not_called()

async def test_land_publishes_on_success(self):
    """Land event IS published when SDK command succeeds."""
    mock_queue = AsyncMock()
    mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
    mock_telemetry = AsyncMock()
    ctx = self._make_ctx(queue=mock_queue, telemetry=mock_telemetry)
    await self.registered_tools["land"](ctx)
    mock_telemetry.publish_event.assert_called_once()
    assert mock_telemetry.publish_event.call_args[0][0] == "land"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_tools/test_flight.py::TestFlightTools::test_takeoff_does_not_publish_on_failure services/tello-mcp/tests/test_tools/test_flight.py::TestFlightTools::test_land_does_not_publish_on_failure services/tello-mcp/tests/test_tools/test_flight.py::TestFlightTools::test_land_publishes_on_success -v`

Expected: `test_takeoff_does_not_publish_on_failure` FAIL, `test_land_does_not_publish_on_failure` FAIL (events published unconditionally). `test_land_publishes_on_success` should PASS.

- [ ] **Step 3: Write the fix — gate event publishing on success**

In `services/tello-mcp/src/tello_mcp/tools/flight.py`:

Add a logger import between the third-party imports and the `if TYPE_CHECKING` block
(i.e., after `from mcp.types import ToolAnnotations`, before `if TYPE_CHECKING:`):
```python
import structlog

logger = structlog.get_logger("tello_mcp.tools.flight")
```

Replace the `takeoff` tool body (lines 27-29):
```python
        result = await queue.enqueue(drone.takeoff, heavy=True)
        if result.get("status") == "ok":
            await telemetry.publish_event("takeoff", {"room_id": room_id})
        else:
            logger.warning(
                "event.skipped_command_failed",
                event_type="takeoff",
                error=result.get("error"),
            )
        return result
```

Replace the `land` tool body (lines 37-39):
```python
        result = await queue.enqueue(drone.safe_land)
        if result.get("status") == "ok":
            await telemetry.publish_event("land", {})
        else:
            logger.warning(
                "event.skipped_command_failed",
                event_type="land",
                error=result.get("error"),
            )
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_tools/test_flight.py -v`

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/tools/flight.py services/tello-mcp/tests/test_tools/test_flight.py
git commit -m "fix: publish events only after SDK success (Bug #3)

Prevents orphaned FlightSessions when takeoff/land SDK commands fail.
Event publishing now gated on result status check."
```

---

## Task 4: TelemetryPublisher Error Handling

**Files:**
- Modify: `services/tello-mcp/tests/test_telemetry.py`
- Modify: `services/tello-mcp/src/tello_mcp/telemetry.py`

- [ ] **Step 1: Write the failing test — Redis xadd failure is caught**

Add to `TestTelemetryPublisher` in `services/tello-mcp/tests/test_telemetry.py`:

```python
async def test_publish_event_logs_redis_failure(self, mock_redis):
    """Redis xadd failure is caught and logged, not raised."""
    mock_redis.xadd = AsyncMock(side_effect=ConnectionError("Redis down"))
    publisher = TelemetryPublisher(
        redis_client=mock_redis,
        channel="tello:telemetry",
        stream="tello:events",
    )
    # Should not raise
    await publisher.publish_event("takeoff", {"room_id": "test"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_telemetry.py::TestTelemetryPublisher::test_publish_event_logs_redis_failure -v`

Expected: FAIL — `ConnectionError: Redis down` propagates.

- [ ] **Step 3: Write the fix — wrap xadd in try/except**

In `services/tello-mcp/src/tello_mcp/telemetry.py`, replace `publish_event`
method (lines 47-56):

```python
    async def publish_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish a flight event to the Redis Stream.

        Args:
            event_type: Event type (e.g., "takeoff", "land", "move").
            data: Event payload.
        """
        fields = {"event_type": event_type, **{k: str(v) for k, v in data.items()}}
        try:
            await self._redis.xadd(self._stream, fields)
            logger.info("event.published", event_type=event_type)
        except Exception:
            logger.exception("event.publish_failed", event_type=event_type)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_telemetry.py -v`

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/telemetry.py services/tello-mcp/tests/test_telemetry.py
git commit -m "fix: catch Redis xadd failures in TelemetryPublisher

Prevents Redis connection errors from crashing event publishing.
Failures are logged with structlog for diagnosis."
```

---

## Task 5: Status Methods + State Reset

**Files:**
- Modify: `services/tello-mcp/tests/test_obstacle.py`
- Modify: `services/tello-mcp/src/tello_mcp/obstacle.py`

- [ ] **Step 1: Write the failing tests — status methods and state reset**

Add to `services/tello-mcp/tests/test_obstacle.py`:

```python
class TestObstacleMonitorStatus:
    def test_status_initial_state(self):
        monitor = ObstacleMonitor(MagicMock())
        status = monitor.status()
        assert status == {
            "running": False,
            "in_danger": False,
            "danger_clear_count": 0,
            "latest_reading_mm": None,
            "latest_zone": None,
        }

    async def test_status_after_start(self):
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 600}
        config = ObstacleConfig(poll_interval_ms=50)
        monitor = ObstacleMonitor(drone, config)
        await monitor.start()
        await asyncio.sleep(0.1)
        status = monitor.status()
        assert status["running"] is True
        assert status["latest_reading_mm"] == 600
        assert status["latest_zone"] == "clear"
        await monitor.stop()

    async def test_start_resets_stale_state(self):
        """Starting the monitor resets _in_danger and _danger_clear_count."""
        drone = MagicMock()
        drone.get_forward_distance.return_value = {"error": "EXHAUSTED"}
        monitor = ObstacleMonitor(drone, ObstacleConfig(poll_interval_ms=50))
        # Simulate stale state from a previous flight
        monitor._in_danger = True
        monitor._danger_clear_count = 2
        await monitor.start()
        assert monitor._in_danger is False
        assert monitor._danger_clear_count == 0
        await monitor.stop()


class TestObstacleResponseHandlerStatus:
    def test_status_initial(self):
        handler = ObstacleResponseHandler(MagicMock())
        assert handler.status() == {"rth_active": False}

    def test_status_rth_active(self):
        handler = ObstacleResponseHandler(MagicMock())
        handler._rth_active = True
        assert handler.status() == {"rth_active": True}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestObstacleMonitorStatus services/tello-mcp/tests/test_obstacle.py::TestObstacleResponseHandlerStatus -v`

Expected: FAIL — `status()` method doesn't exist.

- [ ] **Step 3: Write the implementation — status methods + state reset**

In `services/tello-mcp/src/tello_mcp/obstacle.py`:

Add `status()` to `ObstacleMonitor` (after the `is_running` property, around line 116):
```python
    def status(self) -> dict:
        """Current monitor state for diagnostics."""
        return {
            "running": self._running,
            "in_danger": self._in_danger,
            "danger_clear_count": self._danger_clear_count,
            "latest_reading_mm": self._latest.distance_mm if self._latest else None,
            "latest_zone": self._latest.zone.value if self._latest else None,
        }
```

Modify `start()` to reset stale state (lines 122-128):
```python
    async def start(self) -> None:
        """Start the background polling loop. Idempotent."""
        if self._running:
            return
        self._in_danger = False
        self._danger_clear_count = 0
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("obstacle_monitor.started", poll_interval_ms=self._config.poll_interval_ms)
```

Add `status()` to `ObstacleResponseHandler` (after `__init__`, around line 211):
```python
    def status(self) -> dict:
        """Current handler state for diagnostics."""
        return {"rth_active": self._rth_active}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestObstacleMonitorStatus services/tello-mcp/tests/test_obstacle.py::TestObstacleResponseHandlerStatus -v`

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/obstacle.py services/tello-mcp/tests/test_obstacle.py
git commit -m "feat: add status methods + state reset for observability

ObstacleMonitor.status() and ObstacleResponseHandler.status() expose
internal state for diagnostics. Monitor start() resets stale danger
state from previous flights."
```

---

## Task 6: Full Test Suite Verification + Lint

**Files:**
- No file modifications

- [ ] **Step 1: Run full tello-mcp test suite**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/ -v`

Expected: All tests PASS. Count should be 150 (existing) + new tests = ~165+.

- [ ] **Step 2: Run lint and format checks**

Run: `uv run ruff check services/tello-mcp/ && uv run ruff format --check services/tello-mcp/`

Expected: Clean — no errors.

- [ ] **Step 3: Run all workspace tests (regression check)**

Run each package separately per CLAUDE.md conventions:

```bash
uv run --package tello-core pytest packages/tello-core/tests/ -v
uv run --package tello-navigator pytest services/tello-navigator/tests/ -v
uv run --package tello-telemetry pytest services/tello-telemetry/tests/ -v
```

Expected: All pass. No regressions in other packages.

- [ ] **Step 4: Commit any lint fixes if needed**

If ruff found issues:
```bash
uv run ruff check --fix services/tello-mcp/
uv run ruff format services/tello-mcp/
git add -u && git commit -m "style: fix lint issues from Phase 4c changes"
```

---

## Task 7: Update Memory + Spec + PR

**Files:**
- Modify: `~/.claude/projects/-Users-arthurfantaci-Projects-tello-ai-platform/memory/MEMORY.md`
- Include: `docs/superpowers/specs/2026-03-20-phase4c-obstacle-monitor-bugfixes-design.md`
- Include: `docs/superpowers/plans/2026-03-20-phase4c-obstacle-monitor-bugfixes.md`

- [ ] **Step 1: Add spec + plan to the commit**

The spec and plan files are currently untracked. Stage them:
```bash
git add docs/superpowers/specs/2026-03-20-phase4c-obstacle-monitor-bugfixes-design.md
git add docs/superpowers/plans/2026-03-20-phase4c-obstacle-monitor-bugfixes.md
git commit -m "docs: Phase 4c spec + implementation plan"
```

- [ ] **Step 2: Push branch and create PR**

```bash
git push -u origin feat/phase-4c-obstacle-monitor-bugfixes
```

Create PR with:
- Title: `fix: Phase 4c — ObstacleMonitor bug fixes + observability`
- Body: Summary of three bugs fixed, testing approach, link to spec
- Must include `Closes #N` for the GitHub issue

- [ ] **Step 3: Wait for CI**

Run: `gh pr checks <PR_NUMBER>`

Expected: All checks pass (lint + 4 test suites). Type-check advisory only.

- [ ] **Step 4: Update MEMORY.md with Phase 4c status**

Update current state in MEMORY.md:
- Phase: 4c implementation complete, PR open, CI pending
- Tests: updated count
- Next action: physical test after merge, then Phase 4d

---

## Task 8: Physical Test (Post-Merge Validation)

> **Prerequisites:** PR merged, branch cleaned, on `main`.
> **Requires:** Drone powered on, human present.

- [ ] **Step 1: Claude Code starts infrastructure and services**

1. Verify Docker: `docker compose ps` (Neo4j + Redis healthy)
2. Kill any stale tello-telemetry: `kill $(lsof -iTCP:8200 -sTCP:LISTEN -t) 2>/dev/null`
3. Clear Redis stream: `docker exec tello-ai-platform-redis-1 redis-cli XTRIM tello:events MAXLEN 0`
4. Start tello-telemetry: `export $(grep -v '^#' .env | xargs) && uv run --package tello-telemetry python -m tello_telemetry.server --transport streamable-http --port 8200 &`
5. Verify tello-mcp connected: `get_telemetry` MCP tool
6. Record baseline: Neo4j FlightSession count, ObstacleIncident count, Redis stream length

- [ ] **Step 2: Ask human to confirm drone ready**

"Is the drone positioned facing a wall with ~1m of forward space?"

- [ ] **Step 3: Execute flight**

1. `takeoff(room_id="living-room")`
2. `move(direction="forward", distance_cm=50)` — may return "Motor stop" (expected)
3. Wait for RTH to complete: `get_telemetry` until `height_cm == 0`

- [ ] **Step 4: Post-flight validation**

1. Wait 30 seconds, check Redis XLEN at 0s, 15s, 30s
2. **Pass:** Stream count == 3 (takeoff + obstacle_danger + land), stable over 30s
3. Query Neo4j: `MATCH (fs:FlightSession) WHERE fs.end_time IS NOT NULL RETURN fs ORDER BY fs.start_time DESC LIMIT 1`
4. Query Neo4j: `MATCH (o:ObstacleIncident)-[:TRIGGERED_DURING]->(fs:FlightSession) RETURN o, fs ORDER BY o.timestamp DESC LIMIT 1`
5. **Pass:** FlightSession has `end_time`, ObstacleIncident linked via TRIGGERED_DURING

- [ ] **Step 5: Report results and update MEMORY.md**

If PASS: Update MEMORY.md — Phase 4c COMPLETE, update test counts, note pipeline validated.
If FAIL: Investigate using the new structured logs, iterate on fix.
