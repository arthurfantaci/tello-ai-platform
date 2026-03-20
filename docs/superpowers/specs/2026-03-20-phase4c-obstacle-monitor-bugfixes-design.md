# Phase 4c: ObstacleMonitor Bug Fixes + Observability

**Date:** 2026-03-20
**Phase:** 4c
**Status:** Approved
**Depends on:** Phase 4b (merged, PR #23)

## Problem Statement

End-to-end pipeline testing (2026-03-19 and 2026-03-20) revealed three bugs in the obstacle avoidance event-publishing chain. The drone's physical safety behavior is correct (RTH stops, reverses, and lands reliably), but the software's reporting of those actions to the data pipeline is broken in two distinct failure modes:

### Bug #1: Missing RTH Events (Confirmed Reproducible — Runs 2 & 3)

**Symptom:** ObstacleMonitor triggers RTH, drone physically reverses and lands, but `obstacle_danger` and `land` events are never published to Redis. FlightSession is never closed (no `end_time`). No ObstacleIncident in Neo4j.

**Root cause hypothesis:** An unhandled exception in the `on_obstacle_reading` callback silently kills event publishing. The `_poll_loop` (obstacle.py lines 176-179) has no `try/except` around callback execution — any exception propagates and either kills the callback chain or is swallowed without logging.

**Evidence:** Redis stream shows only `takeoff` event after flights where RTH clearly executed (drone observed reversing and landing). No structured logs available to diagnose further — the failure is completely silent.

### Bug #2: Post-Landing Infinite DANGER Loop (Run 1, Position-Dependent)

**Symptom:** After RTH lands the drone near an obstacle (<200mm), ObstacleMonitor continues polling, sees DANGER, re-triggers RTH on a grounded drone. Produces ~1 `obstacle_danger` + `land` event pair per second indefinitely. Run 1 produced 280 events (140 pairs) before the session was stopped.

**Root cause:** `on_obstacle_reading` has no guard for "drone is already on the ground" or "RTH is already in progress." After landing, if the forward ToF sensor still reads <200mm (drone landed close to obstacle), the callback fires RTH again on a grounded drone.

**Condition:** Only occurs when the drone's final position after RTH reverse is still within DANGER range (<200mm from obstacle). Run 1: drone landed at ~185mm (DANGER). Runs 2-3: drone landed at ~700mm (CLEAR) — no loop.

**Mitigating factor:** The tello-telemetry consumer's `_handle_land()` sets `_current_session = None`, causing subsequent `obstacle_danger` events to be silently dropped (no active session guard). This accidentally prevented Neo4j spam — only 1 ObstacleIncident was written despite 140 DANGER events.

### Bug #3: Orphaned FlightSessions on Failed Takeoff

**Symptom:** `publish_event("takeoff")` fires before checking if the SDK `takeoff()` command succeeded. When the SDK times out or fails, a FlightSession is created in Neo4j with no matching `land` event — an orphaned session with no `end_time`.

**Evidence:** Three orphaned FlightSessions found in Neo4j (cleaned up during testing): one from integration test, one from failed connection attempt, one from SDK timeout.

**Root cause:** In `flight.py`, the takeoff tool publishes the event unconditionally:
```python
result = await queue.enqueue(drone.takeoff, heavy=True)
await telemetry.publish_event("takeoff", {"room_id": room_id})  # fires regardless of result
return result
```

## Design

### Fix #1: Callback Exception Handling in `_poll_loop`

Wrap callback execution in `obstacle.py` `_poll_loop` with `try/except`:

```python
for cb in self._callbacks:
    try:
        cb_result = cb(reading)
        if asyncio.iscoroutine(cb_result):
            await cb_result
    except Exception:
        logger.exception("obstacle.callback_failed", distance_mm=reading.distance_mm, zone=reading.zone.value)
```

This ensures:
- The monitor keeps running after a callback failure
- The failure is logged with full traceback for diagnosis
- Subsequent callbacks still execute even if one fails

### Fix #2: RTH Guards in `ObstacleResponseHandler`

Add two guards to `on_obstacle_reading`:

**Guard A — RTH-in-progress flag:**
```python
# In __init__:
self._rth_active = False

# In on_obstacle_reading:
if self._rth_active:
    logger.debug("obstacle.rth_skipped_active", distance_mm=reading.distance_mm)
    return
```

**Guard B — Grounded check (only when height query succeeds):**
```python
height_result = await asyncio.to_thread(self._drone.get_height)
height_cm = height_result.get("height_cm", 0) if height_result.get("status") == "ok" else 0

# Only skip RTH if we have a confirmed ground reading — a failed get_height
# must NOT suppress RTH, as the drone may be airborne with a sensor error.
if height_result.get("status") == "ok" and height_cm == 0:
    logger.debug("obstacle.rth_skipped_grounded", height_cm=height_cm, distance_mm=reading.distance_mm)
    return
```

**Flag lifecycle:**
```python
self._rth_active = True
try:
    context = ObstacleContext(...)
    await self.execute(ObstacleResponse.RETURN_TO_HOME, context)
finally:
    self._rth_active = False
```

The `finally` block ensures the flag is always cleared, even if `execute()` raises.

### Fix #3: Publish-After-Success in Flight Tools

**Note on dual `land` event paths:** There are two independent paths that publish
`land` events: (1) the `land` MCP tool in flight.py (manual landing) and (2)
`ObstacleResponseHandler.execute()` in obstacle.py (automated RTH landing). These
are mutually exclusive — manual landing goes through the tool, RTH landing goes
through the handler. Both paths should gate on success, but they cannot produce
duplicate events for the same landing.

**takeoff:**

```python
result = await queue.enqueue(drone.takeoff, heavy=True)
if result.get("status") == "ok":
    await telemetry.publish_event("takeoff", {"room_id": room_id})
else:
    logger.warning("event.skipped_command_failed",
                   event_type="takeoff", error=result.get("error"))
return result
```

**land:**

```python
result = await queue.enqueue(drone.safe_land)
if result.get("status") == "ok":
    await telemetry.publish_event("land", {})
else:
    logger.warning("event.skipped_command_failed",
                   event_type="land", error=result.get("error"))
return result
```

### Observability: Structured Log Events

Add structured log events at key decision points:

| Log Event | Logger | Trigger | Key Fields |
|---|---|---|---|
| `obstacle.callback_failed` | `tello_mcp.obstacle` | Callback raises exception | `error`, `distance_mm`, `zone` |
| `obstacle.rth_skipped_grounded` | `tello_mcp.obstacle` | Height guard fires | `height_cm`, `distance_mm` |
| `obstacle.rth_skipped_active` | `tello_mcp.obstacle` | RTH-in-progress guard fires | `distance_mm` |
| `obstacle.rth_started` | `tello_mcp.obstacle` | RTH begins executing | `distance_mm`, `height_cm`, `last_direction` |
| `obstacle.rth_completed` | `tello_mcp.obstacle` | RTH finishes | `outcome`, `reversed_direction` |
| `event.published` | `tello_mcp.telemetry` | Event added to Redis | `event_type` |
| `event.publish_failed` | `tello_mcp.telemetry` | Redis XADD fails | `event_type`, `error` |
| `event.skipped_command_failed` | `tello_mcp.tools` | Event skipped (SDK failure) | `event_type`, `error` |

### Observability: TelemetryPublisher Error Handling

Wrap `xadd` in `publish_event` with try/except to surface Redis failures:

```python
async def publish_event(self, event_type: str, data: dict[str, Any]) -> None:
    fields = {"event_type": event_type, **{k: str(v) for k, v in data.items()}}
    try:
        await self._redis.xadd(self._stream, fields)
        logger.info("event.published", event_type=event_type)
    except Exception:
        logger.exception("event.publish_failed", event_type=event_type)
```

### Observability: Status Methods

**ObstacleMonitor.status():**

```python
def status(self) -> dict:
    return {
        "running": self._running,
        "in_danger": self._in_danger,
        "danger_clear_count": self._danger_clear_count,
        "latest_reading_mm": self._latest.distance_mm if self._latest else None,
        "latest_zone": self._latest.zone.value if self._latest else None,
    }
```

**ObstacleResponseHandler.status():**

```python
def status(self) -> dict:
    return {"rth_active": self._rth_active}
```

### Observability: State Reset on Monitor Start

When the monitor starts (or restarts between flights), reset internal state
to prevent stale values from a previous flight leaking into the next one:

```python
async def start(self) -> None:
    if self._running:
        return
    self._in_danger = False
    self._danger_clear_count = 0
    self._running = True
    self._task = asyncio.create_task(self._poll_loop())
```

## Testing

### Unit Tests

**callback exception handling:**
- `_poll_loop` continues after callback raises `RuntimeError`
- Exception is logged (verify with structlog `capture_logs()`)

**RTH guards:**
- `on_obstacle_reading` returns immediately when `_rth_active` is True
- `on_obstacle_reading` returns immediately when `height_cm == 0`
- `_rth_active` is set to True before `execute()` and False after
- `_rth_active` is cleared even if `execute()` raises

**Publish-after-success:**
- `takeoff` tool does NOT call `publish_event` when SDK returns error
- `land` tool does NOT call `publish_event` when SDK returns error
- `takeoff` tool calls `publish_event` when SDK returns success
- `land` tool calls `publish_event` when SDK returns success

**Status methods:**
- `ObstacleMonitor.status()` returns correct fields
- `ObstacleResponseHandler.status()` returns `rth_active` state

### Physical Test (End-to-End Pipeline Validation)

**Pre-flight (Claude Code automates):**
1. Verify Docker infrastructure (Neo4j + Redis) running and healthy
2. Start tello-telemetry in background
3. Verify tello-mcp connected to drone via `get_telemetry`
4. Record Redis stream baseline count
5. Record Neo4j FlightSession and ObstacleIncident counts

**Flight (Claude Code via MCP, human confirms drone ready):**
1. Ask human: "Is the drone positioned facing a wall with ~1m of forward space?"
2. `takeoff(room_id="living-room")`
3. `move(direction="forward", distance_cm=50)` — may return "Motor stop" (expected)
4. Wait for RTH to complete (check height == 0)

**Post-flight validation (Claude Code automates):**
1. Wait 30 seconds, check Redis stream count at 0s, 15s, 30s
2. Stream count should be exactly 3 (takeoff + obstacle_danger + land)
3. Stream count should NOT grow over 30 seconds (no infinite loop)
4. Query Neo4j: new FlightSession has `end_time` set
5. Query Neo4j: new ObstacleIncident exists with `TRIGGERED_DURING` relationship
6. Report pass/fail with full data

**Pass criteria:**
- Redis: exactly 3 events, stable count for 30s
- Neo4j: FlightSession closed, ObstacleIncident linked
- No orphaned sessions from this test run

## Files Modified

- `services/tello-mcp/src/tello_mcp/obstacle.py` — callback guard, RTH guards, status methods, structured logging
- `services/tello-mcp/src/tello_mcp/tools/flight.py` — publish-after-success for takeoff and land
- `services/tello-mcp/src/tello_mcp/telemetry.py` — publish error logging
- `services/tello-mcp/tests/test_obstacle.py` — callback exception test, RTH guard tests, status tests
- `services/tello-mcp/tests/test_tools/test_flight.py` — publish-on-failure tests

## Out of Scope

- **Phase 4d:** Containerization, Docker Compose orchestration, health check endpoints
- **Phase 4e:** Unified Command Path (architectural refactor before Phase 5)
- New MCP tools for status (status methods are internal; exposure deferred)
- Log aggregation, dashboards, metrics (overkill for current scale)
- tello-telemetry consumer hardening (its "no active session" guard already works)

## Phase Sequencing

- **Phase 4c** (this spec): Bug fixes + observability
- **Phase 4d**: Containerize tello-mcp and tello-telemetry, Docker Compose as single startup, HTTP MCP transport
- **Phase 4e**: Unify CommandQueue + ObstacleMonitor into single command coordination layer (required before Phase 5 adds vision-based obstacle detection as a third actor)
- **Phase 5**: tello-vision (CV pipeline)
- **Phase 6**: tello-voice (NL controller + AI agent with MCP client)
