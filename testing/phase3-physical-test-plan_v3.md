# Phase 3c Physical Test Plan (v3)

**Date:** 2026-03-15
**Tool:** `scripts/fly.py` — direct DroneAdapter, no MCP server needed
**Prereqs:** Drone powered on, Router Mode, connected to home WiFi

---

## Setup

```bash
cd ~/Projects/tello-ai-platform
source .venv/bin/activate
```

---

## Test 1: Discovery + Connection

```bash
uv run python scripts/fly.py --host auto connect
```

**Expected:** Finds drone IP via subnet scan, prints `{'status': 'ok'}`.
If auto fails, use explicit IP: `--host 192.168.68.107`

---

## Test 2: Telemetry

```bash
uv run python scripts/fly.py --host auto telemetry
```

**Expected:** JSON with battery_pct, height_cm, etc. No raw exceptions.

---

## Test 3: LED + Display

```bash
uv run python scripts/fly.py --host auto led 0 255 0
uv run python scripts/fly.py --host auto text "HELLO"
```

**Expected:** LED turns green, matrix scrolls "HELLO".

---

## Test 4: Flight (REPL mode — recommended)

Use REPL to maintain persistent connection and built-in delays:

```bash
uv run python scripts/fly.py --host auto repl
```

Then type each command one at a time:

```
> telemetry          # verify battery > 20%
> led 0 0 255        # blue = about to fly
> takeoff            # 3s stabilization delay built in
> rotate 90          # quarter turn
> rotate -90         # back to original heading
> move forward 50    # 50cm forward
> move back 50       # return to start
> land               # graceful land (emergency fallback if needed)
> quit
```

**Expected:** Each command prints `{'status': 'ok'}`. No "Not joystick" errors.

---

## Test 5: Emergency Stop

Only test if you need to verify the emergency path:

```
> takeoff
> emergency          # motors kill immediately — drone will DROP
```

**Expected:** `{'status': 'ok', 'warning': 'Motors killed'}`. Drone falls.

---

## Test 6: Mission Pad Detection

Place a mission pad under the drone:

```
> takeoff
> pad                # should detect pad ID (1-8)
> land
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Auto-discovery failed" | Use `--host 192.168.68.XXX` with known IP |
| "DRONE_NOT_CONNECTED" | Power cycle drone, wait for WiFi LED, retry |
| "Not joystick" | Increase delays in `scripts/fly.py` (TAKEOFF_DELAY, COMMAND_DELAY) |
| "LAND_FAILED" | `emergency` to kill motors, then power cycle |
| Battery < 20% | Charge before flight testing |

---

## What Changed from v2

- **No MCP server needed** — `fly.py` uses DroneAdapter directly
- **No curl/JSON** — simple CLI commands
- **Built-in delays** — 3s after takeoff, 0.5s between commands
- **Auto-discovery** — `--host auto` finds drone on network
- **Safe land** — automatic emergency fallback if land fails
- **REPL mode** — persistent connection, no reconnect per command
