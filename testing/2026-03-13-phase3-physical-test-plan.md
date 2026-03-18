# Phase 3 Physical Drone Testing Plan

**Date:** 2026-03-13
**Author:** Arthur Fantaci + Claude
**Services Under Test:** tello-mcp, tello-telemetry, tello-navigator
**Duration:** ~65 minutes (50 min without optional Block 5)
**Hardware:** DJI Tello TT with expansion board (router mode)

---

## Prerequisites

### Infrastructure

```bash
# 1. Verify Docker services
docker compose up -d
docker compose ps                    # Neo4j healthy, Redis healthy

# 2. Verify room graph is seeded
docker exec -i tello-ai-platform-neo4j-1 cypher-shell -u neo4j -p tello-dev \
  "MATCH (r:RoomNode) RETURN count(r) AS rooms"
# Expected: 5

# 3. Source environment
set -a && source .env && set +a

# 4. Verify drone connectivity
ping -c 3 192.168.68.107
```

### Environment (.env must contain)

```
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=tello-dev
REDIS_URL=redis://localhost:6379
TELLO_HOST=192.168.68.107
```

### Physical Setup

- [ ] Drone on flat surface in Living Room (488cm x 622cm — largest room)
- [ ] Expansion board powered on (switch labels are REVERSED — verify LED responds)
- [ ] Ceiling fan OFF (234cm effective ceiling)
- [ ] Clear area: minimum 2m x 2m free of obstacles
- [ ] Laptop on same WiFi network as drone (router mode)
- [ ] Battery charged above 50% (14% drain per 20s observed in Phase 1 test)

### Safety Protocol (ALL blocks)

- [ ] Keep `emergency_stop` tool ready at all times
- [ ] If battery drops below 20%, land immediately
- [ ] Stay below 200cm altitude (234cm ceiling with fan)
- [ ] Clear area of obstacles before each flight block
- [ ] Test `emergency_stop` only over a soft surface

---

## Starting Services

Open 3 terminal windows. In each, source the environment first:

```bash
set -a && source .env && set +a
```

**Terminal 1 — tello-mcp (port 8100):**
```bash
uv run --package tello-mcp python -m tello_mcp.server --transport streamable-http --port 8100
```

**Terminal 2 — tello-telemetry (port 8200):**
```bash
uv run --package tello-telemetry python -m tello_telemetry.server --transport streamable-http --port 8200
```

**Terminal 3 — tello-navigator (port 8300):**
```bash
uv run --package tello-navigator python -m tello_navigator.server --transport streamable-http --port 8300
```

---

## Block 1: Smoke Test (tello-mcp only) — ~5 minutes

**Purpose:** Verify the FastMCP 3.x migration didn't break hardware control. Regression test of Phase 1 live test capabilities.

**Only Terminal 1 (tello-mcp) required.**

| # | Tool Call | Expected Result | Observe | Pass |
|---|-----------|----------------|---------|------|
| 1 | `get_telemetry()` | Battery, height, temp values | Drone responds, values reasonable | [ ] |
| 2 | `set_led_color(r=0, g=255, b=0)` | `{"status": "ok"}` | Green LED on expansion board | [ ] |
| 3 | `set_led_color(r=255, g=0, b=0)` | `{"status": "ok"}` | Red LED — visual confirm | [ ] |
| 4 | `detect_mission_pad()` | `{"pad_id": -1, "detected": false}` | No pad under drone | [ ] |
| 5 | `takeoff(room_id="living")` | `{"status": "ok"}` | Drone lifts to ~50cm | [ ] |
| 6 | `get_telemetry()` | height_cm ~50, tof_cm ~50 | In-flight telemetry works | [ ] |
| 7 | `rotate(degrees=90)` | `{"status": "ok"}` | CW rotation (~86° actual) | [ ] |
| 8 | `rotate(degrees=-90)` | `{"status": "ok"}` | CCW rotation back | [ ] |
| 9 | `land()` | `{"status": "ok"}` | Clean landing | [ ] |

**STOP GATE:** If any call fails, do not proceed. The migration broke something.

**Notes:**
```
Battery start: _____%
Battery after: _____%
Rotation accuracy: _____° actual for 90° commanded
```

---

## Block 2: Movement Commands — ~10 minutes

**Purpose:** Validate `move` in all 6 directions. These were NOT tested in Phase 1. The advisory command pattern generates move waypoints, so we need to confirm they work.

**Safety:** Start with 50cm distances. Living Room gives 488cm width — plenty of margin.

| # | Tool Call | Expected | Safety Note | Pass |
|---|-----------|----------|-------------|------|
| 1 | `takeoff(room_id="living")` | Hover at ~50cm | — | [ ] |
| 2 | `move(direction="forward", distance_cm=50)` | Moves forward 50cm | Watch for drift | [ ] |
| 3 | `move(direction="back", distance_cm=50)` | Returns to start | — | [ ] |
| 4 | `move(direction="left", distance_cm=50)` | Lateral movement | — | [ ] |
| 5 | `move(direction="right", distance_cm=50)` | Returns to center | — | [ ] |
| 6 | `move(direction="up", distance_cm=30)` | Ascends | Stay under 200cm! | [ ] |
| 7 | `get_tof_distance()` | tof_cm ~80 | Verify altitude sensor | [ ] |
| 8 | `move(direction="down", distance_cm=30)` | Descends to ~50cm | — | [ ] |
| 9 | `land()` | Clean landing | — | [ ] |

**Notes:**
```
Forward accuracy: _____cm actual for 50cm commanded
Lateral drift observed: yes / no
Up accuracy: _____cm actual for 30cm commanded
```

---

## Block 3: Telemetry Pipeline — ~10 minutes

**Purpose:** First live test of the full telemetry pipeline. The StreamConsumer, AnomalyDetector, and SessionRepository have never processed real drone data.

**Terminals 1 + 2 required (tello-mcp + tello-telemetry).**

| # | Action | What to Verify | Pass |
|---|--------|----------------|------|
| 1 | `takeoff(room_id="living")` via mcp | Telemetry server log: "Created flight session" | [ ] |
| 2 | Hover for 15 seconds | Telemetry samples in logs (~3 at 5s interval) | [ ] |
| 3 | `land()` via mcp | Telemetry server log: "Ended flight session" | [ ] |
| 4 | `list_flight_sessions()` via telemetry | Returns session with room_id="living" | [ ] |
| 5 | `get_flight_session(session_id=<id>)` | Full session details, duration_s > 0 | [ ] |
| 6 | `get_session_telemetry(session_id=<id>)` | 2-3 samples with real battery/height/temp | [ ] |
| 7 | `get_session_anomalies(session_id=<id>)` | Likely empty (normal flight) | [ ] |
| 8 | Neo4j Browser (localhost:7474): `MATCH (fs:FlightSession) RETURN fs` | Session node exists | [ ] |

**Notes:**
```
Session ID: _________________________________
Telemetry samples captured: _____
Duration recorded: _____s
Any anomalies detected: yes / no (type: _______________)
```

---

## Block 4: Single-Room Mission — ~15 minutes

**Purpose:** First live test of the full mission lifecycle. Plan → start → fly → advance → complete.

**All 3 terminals required (mcp + telemetry + navigator).**

**Dwelling prefix for room IDs:** `4309_Donny_Martel_Way_Tewksbury_MA:`

| # | Service | Tool Call | Expected | Pass |
|---|---------|-----------|----------|------|
| 1 | navigator | `create_mission(goal="Survey living room", room_ids=["4309_Donny_Martel_Way_Tewksbury_MA:living"])` | Planned mission with waypoints | [ ] |
| 2 | — | Record `mission_id`, inspect waypoints | takeoff → goto_pad(1) → goto_pad(2) → land | [ ] |
| 3 | navigator | `start_mission(mission_id=<id>)` | First waypoint + suggested_command: takeoff | [ ] |
| 4 | mcp | Execute suggested: `takeoff(room_id="...:living")` | Drone takes off | [ ] |
| 5 | navigator | `advance_mission(mission_id=<id>, current_waypoint_idx=0)` | Next waypoint: goto_pad + suggested: detect_mission_pad | [ ] |
| 6 | mcp | `detect_mission_pad()` | `pad_id` result (may be -1 without physical pads) | [ ] |
| 7 | navigator | `advance_mission(mission_id=<id>, current_waypoint_idx=1)` | Next waypoint | [ ] |
| 8 | mcp | Execute suggested command if applicable | — | [ ] |
| 9 | navigator | Continue advancing through remaining waypoints | — | [ ] |
| 10 | mcp | Execute final suggested: `land()` | Drone lands | [ ] |
| 11 | navigator | Final advance → `{"status": "completed"}` | Mission complete | [ ] |
| 12 | navigator | `get_mission(mission_id=<id>)` | Status = "completed" | [ ] |

**Notes:**
```
Mission ID: _________________________________
Total waypoints: _____
Suggested commands received:
  WP 0: tool=__________ args=__________________________
  WP 1: tool=__________ args=__________________________
  WP 2: tool=__________ args=__________________________
  WP 3: tool=__________ args=__________________________
Mission pads detected: yes / no
Final status: planned / executing / completed / aborted
```

---

## Block 5: Multi-Room Mission (Optional) — ~15 minutes

**Purpose:** Test multi-room mission planning. Drone won't physically move between rooms, but waypoint sequence and advisory commands should be correct.

| # | Tool Call | Expected | Pass |
|---|-----------|----------|------|
| 1 | `create_mission(goal="Patrol living and kitchen", room_ids=["...:living", "...:kitchen"])` | Waypoints: takeoff(living) → pads → pads → land(kitchen) | [ ] |
| 2 | `start_mission(mission_id=<id>)` | First waypoint = takeoff in living | [ ] |
| 3 | Execute takeoff, advance through living room waypoints | Advisory commands work | [ ] |
| 4 | At kitchen waypoints: `abort_mission(mission_id=<id>, reason="Cannot move between rooms")` | Status → aborted | [ ] |
| 5 | `list_missions()` | Shows completed single-room + aborted multi-room | [ ] |

**Notes:**
```
Multi-room mission ID: _________________________________
Total waypoints planned: _____
Waypoints completed before abort: _____
```

---

## Block 6: Error Handling — ~5 minutes

**Purpose:** Verify error paths work correctly.

| # | Test | Expected | Pass |
|---|------|----------|------|
| 1 | `abort_mission` on completed mission | `{"error": "INVALID_TRANSITION"}` | [ ] |
| 2 | `start_mission` on non-existent ID | `{"error": "NOT_FOUND"}` | [ ] |
| 3 | `create_mission` with unknown room | `{"error": "PLANNING_FAILED", "detail": "Unknown rooms: [...]"}` | [ ] |
| 4 | `emergency_stop()` during flight | Motors cut — **soft surface only!** | [ ] |

**Notes:**
```
Emergency stop test: drone fell from _____cm, any damage: yes / no
```

---

## Block 7: Neo4j Verification (no drone) — ~5 minutes

**Purpose:** Verify the full graph state after all flight tests.

Open Neo4j Browser at `http://localhost:7474` and run each query:

### 7.1 All flight sessions
```cypher
MATCH (fs:FlightSession)
RETURN fs.id, fs.room_id, fs.duration_s, fs.min_battery_pct
ORDER BY fs.start_time DESC;
```
**Expected:** At least 3 sessions (Blocks 1, 2, 3 + Block 4 flight)

Result: [ ] Pass — _____ sessions found

### 7.2 Telemetry samples per session
```cypher
MATCH (ts:TelemetrySample)-[:BELONGS_TO]->(fs:FlightSession)
RETURN fs.id AS session, count(ts) AS samples, min(ts.battery_pct) AS min_battery
ORDER BY samples DESC;
```
Result: [ ] Pass — samples linked correctly

### 7.3 All missions with status
```cypher
MATCH (m:Mission)
RETURN m.id, m.goal, m.status, m.room_ids
ORDER BY m.created_at DESC;
```
**Expected:** At least 1 completed, possibly 1 aborted

Result: [ ] Pass — _____ missions found

### 7.4 Waypoints for completed missions
```cypher
MATCH (m:Mission {status: "completed"})-[:CONTAINS_WAYPOINT]->(w:Waypoint)
RETURN m.goal, w.sequence, w.action, w.room_id
ORDER BY m.id, w.sequence;
```
Result: [ ] Pass — waypoint chain intact

### 7.5 Room graph integrity
```cypher
MATCH (r:RoomNode)-[:HAS_PAD]->(p:MissionPad)
RETURN r.name, collect(p.id) AS pads;
```
```cypher
MATCH (a:RoomNode)-[c:CONNECTS_TO]->(b:RoomNode)
RETURN a.name AS from_room, b.name AS to_room, c.passage_type;
```
Result: [ ] Pass — 5 rooms, 8 pads, 4 connections

### 7.6 Full graph visualization
```cypher
MATCH (n) RETURN n;
```
**Screenshot this for your portfolio.**

Result: [ ] Pass — graph looks correct

---

## Results Summary

| Block | Description | Duration | Result |
|-------|-------------|----------|--------|
| 1 | Smoke test (regression) | 5 min | [ ] Pass / [ ] Fail |
| 2 | Movement commands | 10 min | [ ] Pass / [ ] Fail |
| 3 | Telemetry pipeline | 10 min | [ ] Pass / [ ] Fail |
| 4 | Single-room mission | 15 min | [ ] Pass / [ ] Fail |
| 5 | Multi-room mission (optional) | 15 min | [ ] Pass / [ ] Fail / [ ] Skipped |
| 6 | Error handling | 5 min | [ ] Pass / [ ] Fail |
| 7 | Neo4j verification | 5 min | [ ] Pass / [ ] Fail |

**Overall:** [ ] All blocks passed — ready for Phase 4
              [ ] Failures found — see notes above

**Battery at end of testing:** _____%

**Issues discovered:**
```




```

**Date completed:** _______________
**Tester:** _______________
