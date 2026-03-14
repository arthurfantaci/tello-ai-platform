# Phase 3 Physical Test Plan (v2)

> **Version:** 2 (incorporates Phase 3a SDK alignment + Phase 3b navigator pad navigation)
> **Hardware:** DJI Tello TT with expansion board, Router Mode (192.168.68.107)
> **Prerequisites:** Docker up (Neo4j + Redis), room graph seeded, mission pads placed

---

## Safety

- Fly in open area, clear of obstacles
- Battery > 50% before each test block
- Keep emergency_stop tool ready at all times
- **Mission pad detection height:** 30-120cm — drone must be in this range for pad operations
- **Surface requirements:** pads on matte, textured, non-reflective surface. Avoid pure black/white backgrounds
- **Keepalive active:** tello-mcp sends keepalive every 10s — drone should NOT auto-land during idle periods

---

## Block 1: Smoke Test (tello-mcp direct)

Start tello-mcp HTTP server:
```bash
set -a && source .env && set +a
uv run --package tello-mcp python -m tello_mcp.server --transport streamable-http --port 8100
```

### 1.1 Connection + Telemetry
- [ ] `get_telemetry` — verify battery, height, temp, attitude
- [ ] Confirm mission pad auto-enabled on connect (check server logs for "enable_mission_pads")

### 1.2 LED Control
- [ ] `set_led_color(r=0, g=255, b=0)` — green LED on expansion board

### 1.3 Display Tools (replacing display_matrix_text)
- [ ] `display_scroll_text(text="HELLO", direction="l", color="r", rate=0.5)` — red scrolling text
- [ ] `display_static_char(char="A", color="b")` — blue static "A"
- [ ] `display_pattern(pattern="r0r0r0r0" + "0r0r0r0r" * 3 + "r0r0r0r0" * 4)` — checkerboard pattern

### 1.4 Flight Basics
- [ ] `takeoff(room_id="living-room")` — hover at ~50cm
- [ ] `rotate(degrees=90)` — clockwise quarter turn
- [ ] `move(direction="forward", distance_cm=50)` — move forward
- [ ] `land()` — clean landing

### 1.5 Keepalive Verification
- [ ] `takeoff` → wait 30+ seconds without sending commands → drone should NOT auto-land
- [ ] Verify keepalive heartbeats in server logs (every 10s)

---

## Block 2: Mission Pad Detection

### 2.1 Pad Detection (hovering over pad)
- [ ] Place mission pad on floor, hover drone at 50cm over it
- [ ] `detect_mission_pad` — should return `detected: true`, `pad_id: N`, `x_cm`, `y_cm`, `z_cm`
- [ ] Verify x/y/z values change as drone position shifts relative to pad

### 2.2 Pad Detection Direction
- [ ] `set_pad_detection_direction(direction=0)` — downward only (20Hz)
- [ ] `set_pad_detection_direction(direction=2)` — both directions (10Hz each)
- [ ] Verify detection still works after direction change

### 2.3 No Pad Detected
- [ ] Hover in area without pads — `detect_mission_pad` returns `detected: false`, `pad_id: -1`

---

## Block 3: Pad-Relative Navigation

### 3.1 go_to_mission_pad
- [ ] Place pad on floor, hover drone nearby (within detection range)
- [ ] `go_to_mission_pad(x=0, y=0, z=50, speed=30, mid=<pad_id>)` — fly to 50cm directly over pad center
- [ ] Verify drone moves to pad center and hovers at specified height
- [ ] Try with different z values (30cm, 80cm) to verify altitude control

---

## Block 4: Mission Planning + Advisory Commands (tello-navigator)

Start tello-navigator HTTP server:
```bash
uv run --package tello-navigator python -m tello_navigator.server --transport streamable-http --port 8200
```

### 4.1 Create Mission
- [ ] `create_mission(goal="Survey living room", room_ids=["4309_...:living"])`
- [ ] Verify waypoints include `goto_pad` with `speed_cm_s: 30`

### 4.2 Start Mission
- [ ] `start_mission(mission_id=<id>)`
- [ ] Verify first waypoint's `suggested_command` is `takeoff`

### 4.3 Advance Through Mission
- [ ] `advance_mission(mission_id=<id>, current_waypoint_idx=0)` — advance past takeoff
- [ ] When reaching a `goto_pad` waypoint, verify `suggested_command`:
  - `tool: "go_to_mission_pad"`
  - `args.x: 0, args.y: 0, args.z: 50`
  - `args.speed: 30`
  - `args.mid: <pad_id>`
- [ ] Execute the suggested command against tello-mcp
- [ ] Continue advancing until mission completes

---

## Block 5: Telemetry Verification

### 5.1 Session Recording
- [ ] Start tello-telemetry consumer
- [ ] Fly a short mission
- [ ] Query Neo4j for session data — verify telemetry samples recorded

---

## Results Template

| Test | Result | Notes |
|------|--------|-------|
| Block 1.1 | | |
| Block 1.2 | | |
| Block 1.3 scroll | | |
| Block 1.3 static | | |
| Block 1.3 pattern | | |
| Block 1.4 | | |
| Block 1.5 keepalive | | |
| Block 2.1 | | |
| Block 2.2 | | |
| Block 2.3 | | |
| Block 3.1 | | |
| Block 4.1 | | |
| Block 4.2 | | |
| Block 4.3 | | |
| Block 5.1 | | |
