# Forward ToF Sensor Integration — Design Spec

**Phase:** 4 (sensor plumbing) + 4a (active safety)
**Date:** 2026-03-16
**Status:** Draft

## Overview

Integrate the forward-facing Time-of-Flight (ToF) sensor on the Dot-Matrix Display & Distance Sensing Module into the tello-ai-platform. This sensor faces forward from the front of the module, measuring distance to obstacles ahead via the `EXT tof?` command through the Open-Source Controller (ESP32). It returns distance in millimeters (8192 if out of range).

This is completely independent from the drone's built-in downward ToF (Vision Positioning System), which measures altitude via `get_distance_tof()` and returns centimeters.

**Safety motivation:** The drone operates in a home environment with children and pets. Forward obstacle detection and automatic safety stops are a non-negotiable requirement, not a deferred feature.

## Phase Structure

- **Phase 4:** Sensor plumbing — expose the sensor end-to-end (DroneAdapter → MCP tool → fly.py CLI → telemetry), with continuous background polling and zone classification.
- **Phase 4a:** Active safety — forced stop in DANGER zone, options menu (Emergency Landing, Return to Home, Obstacle Avoidance & Continue Mission, Manual Override), with provider pattern for CLI/MCP/future voice UI.
- **Phase 4b:** (Deferred — separate brainstorm cycle) Implement `return_to_home` and `avoid_and_continue` response options via navigator integration.

## Architecture: Approach B — Separate ObstacleMonitor

DroneAdapter provides raw sensor I/O (`get_forward_distance()`). A new ObstacleMonitor class handles zone classification, continuous polling, and stop enforcement. This follows the Pure Core pattern: raw sensor data separated from business logic interpretation.

```
EXT tof? → DroneAdapter.get_forward_distance()  (raw I/O)
               ↓
         ObstacleMonitor._poll_loop()           (background task)
               ↓
         classify_zone() → ObstacleReading      (pure function)
               ↓
         DANGER? → drone.stop()                 (immediate, bypasses queue)
               ↓
         Callbacks → MCP tools / fly.py / navigator
```

### Why ObstacleMonitor is a separate class (not embedded in DroneAdapter)

1. **Pure Core pattern:** DroneAdapter stays focused on hardware I/O; ObstacleMonitor owns business logic (zone classification, threshold management, stop enforcement).
2. **Phase 5 extension:** ObstacleMonitor is the natural place for vision enrichment — classification data plugs into ObstacleReading without touching DroneAdapter.
3. **Testability:** Zone classification is a pure function — testable without mocking any hardware.
4. **Single responsibility:** Each class has one job.

## Data Models (tello-core)

### TelemetryFrame Addition

```python
class TelemetryFrame(BaseModel):
    # ... existing fields ...
    forward_tof_mm: int | None = None  # Forward ToF (Dot-Matrix Module), mm. None if unavailable.
```

- `None` = Dot-Matrix Module not installed or sensor not responding
- `8192` = sensor returns "out of range" (stored as-is; interpretation is in ObstacleReading)
- Units: mm (matching SDK), distinct from downward `tof_cm` (cm)

### ObstacleZone Enum

```python
class ObstacleZone(str, Enum):
    CLEAR = "clear"        # No obstacle in range
    CAUTION = "caution"    # Obstacle detected, advisory only
    WARNING = "warning"    # Obstacle approaching, reduce speed
    DANGER = "danger"      # Obstacle too close, forced stop
```

### ObstacleReading Model

```python
class ObstacleReading(BaseModel):
    distance_mm: int                           # Raw sensor value
    zone: ObstacleZone                         # Interpreted zone
    timestamp: datetime                        # When this reading was taken
    # Phase 5 extension points (optional, None until vision is integrated)
    classification: str | None = None          # e.g., "person", "wall", "pet"
    confidence: float | None = None            # Classification confidence (0.0-1.0)
```

### ObstacleConfig (Config-Driven Thresholds)

```python
@dataclass(frozen=True)
class ObstacleConfig:
    caution_mm: int = 1500    # <150cm → CAUTION
    warning_mm: int = 800     # <80cm → WARNING
    danger_mm: int = 400      # <40cm → DANGER (forced stop)
    out_of_range: int = 8192  # SDK value meaning "nothing detected"
    poll_interval_ms: int = 200  # Polling frequency
```

Overridable via environment variables (e.g., `OBSTACLE_DANGER_MM=500`).

## DroneAdapter — Raw Sensor Method

### New Method: `get_forward_distance()`

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
    except (ValueError, TypeError) as e:
        logger.exception("forward tof parse failed", response=response)
        return {"error": "PARSE_ERROR", "detail": f"Unexpected response: {response}"}
    except Exception as e:
        logger.exception("forward tof query failed")
        return {"error": "COMMAND_FAILED", "detail": str(e)}
```

**Key note:** This is the first expansion command that captures and parses a response. All existing expansion commands (LED, display) are fire-and-forget.

### Integration with `get_telemetry()`

```python
def get_telemetry(self) -> TelemetryFrame | dict:
    # ... existing code ...
    forward_result = self.get_forward_distance()
    forward_mm = forward_result.get("distance_mm") if forward_result.get("status") == "ok" else None

    return TelemetryFrame(
        # ... existing fields ...
        forward_tof_mm=forward_mm,
    )
```

Graceful degradation: if the forward sensor fails, `forward_tof_mm` is `None` and telemetry continues working.

## ObstacleMonitor (New Component)

**File:** `services/tello-mcp/src/tello_mcp/obstacle.py`

### Class Design

```python
class ObstacleMonitor:
    """Continuous forward ToF monitoring with tiered zone enforcement."""

    def __init__(self, drone: DroneAdapter, config: ObstacleConfig | None = None):
        self._drone = drone
        self._config = config or ObstacleConfig()
        self._latest: ObstacleReading | None = None
        self._running = False
        self._task: asyncio.Task | None = None
        self._callbacks: list[Callable[[ObstacleReading], None]] = []

    # --- Lifecycle ---
    async def start(self) -> None       # Start polling loop
    async def stop(self) -> None        # Cancel polling, cleanup

    # --- Core ---
    def classify_zone(self, distance_mm: int) -> ObstacleZone  # Pure function
    async def _poll_loop(self) -> None  # Background task

    # --- Consumer API ---
    @property
    def latest(self) -> ObstacleReading | None   # Last reading
    def on_reading(self, callback: Callable) -> None  # Subscribe

    # --- Phase 5 extension point ---
    def enrich(self, classification: str, confidence: float) -> None
```

### Zone Classification (Pure Function)

```python
def classify_zone(self, distance_mm: int) -> ObstacleZone:
    if distance_mm >= self._config.out_of_range:
        return ObstacleZone.CLEAR
    if distance_mm < self._config.danger_mm:
        return ObstacleZone.DANGER
    if distance_mm < self._config.warning_mm:
        return ObstacleZone.WARNING
    if distance_mm < self._config.caution_mm:
        return ObstacleZone.CAUTION
    return ObstacleZone.CLEAR
```

### Poll Loop with Safety Enforcement

```python
async def _poll_loop(self) -> None:
    while self._running:
        result = self._drone.get_forward_distance()
        if result.get("status") == "ok":
            distance_mm = result["distance_mm"]
            zone = self.classify_zone(distance_mm)
            reading = ObstacleReading(
                distance_mm=distance_mm,
                zone=zone,
                timestamp=datetime.now(UTC),
            )
            self._latest = reading

            # SAFETY: Forced stop in DANGER zone
            if zone == ObstacleZone.DANGER:
                logger.warning("obstacle.danger", distance_mm=distance_mm)
                self._drone.stop()  # Direct call, bypasses command queue

            for cb in self._callbacks:
                cb(reading)

        await asyncio.sleep(self._config.poll_interval_ms / 1000)
```

**Why the stop bypasses the command queue:** The command queue serializes flight commands to prevent conflicts. A safety stop is an override — it must execute immediately, even if a move command is in the queue. This matches the existing `safe_land()` pattern.

### Server Integration

```python
@asynccontextmanager
async def lifespan(mcp):
    drone = DroneAdapter()
    monitor = ObstacleMonitor(drone)
    # ... existing setup ...
    yield {"drone": drone, "monitor": monitor, ...}
    await monitor.stop()
```

## MCP Tools

### New: `get_forward_distance`

In `sensors.py` (it's a sensor reading, not an expansion command):

```python
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
```

Reads from ObstacleMonitor's cached latest reading — zero additional hardware communication.

### New: `get_obstacle_status`

```python
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

### Updated: `get_tof_distance` docstring

Clarify that this is the downward sensor:

```python
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def get_tof_distance(ctx: Context) -> dict:
    """Get DOWNWARD Time-of-Flight distance in cm (built-in Vision Positioning System).

    This is the drone's built-in downward-facing sensor for altitude/ground distance.
    For forward obstacle detection, use get_forward_distance instead.
    """
```

## fly.py CLI Commands

### `tof` — Forward distance reading

```
> tof
Forward ToF: 1245mm (CLEAR)

> tof
Forward ToF: 350mm DANGER — drone stopped
```

### `monitor` — ObstacleMonitor status

```
> monitor
Obstacle monitor: RUNNING
  Latest: 1245mm (CLEAR) @ 14:32:05
  Thresholds: CAUTION <1500mm, WARNING <800mm, DANGER <400mm
  Poll interval: 200ms
```

## Phase 4a: Obstacle Response System

### ObstacleResponse Enum

```python
class ObstacleResponse(str, Enum):
    EMERGENCY_LAND = "emergency_land"          # Land immediately
    RETURN_TO_HOME = "return_to_home"          # Navigate back to launch pad
    AVOID_AND_CONTINUE = "avoid_and_continue"  # Lateral dodge, resume mission
    MANUAL_OVERRIDE = "manual_override"        # User takes control
```

### ObstacleResponseHandler

```python
class ObstacleResponseHandler:
    """Presents obstacle response options and executes the chosen action.

    Phase 4a: emergency_land + manual_override working.
    Phase 4b: return_to_home + avoid_and_continue (navigator integration).
    Phase 6: VoiceResponseProvider.
    """

    def __init__(self, drone: DroneAdapter):
        self._drone = drone
        self._providers: list[ResponseProvider] = []

    async def handle_obstacle(self, reading: ObstacleReading) -> ObstacleResponse:
        choice = await self._get_choice(reading)
        await self._execute(choice)
        return choice

    async def _execute(self, choice: ObstacleResponse) -> dict:
        match choice:
            case ObstacleResponse.EMERGENCY_LAND:
                return self._drone.safe_land()
            case ObstacleResponse.RETURN_TO_HOME:
                return {"error": "NOT_IMPLEMENTED", "detail": "Phase 4b"}
            case ObstacleResponse.AVOID_AND_CONTINUE:
                return {"error": "NOT_IMPLEMENTED", "detail": "Phase 4b"}
            case ObstacleResponse.MANUAL_OVERRIDE:
                return {"status": "ok", "detail": "Manual control resumed"}
```

### ResponseProvider Protocol

```python
class ResponseProvider(Protocol):
    """How obstacle options are presented to the caller."""
    async def present_options(self, reading: ObstacleReading) -> ObstacleResponse: ...
```

**Phase 4a implementations:** CLIResponseProvider (fly.py), MCPResponseProvider (MCP tools).
**Phase 6 extension:** VoiceResponseProvider (verbal options + voice command selection).

## Future Phase Synergies

### Phase 5 (tello-vision)

- `ObstacleReading.classification` + `confidence` fields (what IS the obstacle?)
- `ObstacleMonitor.enrich()` method (vision enriches ToF data in real-time)
- Zone override logic: doorway vs. wall at same distance produce different zones
- Combined perception: ToF distance + CV bounding box = richer obstacle model

### Phase 6 (tello-voice)

- `VoiceResponseProvider` for verbal options menu ("Obstacle at 45cm. What should I do?")
- Obstacle announcement as speech
- Voice-commanded response selection

### Phase 4b (deferred — separate brainstorm)

- `return_to_home`: Navigator route planning back to launch pad
- `avoid_and_continue`: Lateral dodge + resume original waypoint
- Requires navigator changes; will have physical test data to inform design

## Testing Strategy

### Unit Tests (Phase 4)

| Test Area | What's Tested | Approach |
|-----------|--------------|----------|
| `classify_zone()` | All zone boundaries, edge cases | Pure function — no mocks |
| `get_forward_distance()` | Response parsing, errors | Mock `send_expansion_command` |
| `_poll_loop()` | Polling, caching, DANGER stop | Mock drone + asyncio |
| `get_forward_distance` tool | Returns cached reading | Mock monitor |
| `get_obstacle_status` tool | Zone + is_safe logic | Mock monitor |
| TelemetryFrame | `forward_tof_mm` serialization | No mocks |

### Unit Tests (Phase 4a)

| Test Area | What's Tested | Approach |
|-----------|--------------|----------|
| `_execute()` | Each response dispatches correctly | Mock drone |
| `CLIResponseProvider` | Option presentation + parsing | Mock stdin/stdout |
| `MCPResponseProvider` | Options dict + choice acceptance | Direct call |

### Physical Tests (fly.py)

1. `tof` returns valid mm reading while grounded
2. `tof` tracks distance as hand moves toward sensor
3. `monitor` shows status and live readings
4. Takeoff → fly toward wall → DANGER stop triggers
5. DANGER stop → options menu → emergency_land works

### Sensor Characterization (during physical testing)

- Actual detection range vs. spec
- Reading noise/stability
- Command-to-response latency
- Detection surface sensitivity (flat wall vs. narrow object vs. soft material)
- Results inform whether default thresholds (1500/800/400mm) need adjustment

## Files Changed

| File | Change | Phase |
|------|--------|-------|
| `packages/tello-core/src/tello_core/models.py` | Add `forward_tof_mm`, ObstacleZone, ObstacleReading | 4 |
| `packages/tello-core/src/tello_core/__init__.py` | Re-export new models | 4 |
| `services/tello-mcp/src/tello_mcp/drone.py` | Add `get_forward_distance()`, update `get_telemetry()` | 4 |
| `services/tello-mcp/src/tello_mcp/obstacle.py` | **New**: ObstacleMonitor, ObstacleConfig | 4 |
| `services/tello-mcp/src/tello_mcp/tools/sensors.py` | Add tools, update docstrings | 4 |
| `services/tello-mcp/src/tello_mcp/server.py` | Create ObstacleMonitor in lifespan | 4 |
| `scripts/fly.py` | Add `tof`, `monitor` commands | 4 |
| `services/tello-mcp/src/tello_mcp/obstacle.py` | Add ObstacleResponseHandler, providers | 4a |
| `scripts/fly.py` | Options menu on DANGER | 4a |
| Tests across tello-core and tello-mcp | New test files + updated existing | 4, 4a |

## Implementation Notes (from spec review)

These advisory items should be addressed during implementation planning:

1. **ObstacleConfig env var loading:** Use a `from_env()` classmethod following the existing `BaseServiceConfig.from_env()` pattern in the codebase. Not pydantic-settings.
2. **`drone.stop()` in async context:** DroneAdapter methods are synchronous (djitellopy is sync). The poll loop should use `await asyncio.to_thread(self._drone.stop)` for the safety stop to avoid blocking the event loop. Same applies to `get_forward_distance()` calls in the poll loop.
3. **Callback typing:** Use `Callable[[ObstacleReading], Awaitable[None] | None]` to support both sync and async callbacks. The poll loop should check if a callback is a coroutine and `await` it if so.
4. **sensors.py already exists:** The file `services/tello-mcp/src/tello_mcp/tools/sensors.py` already exists with `get_telemetry`, `get_tof_distance`, and `detect_mission_pad`. New tools are added to this existing file.
5. **`start()` idempotency:** `ObstacleMonitor.start()` should be idempotent — if already running, return without creating a second task.

## Explicit Exclusions

- No navigator changes (Phase 4b)
- No vision classification (Phase 5)
- No voice interaction (Phase 6)
- No automatic speed reduction in WARNING zone
- No Redis Stream for obstacle data
- No multi-sensor fusion
