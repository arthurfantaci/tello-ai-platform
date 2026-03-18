# Forward ToF Threshold Fix & Debouncing Design

**Date:** 2026-03-17
**Phase:** Interim phase between Phase 4/4a and Phase 4b
**Status:** Design approved, pending implementation
**Inputs:** Phase 4 physical test results (`testing/phase4-tof-results-2026-03-17.json`), sensor characterization data, VL53L0X research

## Problem Statement

Phase 4 physical testing (2026-03-17) revealed that the ObstacleConfig defaults are calibrated far beyond the sensor's reliable range. The VL53L0X-based forward ToF sensor has ~500mm effective range, but the original thresholds (CAUTION=1500mm, WARNING=800mm, DANGER=400mm) were set assuming a much more capable sensor. Additionally:

- The out-of-range constant is hardcoded as 8192 but the sensor returns 8190
- No debouncing exists — sensor flicker at zone boundaries causes erratic `drone.stop()` calls
- Operator-facing prompts lack imperial measurements
- test_tof.py Test 6 recorded a false FAIL due to djitellopy's retry race condition

## Scope

Seven changes, all in a single PR:

1. Revise ObstacleConfig defaults to match sensor capability
2. Replace the out-of-range magic number with a defensive `>= 8000` threshold
3. Add counter-based debouncing for DANGER zone exit
4. Add imperial measurements to all operator-facing prompts
5. Fix test_tof.py Test 6 takeoff handling
6. Update test_tof.py prompts with revised thresholds and imperial units
7. Bundle untracked project files (housekeeping commit)

## Design

### 1. ObstacleConfig Defaults

**File:** `services/tello-mcp/src/tello_mcp/obstacle.py`

Revised defaults based on sensor characterization:

| Parameter | Old | New | Rationale |
|-----------|-----|-----|-----------|
| `caution_mm` | 1500 | 500 (~20in) | Matches sensor's reliable detection range |
| `warning_mm` | 800 | 300 (~12in) | Operator should slow down / prepare to stop |
| `danger_mm` | 400 | 200 (~8in) | Emergency stop — minimum detected distance was 196mm in testing |
| `out_of_range` | 8192 | Removed | Replaced by `out_of_range_min` |
| `poll_interval_ms` | 200 | 200 (unchanged) | ~3.2 Hz polling rate is adequate |

New fields:

| Parameter | Value | Env Var |
|-----------|-------|---------|
| `out_of_range_min` | 8000 | `OBSTACLE_OUT_OF_RANGE_MIN` |
| `required_clear_readings` | 3 | `OBSTACLE_REQUIRED_CLEAR_READINGS` |

**Why `>= 8000` instead of `== 8190`:** The sensor's reliable range is ~500mm. Any reading above 8000mm is meaningless — it's 16x beyond reliable range. Using a defensive threshold protects against firmware variations (SDK docs say 8192, sensor returns 8190) without losing any useful information.

**Why `required_clear_readings = 3`:** At ~3.2 Hz polling, 3 readings = ~0.9s. This is long enough to filter boundary flicker but short enough to feel responsive to an operator who has moved an obstacle. The sensor's noise (5.3mm std dev) is low enough that 3 consecutive readings reliably indicates a genuine state change, not noise.

### 2. Out-of-Range Detection

**Files affected:**

| File | Change |
|------|--------|
| `obstacle.py` | Field rename: `out_of_range` → `out_of_range_min`. Comparison: `>=` instead of `==` |
| `obstacle.py` (`classify_zone`) | `distance_mm >= config.out_of_range_min` returns CLEAR |
| `drone.py` | Docstring update: "8192" → ">=8000" |
| `sensors.py` | Docstring update: "8192 means nothing detected" → ">=8000 means out of range" |
| `scripts/test_tof.py` | Constant rename: `OUT_OF_RANGE` → `OUT_OF_RANGE_MIN = 8000`, comparisons use `>=` |

**Env var change:** `OBSTACLE_OUT_OF_RANGE` → `OBSTACLE_OUT_OF_RANGE_MIN`

### 3. DANGER Exit Debouncing

**File:** `services/tello-mcp/src/tello_mcp/obstacle.py` — `ObstacleMonitor` class

**New instance state:**
- `_in_danger: bool = False` — whether the monitor is currently in debounced DANGER state
- `_danger_clear_count: int = 0` — consecutive non-DANGER readings since entering DANGER

**Modified `_poll_loop` logic:**

```
On each poll reading:
  1. raw_zone = classify_zone(distance_mm)          # pure function, unchanged
  2. If _in_danger:
     a. If raw_zone is NOT DANGER:
        - Increment _danger_clear_count
        - If _danger_clear_count >= required_clear_readings:
          → Set _in_danger = False, reported_zone = raw_zone
        - Else:
          → reported_zone = DANGER (still debouncing)
     b. If raw_zone IS DANGER:
        - Reset _danger_clear_count = 0
        - reported_zone = DANGER
  3. If NOT _in_danger:
     a. If raw_zone IS DANGER:
        - Set _in_danger = True, reset _danger_clear_count = 0
        - Call drone.stop() immediately
        - reported_zone = DANGER
     b. Else:
        - reported_zone = raw_zone (no debouncing)
  4. Fire callbacks with reported_zone
```

**Key design decisions:**

- **`classify_zone()` stays pure.** It returns the raw zone for a single reading. Debouncing is the monitor's concern, not the classifier's. This means `fly.py` can call `classify_zone()` directly for instant one-shot readings without debounce delay.
- **Asymmetric: instant entry, delayed exit.** Entering DANGER triggers `drone.stop()` immediately — no debounce delay. Exiting DANGER requires 3 consecutive non-DANGER readings. False positives (stopping when safe) are harmless; false negatives (not stopping when dangerous) risk collision.
- **Only DANGER transitions are debounced.** CAUTION↔WARNING flickering is cosmetic — neither triggers `drone.stop()`. Debouncing all transitions would add complexity and latency with no safety benefit.
- **Single DANGER reading resets the counter.** During the exit window, if even one DANGER reading arrives, `_danger_clear_count` resets to 0. The operator must have 3 *consecutive* clear readings.

### 4. Operator-Facing Imperial Measurements

**Files:** `scripts/fly.py`, `scripts/test_tof.py`, `services/tello-mcp/src/tello_mcp/tools/sensors.py`

**fly.py changes:**

A `mm_to_imperial(mm: int) -> str` helper function within `fly.py` (not shared — only used for operator display):
- Values < 1000mm: returns `"~{x}in"` (e.g., `"~13.5in"`)
- Values >= 1000mm: returns `"~{x}ft"` (e.g., `"~3.3ft"`)

Updated output formats:
- `tof` command: `"Forward ToF: 342mm (~13.5in) (WARNING)"` (was: `"Forward ToF: 342mm (WARNING)"`)
- `monitor` command: `"Thresholds: CAUTION <500mm (~20in), WARNING <300mm (~12in), DANGER <200mm (~8in)"` (was: old threshold values without imperial)

**test_tof.py prompt changes:**

| Location | Current | Updated |
|----------|---------|---------|
| Test 3 instruction | "Hold hand less than 40cm" | "Hold hand less than 200mm (~8in)" |
| Test 6 pre-flight | "too close (< 1500mm)" | "too close (< 500mm / ~20in)" |
| Test 6 operator | "Place drone facing wall (~2m away)" | "Place drone facing wall (~2m / ~6.5ft away)" |
| Distance outputs | `"{mm}mm ({zone})"` | `"{mm}mm (~{in}in) ({zone})"` |

**sensors.py docstring changes:**
- `get_forward_distance`: `"8192 means nothing detected"` → `">=8000 means nothing detected (out of range)"`
- `get_obstacle_status`: `"CAUTION (<150cm), WARNING (<80cm), DANGER (<40cm)"` → `"CAUTION (<500mm/~20in), WARNING (<300mm/~12in), DANGER (<200mm/~8in)"`

### 5. Test 6 Takeoff Fix

**File:** `scripts/test_tof.py`

**Root cause:** djitellopy's `takeoff()` sends the SDK `takeoff` command and expects `"ok"`. If the drone responds but djitellopy's retry logic sends another `takeoff` to an already-airborne drone, the SDK returns `"error"` (can't take off while flying). djitellopy reports the *last* response, so the whole call fails even though the drone is flying.

**Fix:** After a takeoff "failure," check whether the drone is actually airborne before recording a FAIL:

```python
result = drone.takeoff()
if result.get("status") != "ok":
    # Takeoff reported failure — check if drone is actually airborne
    try:
        height = tello.get_height()  # direct SDK call for diagnostics
        if height > 0:
            # Drone IS flying — djitellopy retry race condition
            print(f"  NOTE: takeoff() returned error but drone is airborne (height={height}cm)")
            print(f"  Known djitellopy retry race condition — continuing test")
            takeoff_succeeded = True
        else:
            print(f"  FAIL — takeoff genuinely failed: {result}")
            takeoff_succeeded = False
    except Exception:
        print(f"  FAIL — takeoff failed and height check unavailable: {result}")
        takeoff_succeeded = False
```

**Enhanced failure diagnostics:** On any Test 6 outcome (pass or fail), capture:
- `takeoff_raw_result`: the raw dict from `drone.takeoff()`
- `height_after_takeoff_cm`: post-takeoff height check
- `battery_at_takeoff`: battery level at takeoff time
- `takeoff_race_condition_detected`: boolean flag if height > 0 despite error response

This data goes into the test results JSON so future physical test failures are diagnosable from the file alone.

### 6. Updated test_tof.py Thresholds

All hardcoded threshold references in test_tof.py update to match the new ObstacleConfig defaults:

- `OUT_OF_RANGE = 8192` → `OUT_OF_RANGE_MIN = 8000` with `>=` comparisons
- Test 3 close-object check: 400mm → 200mm boundary
- Test 6 pre-flight safety gate: 1500mm → 500mm
- Zone classification throughout uses the new thresholds via `ObstacleConfig()` defaults

### 7. Untracked File Cleanup

**Committed as a separate "chore:" commit** before the implementation commits on the worktree branch.

**Step 1 — .gitignore additions:**
```
docs/tello-drone-docs/*.pdf
testing/*.pdf
testing/*.html
testing/*.jpeg
.claude/hookify.*.local.md
```

**Step 2 — Tracked files to commit:**
- `.claude/settings.json` (modified)
- `.gitignore` (modified)
- `.mcp.json` (modified)
- `.claude/hooks/require-issue-and-branch.sh`
- `docs/superpowers/plans/*.md` (3 historical plans)
- `docs/superpowers/specs/*.md` (2 historical specs)
- `docs/superpowers/research/*.md` (1 research doc)
- `testing/2026-03-13-phase3-physical-test-plan.md`
- `testing/phase4-tof-results-2026-03-17.json`
- `services/tello-vision/src/tello_vision/__init__.py` (placeholder)
- `services/tello-voice/src/tello_voice/__init__.py` (placeholder)

## Testing Strategy

### Unit Tests

**File:** `services/tello-mcp/tests/test_obstacle.py`

All existing tests update assertions to match new defaults (500/300/200/8000).

New tests for debouncing:
- `test_danger_exit_requires_consecutive_clear_readings` — 2 clear readings followed by 1 DANGER resets count; 3 consecutive clears exits DANGER
- `test_danger_entry_is_immediate` — single DANGER reading triggers `drone.stop()` with no delay
- `test_debounce_only_applies_to_danger` — CAUTION↔WARNING transitions have no debounce delay
- `test_danger_clear_count_resets_on_danger_reading` — mid-debounce DANGER reading resets counter to 0

**Files:** `services/tello-mcp/tests/test_drone.py`, `packages/tello-core/tests/test_models.py`

Update hardcoded 8192 values to 8190 or appropriate values in test fixtures.

### Physical Testing

**Required before merge** (per `feedback_physical_test_before_merge` rule).

Physical test run generates `testing/forward-tof-threshold-results-YYYY-MM-DD.json` containing:
- New `obstacle_config` showing 500/300/200/8000 thresholds
- Enhanced Test 6 with `takeoff_raw_result`, `height_after_takeoff_cm`, `battery_at_takeoff`, `takeoff_race_condition_detected` fields
- All test prompts verified against updated thresholds

## Files Changed Summary

| File | Type of Change |
|------|---------------|
| `services/tello-mcp/src/tello_mcp/obstacle.py` | Config defaults, field rename, debounce logic |
| `services/tello-mcp/tests/test_obstacle.py` | Assertion updates, new debounce tests |
| `services/tello-mcp/src/tello_mcp/tools/sensors.py` | Docstring updates |
| `services/tello-mcp/src/tello_mcp/drone.py` | Docstring update |
| `services/tello-mcp/tests/test_drone.py` | Test fixture updates |
| `packages/tello-core/tests/test_models.py` | Test fixture updates |
| `scripts/fly.py` | Imperial helper, updated output formats |
| `scripts/test_tof.py` | Thresholds, imperial prompts, Test 6 fix |
| `.gitignore` | Exclude PDFs, HTML, JPEG, hookify locals |
| Various untracked files | Housekeeping commit |

## Implementation Notes

These items are implicit in the design but worth calling out for the planner:

- **test_tof.py comparison sites:** Multiple `!= OUT_OF_RANGE` checks (lines ~98, 179, 436, 572, 583, 593) must all become `>= OUT_OF_RANGE_MIN`
- **test_tof.py `save_results` output:** The JSON output key `"out_of_range"` should become `"out_of_range_min"` for consistency
- **test_tof.py Test 3 strings:** Docstring (`"verify DANGER zone at <40cm"`) and failure message (`"Expected DANGER (<400mm)"`) must update to reflect the 200mm threshold

## Out of Scope

- **Phase 4b (Navigator Obstacle Avoidance):** Separate brainstorm cycle after this merges
- **Debouncing non-DANGER transitions:** No safety benefit, adds complexity
- **Hysteresis bands:** Counter-based debouncing is simpler and addresses the observed failure mode
- **DroneAdapter changes:** No code changes to `drone.py` beyond docstring update
