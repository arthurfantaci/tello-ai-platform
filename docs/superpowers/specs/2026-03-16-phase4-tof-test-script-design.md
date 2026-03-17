# Phase 4 ToF Physical Test Script — Design Spec

**Date:** 2026-03-16
**Status:** Draft

## Overview

A guided interactive test script (`scripts/test_tof.py`) that validates Phase 4's forward ToF sensor integration and collects sensor characterization data to inform Phase 4b design (obstacle avoidance routing, return-to-home).

Separate from `fly.py` — this is a purpose-built test harness, not a REPL extension.

## Connection and Initialization

```python
from tello_mcp.drone import DroneAdapter
from tello_mcp.obstacle import ObstacleConfig, ObstacleMonitor
```

- `DroneAdapter(host=args.host)` + `drone.connect()` at script start
- `ObstacleConfig.from_env()` for threshold values
- `ObstacleMonitor(drone, config)` instantiated but **poll loop NOT started** — used only for `classify_zone()` as a pure function. No background polling during tests; all sensor reads are explicit `drone.get_forward_distance()` calls.
- Battery read: `drone.get_telemetry().battery_pct`

## Test Sequence

Six tests, grounded first, flight last. **If Test 1 fails (sensor unavailable), tests 2-6 are skipped** — no point testing a sensor that doesn't respond.

### Test 1: Sensor Alive

**Goal:** Verify `get_forward_distance()` returns a valid mm reading while grounded.

- Prompt: "Point drone forward at open room. Press Enter."
- Call `drone.get_forward_distance()` once
- PASS if `status == "ok"` and `distance_mm` is an integer
- **FAIL halts all subsequent tests** (marked as SKIPPED)
- Record: raw reading, zone classification

### Test 2: Range Sweep

**Goal:** Verify readings track as an obstacle approaches the sensor.

- Prompt: "Slowly move your hand toward the sensor over 10 seconds. Press Enter to start."
- Collect 20 samples at 500ms intervals (10 seconds total)
- Exclude out-of-range readings (8192) from stats
- PASS if at least 3 distinct distance values observed (readings actually change)
- Record: all 20 readings with timestamps, min, max, distinct_values

### Test 3: Close Object Detection

**Goal:** Verify DANGER zone triggers at close range.

- Prompt: "Hold your hand less than 40cm from the sensor. Press Enter."
- Call `get_forward_distance()` once
- Classify zone via `monitor.classify_zone(distance_mm)`
- PASS if zone is DANGER (distance_mm < 400). If WARNING, record as marginal pass with note.
- Record: reading, zone

### Test 4: Stability Test

**Goal:** Measure sensor noise at a fixed distance.

- Prompt: "Point drone at a wall or flat surface at a fixed distance (~1m). Press Enter."
- Collect 30 samples at 200ms intervals (6 seconds total)
- Exclude out-of-range readings (8192) from stats computation
- Compute: mean, std deviation, min, max
- PASS if std deviation < 50mm (sensor is reasonably stable)
- Record: all 30 readings, computed stats
- **Populates `sensor_characterization`:** mean → `noise_mean_mm`, std → `noise_std_mm`

### Test 5: Telemetry Integration

**Goal:** Verify `forward_tof_mm` appears in the `TelemetryFrame`.

- Call `drone.get_telemetry()` once
- PASS if result is a `TelemetryFrame` and `forward_tof_mm` is not None
- Record: full telemetry frame as dict

### Test 6: Flight DANGER Stop (Optional)

**Goal:** Verify the full safety pipeline in flight: takeoff → approach wall → DANGER stop → options menu → emergency_land.

**No ObstacleMonitor poll loop running.** Distance checks are manual — the script calls `get_forward_distance()` explicitly between moves. This avoids race conditions between the poll loop's forced stop and the script's move commands.

- Battery gate: warn and confirm if battery < 30%
- Prompt: "FLIGHT TEST. Place drone on flat surface facing a wall (~2m away). Ready to fly? (y/n)"
- If declined: SKIP (not a failure)
- **Pre-flight distance gate:** Call `get_forward_distance()` before takeoff. If distance_mm < 1500, abort: "Too close to wall. Move drone back and retry."
- Sequence:
  1. `drone.takeoff()`, wait 3 seconds for stabilization
  2. Prompt: "Drone is hovering. It will now fly forward. Press Enter when ready."
  3. Call `get_forward_distance()`, record reading
  4. `drone.move("forward", 100)` (1 meter toward wall)
  5. Call `get_forward_distance()`, check zone
  6. If DANGER: PASS — proceed to step 9
  7. If not DANGER: `drone.move("forward", 50)` (another 50cm)
  8. Call `get_forward_distance()`, check zone again
  9. If DANGER detected: present `CLIResponseProvider` options menu, execute chosen response via `ObstacleResponseHandler`
  10. If never DANGER after 150cm travel: `drone.safe_land()`, record as NEEDS_ADJUSTMENT (thresholds may need tuning for this environment)
- Record: distance at each check, whether DANGER triggered, chosen response, action result

## Output

**File:** `testing/phase4-tof-results-YYYY-MM-DD.json`

```json
{
  "date": "2026-03-16T14:30:00",
  "drone_host": "192.168.68.107",
  "battery_start": 85,
  "battery_end": 78,
  "obstacle_config": {
    "caution_mm": 1500,
    "warning_mm": 800,
    "danger_mm": 400,
    "out_of_range": 8192,
    "poll_interval_ms": 200
  },
  "tests": [
    {
      "name": "sensor_alive",
      "status": "pass",
      "reading": {"distance_mm": 1450, "zone": "caution"},
      "notes": ""
    },
    {
      "name": "range_sweep",
      "status": "pass",
      "readings": [
        {"timestamp": "...", "distance_mm": 2000},
        {"timestamp": "...", "distance_mm": 1800}
      ],
      "stats": {"min": 350, "max": 2000, "distinct_values": 15},
      "notes": ""
    },
    {
      "name": "close_object",
      "status": "pass",
      "reading": {"distance_mm": 280, "zone": "danger"},
      "notes": ""
    },
    {
      "name": "stability",
      "status": "pass",
      "readings": ["...30 readings..."],
      "stats": {"mean": 1015.3, "std": 12.5, "min": 990, "max": 1040},
      "notes": ""
    },
    {
      "name": "telemetry_integration",
      "status": "pass",
      "telemetry_snapshot": {"battery_pct": 82, "forward_tof_mm": 1020, "...": "..."},
      "notes": ""
    },
    {
      "name": "flight_danger_stop",
      "status": "pass",
      "pre_flight_distance_mm": 2100,
      "distance_checks": [
        {"phase": "pre_move", "distance_mm": 2100, "zone": "clear"},
        {"phase": "after_100cm", "distance_mm": 850, "zone": "caution"},
        {"phase": "after_150cm", "distance_mm": 320, "zone": "danger"}
      ],
      "danger_triggered": true,
      "chosen_response": "emergency_land",
      "action_result": {"status": "ok"},
      "notes": ""
    }
  ],
  "sensor_characterization": {
    "effective_range_mm": {"min": 280, "max": 2100},
    "noise_std_mm": 12.5,
    "noise_mean_mm": 1015.3,
    "response_latency_note": "estimated from sampling interval"
  }
}
```

**`sensor_characterization` is populated from:**
- `effective_range_mm.min` — smallest non-8192 reading across all tests
- `effective_range_mm.max` — largest non-8192 reading across all tests
- `noise_std_mm` — from Test 4 stability stats
- `noise_mean_mm` — from Test 4 stability stats

## Safety

- **Tests 1-5:** Grounded only. No flight risk.
- **Test 6:** Explicit y/n confirmation before takeoff. Skippable. Pre-flight distance gate prevents collision if too close to wall.
- **Ctrl+C handler:** Catches `KeyboardInterrupt` at any point, calls `drone.safe_land()` if airborne, then exits gracefully.
- **Battery check:** Warns if battery < 30% before Test 6.

## Script Structure

```
scripts/test_tof.py
├── main()              — argparse (--host), connect, run tests, save results
├── run_test_1()        — sensor alive
├── run_test_2()        — range sweep
├── run_test_3()        — close object
├── run_test_4()        — stability
├── run_test_5()        — telemetry integration
├── run_test_6()        — flight DANGER stop
├── save_results()      — write JSON to testing/
├── build_characterization() — compute sensor_characterization from test data
└── print_summary()     — console summary of all test results
```

Each `run_test_N()` returns a dict with `name`, `status`, raw data, and `notes`.

## What This Is NOT

- Not a unit test (no pytest, no assertions that block CI)
- Not an extension to fly.py (separate script, single-purpose)
- Not automated flight (all flight is guided with human confirmation)
- Not running the ObstacleMonitor poll loop (all reads are explicit)
