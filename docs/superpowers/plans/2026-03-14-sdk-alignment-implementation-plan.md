# SDK Alignment Implementation Plan (Phase 3a + 3b)

> **For agentic workers:** REQUIRED: Use
> superpowers:subagent-driven-development (if subagents
> available) or superpowers:executing-plans to implement
> this plan. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Fix tello-mcp SDK regressions, add mission pad
enablement and pad-relative navigation, complete
tello-navigator goto_pad waypoint action.

**Architecture:** Two-phase delivery. Phase 3a fixes the
tello-mcp hardware layer (DroneAdapter bugs, keepalive,
mission pad enablement, go_xyz_speed_mid). Phase 3b
updates tello-navigator to use the new pad navigation
tool in its advisory command mapping.

**Tech Stack:** Python 3.13, FastMCP 3.x, djitellopy,
Neo4j (sync driver), Redis (async), Pydantic, structlog,
pytest-asyncio.

**Spec:**
`docs/superpowers/specs/2026-03-14-sdk-alignment-design.md`

---

## Chunk 1: Phase 3a — tello-mcp SDK Alignment

### Task 1: Fix DroneAdapter set_led and display methods

Per spec Sections 3.1.1 and 3.1.2. Fix the two critical
runtime bugs and replace display_text with three focused
methods.

**Files:**

- Modify: `services/tello-mcp/src/tello_mcp/drone.py`
- Modify: `services/tello-mcp/tests/test_drone.py`

- [ ] **Step 1: Write failing tests** — replace
  `test_set_led` assertion from
  `mock_drone.set_led.assert_called_once_with(r=255, g=0, b=0)`
  to
  `mock_drone.send_expansion_command.assert_called_once_with("led 255 0 0")`.
  Remove `test_display_text` and
  `test_display_text_when_not_connected`. Add three new
  test methods:

  ```python
  def test_display_scroll_text(self, mock_drone):
      with patch("tello_mcp.drone.Tello", return_value=mock_drone):
          adapter = DroneAdapter()
          adapter.connect()
          result = adapter.display_scroll_text("hello")
          mock_drone.send_expansion_command.assert_called_once_with(
              "mled l r 0.5 hello"
          )
          assert result["status"] == "ok"

  def test_display_static_char(self, mock_drone):
      with patch("tello_mcp.drone.Tello", return_value=mock_drone):
          adapter = DroneAdapter()
          adapter.connect()
          result = adapter.display_static_char("heart", "b")
          mock_drone.send_expansion_command.assert_called_once_with(
              "mled s b heart"
          )
          assert result["status"] == "ok"

  def test_display_pattern(self, mock_drone):
      with patch("tello_mcp.drone.Tello", return_value=mock_drone):
          adapter = DroneAdapter()
          adapter.connect()
          result = adapter.display_pattern("rrrrbbbb" + "0" * 56)
          mock_drone.send_expansion_command.assert_called_once_with(
              "mled g rrrrbbbb" + "0" * 56
          )
          assert result["status"] == "ok"

  def test_display_scroll_text_when_not_connected(self):
      with patch("tello_mcp.drone.Tello"):
          adapter = DroneAdapter()
          result = adapter.display_scroll_text("hi")
          assert result["error"] == "DRONE_NOT_CONNECTED"
  ```

- [ ] **Step 2: Run tests to verify failure.**

  ```bash
  uv run --package tello-mcp pytest services/tello-mcp/tests/test_drone.py -v
  ```

  Expected: `test_set_led` fails (wrong mock method),
  `test_display_scroll_text` etc. fail (method not found).

- [ ] **Step 3: Fix `set_led()`** — change line 170 from
  `self._tello.set_led(r=r, g=g, b=b)` to
  `self._tello.send_expansion_command(f"led {r} {g} {b}")`.

- [ ] **Step 4: Replace `display_text()`** — remove the
  `display_text` method (lines 176-189). Add three new
  methods: `display_scroll_text(text, direction, color, rate)`,
  `display_static_char(char, color)`,
  `display_pattern(pattern)`. Each follows the standard
  error-handling pattern: `_require_connection()` guard,
  try/except wrapping `send_expansion_command()`, structured
  return dict. See spec Section 3.1.2 for full method bodies.

- [ ] **Step 5: Run tests to verify pass.**

  ```bash
  uv run --package tello-mcp pytest services/tello-mcp/tests/test_drone.py -v
  ```

  Expected: All pass.

- [ ] **Step 6: Lint and format.**

  ```bash
  uv run ruff check . --fix && uv run ruff format .
  ```

- [ ] **Step 7: Commit.**

  ```bash
  git add services/tello-mcp/src/tello_mcp/drone.py services/tello-mcp/tests/test_drone.py
  git commit -m "fix(tello-mcp): use send_expansion_command for LED and display methods"
  ```

---

### Task 2: Add mission pad enablement + keepalive to DroneAdapter

Per spec Sections 3.1.3, 3.1.4, 3.1.7. Auto-enable pads
in connect(), add keepalive(), add
set_pad_detection_direction().

**Files:**

- Modify: `services/tello-mcp/src/tello_mcp/drone.py`
- Modify: `services/tello-mcp/tests/test_drone.py`
- Modify: `services/tello-mcp/tests/conftest.py`

- [ ] **Step 1: Update `mock_drone` fixture** — add mock
  methods to `conftest.py`:

  ```python
  drone.enable_mission_pads = MagicMock()
  drone.disable_mission_pads = MagicMock()
  drone.set_mission_pad_detection_direction = MagicMock()
  drone.send_keepalive = MagicMock()
  drone.go_xyz_speed_mid = MagicMock()
  drone.send_expansion_command = MagicMock()
  drone.get_mission_pad_distance_x = MagicMock(return_value=10)
  drone.get_mission_pad_distance_y = MagicMock(return_value=20)
  drone.get_mission_pad_distance_z = MagicMock(return_value=50)
  ```

- [ ] **Step 2: Write failing tests:**

  ```python
  def test_connect_enables_mission_pads(self, mock_drone):
      with patch("tello_mcp.drone.Tello", return_value=mock_drone):
          adapter = DroneAdapter()
          adapter.connect()
          mock_drone.enable_mission_pads.assert_called_once()
          mock_drone.set_mission_pad_detection_direction.assert_called_once_with(0)

  def test_connect_succeeds_if_pad_enable_fails(self, mock_drone):
      mock_drone.enable_mission_pads.side_effect = Exception("pad error")
      with patch("tello_mcp.drone.Tello", return_value=mock_drone):
          adapter = DroneAdapter()
          result = adapter.connect()
          assert result["status"] == "ok"
          assert adapter.is_connected

  def test_keepalive(self, mock_drone):
      with patch("tello_mcp.drone.Tello", return_value=mock_drone):
          adapter = DroneAdapter()
          adapter.connect()
          adapter.keepalive()
          mock_drone.send_keepalive.assert_called_once()

  def test_keepalive_when_not_connected(self):
      with patch("tello_mcp.drone.Tello"):
          adapter = DroneAdapter()
          adapter.keepalive()  # should not raise

  def test_set_pad_detection_direction(self, mock_drone):
      with patch("tello_mcp.drone.Tello", return_value=mock_drone):
          adapter = DroneAdapter()
          adapter.connect()
          result = adapter.set_pad_detection_direction(2)
          mock_drone.set_mission_pad_detection_direction.assert_called_once_with(2)
          assert result["status"] == "ok"
  ```

- [ ] **Step 3: Run tests to verify failure.**

  ```bash
  uv run --package tello-mcp pytest services/tello-mcp/tests/test_drone.py -v -k "pad or keepalive or connect_enables"
  ```

- [ ] **Step 4: Implement** — update `connect()` per spec
  Section 3.1.3 (best-effort pad enablement). Add
  `keepalive()` per Section 3.1.4. Add
  `set_pad_detection_direction()` per Section 3.1.7.

- [ ] **Step 5: Run tests to verify pass.**

  ```bash
  uv run --package tello-mcp pytest services/tello-mcp/tests/test_drone.py -v
  ```

- [ ] **Step 6: Commit.**

  ```bash
  git add services/tello-mcp/
  git commit -m "feat(tello-mcp): auto-enable mission pads on connect, add keepalive + pad direction"
  ```

---

### Task 3: Expand detect_mission_pad + add go_xyz_speed_mid

Per spec Sections 3.1.5 and 3.1.6. Expand
detect_mission_pad return value with x/y/z coordinates.
Add go_xyz_speed_mid for pad-relative navigation.

**Files:**

- Modify: `services/tello-mcp/src/tello_mcp/drone.py`
- Modify: `services/tello-mcp/tests/test_drone.py`

- [ ] **Step 1: Write failing tests:**

  ```python
  def test_detect_mission_pad_with_pad(self, mock_drone):
      mock_drone.get_mission_pad_id.return_value = 3
      with patch("tello_mcp.drone.Tello", return_value=mock_drone):
          adapter = DroneAdapter()
          adapter.connect()
          result = adapter.detect_mission_pad()
          assert result["pad_id"] == 3
          assert result["detected"] is True
          assert result["x_cm"] == 10
          assert result["y_cm"] == 20
          assert result["z_cm"] == 50

  def test_detect_mission_pad_no_pad(self, mock_drone):
      mock_drone.get_mission_pad_id.return_value = -1
      with patch("tello_mcp.drone.Tello", return_value=mock_drone):
          adapter = DroneAdapter()
          adapter.connect()
          result = adapter.detect_mission_pad()
          assert result["pad_id"] == -1
          assert result["detected"] is False
          assert "x_cm" not in result

  def test_go_xyz_speed_mid(self, mock_drone):
      with patch("tello_mcp.drone.Tello", return_value=mock_drone):
          adapter = DroneAdapter()
          adapter.connect()
          result = adapter.go_xyz_speed_mid(0, 0, 50, 30, 1)
          mock_drone.go_xyz_speed_mid.assert_called_once_with(0, 0, 50, 30, 1)
          assert result["status"] == "ok"

  def test_go_xyz_speed_mid_when_not_connected(self):
      with patch("tello_mcp.drone.Tello"):
          adapter = DroneAdapter()
          result = adapter.go_xyz_speed_mid(0, 0, 50, 30, 1)
          assert result["error"] == "DRONE_NOT_CONNECTED"
  ```

- [ ] **Step 2: Run tests to verify failure.**

  ```bash
  uv run --package tello-mcp pytest services/tello-mcp/tests/test_drone.py -v -k "detect_mission_pad or go_xyz"
  ```

- [ ] **Step 3: Implement** — expand `detect_mission_pad()`
  per spec Section 3.1.5. Add `go_xyz_speed_mid()` per
  Section 3.1.6.

- [ ] **Step 4: Run all drone tests.**

  ```bash
  uv run --package tello-mcp pytest services/tello-mcp/tests/test_drone.py -v
  ```

  Expected: All pass (~25 tests).

- [ ] **Step 5: Commit.**

  ```bash
  git add services/tello-mcp/src/tello_mcp/drone.py services/tello-mcp/tests/test_drone.py
  git commit -m "feat(tello-mcp): expand detect_mission_pad return + add go_xyz_speed_mid"
  ```

---

### Task 4: Add keepalive background task to server.py

Per spec Section 3.2. Add background asyncio task that
sends keepalive every 10 seconds.

**Files:**

- Modify: `services/tello-mcp/src/tello_mcp/server.py`

- [ ] **Step 1: Add `_keepalive_loop` function** and
  integrate into lifespan. Add `import asyncio` and
  `from contextlib import suppress` (if not present).

  ```python
  async def _keepalive_loop(drone: DroneAdapter) -> None:
      """Send keepalive every 10s to prevent 15s auto-land timeout."""
      while True:
          await asyncio.sleep(10)
          if drone.is_connected:
              await asyncio.to_thread(drone.keepalive)
  ```

  In lifespan, after creating drone, start the task:

  ```python
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

- [ ] **Step 2: Verify import works.**

  ```bash
  uv run python -c "from tello_mcp.server import mcp; print(mcp.name)"
  ```

  Expected: `tello-mcp`

- [ ] **Step 3: Commit.**

  ```bash
  git add services/tello-mcp/src/tello_mcp/server.py
  git commit -m "feat(tello-mcp): add keepalive background task to prevent 15s auto-land"
  ```

---

### Task 5: Update MCP tools (expansion.py + flight.py)

Per spec Sections 3.3.1, 3.3.2, 3.3.3. Replace
display_matrix_text with 3 display tools, add
set_pad_detection_direction, add go_to_mission_pad.

**Files:**

- Modify: `services/tello-mcp/src/tello_mcp/tools/expansion.py`
- Modify: `services/tello-mcp/src/tello_mcp/tools/flight.py`
- Modify: `services/tello-mcp/tests/test_tools/test_expansion.py`
- Modify: `services/tello-mcp/tests/test_tools/test_flight.py`

- [ ] **Step 1: Write failing expansion tests** — remove
  `test_display_matrix_text_registered` and
  `test_display_matrix_text_calls_drone`. Add:

  ```python
  def test_display_scroll_text_registered(self):
      assert "display_scroll_text" in self.registered_tools

  def test_display_static_char_registered(self):
      assert "display_static_char" in self.registered_tools

  def test_display_pattern_registered(self):
      assert "display_pattern" in self.registered_tools

  def test_set_pad_detection_direction_registered(self):
      assert "set_pad_detection_direction" in self.registered_tools

  async def test_display_scroll_text_calls_drone(self):
      mock_queue = AsyncMock()
      mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
      ctx = self._make_ctx(queue=mock_queue)
      result = await self.registered_tools["display_scroll_text"](
          ctx, text="hello", direction="l", color="r", rate=0.5,
      )
      mock_queue.enqueue.assert_called_once()
      assert result["status"] == "ok"

  async def test_display_static_char_calls_drone(self):
      mock_queue = AsyncMock()
      mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
      ctx = self._make_ctx(queue=mock_queue)
      result = await self.registered_tools["display_static_char"](
          ctx, char="heart", color="b",
      )
      mock_queue.enqueue.assert_called_once()
      assert result["status"] == "ok"

  async def test_display_pattern_calls_drone(self):
      mock_queue = AsyncMock()
      mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
      ctx = self._make_ctx(queue=mock_queue)
      result = await self.registered_tools["display_pattern"](
          ctx, pattern="rrrrbbbb" + "0" * 56,
      )
      mock_queue.enqueue.assert_called_once()
      assert result["status"] == "ok"

  async def test_set_pad_detection_direction_calls_drone(self):
      mock_queue = AsyncMock()
      mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
      ctx = self._make_ctx(queue=mock_queue)
      result = await self.registered_tools["set_pad_detection_direction"](
          ctx, direction=2,
      )
      mock_queue.enqueue.assert_called_once()
      assert result["status"] == "ok"
  ```

- [ ] **Step 2: Write failing flight test:**

  ```python
  def test_go_to_mission_pad_registered(self):
      assert "go_to_mission_pad" in self.registered_tools

  async def test_go_to_mission_pad_calls_drone(self):
      mock_queue = AsyncMock()
      mock_queue.enqueue = AsyncMock(return_value={"status": "ok"})
      ctx = self._make_ctx(queue=mock_queue)
      result = await self.registered_tools["go_to_mission_pad"](
          ctx, x=0, y=0, z=50, speed=30, mid=1,
      )
      mock_queue.enqueue.assert_called_once()
      assert result["status"] == "ok"
  ```

- [ ] **Step 3: Run tests to verify failure.**

  ```bash
  uv run --package tello-mcp pytest services/tello-mcp/tests/test_tools/ -v
  ```

- [ ] **Step 4: Update `expansion.py`** — remove
  `display_matrix_text` tool. Add `display_scroll_text`,
  `display_static_char`, `display_pattern`, and
  `set_pad_detection_direction` tools per spec Section
  3.3.1 and 3.3.2.

- [ ] **Step 5: Update `flight.py`** — add
  `go_to_mission_pad` tool per spec Section 3.3.3.

- [ ] **Step 6: Run all tello-mcp tests.**

  ```bash
  uv run --package tello-mcp pytest services/tello-mcp/tests/ -v
  ```

  Expected: ~45 passing.

- [ ] **Step 7: Lint and format.**

  ```bash
  uv run ruff check . --fix && uv run ruff format .
  ```

- [ ] **Step 8: Commit.**

  ```bash
  git add services/tello-mcp/
  git commit -m "feat(tello-mcp): replace display tool with 3 focused tools, add pad direction + go_to_mission_pad"
  ```

---

### Task 6: Documentation fixes + final verification

Per spec Section 3.4. Update CLAUDE.md, architecture.md,
and memory files. Run full test suite.

**Files:**

- Modify: `CLAUDE.md`
- Modify: `docs/architecture.md`
- Modify: 5 memory files (see spec Section 3.4 table)

- [ ] **Step 1: Update `CLAUDE.md`** — change
  `services/tello-navigator/` description from
  "LangGraph mission planner (placeholder)" to
  "LangGraph mission planner". Add to Error Handling
  section: "15-second SDK timeout: drone auto-lands if
  no command received for 15s. tello-mcp runs a
  background keepalive task to prevent this."

- [ ] **Step 2: Update `docs/architecture.md`** — fix
  tello-navigator description. Remove "rate limiting"
  from Redis capabilities table.

- [ ] **Step 3: Update memory files** — per spec Section
  3.4 table: `pattern_advisory_commands.md`,
  `project_live_test_results.md`,
  `project_room_graph_data.md`, `project_overview.md`.

- [ ] **Step 4: Run full test suite.**

  ```bash
  uv run --package tello-core pytest packages/tello-core/tests/ -v
  uv run --package tello-mcp pytest services/tello-mcp/tests/ -v
  uv run --package tello-navigator pytest services/tello-navigator/tests/ -v
  uv run --package tello-telemetry pytest services/tello-telemetry/tests/ -v
  ```

  Expected: ~190+ total (54 core + 45 mcp + 50 navigator
  + 45 telemetry).

- [ ] **Step 5: Lint and format.**

  ```bash
  uv run ruff check . --fix && uv run ruff format .
  ```

- [ ] **Step 6: Commit.**

  ```bash
  git add CLAUDE.md docs/architecture.md
  git commit -m "docs: fix navigator description, add 15s timeout, update memory files"
  ```

- [ ] **Step 7: Push and create PR.**

  ```bash
  git push -u origin <branch-name>
  gh pr create --title "fix: SDK alignment for tello-mcp (Phase 3a)" --body "Closes #<issue>"
  ```

---

## Chunk 2: Phase 3b — tello-navigator Pad Navigation Alignment

> **Prerequisite:** Phase 3a PR must be merged and
> physically tested before starting Phase 3b. Create a
> new GitHub Issue and worktree for Phase 3b.

### Task 7: Add speed_cm_s to Waypoint model

Per spec Section 4.1. Add speed field for pad-relative
navigation waypoints.

**Files:**

- Modify: `packages/tello-core/src/tello_core/models.py`
- Modify: `packages/tello-core/tests/test_models.py`

- [ ] **Step 1: Write failing tests** — add to
  `TestWaypoint` class:

  ```python
  def test_waypoint_with_speed(self):
      wp = Waypoint(
          id="wp1", sequence=0, room_id="living",
          action="goto_pad", pad_id=1, speed_cm_s=30,
      )
      assert wp.speed_cm_s == 30

  def test_waypoint_speed_bounds(self):
      with pytest.raises(ValidationError):
          Waypoint(
              id="wp1", sequence=0, room_id="living",
              action="goto_pad", speed_cm_s=5,  # below 10
          )
      with pytest.raises(ValidationError):
          Waypoint(
              id="wp1", sequence=0, room_id="living",
              action="goto_pad", speed_cm_s=200,  # above 100
          )

  def test_waypoint_speed_optional(self):
      wp = Waypoint(
          id="wp1", sequence=0, room_id="living",
          action="move", direction="forward", distance_cm=100,
      )
      assert wp.speed_cm_s is None
  ```

- [ ] **Step 2: Run tests to verify failure.**

  ```bash
  uv run --package tello-core pytest packages/tello-core/tests/test_models.py -v -k "speed"
  ```

- [ ] **Step 3: Implement** — add to Waypoint model:

  ```python
  speed_cm_s: int | None = Field(default=None, ge=10, le=100)
  ```

- [ ] **Step 4: Run tests to verify pass.**

  ```bash
  uv run --package tello-core pytest packages/tello-core/tests/test_models.py -v
  ```

- [ ] **Step 5: Commit.**

  ```bash
  git add packages/tello-core/
  git commit -m "feat(tello-core): add speed_cm_s field to Waypoint model"
  ```

---

### Task 8: Update planner waypoint generation + advisory command mapping

Per spec Sections 4.2, 4.3, 4.4. Add speed_cm_s to
goto_pad waypoints, update _suggested_command mapping,
update repository persistence.

**Files:**

- Modify: `services/tello-navigator/src/tello_navigator/planner.py`
- Modify: `services/tello-navigator/src/tello_navigator/tools/missions.py`
- Modify: `services/tello-navigator/src/tello_navigator/repository.py`
- Modify: `services/tello-navigator/tests/test_planner.py`
- Modify: `services/tello-navigator/tests/test_tools/test_missions.py`
- Modify: `services/tello-navigator/tests/test_repository.py`

- [ ] **Step 1: Write failing planner test** — in
  `TestGenerateWaypoints`, update the test that checks
  `goto_pad` waypoints. The planner's
  `_generate_waypoints()` returns a list of raw dicts
  (not Pydantic models). Assert the dict includes
  `speed_cm_s`:

  ```python
  # In the existing test that checks goto_pad waypoints:
  goto_pads = [wp for wp in result["waypoints"] if wp["action"] == "goto_pad"]
  assert len(goto_pads) > 0
  for wp in goto_pads:
      assert wp["speed_cm_s"] == 30
  ```

- [ ] **Step 2: Write failing missions test** — in the
  test for `_suggested_command()`, update the mock
  planner return to include `speed_cm_s` in goto_pad
  waypoints. Then verify the suggested command changed.
  **Note:** `_suggested_command(waypoint)` receives a
  raw dict (not a Pydantic Waypoint instance), so
  `.get()` is the correct access pattern:

  ```python
  # In test setup, update the planner mock waypoints:
  {"id": "wp_1", "sequence": 1, "room_id": "living",
   "pad_id": 1, "action": "goto_pad", "speed_cm_s": 30}

  # Then in assertion:
  result = await self.registered_tools["advance_mission"](
      self.mock_ctx, mission_id="m1", current_waypoint_idx=0,
  )
  assert result["suggested_command"]["tool"] == "go_to_mission_pad"
  assert result["suggested_command"]["args"]["mid"] == 1
  assert result["suggested_command"]["args"]["speed"] == 30
  assert result["suggested_command"]["args"]["z"] == 50
  ```

- [ ] **Step 3: Write failing repository test** — in
  `TestSaveWaypoints`, verify the Cypher `s.run()` call
  includes `speed_cm_s` in its parameters:

  ```python
  # After calling repo.save_waypoints(mission_id, waypoints):
  call_args = mock_session.run.call_args_list
  # Find the waypoint CREATE call and check params include speed_cm_s
  ```

- [ ] **Step 4: Run tests to verify failure.**

  ```bash
  uv run --package tello-navigator pytest services/tello-navigator/tests/ -v -k "waypoint or mission or save"
  ```

- [ ] **Step 5: Update `planner.py`** — in
  `_generate_waypoints()`, add `"speed_cm_s": 30` to
  `goto_pad` waypoint dicts.

- [ ] **Step 6: Update `missions.py`** — in
  `_suggested_command()`, change `goto_pad` mapping from
  `{"tool": "detect_mission_pad", "args": {}}` to
  `{"tool": "go_to_mission_pad", "args": {"x": 0, "y": 0, "z": 50, "speed": waypoint.get("speed_cm_s", 30), "mid": waypoint.get("pad_id")}}`.

- [ ] **Step 7: Update `repository.py`** — add
  `speed_cm_s: $speed_cm_s` to the Waypoint Cypher
  CREATE and `speed_cm_s=wp.speed_cm_s` to params.

- [ ] **Step 8: Run all navigator tests.**

  ```bash
  uv run --package tello-navigator pytest services/tello-navigator/tests/ -v
  ```

  Expected: ~55 passing.

- [ ] **Step 9: Lint and format.**

  ```bash
  uv run ruff check . --fix && uv run ruff format .
  ```

- [ ] **Step 10: Commit.**

  ```bash
  git add services/tello-navigator/ packages/tello-core/
  git commit -m "feat(tello-navigator): update goto_pad advisory command to use go_to_mission_pad"
  ```

---

### Task 9: Update physical test plan + final verification

Per spec Section 4.5. Rename test plan, incorporate 3a +
3b changes.

**Files:**

- Rename: `testing/2026-03-13-phase3-physical-test-plan.md`
  → `testing/phase3-physical-test-plan_v2.md`
- Modify: `testing/phase3-physical-test-plan_v2.md`

- [ ] **Step 1: Rename the test plan file.**

  ```bash
  mv testing/2026-03-13-phase3-physical-test-plan.md testing/phase3-physical-test-plan_v2.md
  ```

- [ ] **Step 2: Update test plan content** — per spec
  Section 4.5:
  - Block 1: Replace `display_matrix_text` with
    `display_scroll_text`, `display_static_char`,
    `display_pattern` test steps.
  - Block 4: Update `goto_pad` advisory command from
    `detect_mission_pad` to `go_to_mission_pad`.
  - Add keepalive test step (hover 30s+ without commands).
  - Add detect_mission_pad x/y/z test step.
  - Add go_to_mission_pad test step.
  - Add pad detection height constraint to safety section.

- [ ] **Step 3: Run full test suite.**

  ```bash
  uv run --package tello-core pytest packages/tello-core/tests/ -v
  uv run --package tello-mcp pytest services/tello-mcp/tests/ -v
  uv run --package tello-navigator pytest services/tello-navigator/tests/ -v
  uv run --package tello-telemetry pytest services/tello-telemetry/tests/ -v
  ```

  Expected: ~200+ total.

- [ ] **Step 4: Lint and format.**

  ```bash
  uv run ruff check . --fix && uv run ruff format .
  ```

- [ ] **Step 5: Commit.**

  ```bash
  git add testing/ services/ packages/
  git commit -m "docs: update physical test plan to v2 with SDK alignment changes"
  ```

- [ ] **Step 6: Push and create PR.**

  ```bash
  git push -u origin <branch-name>
  gh pr create --title "feat: navigator pad navigation alignment (Phase 3b)" --body "Closes #<issue>"
  ```
