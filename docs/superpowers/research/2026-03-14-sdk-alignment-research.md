# SDK Alignment Update Plan

**Date:** 2026-03-14
**Author:** Arthur Fantaci + Claude (sdk-alignment-team)
**Status:** Draft — feeds into brainstorming for combined SDK fix + Phase 4 cycle
**Sources:** Tello SDK 3.0 User Guide, Mission Pad & Flight Map User Guide, RoboMaster TT User Manual, djitellopy source analysis, full codebase trace, documentation audit

---

## Executive Summary

A team of 3 research agents (SDK analyst, codebase analyst, docs analyst) independently analyzed the entire tello-ai-platform codebase against the Tello TT SDK 3.0 documentation and djitellopy library source. They found **2 critical runtime bugs**, **10 high-priority gaps**, and **12 documentation inaccuracies** across 22 files.

The most significant findings:
1. `set_led()` and `display_text()` in DroneAdapter call djitellopy methods that **do not exist** — they will `AttributeError` at runtime
2. Mission pad detection (`detect_mission_pad`) is non-functional — the `mon` enable command is never sent
3. The navigator's `goto_pad` advisory command maps to a read-only detection tool, not pad-relative navigation
4. No keepalive mechanism — the drone auto-lands after 15 seconds of no commands

---

## Priority Tiers

### Tier 1: CRITICAL — Runtime Bugs (blocks physical testing)

#### 1.1 DroneAdapter.set_led() calls nonexistent method
**Current code** (`drone.py:170`):
```python
self._tello.set_led(r=r, g=g, b=b)
```
**Problem:** djitellopy has no `set_led()` method. LED control goes through `send_expansion_command()`.
**Fix:**
```python
self._tello.send_expansion_command(f"led {r} {g} {b}")
```
**Files:** `drone.py`, `test_drone.py` (update mock assertions)
**Phase 1 live test note:** LED worked — this means the Phase 1 code used a different call path that was lost in the Phase 3 migration. Verify by checking git history.

#### 1.2 DroneAdapter.display_text() calls nonexistent method
**Current code** (`drone.py:185`):
```python
self._tello.set_display(text)
```
**Problem:** djitellopy has no `set_display()` method. The correct EXT mled command requires a direction and color parameter.
**Fix:**
```python
self._tello.send_expansion_command(f"mled l r 0.5 {text}")
# mled l = scroll left, r = red color, 0.5 = frame rate Hz
```
**Files:** `drone.py`, `test_drone.py`, `expansion.py` (add `color` and `direction` params)
**Root cause of Phase 1 "matrix error":** Missing color parameter in the `mled s` command.

#### 1.3 Correct EXT mled Command Formats (reference)
| Command | Format | Example |
|---------|--------|---------|
| Solid LED | `EXT led r g b` | `EXT led 255 0 0` (red) |
| LED pulse | `EXT led br t r g b` | `EXT led br 0.5 0 255 0` (green pulse) |
| LED blink | `EXT led bl t r1 g1 b1 r2 g2 b2` | alternating colors |
| Matrix grid | `EXT mled g xxxx` | xxxx = 64 chars of r/b/p/0 |
| Matrix scroll text | `EXT mled l/r/u/d r/b/p t xxxx` | `EXT mled l r 0.5 hello` |
| Matrix static char | `EXT mled s r/b/p xxxx` | `EXT mled s b heart` |
| Matrix brightness | `EXT mled sl n` | n = 0-255 |
| EXT ToF | `EXT tof?` | returns mm (not cm!) |

---

### Tier 2: HIGH — Core Functionality Gaps (blocks navigator mission pads)

#### 2.1 Mission pad detection never enabled
**Problem:** `detect_mission_pad()` calls `get_mission_pad_id()` but the SDK requires `mon` command first. Without it, `mid` state field returns -2 (disabled).
**Fix:** Add to DroneAdapter:
```python
def enable_mission_pads(self) -> dict:
    self._tello.enable_mission_pads()
    return {"status": "ok"}

def disable_mission_pads(self) -> dict:
    self._tello.disable_mission_pads()
    return {"status": "ok"}

def set_pad_detection_direction(self, direction: int = 2) -> dict:
    self._tello.set_mission_pad_detection_direction(direction)
    return {"status": "ok"}
```
**Decision needed:** Auto-enable in `connect()` or expose as explicit MCP tools? Recommend: auto-enable with `mdirection 0` (downward only, 20Hz) in `connect()`, plus MCP tool for changing direction.
**Files:** `drone.py`, `sensors.py` or new `pads.py`, `test_drone.py`

#### 2.2 No keepalive — 15-second auto-land
**Problem:** If no SDK command is sent for 15 seconds, the drone auto-lands. During mission testing, gaps between waypoint advancements easily exceed 15s.
**Fix:** Add background keepalive task to tello-mcp lifespan:
```python
async def _keepalive_loop(drone: DroneAdapter):
    while True:
        await asyncio.sleep(10)
        if drone.is_connected:
            await asyncio.to_thread(drone.keepalive)
```
**DroneAdapter addition:**
```python
def keepalive(self) -> None:
    if self._connected:
        self._tello.send_keepalive()
```
**Files:** `drone.py`, `server.py` (add background task in lifespan)

#### 2.3 Mission pad state getters missing (x, y, z relative to pad)
**Problem:** `detect_mission_pad()` only returns `pad_id`. The SDK also provides x/y/z coordinates (cm) of the drone relative to the detected pad — essential for pad-relative navigation.
**Fix:** Expand `detect_mission_pad()` return value:
```python
def detect_mission_pad(self) -> dict:
    pad_id = self._tello.get_mission_pad_id()
    if pad_id == -2:
        return {"pad_id": -2, "detected": False, "enabled": False}
    if pad_id == -1:
        return {"pad_id": -1, "detected": False, "enabled": True}
    return {
        "pad_id": pad_id,
        "detected": True,
        "enabled": True,
        "x_cm": self._tello.get_mission_pad_distance_x(),
        "y_cm": self._tello.get_mission_pad_distance_y(),
        "z_cm": self._tello.get_mission_pad_distance_z(),
    }
```
**Files:** `drone.py`, `test_drone.py`

#### 2.4 Pad-relative navigation not implemented
**Problem:** `go_xyz_speed_mid` is the core pad navigation command — fly to (x,y,z) relative to a detected pad at set speed. Not in DroneAdapter or MCP tools.
**Fix:** Add to DroneAdapter:
```python
def go_xyz_speed_mid(self, x: int, y: int, z: int, speed: int, mid: int) -> dict:
    """Fly to coordinates relative to mission pad.

    Args:
        x, y: -500 to 500 cm
        z: 0 to 500 cm (must be positive for pad-relative)
        speed: 10-100 cm/s
        mid: mission pad ID (1-8, -1=random, -2=nearest)
    """
    if err := self._require_connection():
        return err
    try:
        self._tello.go_xyz_speed_mid(x, y, z, speed, mid)
        return {"status": "ok"}
    except Exception as e:
        return {"error": "COMMAND_FAILED", "detail": str(e)}
```
Add MCP tool in `flight.py` or new `pads.py` module.
**Files:** `drone.py`, `flight.py` or new `pads.py`, `test_drone.py`, tests

#### 2.5 Navigator goto_pad advisory command is wrong
**Problem:** `_suggested_command()` maps `goto_pad` to `{"tool": "detect_mission_pad", "args": {}}`. This is a read command, not navigation. Should map to `go_xyz_speed_mid`.
**Fix:** Update mapping:
```python
if action == "goto_pad":
    return {
        "tool": "go_xyz_speed_mid",
        "args": {
            "x": 0, "y": 0,
            "z": waypoint.get("z_cm", 50),
            "speed": waypoint.get("speed_cm_s", 30),
            "mid": waypoint.get("pad_id"),
        },
    }
```
**Cascade:** Planner's `_generate_waypoints()` must store z_cm and speed_cm_s in waypoint dicts. Waypoint model may need `speed_cm_s` field.
**Files:** `missions.py` (_suggested_command), `planner.py` (_generate_waypoints), `models.py` (Waypoint), `repository.py` (save_waypoints), tests

---

### Tier 3: MEDIUM — Model & Telemetry Expansion

#### 3.1 TelemetryFrame missing mission pad fields
Add optional fields to TelemetryFrame for pad-relative state:
```python
mid: int | None = None          # detected pad ID
pad_x_cm: int | None = None     # x offset from pad
pad_y_cm: int | None = None     # y offset from pad
pad_z_cm: int | None = None     # z offset from pad
```
**Files:** `models.py`, `drone.py` (get_telemetry), `test_models.py`

#### 3.2 TelemetryFrame missing velocity/acceleration
Add velocity and acceleration fields (useful for anomaly detection):
```python
vgx_dm_s: int | None = None    # x velocity (dm/s)
vgy_dm_s: int | None = None    # y velocity (dm/s)
vgz_dm_s: int | None = None    # z velocity (dm/s)
agx_cm_s2: float | None = None # x acceleration (cm/s^2)
agy_cm_s2: float | None = None
agz_cm_s2: float | None = None
baro_cm: float | None = None   # barometer altitude (cm)
```
**Files:** `models.py`, `drone.py`, `test_models.py`

#### 3.3 Waypoint model needs speed field
Add `speed_cm_s` for pad-relative navigation waypoints:
```python
speed_cm_s: int | None = Field(default=None, ge=10, le=100)
```
**Files:** `models.py`, `planner.py`, `repository.py`, tests

#### 3.4 Mission pad recognition constraints
Document in code and memory:
- Height range: 30-120cm for small pads
- Detection area: 40x40cm at 30cm, 100x100cm at 120cm
- Surface: matte, textured, non-reflective
- Lighting: moderate (300-100,000 lux)
- Downward camera required for `go_xyz_speed_mid`

---

### Tier 4: HIGH (Phase 4) — Video Stream

#### 4.1 Video stream support
**djitellopy methods:** `streamon()`, `streamoff()`, `get_frame_read()`, `set_video_direction(0|1)`, `set_video_resolution()`, `set_video_fps()`
**SDK note:** "Tello EDUs do not support video streaming while connected to a WiFi-network" — **verify this works in router mode** before Phase 4 design.
**Files:** `drone.py` (new methods), new `tools/video.py`, `server.py` (register)

#### 4.2 General 3D movement (go_xyz_speed)
`go_xyz_speed(x,y,z,speed)` — fly to relative 3D position without pad. Useful for survey patterns.
**Files:** `drone.py`, `flight.py`

#### 4.3 RC control (continuous movement)
`send_rc_control(lr, fb, ud, yaw)` — joystick-style continuous control. Phase 5 (voice) dependency.
**Files:** `drone.py`, new tool

---

### Tier 5: Documentation Fixes

| # | File | Fix | Priority |
|---|------|-----|----------|
| 1 | `pattern_advisory_commands.md` | Update goto_pad mapping to go_xyz_speed_mid, document detection prerequisite | HIGH |
| 2 | `project_live_test_results.md` | Document matrix error root cause (missing color param) | HIGH |
| 3 | `project_room_graph_data.md` | Add mission pad recognition height constraint (30-120cm) | HIGH |
| 4 | `CLAUDE.md` | Remove "(placeholder)" from navigator. Add 15s timeout to error handling. | MEDIUM |
| 5 | `architecture.md` | Fix navigator description (no telemetry subscription). Remove "rate limiting" overclaim. | MEDIUM |
| 6 | `project_overview.md` | Note missing tools (enable_mission_pad, go_xyz_speed_mid, etc.) | MEDIUM |
| 7 | Navigator spec `§6.4` | Add callout: goto_pad is detection-only in v1, full nav is v2 with go_xyz_speed_mid | MEDIUM |
| 8 | Navigator spec `§6.3` | Note pad detection height constraint (30-120cm) in waypoint generation | MEDIUM |

---

## Implementation Sequence

**Phase 3a: SDK Hotfix (before physical testing)**
1. Fix `set_led()` → `send_expansion_command("led ...")` (CRITICAL)
2. Fix `display_text()` → `send_expansion_command("mled ...")` (CRITICAL)
3. Add `enable_mission_pads()` to DroneAdapter (CRITICAL)
4. Add keepalive background task (HIGH)
5. Expand `detect_mission_pad()` return with x/y/z (HIGH)
6. Update tests for all above
7. Update memory/docs (Tier 5 fixes)

**Phase 3b: Navigator Pad Navigation (after physical testing validates basics)**
1. Add `go_xyz_speed_mid()` to DroneAdapter + MCP tool (HIGH)
2. Update `_suggested_command()` goto_pad mapping (HIGH)
3. Update planner waypoint generation with speed/z fields (HIGH)
4. Add `speed_cm_s` to Waypoint model (MEDIUM)
5. Update tests for all above

**Phase 4: Vision Pipeline (per established workflow)**
1. Brainstorm → Spec → Issue → Worktree → Plan → Implement
2. Video stream support (drone + MCP tools)
3. TelemetryFrame expansion (velocity, acceleration, pad fields)
4. tello-vision service implementation

---

## Decision Points for Brainstorming

These design decisions should be resolved during the brainstorming phase:

1. **Should `enable_mission_pads()` be auto-called in `connect()` or exposed as an explicit tool?**
   - Auto-enable is simpler but adds latency to connect
   - Explicit tool gives Claude/voice control over when to enable

2. **Should `goto_pad` advisory command use `go 0 0 z speed mid` (fly directly over pad) or `go x y z speed mid` (fly to specific offset)?**
   - Direct-over-pad is simpler for v1
   - Offset navigation enables survey patterns in v2

3. **New MCP tool module for pad operations?**
   - Add to existing `sensors.py` and `flight.py`?
   - Create new `pads.py` module? (cleaner separation, but more files)

4. **Video stream in router mode — does it work?**
   - SDK doc warns about WiFi-network streaming limitations
   - Must verify before Phase 4 design commits to this approach

5. **Should Phase 3a (hotfix) follow the full Brainstorm → Spec workflow, or is it a targeted bugfix?**
   - The fixes are bug corrections and missing prerequisites, not new features
   - Recommend: targeted bugfix PR with Issue, but skip brainstorm/spec
   - Document decision either way

---

## Files Impact Summary

| File | Changes | Tier |
|------|---------|------|
| `services/tello-mcp/src/tello_mcp/drone.py` | Fix set_led, display_text, add enable/disable mission pads, keepalive, go_xyz_speed_mid, expanded detect_mission_pad | 1, 2 |
| `services/tello-mcp/src/tello_mcp/server.py` | Add keepalive background task | 2 |
| `services/tello-mcp/src/tello_mcp/tools/sensors.py` | Add enable_mission_pads tool (or new pads.py) | 2 |
| `services/tello-mcp/src/tello_mcp/tools/flight.py` | Add go_xyz_speed_mid tool | 2 |
| `services/tello-mcp/src/tello_mcp/tools/expansion.py` | Add color/direction params to display_matrix_text | 1 |
| `services/tello-mcp/tests/test_drone.py` | Fix assertions for set_led, display_text, add new method tests | 1, 2 |
| `services/tello-navigator/src/tello_navigator/tools/missions.py` | Fix _suggested_command goto_pad mapping | 2 |
| `services/tello-navigator/src/tello_navigator/planner.py` | Add speed/z to waypoint generation | 2 |
| `packages/tello-core/src/tello_core/models.py` | Waypoint speed_cm_s, TelemetryFrame pad/velocity fields | 3 |
| `services/tello-navigator/src/tello_navigator/repository.py` | Persist new waypoint fields | 3 |
| Memory files (6 files) | Documentation corrections per Tier 5 table | 5 |
| `CLAUDE.md` | Remove placeholder tag, add timeout constraint | 5 |
| `docs/architecture.md` | Fix navigator description, remove overclaims | 5 |
