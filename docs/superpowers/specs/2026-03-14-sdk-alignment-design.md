# SDK Alignment Design Specification (Phase 3a + 3b)

**Date:** 2026-03-14
**Author:** Arthur Fantaci + Claude
**Status:** Draft
**Scope:** Fix tello-mcp SDK regressions, add mission pad enablement and
pad-relative navigation, complete tello-navigator goto_pad waypoint action
**Delivery:** Two PRs — Phase 3a (tello-mcp), Phase 3b (tello-navigator)

---

## 1. Overview

Phase 3's FastMCP migration introduced two runtime bugs (expansion board
methods call nonexistent djitellopy methods) and exposed several gaps where
existing features depend on SDK prerequisites that were never implemented
(mission pad enablement, keepalive). Additionally, the navigator's
`goto_pad` waypoint action maps to a read-only detection tool rather than
pad-relative navigation.

This spec covers a two-phase fix:

- **Phase 3a** delivers a fully working tello-mcp hardware layer: expansion
  board tools, mission pad detection, keepalive, and the `go_to_mission_pad`
  MCP tool.
- **Phase 3b** updates tello-navigator to use `go_to_mission_pad` in its
  advisory command mapping, completing the `goto_pad` waypoint action.

**Not in scope:** video streaming (Phase 4), TelemetryFrame expansion with
velocity/acceleration fields (Phase 4), RC continuous control (Phase 5),
curve flight, jump/multi-pad handoff (future).

---

## 2. Design Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Mission pad enablement | Auto-enable downward detection (20Hz) in `DroneAdapter.connect()`. Expose `set_pad_detection_direction` tool for changing direction. | Pads should "just work" after connect. Direction change is a rare operation — explicit tool is appropriate. |
| 2 | Display tool API | Split into 3 focused tools: `display_scroll_text`, `display_static_char`, `display_pattern` | The SDK has 3 distinct `EXT mled` command formats with different parameter shapes. One combined tool creates a confusing API where some params apply to some modes and not others. |
| 3 | New pad tool location | `set_pad_detection_direction` in `expansion.py` (hardware config write). `go_to_mission_pad` in `flight.py` (flight command). | sensors.py is read-only by convention. Pad direction setting is a write operation, grouped with other hardware config tools in expansion.py. |
| 4 | Keepalive mechanism | Background asyncio task in tello-mcp lifespan, sends keepalive every 10 seconds while connected | The SDK auto-lands after 15 seconds of silence. A background task is the only reliable approach — depending on callers to send keepalive is fragile. |
| 5 | goto_pad advisory command | Map to `go_to_mission_pad` with `x=0, y=0, z=50, speed=30, mid=pad_id` (fly to 50cm directly over pad center at 30 cm/s) | `detect_mission_pad` is read-only. `go_to_mission_pad` wraps the SDK's `go x y z speed mid` command, which flies to coordinates relative to a detected pad. |
| 6 | Delivery | One spec, one plan. Two Issues, two branches, two PRs. 3a merged and physically tested before 3b starts. | Physical testing validates the hardware layer before the navigator builds on it. |

---

## 3. Phase 3a — tello-mcp SDK Alignment

### 3.1 DroneAdapter Fixes (drone.py)

#### 3.1.1 Fix set_led() — CRITICAL

**Current (broken):**
```python
self._tello.set_led(r=r, g=g, b=b)  # AttributeError: no such method
```

**Fixed:**
```python
self._tello.send_expansion_command(f"led {r} {g} {b}")
```

Method signature unchanged: `set_led(self, r: int, g: int, b: int) -> dict`.
Same `_require_connection()` guard and try/except error handling.

#### 3.1.2 Replace display_text() with three methods — CRITICAL

Remove `display_text()`. Add three methods matching the SDK's three
distinct `EXT mled` command formats:

```python
def display_scroll_text(self, text: str, direction: str = "l",
                        color: str = "r", rate: float = 0.5) -> dict:
    """Scroll text on the 8x8 LED matrix.

    Args:
        text: Text to display (max 70 characters).
        direction: Scroll direction — l (left), r (right), u (up), d (down).
        color: Display color — r (red), b (blue), p (purple).
        rate: Frame rate in Hz (0.1-2.5).
    """
    # SDK: EXT mled l/r/u/d r/b/p t xxxx
    self._tello.send_expansion_command(
        f"mled {direction} {color} {rate} {text}"
    )

def display_static_char(self, char: str, color: str = "r") -> dict:
    """Display a static character on the 8x8 LED matrix.

    Args:
        char: Single ASCII character or "heart".
        color: Display color — r (red), b (blue), p (purple).
    """
    # SDK: EXT mled s r/b/p xxxx
    self._tello.send_expansion_command(f"mled s {color} {char}")

def display_pattern(self, pattern: str) -> dict:
    """Display a dot-matrix pattern on the 8x8 LED matrix.

    Args:
        pattern: Up to 64 characters using r (red), b (blue),
                 p (purple), 0 (off). Unspecified positions are off.
    """
    # SDK: EXT mled g xxxx
    self._tello.send_expansion_command(f"mled g {pattern}")
```

All three follow the standard error-handling pattern: `_require_connection()`
guard, try/except wrapping `send_expansion_command()`, structured return dict.

#### 3.1.3 Auto-enable mission pads in connect()

Mission pad enablement is best-effort — if it fails, the connection
still succeeds. Pads are a nice-to-have, not a connection prerequisite.

```python
def connect(self) -> dict:
    try:
        self._tello.connect()
        self._connected = True
        logger.info(
            "Drone connected, battery=%d%%",
            self._tello.get_battery(),
        )
    except Exception as e:
        logger.exception("Failed to connect to drone")
        return {"error": "CONNECTION_FAILED", "detail": str(e)}

    # Best-effort pad enablement — warn on failure, don't kill connection
    try:
        self._tello.enable_mission_pads()
        self._tello.set_mission_pad_detection_direction(0)  # downward, 20Hz
    except Exception:
        logger.warning("Mission pad enablement failed — pad detection unavailable")

    return {"status": "ok"}
```

**Design note:** `self._connected = True` is set before pad enablement.
If pad enable fails, `is_connected` is `True` (correct — the drone IS
connected) and the connection returns success. Pad detection tools will
return `pad_id: -2` (disabled) which is a clear signal to the caller.

#### 3.1.4 Add keepalive()

```python
def keepalive(self) -> None:
    """Send keepalive to prevent 15-second auto-land timeout."""
    if self._connected:
        self._tello.send_keepalive()
```

No return value, no error handling — this is a fire-and-forget background
call. If it fails, the worst case is the drone auto-lands (safe failure).

#### 3.1.5 Expand detect_mission_pad() return value

```python
def detect_mission_pad(self) -> dict:
    """Scan for nearest mission pad.

    Returns:
        Dict with pad_id and detection status. When detected,
        includes x/y/z coordinates (cm) relative to the pad.
        pad_id values: -2 (detection disabled), -1 (enabled but
        no pad detected), 1-8 (detected pad ID).
    """
    if err := self._require_connection():
        return err
    pad_id = self._tello.get_mission_pad_id()
    if pad_id < 1:
        return {"pad_id": pad_id, "detected": False}
    return {
        "pad_id": pad_id,
        "detected": True,
        "x_cm": self._tello.get_mission_pad_distance_x(),
        "y_cm": self._tello.get_mission_pad_distance_y(),
        "z_cm": self._tello.get_mission_pad_distance_z(),
    }
```

#### 3.1.6 Add go_xyz_speed_mid()

```python
def go_xyz_speed_mid(self, x: int, y: int, z: int,
                     speed: int, mid: int) -> dict:
    """Fly to coordinates relative to a mission pad.

    Args:
        x: -500 to 500 cm (pad-relative X axis).
        y: -500 to 500 cm (pad-relative Y axis).
        z: 0 to 500 cm (altitude above pad, must be positive).
        speed: 10-100 cm/s.
        mid: Mission pad ID (1-8).
    """
    if err := self._require_connection():
        return err
    try:
        self._tello.go_xyz_speed_mid(x, y, z, speed, mid)
        return {"status": "ok"}
    except Exception as e:
        logger.exception("go_xyz_speed_mid failed")
        return {"error": "COMMAND_FAILED", "detail": str(e)}
```

#### 3.1.7 Add set_pad_detection_direction()

```python
def set_pad_detection_direction(self, direction: int = 0) -> dict:
    """Set mission pad detection direction.

    Args:
        direction: 0 = downward only (20Hz),
                   1 = forward only (20Hz),
                   2 = both (10Hz each, alternating).
    """
    if err := self._require_connection():
        return err
    try:
        self._tello.set_mission_pad_detection_direction(direction)
        return {"status": "ok"}
    except Exception as e:
        logger.exception("set_pad_detection_direction failed")
        return {"error": "COMMAND_FAILED", "detail": str(e)}
```

### 3.2 Keepalive Background Task (server.py)

Add a background asyncio task in the tello-mcp lifespan. Follows the same
pattern as tello-telemetry's StreamConsumer background task.

```python
async def _keepalive_loop(drone: DroneAdapter) -> None:
    """Send keepalive every 10s to prevent 15s auto-land timeout."""
    while True:
        await asyncio.sleep(10)
        if drone.is_connected:
            await asyncio.to_thread(drone.keepalive)
```

In the lifespan:

```python
@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    # ... existing setup ...
    keepalive_task = asyncio.create_task(_keepalive_loop(drone))
    try:
        yield { ... }
    finally:
        keepalive_task.cancel()
        with suppress(asyncio.CancelledError):
            await keepalive_task
        drone.disconnect()
        await redis.aclose()
```

### 3.3 MCP Tool Changes

#### 3.3.1 expansion.py — Replace display tool, keep LED tool

`set_led_color` keeps the same signature — the fix is in DroneAdapter.

Replace `display_matrix_text` with three new tools:

```python
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
async def display_scroll_text(
    ctx: Context,
    text: str,
    direction: str = "l",
    color: str = "r",
    rate: float = 0.5,
) -> dict:
    """Scroll text on the 8x8 LED matrix.

    Args:
        text: Text to display (max 70 characters).
        direction: Scroll direction (l=left, r=right, u=up, d=down).
        color: Display color (r=red, b=blue, p=purple).
        rate: Frame rate in Hz (0.1-2.5).
    """
    drone = ctx.lifespan_context["drone"]
    queue = ctx.lifespan_context["queue"]
    return await queue.enqueue(
        lambda: drone.display_scroll_text(text, direction, color, rate)
    )

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
async def display_static_char(
    ctx: Context, char: str, color: str = "r",
) -> dict:
    """Display a static character on the 8x8 LED matrix.

    Args:
        char: Single ASCII character or "heart".
        color: Display color (r=red, b=blue, p=purple).
    """
    drone = ctx.lifespan_context["drone"]
    queue = ctx.lifespan_context["queue"]
    return await queue.enqueue(
        lambda: drone.display_static_char(char, color)
    )

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
async def display_pattern(ctx: Context, pattern: str) -> dict:
    """Display a dot-matrix pattern on the 8x8 LED matrix.

    Args:
        pattern: Up to 64 chars using r (red), b (blue), p (purple), 0 (off).
    """
    drone = ctx.lifespan_context["drone"]
    queue = ctx.lifespan_context["queue"]
    return await queue.enqueue(lambda: drone.display_pattern(pattern))
```

#### 3.3.2 expansion.py — Add pad detection direction tool

`sensors.py` is a read-only module (docstring: "Sensor and state MCP
tools (read-only)"). Since `set_pad_detection_direction` is a write
operation (changes drone config), it belongs in `expansion.py` alongside
other hardware configuration tools like `set_led_color`.

```python
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
async def set_pad_detection_direction(
    ctx: Context, direction: int = 0,
) -> dict:
    """Set mission pad detection direction.

    Args:
        direction: 0=downward (20Hz), 1=forward (20Hz), 2=both (10Hz each).
    """
    drone = ctx.lifespan_context["drone"]
    queue = ctx.lifespan_context["queue"]
    return await queue.enqueue(
        lambda: drone.set_pad_detection_direction(direction)
    )
```

Uses the command queue for consistency with other expansion.py tools.

#### 3.3.3 flight.py — Add pad-relative navigation tool

```python
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
async def go_to_mission_pad(
    ctx: Context,
    x: int,
    y: int,
    z: int,
    speed: int,
    mid: int,
) -> dict:
    """Fly to coordinates relative to a detected mission pad.

    Args:
        x: X position relative to pad (-500 to 500 cm).
        y: Y position relative to pad (-500 to 500 cm).
        z: Altitude above pad (0 to 500 cm, must be positive).
        speed: Flight speed (10-100 cm/s).
        mid: Target mission pad ID (1-8).
    """
    drone = ctx.lifespan_context["drone"]
    queue = ctx.lifespan_context["queue"]
    return await queue.enqueue(
        lambda: drone.go_xyz_speed_mid(x, y, z, speed, mid)
    )
```

### 3.4 Documentation Fixes (bundled in 3a PR)

| File | Change |
|------|--------|
| `CLAUDE.md` | Remove "(placeholder)" from tello-navigator description. Add to Error Handling section: "15-second SDK timeout: drone auto-lands if no command received for 15s. tello-mcp runs a background keepalive task to prevent this." |
| `docs/architecture.md` | Fix tello-navigator description: "Receives mission goals, decomposes into waypoint sequences. Persists in Neo4j, checkpoints via Redis. Returns advisory commands — caller executes against tello-mcp." Remove "rate limiting" from Redis capabilities (not implemented). |
| `pattern_advisory_commands.md` | Update goto_pad row: note that in Phase 3a it maps to `detect_mission_pad` (detection only), Phase 3b updates to `go_to_mission_pad` (pad-relative navigation). |
| `project_live_test_results.md` | Document matrix error root cause: missing color parameter in `EXT mled s` command. Mark as resolved. |
| `project_room_graph_data.md` | Add SDK constraints section: pad detection height 30-120cm, detection area varies with height, surface must be matte/textured/non-reflective, moderate lighting required. |
| `project_overview.md` | Update tello-mcp tool list to reflect new tools (display_scroll_text, display_static_char, display_pattern, set_pad_detection_direction, go_to_mission_pad). |

### 3.5 SDK Behavioral Constraints (reference for implementers)

These are not code changes but must be understood during implementation
and testing:

1. **15-second command timeout** — drone auto-lands if no SDK command
   received. Mitigated by keepalive background task (Section 3.2).
2. **Mission pad detection height** — 30-120cm for small pads. Drone must
   be within this range for `detect_mission_pad` and `go_to_mission_pad`
   to work.
3. **Detection area** — 40x40cm at 30cm height, 100x100cm at 120cm height.
4. **Surface requirements** — pads must be on matte, textured,
   non-reflective surfaces. Avoid pure black/white backgrounds.
5. **Detection frequency** — downward only: 20Hz. Both directions: 10Hz
   each (alternating).
6. **Downward camera required for go_xyz_speed_mid** — forward-only
   detection (`mdirection 1`) disables pad-relative navigation commands.
   This is why we default to `mdirection 0` (downward).
7. **EXT mled color parameter** — `r` (red), `b` (blue), `p` (purple),
   `0` (off). Pattern strings use these same characters. Max 64 characters
   for grid patterns, max 70 for scroll text.

---

## 4. Phase 3b — tello-navigator Pad Navigation Alignment

### 4.1 Waypoint Model Expansion (models.py)

Add `speed_cm_s` field to the `Waypoint` model:

```python
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
```

Re-export from `tello_core.__init__` — already exported, no change needed.

### 4.2 Planner Waypoint Generation (planner.py)

Update `_generate_waypoints()` to include `speed_cm_s` on `goto_pad`
waypoints:

```python
# In the room_pads loop:
waypoints.append({
    "id": f"{state['mission_id']}_wp_{seq}",
    "sequence": seq,
    "room_id": room_id,
    "pad_id": pad["id"],
    "action": "goto_pad",
    "speed_cm_s": 30,  # conservative default for indoor pad navigation
})
```

The speed of 30 cm/s is conservative for indoor use. The SDK allows
10-100 cm/s; faster speeds risk overshooting in confined rooms.

### 4.3 Advisory Command Mapping (missions.py)

Update `_suggested_command()` for the `goto_pad` action:

```python
# Current (Phase 3):
if action == "goto_pad":
    return {"tool": "detect_mission_pad", "args": {}}

# Phase 3b:
if action == "goto_pad":
    return {
        "tool": "go_to_mission_pad",
        "args": {
            "x": 0,
            "y": 0,
            "z": 50,
            "speed": waypoint.get("speed_cm_s", 30),
            "mid": waypoint.get("pad_id"),
        },
    }
```

This advisory command tells the caller: "fly to the origin (0, 0) of
pad N's coordinate system at 50cm altitude, at 30 cm/s." This positions
the drone directly over the center of the detected pad.

The `z=50` value is within the mission pad detection range (30-120cm)
and matches the standard takeoff hover height, ensuring the pad remains
detectable during and after the maneuver.

**Invariant:** `pad_id` is always non-None for `goto_pad` waypoints. The
planner's `_generate_waypoints()` only creates `goto_pad` waypoints from
the `room_pads` list, which always has `pad["id"]` set. If a future code
path creates `goto_pad` without a `pad_id`, `go_to_mission_pad` will
receive `mid=None` and fail at the SDK level.

### 4.4 Repository Persistence (repository.py)

Update `save_waypoints()` Cypher CREATE to include the new field:

```cypher
CREATE (w:Waypoint {
    id: $wp_id,
    sequence: $sequence,
    room_id: $room_id,
    pad_id: $pad_id,
    action: $action,
    direction: $direction,
    distance_cm: $distance_cm,
    degrees: $degrees,
    speed_cm_s: $speed_cm_s
})<-[:CONTAINS_WAYPOINT {sequence: $sequence}]-(m)
```

Add `speed_cm_s=wp.speed_cm_s` to the parameter dict.

### 4.5 Update Physical Test Plan

Rename `testing/2026-03-13-phase3-physical-test-plan.md` to
`testing/phase3-physical-test-plan_v2.md`.

Updates to incorporate:

- **Block 1 (smoke test):** Replace `display_matrix_text` with
  `display_scroll_text`, `display_static_char`, and `display_pattern`
  test steps.
- **Block 4 (single-room mission):** Update expected `goto_pad` advisory
  command from `detect_mission_pad` to `go_to_mission_pad` with x/y/z/speed/mid
  parameters.
- **New test step:** Verify keepalive — hover for 30+ seconds without
  sending commands. Drone should NOT auto-land.
- **New test step:** Verify `detect_mission_pad` returns x/y/z coordinates
  when hovering over a placed pad (requires physical pad).
- **New test step:** Verify `go_to_mission_pad` — fly to pad center from
  a nearby position.
- **Safety section:** Add mission pad detection height constraint (30-120cm)
  and surface requirements.

---

## 5. Testing Strategy

All tests use mocked djitellopy, Redis, and Neo4j — no real connections
in unit tests.

### Phase 3a Tests

| Module | Key test cases |
|--------|---------------|
| `test_drone.py` | Fix `set_led` assertion to use `send_expansion_command("led ...")`. Remove `display_text` tests, add `display_scroll_text`, `display_static_char`, `display_pattern` tests. Add `connect` test verifying `enable_mission_pads()` + `set_mission_pad_detection_direction(0)` called. Add `keepalive` test. Add `go_xyz_speed_mid` test. Add `set_pad_detection_direction` test. Add `detect_mission_pad` expanded return (with x/y/z). |
| `test_expansion.py` | Remove `display_matrix_text` registration/invocation tests. Add `display_scroll_text`, `display_static_char`, `display_pattern` registration + invocation tests. |
| `test_flight.py` | Add `go_to_mission_pad` registration + invocation test. |
| `test_expansion.py` | Also add `set_pad_detection_direction` registration + invocation test. |

### Phase 3b Tests

| Module | Key test cases |
|--------|---------------|
| `test_models.py` | Add `speed_cm_s` validation to `TestWaypoint` (range 10-100, optional). |
| `test_planner.py` | Update `TestGenerateWaypoints` to verify `goto_pad` waypoints include `speed_cm_s: 30`. |
| `test_missions.py` | Update `TestAdvanceMission` / `TestStartMission` to verify `goto_pad` suggested command is `go_to_mission_pad` with correct args. |
| `test_repository.py` | Update `TestSaveWaypoints` to verify `speed_cm_s` parameter passed to Cypher. |

**Target:** Phase 3a: ~45 tello-mcp tests (up from 37). Phase 3b: ~55
tello-navigator tests (up from 50).

---

## 6. File Impact Summary

### Phase 3a Files

| File | Change Type | Description |
|------|------------|-------------|
| `services/tello-mcp/src/tello_mcp/drone.py` | Modify | Fix set_led, replace display_text with 3 methods, add connect pad enable, keepalive, go_xyz_speed_mid, set_pad_detection_direction, expand detect_mission_pad |
| `services/tello-mcp/src/tello_mcp/server.py` | Modify | Add keepalive background task in lifespan |
| `services/tello-mcp/src/tello_mcp/tools/expansion.py` | Modify | Replace display_matrix_text with 3 display tools, add set_pad_detection_direction |
| `services/tello-mcp/src/tello_mcp/tools/flight.py` | Modify | Add go_to_mission_pad tool |
| `services/tello-mcp/tests/test_drone.py` | Modify | Fix/add tests for all DroneAdapter changes |
| `services/tello-mcp/tests/test_tools/test_expansion.py` | Modify | Replace display_matrix_text tests with 3 new tool tests |
| `services/tello-mcp/tests/test_tools/test_flight.py` | Modify | Add go_to_mission_pad test |
| `services/tello-mcp/tests/test_tools/test_sensors.py` | No change | Sensors remain read-only |
| `CLAUDE.md` | Modify | Remove navigator placeholder tag, add 15s timeout |
| `docs/architecture.md` | Modify | Fix navigator description, remove rate limiting |
| Memory files (5) | Modify | Per Section 3.4 table |

### Phase 3b Files

| File | Change Type | Description |
|------|------------|-------------|
| `packages/tello-core/src/tello_core/models.py` | Modify | Add speed_cm_s to Waypoint |
| `packages/tello-core/tests/test_models.py` | Modify | Add speed_cm_s validation tests |
| `services/tello-navigator/src/tello_navigator/planner.py` | Modify | Add speed_cm_s to goto_pad waypoints |
| `services/tello-navigator/src/tello_navigator/tools/missions.py` | Modify | Update _suggested_command goto_pad mapping |
| `services/tello-navigator/src/tello_navigator/repository.py` | Modify | Persist speed_cm_s field |
| `services/tello-navigator/tests/test_planner.py` | Modify | Verify speed_cm_s in generated waypoints |
| `services/tello-navigator/tests/test_tools/test_missions.py` | Modify | Verify goto_pad advisory command |
| `services/tello-navigator/tests/test_repository.py` | Modify | Verify speed_cm_s persistence |
| `testing/phase3-physical-test-plan_v2.md` | Create | Updated test plan incorporating 3a + 3b changes |

---

## 7. v2 Upgrade Paths (Post-Phase 5)

Capabilities deferred from this spec that build on the foundation laid here:

- **Curve flight via pads** — `curve_xyz_speed_mid()` for smooth arced
  pad-to-pad transitions. Requires DroneAdapter + MCP tool wrapper.
- **Jump between pads** — `go_xyz_speed_yaw_mid()` for multi-pad handoff
  with yaw control. Enables room-to-room transitions.
- **Dynamic goto_pad z-height** — currently hardcoded at 50cm. Could be
  derived from room height or pad detection distance for optimal detection.
- **Forward camera pad detection** — `mdirection 1` or `2` for detecting
  pads ahead of the drone during approach. Requires tello-vision integration.
- **Pad position calibration** — use `detect_mission_pad` x/y/z returns
  to update seed data pad positions from flight measurements.
