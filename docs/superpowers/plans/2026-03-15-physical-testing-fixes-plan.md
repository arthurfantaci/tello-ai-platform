# Physical Testing Fixes Plan

> **Status:** Draft — needs brainstorm/spec approval before implementation
> **Context:** 2026-03-14 physical test session failed on 6 issues
> **Goal:** Make tello-mcp reliably connectable and controllable for physical drone testing

---

## Issues Found (prioritized)

### P0 — Blocking: Can't fly the drone

| # | Issue | Root Cause | Impact |
|---|-------|-----------|--------|
| 1 | No drone connection on startup | Lifespan creates DroneAdapter but never calls connect(). No connect MCP tool exists. | Can't do anything — all tools return DRONE_NOT_CONNECTED |
| 2 | get_telemetry gives confusing error when not connected | Missing `_require_connection()` guard — throws raw TelloException | Misleading error message, hard to diagnose |
| 3 | "error Not joystick" on rotate after takeoff | Tello TT expansion board switch position or firmware mode issue | Flight commands rejected, drone stuck in air |

### P1 — Painful: Makes testing unreliable

| # | Issue | Root Cause | Impact |
|---|-------|-----------|--------|
| 4 | Land fails after "Not joystick" error | Drone rejects all SDK commands in error state | Drone stuck airborne until auto-land timeout |
| 5 | DHCP IP changes break startup | Router assigns new IP each boot, .env has hardcoded TELLO_HOST | Must discover IP and restart server each session |

### P2 — Quality of life

| # | Issue | Root Cause | Impact |
|---|-------|-----------|--------|
| 6 | MCP-over-HTTP is clunky for manual testing | curl + JSON-RPC + SSE parsing is slow and error-prone | Testing is painful, hard to demo |

---

## Proposed Fixes

### Fix 1: Auto-connect + connect_drone tool (P0, Issue #1)

**Change:** Two-part fix:
1. Add `connect_drone` MCP tool that calls `drone.connect()` — gives explicit control
2. Auto-connect in lifespan (best-effort, like mission pad enablement) — just works on startup

**Why both:** Auto-connect handles the 90% case (server starts, drone is ready). The explicit tool handles reconnection if the drone was power-cycled mid-session.

**Files:** `server.py` (lifespan), new tool in `flight.py` or a new `connection.py` tool module

### Fix 2: Add _require_connection() to get_telemetry (P0, Issue #2)

**Change:** Wrap `get_telemetry()` in the standard connection check. Return `{"error": "DRONE_NOT_CONNECTED"}` instead of letting djitellopy throw.

**Challenge:** `get_telemetry()` currently returns `TelemetryFrame` (Pydantic model), not `dict`. Need to decide: change return type to `dict | TelemetryFrame`, or return a dict with an error key.

**Files:** `drone.py`, `test_drone.py`

### Fix 3: Investigate "Not joystick" error (P0, Issue #3)

**Research needed before fix.** This requires:
1. Check Tello SDK 3.0 docs for "Not joystick" error meaning
2. Test with expansion board switch in BOTH positions
3. Test with expansion board completely removed
4. Check if firmware update is needed
5. Check if `rc 0 0 0 0` (neutral RC command) clears the state

**Likely root cause:** The Tello TT in Router Mode with expansion board may default to "joystick mode" where it expects RC-style control (continuous `rc` commands) rather than discrete SDK commands (`cw`, `forward`, etc.). The `command` SDK init may not fully switch it.

**Files:** Potentially `drone.py` (add RC init sequence after connect)

### Fix 4: Emergency fallback when commands fail (P1, Issue #4)

**Change:** Add retry logic or fallback in DroneAdapter:
- If `land()` fails, try `emergency()` (motor kill)
- Add a `force_land()` method that tries land → emergency → raw UDP "land" command
- Log aggressively when commands fail so the operator knows what's happening

**Files:** `drone.py`, `test_drone.py`

### Fix 5: Auto-discover drone IP (P1, Issue #5)

**Options (pick one):**
1. **ARP scan on startup** — scan the subnet for the Tello's MAC address (starts with `60:60:1F` for DJI)
2. **mDNS/Bonjour** — Tello may advertise itself (needs investigation)
3. **DHCP reservation** — configure router to always assign same IP (no code change, but fragile)
4. **Config option: `TELLO_HOST=auto`** — triggers subnet scan in DroneAdapter.__init__

**Recommended:** Option 4 with ARP scan. Falls back to the configured IP if scan fails.

**Files:** `drone.py` or new `discovery.py` module, `config.py`

### Fix 6: Add CLI test script (P2, Issue #6)

**Change:** Create `scripts/fly.py` — a simple CLI that bypasses MCP entirely:
```bash
uv run python scripts/fly.py --host auto takeoff
uv run python scripts/fly.py --host auto land
uv run python scripts/fly.py --host auto telemetry
uv run python scripts/fly.py --host auto led 0 255 0
```

Uses DroneAdapter directly, no MCP/HTTP overhead. Good for quick smoke tests and demos.

**Files:** New `scripts/fly.py`

---

## Recommended Execution Order

1. **Fix 3 first** (research) — if "Not joystick" can't be resolved, nothing else matters
2. **Fix 1** (auto-connect) — unblocks all MCP-based testing
3. **Fix 2** (get_telemetry guard) — quick fix, improves error clarity
4. **Fix 6** (CLI script) — enables testing while MCP issues are debugged
5. **Fix 4** (emergency fallback) — safety improvement
6. **Fix 5** (auto-discover) — quality of life

Fixes 1, 2, 4, 6 could be one PR ("Phase 3c: operational readiness").
Fix 3 needs research first — may be a hardware/firmware issue.
Fix 5 is nice-to-have, could defer.

---

## Open Questions

1. What does the Tello SDK 3.0 doc say about "Not joystick" error?
2. Does the expansion board switch position affect SDK command acceptance?
3. Is there a firmware update available for the Tello TT?
4. Should connect_drone be in flight.py or its own module?
5. Should we add a `disconnect_drone` tool too (for clean shutdown)?
