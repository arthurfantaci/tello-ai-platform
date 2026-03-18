# Phase 4b: Navigator Obstacle Avoidance — Design Spec

## Summary

Add obstacle avoidance safety to the tello-ai-platform so the drone autonomously stops, reverses, and lands when the forward ToF sensor detects an imminent collision. This phase solves the SDK command contention blocker, implements the RETURN_TO_HOME response action, persists obstacle incidents to Neo4j, and fixes the missing land event.

## Design Constraints (from physical testing)

- **SDK command contention:** The Tello SDK communicates over a single UDP port (8889). Concurrent calls (ObstacleMonitor sensor polls + flight commands) cause crossed responses. Must be serialized before any concurrent operation.
- **Forward ToF at altitude:** The VL53L0X sensor (25-degree FOV) reliably detects obstacles at <50cm (~20in) while airborne. It is a close-range last-resort safety device, not a navigation sensor.
- **Sensor characterization:** 500mm max reliable range, 8190 out-of-range value, 3.2 Hz polling rate, 5.3mm noise at fixed distance.
- **Autonomous safety principle:** Safety actions (stop, reverse, land) execute immediately without caller permission. Strategic actions (abort mission, retry) are deferred to the caller after the drone is safe.

## Section 1: Command Serialization

### Problem

The ObstacleMonitor polls `get_forward_distance()` via `asyncio.to_thread()` while MCP flight tools dispatch movement commands via the same mechanism. Both hit DroneAdapter methods that call djitellopy on the single UDP port. Responses get crossed — the monitor receives `"ok"` (a move response) while the move command receives `"tof 8190"` (a sensor reading).

### Solution

Add `threading.Lock` to DroneAdapter. Every method that calls djitellopy acquires the lock before executing.

### Changes

**File:** `services/tello-mcp/src/tello_mcp/drone.py`

- Add `self._command_lock = threading.Lock()` to `__init__`
- Wrap all SDK-calling methods with `with self._command_lock:`:
  - `connect`, `disconnect`, `keepalive`
  - `takeoff`, `land`, `safe_land`, `emergency`, `stop` (new)
  - `move`, `rotate`, `go_xyz_speed_mid`
  - `get_telemetry`, `get_forward_distance`, `detect_mission_pad`
  - `set_pad_detection_direction`
  - `set_led`, `display_scroll_text`, `display_static_char`, `display_pattern`

### Bug Fix: Missing `stop()` Method

ObstacleMonitor (obstacle.py line 162) calls `self._drone.stop()` when entering DANGER zone, but DroneAdapter has no `stop()` method. Tests pass because they mock it.

Add:
```python
def stop(self) -> dict:
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

### Latency Impact

Worst case ~300ms added when contention occurs (one call waits for another to finish). Acceptable given the drone's 15-second auto-land timeout and the sensor's 3.2 Hz polling rate.

## Section 2: RETURN_TO_HOME Strategy

### Architecture

Uses the Strategy Pattern with Python's `Protocol` for dependency injection. The ObstacleResponseHandler receives a strategy at construction time and delegates to it without knowing the implementation details.

### New Types

**File:** `services/tello-mcp/src/tello_mcp/strategies.py`

```python
@dataclass(frozen=True)
class ObstacleContext:
    last_direction: str            # direction drone was moving
    last_distance_cm: int          # commanded move distance
    height_cm: int                 # altitude from downward ToF at detection time
    forward_distance_mm: int       # forward ToF reading that triggered DANGER
    mission_id: str | None = None  # active mission, if any
    room_id: str | None = None     # current room, if known

class ReturnToHomeStrategy(Protocol):
    def return_to_home(self, drone: DroneAdapter, context: ObstacleContext) -> dict: ...

class SimpleReverseRTH:
    """Phase 4b strategy: stop, reverse last movement, land."""

    def return_to_home(self, drone: DroneAdapter, context: ObstacleContext) -> dict:
        # Reverse the last movement (skip if no movement recorded)
        if context.last_direction and context.last_distance_cm > 0:
            opposite = _opposite_direction(context.last_direction)
            drone.move(opposite, context.last_distance_cm)
        drone.land()
        return {
            "status": "returned",
            "method": "simple_reverse",
            "reversed_direction": opposite if context.last_direction else None,
            "height_cm": context.height_cm,
            "forward_distance_mm": context.forward_distance_mm,
            "landed": True,
        }
```

### Context Population

- MCP flight tools (`move`, `rotate`, `go_to_mission_pad`) update a shared `last_command` dict on the lifespan context after each execution.
- When DANGER triggers, ObstacleMonitor builds `ObstacleContext` by:
  - Reading `last_command` for direction and distance
  - Calling `drone.get_telemetry()` for `height_cm` (serialized through the lock)
  - Using the DANGER reading for `forward_distance_mm`
  - Reading `mission_id` and `room_id` from lifespan context
- If no `last_command` exists (DANGER during hover), RTH skips reverse and just lands.

### Handler Integration

**File:** `services/tello-mcp/src/tello_mcp/obstacle.py`

- `ObstacleResponseHandler.__init__` receives `rth_strategy: ReturnToHomeStrategy`
- `RETURN_TO_HOME` case: `self._rth.return_to_home(drone, context)`
- `EMERGENCY_LAND` and `MANUAL_OVERRIDE` unchanged

### Startup Wiring

**File:** `services/tello-mcp/src/tello_mcp/server.py`

```python
strategy = SimpleReverseRTH()
handler = ObstacleResponseHandler(drone=drone, rth_strategy=strategy)
```

### Future Enhancement Path

Phase 5 (vision): inject `VisionGuidedRTH` — uses camera to navigate home.
Phase 6 (voice): inject `VoiceConfirmedRTH` — asks operator before returning.
ObstacleResponseHandler code never changes. Only the strategy injected at startup changes.

### Files Touched

- New: `services/tello-mcp/src/tello_mcp/strategies.py`
- Modified: `services/tello-mcp/src/tello_mcp/obstacle.py`
- Modified: `services/tello-mcp/src/tello_mcp/tools/flight.py`
- Modified: `services/tello-mcp/src/tello_mcp/server.py`

## Section 3: Obstacle Event Publishing & Neo4j Persistence

### Event Publishing (tello-mcp)

When ObstacleResponseHandler completes a DANGER response, publish to `tello:events` Redis stream:

```python
await telemetry.publish_event("obstacle_danger", {
    "forward_distance_mm": context.forward_distance_mm,
    "forward_distance_in": round(context.forward_distance_mm / 25.4, 1),
    "height_cm": context.height_cm,
    "zone": "DANGER",
    "response": "RETURN_TO_HOME",
    "outcome": "landed",
    "mission_id": context.mission_id,
    "room_id": context.room_id,
    "reversed_direction": "back",
})
```

Uses the existing `tello:events` stream — no new infrastructure.

### Bug Fix: Land Event Publishing

Add `await telemetry.publish_event("land", {})` to:
- The `land()` MCP tool in `tools/flight.py`
- `SimpleReverseRTH.return_to_home()` after `drone.land()` (since RTH calls the adapter directly, not the MCP tool)

This closes the gap where FlightSessions never receive an `end_time`.

### Event Consumption (tello-telemetry)

**File:** `services/tello-telemetry/src/tello_telemetry/consumer.py`

Add route in `_process_message`:
```python
elif event_type == "obstacle_danger":
    await self._handle_obstacle(fields)
```

`_handle_obstacle()` builds an `ObstacleIncident` model and calls `repo.add_obstacle_incident()`.

### Neo4j Schema Addition

**File:** `services/tello-telemetry/src/tello_telemetry/session_repo.py`

New method `add_obstacle_incident(session_id, incident)`:

```cypher
MATCH (fs:FlightSession {id: $session_id})
CREATE (oi:ObstacleIncident {
    id: $id,
    timestamp: $timestamp,
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
```

### New Model

**File:** `packages/tello-core/src/tello_core/models.py`

```python
class ObstacleIncident(BaseModel):
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

### Files Touched

- Modified: `services/tello-mcp/src/tello_mcp/obstacle.py` (publish event after response)
- Modified: `services/tello-mcp/src/tello_mcp/tools/flight.py` (land event)
- Modified: `services/tello-mcp/src/tello_mcp/strategies.py` (RTH publishes land event)
- Modified: `services/tello-telemetry/src/tello_telemetry/consumer.py` (obstacle_danger route)
- Modified: `services/tello-telemetry/src/tello_telemetry/session_repo.py` (add_obstacle_incident)
- Modified: `packages/tello-core/src/tello_core/models.py` (ObstacleIncident model)

## Section 4: Testing Strategy

### Project-Wide Requirement

tello-telemetry MUST be running during all physical tests, integration tests, and manual drone operations. Without it, the Redis → Neo4j pipeline is inactive and no flight data is persisted.

### Unit Tests (mocked, fast)

**tello-mcp tests:**

| Test | Verifies |
|------|----------|
| `test_drone_command_lock` | Two concurrent calls execute sequentially via lock |
| `test_drone_stop_method` | `stop()` exists and calls `send_control_command("stop")` |
| `test_obstacle_context_built` | ObstacleContext includes height_cm, forward_distance_mm, last_direction, last_distance_cm |
| `test_simple_reverse_rth` | `return_to_home()` calls `move(opposite)` then `land()` in order |
| `test_simple_reverse_rth_no_last_command` | RTH skips reverse and just lands when no movement recorded |
| `test_obstacle_event_published` | Response handler calls `publish_event("obstacle_danger", ...)` with correct fields |
| `test_land_event_published` | `land()` tool publishes `"land"` event |
| `test_rth_publishes_land_event` | SimpleReverseRTH publishes land event after landing |

**tello-telemetry tests:**

| Test | Verifies |
|------|----------|
| `test_handle_obstacle_event` | `obstacle_danger` event routed to `_handle_obstacle()`, calls repo correctly |
| `test_handle_land_event` | `land` event calls `repo.end_session()` |
| `test_obstacle_incident_cypher` | `add_obstacle_incident()` generates correct Cypher with TRIGGERED_DURING |

### Integration Tests (real Redis + real Neo4j)

**File:** `services/tello-telemetry/tests/test_integration.py`

| Test | Verifies |
|------|----------|
| `test_obstacle_pipeline_end_to_end` | Publish takeoff → obstacle_danger → land to real Redis. Run consumer. Query Neo4j: FlightSession + ObstacleIncident linked via TRIGGERED_DURING, height_cm and forward_distance_mm present |
| `test_flight_session_lifecycle` | Publish takeoff → 3× telemetry → land. Verify FlightSession has 3 samples and correct duration_s |
| `test_consumer_liveness_check` | Publish heartbeat from MCP startup, verify ACK within timeout |

### Physical Tests (real drone)

**File:** `testing/test_phase4b.py`

Three-stage script:

1. **Stage 1 — Lock verification:** Start ObstacleMonitor + execute 5 forward/back movements. Log all responses. Assert zero crossed responses.
2. **Stage 2 — RETURN_TO_HOME trigger:** Fly forward toward wall/object. Verify drone stops at DANGER threshold (~8in / 200mm), reverses, and lands. Record height_cm and forward_distance_mm.
3. **Stage 3 — Pipeline verification:** With tello-telemetry running, query Neo4j after Stage 2. Verify FlightSession + ObstacleIncident exist with correct spatial data.

### Physical Test Prerequisites

1. `docker compose up -d` (Redis + Neo4j healthy)
2. Start tello-telemetry: `uv run --package tello-telemetry python -m tello_telemetry.server`
3. Start tello-mcp: `uv run --package tello-mcp python -m tello_mcp.server`
4. Drone powered on and connected (Router Mode, DHCP)
5. Clear flight area with a wall or object for RTH testing

## Out of Scope (Deferred)

| Item | Deferred To | Reason |
|------|-------------|--------|
| `avoid_and_continue` response | Phase 5+ | Sensor FOV at altitude limits reliable detection to <50cm — not enough for path planning |
| Navigator deep integration | Phase 5/6 brainstorm | Mission pause/resume, obstacle-aware waypoint replanning |
| Keyboard manual control | Phase 6 (tello-voice) | Client-side feature, not MCP server scope |
| Mission stream consumer | Separate design cycle | `tello:missions` stream needs its own consumer service |
| Forward ToF in telemetry samples | Future enhancement | Nice to have, not blocking |
| Waypoint visit tracking | With mission consumer | Depends on mission stream consumer |

## Files Summary

### New Files
- `services/tello-mcp/src/tello_mcp/strategies.py`
- `services/tello-telemetry/tests/test_integration.py`
- `testing/test_phase4b.py`

### Modified Files
- `services/tello-mcp/src/tello_mcp/drone.py` (lock + stop method)
- `services/tello-mcp/src/tello_mcp/obstacle.py` (handler + context + event publishing)
- `services/tello-mcp/src/tello_mcp/tools/flight.py` (last_command tracking + land event)
- `services/tello-mcp/src/tello_mcp/server.py` (strategy injection)
- `services/tello-telemetry/src/tello_telemetry/consumer.py` (obstacle_danger + land routes)
- `services/tello-telemetry/src/tello_telemetry/session_repo.py` (add_obstacle_incident)
- `packages/tello-core/src/tello_core/models.py` (ObstacleIncident model)
