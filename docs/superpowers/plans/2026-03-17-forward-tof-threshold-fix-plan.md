# Forward ToF Threshold Fix Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development
> (if subagents available) or superpowers:executing-plans to implement this plan.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Revise ObstacleConfig defaults to match physical sensor capability,
add DANGER exit debouncing, and improve operator-facing prompts with imperial
measurements.

**Architecture:** All changes are in the tello-mcp obstacle subsystem
(`obstacle.py`, its tests, and two scripts). The debounce state machine lives
in `ObstacleMonitor._poll_loop` — `classify_zone()` stays a pure function.
No new files are created.

**Tech Stack:** Python 3.13, pytest-asyncio, structlog, dataclasses

**Spec:** `docs/superpowers/specs/2026-03-17-forward-tof-threshold-fix-design.md`

---

## Chunk 0: Housekeeping — Untracked File Cleanup

### Task 0: Update .gitignore and commit untracked project files

**Files:**
- Modify: `.gitignore`
- Add: `.claude/settings.json`, `.mcp.json`, `.claude/hooks/require-issue-and-branch.sh`
- Add: `docs/superpowers/plans/*.md` (3 historical plans)
- Add: `docs/superpowers/specs/*.md` (2 historical specs + this phase's spec)
- Add: `docs/superpowers/research/*.md` (1 research doc)
- Add: `testing/2026-03-13-phase3-physical-test-plan.md`
- Add: `testing/phase4-tof-results-2026-03-17.json`
- Add: `services/tello-vision/src/tello_vision/__init__.py`
- Add: `services/tello-voice/src/tello_voice/__init__.py`

- [ ] **Step 1: Add exclusions to .gitignore**

Append these lines to `.gitignore`:

```
# Vendor PDFs (large binary files)
docs/tello-drone-docs/*.pdf

# Generated test artifacts
testing/*.pdf
testing/*.html
testing/*.jpeg

# Machine-specific hookify configs
.claude/hookify.*.local.md
```

- [ ] **Step 2: Stage all tracked files**

```bash
git add .gitignore \
  .claude/settings.json \
  .mcp.json \
  .claude/hooks/require-issue-and-branch.sh \
  docs/superpowers/plans/ \
  docs/superpowers/specs/ \
  docs/superpowers/research/ \
  testing/2026-03-13-phase3-physical-test-plan.md \
  testing/phase4-tof-results-2026-03-17.json \
  services/tello-vision/src/tello_vision/__init__.py \
  services/tello-voice/src/tello_voice/__init__.py
```

- [ ] **Step 3: Verify only intended files are staged**

```bash
git status
```

Expected: Only the files listed above are staged. No PDFs, no HTMLs,
no `.claude/hookify.*.local.md` files.

- [ ] **Step 4: Commit housekeeping**

```bash
git commit -m "chore: track untracked project files and update .gitignore

- Add .gitignore exclusions for vendor PDFs, generated test artifacts,
  and machine-specific hookify configs
- Track historical plans, specs, research docs, and test artifacts
- Add placeholder __init__.py for tello-vision and tello-voice services
- Track .claude/settings.json, .mcp.json, and hooks"
```

## Chunk 1: ObstacleConfig + classify_zone + Unit Tests

### Task 1: Update ObstacleConfig defaults and field rename

**Files:**
- Modify: `services/tello-mcp/src/tello_mcp/obstacle.py:30-60`
- Test: `services/tello-mcp/tests/test_obstacle.py`

- [ ] **Step 1: Update test assertions for new defaults**

In `test_obstacle.py`, update `TestObstacleConfig.test_default_values`:

```python
def test_default_values(self):
    config = ObstacleConfig()
    assert config.caution_mm == 500
    assert config.warning_mm == 300
    assert config.danger_mm == 200
    assert config.out_of_range_min == 8000
    assert config.required_clear_readings == 3
    assert config.poll_interval_ms == 200
```

Update `test_from_env_no_vars`:

```python
def test_from_env_no_vars(self):
    config = ObstacleConfig.from_env()
    assert config.danger_mm == 200  # default
```

Update `test_from_env` — change `caution_mm == 1500` assertion to `500`:

```python
def test_from_env(self, monkeypatch):
    monkeypatch.setenv("OBSTACLE_DANGER_MM", "500")
    monkeypatch.setenv("OBSTACLE_POLL_INTERVAL_MS", "100")
    config = ObstacleConfig.from_env()
    assert config.danger_mm == 500
    assert config.poll_interval_ms == 100
    assert config.caution_mm == 500  # default
```

Update `test_custom_values` — change `caution_mm == 1500` assertion to `500`:

```python
def test_custom_values(self):
    config = ObstacleConfig(danger_mm=500, poll_interval_ms=100)
    assert config.danger_mm == 500
    assert config.poll_interval_ms == 100
    assert config.caution_mm == 500  # unchanged default
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestObstacleConfig -v`

Expected: FAIL — old defaults don't match new assertions.

- [ ] **Step 3: Update ObstacleConfig in obstacle.py**

Replace the dataclass fields and docstring:

```python
@dataclass(frozen=True, slots=True)
class ObstacleConfig:
    """Configuration for obstacle detection thresholds.

    Overridable via environment variables:
        OBSTACLE_CAUTION_MM, OBSTACLE_WARNING_MM, OBSTACLE_DANGER_MM,
        OBSTACLE_OUT_OF_RANGE_MIN, OBSTACLE_REQUIRED_CLEAR_READINGS,
        OBSTACLE_POLL_INTERVAL_MS
    """

    caution_mm: int = 500
    warning_mm: int = 300
    danger_mm: int = 200
    out_of_range_min: int = 8000
    required_clear_readings: int = 3
    poll_interval_ms: int = 200

    @classmethod
    def from_env(cls) -> ObstacleConfig:
        """Load config from environment, falling back to defaults."""
        env_map = {
            "caution_mm": "OBSTACLE_CAUTION_MM",
            "warning_mm": "OBSTACLE_WARNING_MM",
            "danger_mm": "OBSTACLE_DANGER_MM",
            "out_of_range_min": "OBSTACLE_OUT_OF_RANGE_MIN",
            "required_clear_readings": "OBSTACLE_REQUIRED_CLEAR_READINGS",
            "poll_interval_ms": "OBSTACLE_POLL_INTERVAL_MS",
        }
        kwargs: dict[str, int] = {}
        for field, env_var in env_map.items():
            val = os.environ.get(env_var)
            if val is not None:
                kwargs[field] = int(val)
        return cls(**kwargs)
```

- [ ] **Step 4: Update classify_zone to use out_of_range_min with >=**

In `ObstacleMonitor.classify_zone`, change line 84:

```python
# Before:
if distance_mm >= self._config.out_of_range:
# After:
if distance_mm >= self._config.out_of_range_min:
```

- [ ] **Step 5: Run ObstacleConfig tests — verify they pass**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestObstacleConfig -v`

Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/obstacle.py services/tello-mcp/tests/test_obstacle.py
git commit -m "feat(obstacle): revise config defaults to match sensor capability

CAUTION=500mm, WARNING=300mm, DANGER=200mm based on physical testing.
Rename out_of_range to out_of_range_min (>=8000) for firmware resilience.
Add required_clear_readings field for debounce config."
```

### Task 2: Update classify_zone tests for new boundaries

**Files:**
- Modify: `services/tello-mcp/tests/test_obstacle.py:54-93`

- [ ] **Step 1: Update TestClassifyZone assertions**

```python
class TestClassifyZone:
    """Tests for the pure zone classification function."""

    def setup_method(self):
        self.config = ObstacleConfig()
        self.monitor = ObstacleMonitor(MagicMock(), self.config)

    def test_out_of_range_is_clear(self):
        assert self.monitor.classify_zone(8000) == ObstacleZone.CLEAR

    def test_well_above_out_of_range_is_clear(self):
        assert self.monitor.classify_zone(8190) == ObstacleZone.CLEAR

    def test_above_caution_is_clear(self):
        assert self.monitor.classify_zone(600) == ObstacleZone.CLEAR

    def test_at_caution_boundary_is_clear(self):
        assert self.monitor.classify_zone(500) == ObstacleZone.CLEAR

    def test_below_caution_is_caution(self):
        assert self.monitor.classify_zone(499) == ObstacleZone.CAUTION

    def test_at_warning_boundary_is_caution(self):
        assert self.monitor.classify_zone(300) == ObstacleZone.CAUTION

    def test_below_warning_is_warning(self):
        assert self.monitor.classify_zone(299) == ObstacleZone.WARNING

    def test_at_danger_boundary_is_warning(self):
        assert self.monitor.classify_zone(200) == ObstacleZone.WARNING

    def test_below_danger_is_danger(self):
        assert self.monitor.classify_zone(199) == ObstacleZone.DANGER

    def test_zero_is_danger(self):
        assert self.monitor.classify_zone(0) == ObstacleZone.DANGER

    def test_custom_thresholds(self):
        config = ObstacleConfig(caution_mm=1000, warning_mm=500, danger_mm=200)
        monitor = ObstacleMonitor(MagicMock(), config)
        assert monitor.classify_zone(999) == ObstacleZone.CAUTION
        assert monitor.classify_zone(499) == ObstacleZone.WARNING
        assert monitor.classify_zone(199) == ObstacleZone.DANGER
```

- [ ] **Step 2: Run classify_zone tests**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestClassifyZone -v`

Expected: All PASS.

- [ ] **Step 3: Update lifecycle test fixture values**

In `TestObstacleMonitorLifecycle.test_start_is_idempotent` (line 99),
change `distance_mm": 8192` to `distance_mm": 8000`:

```python
drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 8000}
```

- [ ] **Step 4: Run lifecycle tests**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestObstacleMonitorLifecycle -v`

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add services/tello-mcp/tests/test_obstacle.py
git commit -m "test(obstacle): update zone classification tests for new thresholds"
```

### Task 3: Update polling tests for new thresholds

**Files:**
- Modify: `services/tello-mcp/tests/test_obstacle.py:113-187`

- [ ] **Step 1: Update TestObstacleMonitorPolling assertions**

`test_poll_caches_latest_reading` (line 116): Change `distance_mm": 1200`
to a value in CAUTION range with new thresholds. 400 is between 300
(warning) and 500 (caution), so it's CAUTION:

```python
async def test_poll_caches_latest_reading(self):
    drone = MagicMock()
    drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 400}
    config = ObstacleConfig(poll_interval_ms=50)
    monitor = ObstacleMonitor(drone, config)
    await monitor.start()
    await asyncio.sleep(0.15)  # allow a few polls
    await monitor.stop()
    assert monitor.latest is not None
    assert monitor.latest.distance_mm == 400
    assert monitor.latest.zone == ObstacleZone.CAUTION
```

`test_danger_zone_calls_stop` (line 128): 200 is at WARNING boundary
(not danger) with new thresholds. Use 150 instead:

```python
async def test_danger_zone_calls_stop(self):
    drone = MagicMock()
    drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 150}
    drone.stop = MagicMock(return_value={"status": "ok"})
    config = ObstacleConfig(poll_interval_ms=50)
    monitor = ObstacleMonitor(drone, config)
    await monitor.start()
    await asyncio.sleep(0.15)
    await monitor.stop()
    drone.stop.assert_called()
```

`test_clear_zone_does_not_call_stop` (line 139): Change `8192` to `8000`:

```python
async def test_clear_zone_does_not_call_stop(self):
    drone = MagicMock()
    drone.get_forward_distance.return_value = {"status": "ok", "distance_mm": 8000}
    drone.stop = MagicMock()
    config = ObstacleConfig(poll_interval_ms=50)
    monitor = ObstacleMonitor(drone, config)
    await monitor.start()
    await asyncio.sleep(0.15)
    await monitor.stop()
    drone.stop.assert_not_called()
```

- [ ] **Step 2: Run polling tests**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestObstacleMonitorPolling -v`

Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add services/tello-mcp/tests/test_obstacle.py
git commit -m "test(obstacle): update polling tests for revised thresholds"
```

## Chunk 2: Debounce Logic + Tests

### Task 4: Write debounce tests

**Files:**
- Modify: `services/tello-mcp/tests/test_obstacle.py`

- [ ] **Step 1: Add TestObstacleMonitorDebounce class**

Add after `TestObstacleMonitorPolling`:

```python
class TestObstacleMonitorDebounce:
    """Tests for DANGER exit debouncing in the poll loop."""

    def _make_monitor(self, readings: list[int], poll_ms: int = 50) -> tuple:
        """Create a monitor with a sequence of mocked readings."""
        drone = MagicMock()
        drone.get_forward_distance.side_effect = [
            {"status": "ok", "distance_mm": mm} for mm in readings
        ]
        drone.stop = MagicMock(return_value={"status": "ok"})
        config = ObstacleConfig(
            poll_interval_ms=poll_ms,
            required_clear_readings=3,
        )
        monitor = ObstacleMonitor(drone, config)
        return monitor, drone

    async def test_danger_entry_is_immediate(self):
        """Single DANGER reading triggers drone.stop() with no delay."""
        monitor, drone = self._make_monitor([150])
        await monitor.start()
        await asyncio.sleep(0.1)
        await monitor.stop()
        drone.stop.assert_called()
        assert monitor.latest.zone == ObstacleZone.DANGER

    async def test_danger_exit_requires_consecutive_clear(self):
        """3 consecutive non-DANGER readings needed to exit DANGER."""
        # DANGER, then 2 clear (not enough), then 1 DANGER (reset),
        # then 3 clear (enough to exit)
        readings = [150, 600, 600, 150, 600, 600, 600]
        monitor, drone = self._make_monitor(readings)
        collected: list[ObstacleReading] = []
        monitor.on_reading(collected.append)
        await monitor.start()
        await asyncio.sleep(0.5)
        await monitor.stop()
        # Verify the reported zones include debounced DANGER holdovers
        zones = [r.zone for r in collected]
        # First reading: DANGER (immediate entry)
        assert zones[0] == ObstacleZone.DANGER
        # Readings 2-3: still DANGER (debouncing, only 2 clear)
        assert zones[1] == ObstacleZone.DANGER
        assert zones[2] == ObstacleZone.DANGER
        # Reading 4: DANGER (actual DANGER reading, counter reset)
        assert zones[3] == ObstacleZone.DANGER
        # Readings 5-6: still DANGER (debouncing, only 2 clear)
        assert zones[4] == ObstacleZone.DANGER
        assert zones[5] == ObstacleZone.DANGER
        # Reading 7: CLEAR (3 consecutive clear reached)
        assert zones[6] == ObstacleZone.CLEAR

    async def test_debounce_does_not_apply_to_non_danger(self):
        """CAUTION/WARNING/CLEAR transitions are instant, no debounce."""
        readings = [400, 250, 400]  # CAUTION -> WARNING -> CAUTION
        monitor, _drone = self._make_monitor(readings)
        collected: list[ObstacleReading] = []
        monitor.on_reading(collected.append)
        await monitor.start()
        await asyncio.sleep(0.25)
        await monitor.stop()
        zones = [r.zone for r in collected]
        assert zones[0] == ObstacleZone.CAUTION
        assert zones[1] == ObstacleZone.WARNING
        assert zones[2] == ObstacleZone.CAUTION

    async def test_single_danger_during_debounce_resets_counter(self):
        """A DANGER reading mid-debounce resets the clear counter."""
        # DANGER, 2 clear, 1 DANGER (reset), 1 clear — still in DANGER
        readings = [150, 600, 600, 150, 600]
        monitor, _drone = self._make_monitor(readings)
        collected: list[ObstacleReading] = []
        monitor.on_reading(collected.append)
        await monitor.start()
        await asyncio.sleep(0.35)
        await monitor.stop()
        zones = [r.zone for r in collected]
        # All should report DANGER — never reached 3 consecutive clear
        assert all(z == ObstacleZone.DANGER for z in zones)
```

- [ ] **Step 2: Run debounce tests — verify they fail**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestObstacleMonitorDebounce -v`

Expected: FAIL — debounce logic not yet implemented.

- [ ] **Step 3: Commit failing tests**

```bash
git add services/tello-mcp/tests/test_obstacle.py
git commit -m "test(obstacle): add DANGER exit debounce tests (red)"
```

### Task 5: Implement debounce logic in ObstacleMonitor

**Files:**
- Modify: `services/tello-mcp/src/tello_mcp/obstacle.py:63-154`

- [ ] **Step 1: Add debounce state to __init__**

In `ObstacleMonitor.__init__`, add after `self._callbacks`:

```python
self._in_danger = False
self._danger_clear_count = 0
```

- [ ] **Step 2: Replace _poll_loop with debounced version**

Replace the `_poll_loop` method:

```python
async def _poll_loop(self) -> None:
    """Background task: poll forward ToF and enforce safety zones."""
    while self._running:
        result = await asyncio.to_thread(self._drone.get_forward_distance)
        if result.get("status") == "ok":
            distance_mm = result["distance_mm"]
            raw_zone = self.classify_zone(distance_mm)

            # Debounce DANGER exit
            if self._in_danger:
                if raw_zone != ObstacleZone.DANGER:
                    self._danger_clear_count += 1
                    if self._danger_clear_count >= self._config.required_clear_readings:
                        self._in_danger = False
                        reported_zone = raw_zone
                    else:
                        reported_zone = ObstacleZone.DANGER
                else:
                    self._danger_clear_count = 0
                    reported_zone = ObstacleZone.DANGER
            else:
                if raw_zone == ObstacleZone.DANGER:
                    self._in_danger = True
                    self._danger_clear_count = 0
                    logger.warning("obstacle.danger", distance_mm=distance_mm)
                    await asyncio.to_thread(self._drone.stop)
                    reported_zone = ObstacleZone.DANGER
                else:
                    reported_zone = raw_zone

            reading = ObstacleReading(
                distance_mm=distance_mm,
                zone=reported_zone,
                timestamp=datetime.now(UTC),
            )
            self._latest = reading

            for cb in self._callbacks:
                cb_result = cb(reading)
                if asyncio.iscoroutine(cb_result):
                    await cb_result

        await asyncio.sleep(self._config.poll_interval_ms / 1000)
```

- [ ] **Step 3: Run debounce tests — verify they pass**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py::TestObstacleMonitorDebounce -v`

Expected: All PASS.

- [ ] **Step 4: Run ALL obstacle tests**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_obstacle.py -v`

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/obstacle.py
git commit -m "feat(obstacle): add DANGER exit debouncing

Require 3 consecutive non-DANGER readings before exiting DANGER state.
DANGER entry remains immediate (drone.stop() on first reading).
Only DANGER transitions are debounced — other zones transition instantly."
```

## Chunk 3: Cross-Service Test Fixes + Docstrings

### Task 6: Update test_drone.py fixtures

**Files:**
- Modify: `services/tello-mcp/tests/test_drone.py:233-240`

- [ ] **Step 1: Update out-of-range test fixture**

Change `test_get_forward_distance_out_of_range`:

```python
def test_get_forward_distance_out_of_range(self, mock_drone):
    mock_drone.send_read_command.return_value = "tof 8190"
    with patch("tello_mcp.drone.Tello", return_value=mock_drone):
        adapter = DroneAdapter()
        adapter.connect()
        result = adapter.get_forward_distance()
        assert result["status"] == "ok"
        assert result["distance_mm"] == 8190
```

- [ ] **Step 2: Run test_drone.py**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/test_drone.py -v`

Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add services/tello-mcp/tests/test_drone.py
git commit -m "test(drone): update ToF out-of-range fixture to 8190"
```

### Task 7: Update test_models.py fixtures

**Files:**
- Modify: `packages/tello-core/tests/test_models.py:120-122`

- [ ] **Step 1: Update forward_tof_mm test value**

Change the test at line 120:

```python
forward_tof_mm=8190,
```

And the assertion at line 122:

```python
assert frame.forward_tof_mm == 8190
```

- [ ] **Step 2: Run test_models.py**

Run: `uv run --package tello-core pytest packages/tello-core/tests/test_models.py -v`

Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add packages/tello-core/tests/test_models.py
git commit -m "test(core): update forward_tof_mm fixture to 8190"
```

### Task 8: Update docstrings in drone.py and sensors.py

**Files:**
- Modify: `services/tello-mcp/src/tello_mcp/drone.py:265`
- Modify: `services/tello-mcp/src/tello_mcp/tools/sensors.py:49-68`

- [ ] **Step 1: Update drone.py docstring**

Change line 265:

```python
# Before:
Returns distance in mm, or 8192 if out of range.
# After:
Returns distance in mm. Readings >=8000 indicate out of range.
```

- [ ] **Step 2: Update sensors.py get_forward_distance docstring**

Change lines 49-52:

```python
async def get_forward_distance(ctx: Context) -> dict:
    """Get forward-facing ToF distance in mm (Dot-Matrix Module sensor).

    Returns distance to nearest obstacle ahead. >=8000 means out of range.
    Includes obstacle zone classification (CLEAR/CAUTION/WARNING/DANGER).
    """
```

- [ ] **Step 3: Update sensors.py get_obstacle_status docstring**

Change lines 64-68:

```python
async def get_obstacle_status(ctx: Context) -> dict:
    """Check if the path ahead is clear. Returns zone and distance.

    Zones: CLEAR (safe), CAUTION (<500mm/~20in), WARNING (<300mm/~12in),
    DANGER (<200mm/~8in). In DANGER zone, the drone has already been stopped.
    """
```

- [ ] **Step 4: Run full tello-mcp test suite**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/ -v`

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/drone.py services/tello-mcp/src/tello_mcp/tools/sensors.py
git commit -m "docs(mcp): update ToF docstrings for new thresholds and out-of-range"
```

## Chunk 4: Operator-Facing Scripts

### Task 9: Add imperial helper and update fly.py

**Files:**
- Modify: `scripts/fly.py:132-165`

- [ ] **Step 1: Add mm_to_imperial helper**

Add after the `COMMAND_DELAY` constant (line 48):

```python
def mm_to_imperial(mm: int) -> str:
    """Convert mm to approximate imperial string for operator display."""
    inches = mm / 25.4
    if inches >= 36:
        return f"~{inches / 12:.1f}ft"
    return f"~{inches:.1f}in"
```

- [ ] **Step 2: Update tof command output**

Change the `tof` case (line 139):

```python
# Before:
print(f"Forward ToF: {mm}mm ({zone.value.upper()})")
# After:
print(f"Forward ToF: {mm}mm ({mm_to_imperial(mm)}) ({zone.value.upper()})")
```

- [ ] **Step 3: Update monitor command output**

Replace the `monitor` case (lines 155-165):

```python
case "monitor":
    config = ObstacleConfig.from_env()
    print("Obstacle monitor config:")
    print(
        f"  Thresholds: CAUTION <{config.caution_mm}mm"
        f" ({mm_to_imperial(config.caution_mm)}),"
        f" WARNING <{config.warning_mm}mm"
        f" ({mm_to_imperial(config.warning_mm)}),"
        f" DANGER <{config.danger_mm}mm"
        f" ({mm_to_imperial(config.danger_mm)})"
    )
    print(f"  Out of range: >={config.out_of_range_min}mm")
    print(f"  Poll interval: {config.poll_interval_ms}ms")
    print(f"  Debounce: {config.required_clear_readings} clear readings to exit DANGER")
    print("  Note: Continuous monitoring runs inside the MCP server.")
    print("  Use 'tof' for a one-shot forward distance reading.")
```

- [ ] **Step 4: Verify fly.py has no syntax errors**

Run: `uv run python -c "import scripts.fly" 2>&1 || uv run python -m py_compile scripts/fly.py`

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add scripts/fly.py
git commit -m "feat(fly): add imperial measurements to ToF and monitor output"
```

### Task 10: Update test_tof.py — constants, prompts, and Test 6 fix

**Files:**
- Modify: `scripts/test_tof.py`

- [ ] **Step 1: Update constants and add imperial helper**

At top of file, change line 32 and add helper:

```python
# Before:
OUT_OF_RANGE = 8192

# After:
OUT_OF_RANGE_MIN = 8000


def mm_to_imperial(mm: int) -> str:
    """Convert mm to approximate imperial string for operator display."""
    inches = mm / 25.4
    if inches >= 36:
        return f"~{inches / 12:.1f}ft"
    return f"~{inches:.1f}in"
```

- [ ] **Step 2: Update Test 1 output with imperial**

In `run_test_1`, change the print line:

```python
# Before:
print(f"  Reading: {mm}mm ({zone.value.upper()})")
# After:
print(f"  Reading: {mm}mm ({mm_to_imperial(mm)}) ({zone.value.upper()})")
```

- [ ] **Step 3: Update Test 2 — OUT_OF_RANGE filter and imperial output**

In `run_test_2`, change the filter (line 98) and print (line 89):

```python
# Filter — line 98:
if r["distance_mm"] is not None and r["distance_mm"] < OUT_OF_RANGE_MIN

# Print — line 89:
print(f"  [{i + 1:2d}/20] {mm}mm ({mm_to_imperial(mm)}) ({zone.value.upper()})")
```

- [ ] **Step 4: Update Test 3 — docstring, prompt, thresholds**

Replace `run_test_3`:

```python
def run_test_3(drone: DroneAdapter, monitor: ObstacleMonitor) -> dict:
    """Test 3: Close Object — verify DANGER zone at <200mm (~8in)."""
    print("\n" + "─" * 60)
    print("TEST 3: Close Object Detection")
    print("─" * 60)
    prompt("Hold your hand less than 200mm (~8in) from the sensor.")

    result = read_distance(drone)
    if result.get("status") != "ok":
        print(f"  FAIL — sensor error: {result}")
        return {
            "name": "close_object",
            "status": "fail",
            "reading": None,
            "notes": str(result),
        }

    mm = result["distance_mm"]
    zone = monitor.classify_zone(mm)
    print(f"  Reading: {mm}mm ({mm_to_imperial(mm)}) ({zone.value.upper()})")

    if zone.value == "danger":
        status = "pass"
        notes = ""
    elif zone.value == "warning":
        status = "pass"
        notes = "Marginal — WARNING zone, not DANGER. Hand may be >200mm (~8in)."
    else:
        status = "fail"
        notes = f"Expected DANGER (<200mm/~8in), got {zone.value} ({mm}mm)"

    print(f"  {status.upper()}" + (f" ({notes})" if notes else ""))
    return {
        "name": "close_object",
        "status": status,
        "reading": {"distance_mm": mm, "zone": zone.value},
        "notes": notes,
    }
```

- [ ] **Step 5: Update Test 4 — OUT_OF_RANGE filter and imperial prompt**

In `run_test_4`:

Change prompt (line 163):

```python
prompt("Point drone at a wall or flat surface ~1m (~3.3ft) away. Keep still.")
```

Change filter (line 179):

```python
if r["distance_mm"] is not None and r["distance_mm"] < OUT_OF_RANGE_MIN
```

- [ ] **Step 6: Update Test 6 — prompts, thresholds, takeoff fix**

Replace `run_test_6` entirely:

```python
def run_test_6(
    drone: DroneAdapter,
    monitor: ObstacleMonitor,
    config: ObstacleConfig,
    battery: int | None,
    tello,
) -> dict:
    """Test 6: Flight DANGER Stop — full safety pipeline."""
    print("\n" + "─" * 60)
    print("TEST 6: Flight DANGER Stop (OPTIONAL)")
    print("─" * 60)

    # Battery gate
    if battery is not None and battery < 30:
        print(f"  WARNING: Battery is {battery}% (< 30%)")
        resp = input("  Continue anyway? (y/n): ").strip().lower()
        if resp != "y":
            print("  SKIPPED (low battery)")
            return {
                "name": "flight_danger_stop",
                "status": "skipped",
                "notes": f"Low battery ({battery}%)",
            }

    resp = (
        input(
            "\n  FLIGHT TEST. Place drone on flat surface "
            "facing a wall (~2m / ~6.5ft away).\n"
            "  Ready to fly? (y/n): "
        )
        .strip()
        .lower()
    )
    if resp != "y":
        print("  SKIPPED (user declined)")
        return {
            "name": "flight_danger_stop",
            "status": "skipped",
            "notes": "User declined",
        }

    # Pre-flight distance gate
    pre = read_distance(drone)
    if pre.get("status") != "ok":
        print(f"  ABORT — cannot read sensor: {pre}")
        return {
            "name": "flight_danger_stop",
            "status": "fail",
            "notes": f"Pre-flight sensor error: {pre}",
        }

    pre_mm = pre["distance_mm"]
    if pre_mm < 500 and pre_mm < OUT_OF_RANGE_MIN:
        print(
            f"  ABORT — too close to wall ({pre_mm}mm / "
            f"{mm_to_imperial(pre_mm)} < 500mm / ~20in). "
            f"Move drone back and retry."
        )
        return {
            "name": "flight_danger_stop",
            "status": "fail",
            "pre_flight_distance_mm": pre_mm,
            "notes": "Too close to wall",
        }

    distance_checks = [
        {
            "phase": "pre_flight",
            "distance_mm": pre_mm,
            "zone": monitor.classify_zone(pre_mm).value,
        },
    ]

    # Takeoff with race condition detection
    print("  Taking off...")
    takeoff_result = drone.takeoff()
    takeoff_succeeded = False
    height_after_takeoff = None
    takeoff_race_condition = False

    if takeoff_result.get("status") == "ok":
        takeoff_succeeded = True
    else:
        # Takeoff reported failure — check if drone is actually airborne
        # (djitellopy retry race condition: drone took off but retries
        # sent 'takeoff' to an airborne drone, getting 'error' back)
        try:
            height_after_takeoff = tello.get_height()
            if height_after_takeoff > 0:
                print(
                    f"  NOTE: takeoff() returned error but drone is "
                    f"airborne (height={height_after_takeoff}cm)"
                )
                print("  Known djitellopy retry race condition — continuing test")
                takeoff_succeeded = True
                takeoff_race_condition = True
            else:
                print(f"  FAIL — takeoff genuinely failed: {takeoff_result}")
        except Exception:
            print(f"  FAIL — takeoff failed and height check unavailable: {takeoff_result}")

    if not takeoff_succeeded:
        return {
            "name": "flight_danger_stop",
            "status": "fail",
            "takeoff_raw_result": takeoff_result,
            "height_after_takeoff_cm": height_after_takeoff,
            "battery_at_takeoff": battery,
            "takeoff_race_condition_detected": False,
            "notes": f"Takeoff failed: {takeoff_result}",
        }

    print(f"  Stabilizing ({TAKEOFF_DELAY}s)...")
    time.sleep(TAKEOFF_DELAY)

    danger_triggered = False
    chosen_response = None
    action_result = None

    try:
        prompt("Drone is hovering. It will fly forward 100cm (~3.3ft).")

        # Check before move
        r = read_distance(drone)
        if r.get("status") == "ok":
            mm = r["distance_mm"]
            zone = monitor.classify_zone(mm)
            distance_checks.append({"phase": "pre_move", "distance_mm": mm, "zone": zone.value})
            print(f"  Pre-move: {mm}mm ({mm_to_imperial(mm)}) ({zone.value.upper()})")

        # Move 100cm forward
        print("  Moving forward 100cm (~3.3ft)...")
        drone.move("forward", 100)
        time.sleep(COMMAND_DELAY)

        # Check after first move
        r = read_distance(drone)
        if r.get("status") == "ok":
            mm = r["distance_mm"]
            zone = monitor.classify_zone(mm)
            distance_checks.append({"phase": "after_100cm", "distance_mm": mm, "zone": zone.value})
            print(f"  After 100cm: {mm}mm ({mm_to_imperial(mm)}) ({zone.value.upper()})")

            if zone.value == "danger":
                danger_triggered = True
            else:
                # Move another 50cm
                print("  Not DANGER yet. Moving forward 50cm (~20in)...")
                drone.move("forward", 50)
                time.sleep(COMMAND_DELAY)

                r = read_distance(drone)
                if r.get("status") == "ok":
                    mm = r["distance_mm"]
                    zone = monitor.classify_zone(mm)
                    distance_checks.append(
                        {
                            "phase": "after_150cm",
                            "distance_mm": mm,
                            "zone": zone.value,
                        }
                    )
                    print(
                        f"  After 150cm: {mm}mm ({mm_to_imperial(mm)}) "
                        f"({zone.value.upper()})"
                    )
                    if zone.value == "danger":
                        danger_triggered = True

        if danger_triggered:
            print("\n  DANGER DETECTED — presenting options menu")
            last_check = distance_checks[-1]
            reading = ObstacleReading(
                distance_mm=last_check["distance_mm"],
                zone=monitor.classify_zone(last_check["distance_mm"]),
                timestamp=datetime.now(UTC),
            )
            provider = CLIResponseProvider()
            choice = asyncio.run(provider.present_options(reading))
            chosen_response = choice.value
            handler = ObstacleResponseHandler(drone)
            action_result = asyncio.run(handler.execute(choice))
            print(f"  Action result: {action_result}")
        else:
            print("\n  No DANGER triggered after 150cm (~5ft). Landing safely.")
            drone.safe_land()

    except Exception as e:
        print(f"\n  ERROR during flight: {e}")
        print("  Emergency landing...")
        drone.safe_land()
        return {
            "name": "flight_danger_stop",
            "status": "fail",
            "distance_checks": distance_checks,
            "takeoff_raw_result": takeoff_result,
            "height_after_takeoff_cm": height_after_takeoff,
            "battery_at_takeoff": battery,
            "takeoff_race_condition_detected": takeoff_race_condition,
            "notes": f"Flight error: {e}",
        }

    status = "pass" if danger_triggered else "needs_adjustment"
    notes = "" if danger_triggered else "DANGER never triggered — thresholds may need tuning"
    print(f"\n  {status.upper()}" + (f" ({notes})" if notes else ""))

    return {
        "name": "flight_danger_stop",
        "status": status,
        "pre_flight_distance_mm": pre_mm,
        "distance_checks": distance_checks,
        "danger_triggered": danger_triggered,
        "chosen_response": chosen_response,
        "action_result": action_result,
        "takeoff_raw_result": takeoff_result,
        "height_after_takeoff_cm": height_after_takeoff,
        "battery_at_takeoff": battery,
        "takeoff_race_condition_detected": takeoff_race_condition,
        "notes": notes,
    }
```

- [ ] **Step 7: Update save_results output filename and config key**

In `save_results` (line 467):

```python
# Before:
path = testing_dir / f"phase4-tof-results-{date_str}.json"
# After:
path = testing_dir / f"forward-tof-threshold-results-{date_str}.json"
```

In `main`, update the obstacle_config output dict (line 615):

```python
"obstacle_config": {
    "caution_mm": config.caution_mm,
    "warning_mm": config.warning_mm,
    "danger_mm": config.danger_mm,
    "out_of_range_min": config.out_of_range_min,
    "required_clear_readings": config.required_clear_readings,
    "poll_interval_ms": config.poll_interval_ms,
},
```

- [ ] **Step 8: Update main() — OUT_OF_RANGE_MIN filters and Test 6 call**

In `main()`, update all `OUT_OF_RANGE` references to `OUT_OF_RANGE_MIN`
with `<` comparisons instead of `!=`:

Line 536 (threshold display):

```python
print(
    f"Thresholds: CAUTION <{config.caution_mm}mm ({mm_to_imperial(config.caution_mm)}), "
    f"WARNING <{config.warning_mm}mm ({mm_to_imperial(config.warning_mm)}), "
    f"DANGER <{config.danger_mm}mm ({mm_to_imperial(config.danger_mm)})"
)
```

Line 572 (Test 2 filter):

```python
if r["distance_mm"] is not None and r["distance_mm"] < OUT_OF_RANGE_MIN:
```

Line 583 (Test 4 filter):

```python
if r["distance_mm"] is not None and r["distance_mm"] < OUT_OF_RANGE_MIN:
```

Line 589 (Test 6 call — pass `tello` for height check):

```python
t6 = run_test_6(drone, monitor, config, battery_start, drone._tello)
```

Line 592 (Test 6 distance filter):

```python
if check["distance_mm"] is not None and check["distance_mm"] < OUT_OF_RANGE_MIN:
```

In `build_characterization` (line 436):

```python
valid = [r for r in all_readings if r < OUT_OF_RANGE_MIN]
```

Update the title in main (line 515):

```python
print("  Forward ToF Sensor — Threshold Verification Test Suite")
```

Update the description in argparse (line 505):

```python
description="Forward ToF threshold verification test script",
```

- [ ] **Step 9: Verify test_tof.py has no syntax errors**

Run: `uv run python -m py_compile scripts/test_tof.py`

Expected: No errors.

- [ ] **Step 10: Commit**

```bash
git add scripts/test_tof.py
git commit -m "feat(test_tof): update thresholds, add imperial, fix Test 6 takeoff

- OUT_OF_RANGE_MIN=8000 with >= comparisons
- Imperial measurements in all operator prompts
- Test 6: detect djitellopy takeoff retry race condition via height check
- Enhanced failure diagnostics in results JSON
- Results filename: forward-tof-threshold-results-*.json"
```

## Chunk 5: Full Verification + Lint

### Task 11: Run full test suite and lint

**Files:** None (verification only)

- [ ] **Step 1: Run all tello-core tests**

Run: `uv run --package tello-core pytest packages/tello-core/tests/ -v`

Expected: All PASS.

- [ ] **Step 2: Run all tello-mcp tests**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/ -v`

Expected: All PASS.

- [ ] **Step 3: Run all tello-navigator tests**

Run: `uv run --package tello-navigator pytest services/tello-navigator/tests/ -v`

Expected: All PASS.

- [ ] **Step 4: Run all tello-telemetry tests**

Run: `uv run --package tello-telemetry pytest services/tello-telemetry/tests/ -v`

Expected: All PASS.

- [ ] **Step 5: Run lint and format check**

Run: `uv run ruff check . && uv run ruff format --check .`

Expected: No errors. If lint errors are found, fix and re-run.

- [ ] **Step 6: Commit any lint fixes**

Only if Step 5 required fixes:

```bash
git add -u
git commit -m "style: fix lint issues from threshold update"
```
