# Tello Navigator Implementation Plan

> **For agentic workers:** REQUIRED: Use
> superpowers:subagent-driven-development (if subagents
> available) or superpowers:executing-plans to implement
> this plan. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Build the LangGraph mission planner service
that decomposes goals into waypoint sequences, persists
to Neo4j, and tracks execution via Redis-checkpointed
state graph.

**Architecture:** FastMCP service following
tello-telemetry patterns — lifespan context manager,
`ctx.lifespan_context` tool injection, sync Neo4j driver
via `asyncio.to_thread()`, Redis Stream event publishing.
LangGraph `StateGraph` for deterministic planning with
`AsyncRedisSaver` checkpointing.

**Tech Stack:** Python 3.13, FastMCP 3.x, LangGraph,
langgraph-checkpoint-redis, Neo4j (sync driver),
Redis (async), Pydantic, structlog, pytest-asyncio.

**Spec:**
`docs/superpowers/specs/2026-03-13-tello-navigator-design.md`

---

## Chunk 1: Bundled Prerequisites + Models

### Task 1: FastMCP 3.x Migration (tello-mcp + tello-telemetry)

Per spec Section 12.6. This migration was completed
locally in a prior session but reverted. Re-apply the
changes.

**Files:**

- Modify: `services/tello-mcp/src/tello_mcp/server.py`
- Modify: `services/tello-mcp/src/tello_mcp/tools/flight.py`
- Modify: `services/tello-mcp/src/tello_mcp/tools/sensors.py`
- Modify: `services/tello-mcp/src/tello_mcp/tools/expansion.py`
- Modify: `services/tello-mcp/src/tello_mcp/drone.py`
- Modify: `services/tello-mcp/tests/test_tools/test_flight.py`
- Modify: `services/tello-telemetry/src/tello_telemetry/server.py`
- Modify: `services/tello-telemetry/src/tello_telemetry/tools/queries.py`
- Modify: `services/tello-telemetry/tests/test_tools/test_queries.py`
- Modify: `pyproject.toml` (dependency-groups migration)
- Modify: `.gitignore`

- [ ] **Step 1:** Add lifespan context manager to
  tello-mcp `server.py` — yield
  `{drone, queue, redis, telemetry, config}` dict.
  Add `DroneAdapter(host=config.tello_host)`.
  Remove old `mcp.state` assignments from `main()`.

- [ ] **Step 2:** Update all tello-mcp tool modules
  (`flight.py`, `sensors.py`, `expansion.py`) — add
  `ctx: Context` as first param, replace
  `mcp.state["key"]` with
  `ctx.lifespan_context["key"]`. Add
  `from fastmcp import Context` as runtime import.

- [ ] **Step 3:** Add `set_led()` and `display_text()`
  methods to `DroneAdapter`. Accept `host` param in
  `__init__`.

- [ ] **Step 4:** Update tello-mcp test — change
  `mcp.state = {...}` to
  `mock_ctx.lifespan_context = {...}`, pass `mock_ctx`
  as first arg to tool calls.

- [ ] **Step 5:** Update tello-telemetry `server.py` —
  change lifespan to
  `yield {"session_repo": session_repo}` instead of
  `server.state["session_repo"] = ...`. Change return
  type to `AsyncIterator[dict]`.

- [ ] **Step 6:** Update tello-telemetry
  `tools/queries.py` — add `ctx: Context` param,
  replace `mcp.state["session_repo"]` with
  `ctx.lifespan_context["session_repo"]`.

- [ ] **Step 7:** Update tello-telemetry tests —
  `mock_ctx.lifespan_context = {"session_repo": ...}`,
  pass to tool calls.

- [ ] **Step 8:** Migrate `pyproject.toml` — change
  `[tool.uv] dev-dependencies` to
  `[dependency-groups] dev`. Add `*.docx` to
  `.gitignore`. Add
  `"**/tools/**/*.py" = ["D417", "TC002"]` to ruff
  per-file-ignores.

- [ ] **Step 9:** Run all tests per-package.

  ```bash
  uv run --package tello-core pytest packages/tello-core/tests/ -v
  uv run --package tello-mcp pytest services/tello-mcp/tests/ -v
  uv run --package tello-telemetry pytest services/tello-telemetry/tests/ -v
  ```

  Expected: 110 passing.

- [ ] **Step 10:** Lint and format.

  ```bash
  uv run ruff check . --fix && uv run ruff format .
  ```

- [ ] **Step 11:** Commit.

  ```bash
  git add -A
  git commit -m "fix: migrate to FastMCP 3.x lifespan context + expansion board methods"
  ```

---

### Task 2: Add Mission Models to tello-core

Per spec Section 8 and Section 12.1.

**Files:**

- Modify: `packages/tello-core/src/tello_core/models.py`
- Modify: `packages/tello-core/src/tello_core/__init__.py`
- Test: `packages/tello-core/tests/test_models.py`

- [ ] **Step 1: Write failing tests** — add
  `TestWaypoint`, `TestMissionStatus`, `TestMission`,
  `TestDwelling` classes to `test_models.py`. Cover:
  valid construction, validation bounds (distance
  20-500, degrees -360 to 360, sequence >= 0), invalid
  action rejected, enum values, serialization roundtrip.

- [ ] **Step 2: Run tests to verify failure.**

  ```bash
  uv run --package tello-core pytest packages/tello-core/tests/test_models.py -v
  ```

  Expected: ImportError (models don't exist yet).

- [ ] **Step 3: Implement models** — add `Waypoint`,
  `MissionStatus` (StrEnum), `Mission`, `Dwelling` to
  `models.py` under `# ── Navigation Layer` section.
  Add `from enum import StrEnum` import.

- [ ] **Step 4: Update `__init__.py`** — add all 4 new
  models to imports and `__all__`.

- [ ] **Step 5: Run tests to verify pass.**

  ```bash
  uv run --package tello-core pytest packages/tello-core/tests/test_models.py -v
  ```

  Expected: All pass (29+ tests).

- [ ] **Step 6: Commit.**

  ```bash
  git add packages/tello-core/
  git commit -m "feat(tello-core): add Mission, Waypoint, MissionStatus, Dwelling models"
  ```

---

### Task 3: Scaffold tello-navigator Package

Per spec Sections 3, 4, 5, and 12.2-12.5.

**Files:**

- Modify: `services/tello-navigator/pyproject.toml`
- Create: `services/tello-navigator/src/tello_navigator/__init__.py`
- Create: `services/tello-navigator/src/tello_navigator/config.py`
- Create: `services/tello-navigator/tests/conftest.py`
- Test: `services/tello-navigator/tests/test_config.py`
- Modify: `pyproject.toml` (root — pythonpath, coverage, lint)
- Modify: `.pre-commit-config.yaml`
- Create: `scripts/no-commit-to-main.sh`

- [ ] **Step 1:** Update
  `services/tello-navigator/pyproject.toml` with full
  dependencies per spec Section 4. Add
  `[tool.hatch.build.targets.wheel]` and
  `[tool.uv.sources]`.

- [ ] **Step 2:** Create `__init__.py` with docstring.
  Create empty `tools/__init__.py`. Create
  `tests/__init__.py` and `tests/test_tools/__init__.py`.

- [ ] **Step 3: Write failing config test** —
  `test_config.py` with `TestTelloNavigatorConfig`:
  test defaults, env overrides, missing env raises,
  frozen immutability.

- [ ] **Step 4: Implement `config.py`** —
  `TelloNavigatorConfig(BaseServiceConfig)` with 5
  fields per spec Section 5. Use `from_env` override
  pattern matching tello-telemetry.

- [ ] **Step 5: Run config tests.**

  ```bash
  uv run --package tello-navigator pytest services/tello-navigator/tests/test_config.py -v
  ```

  Expected: 4 passing.

- [ ] **Step 6:** Update root `pyproject.toml` — add
  `services/tello-navigator/src` to `pythonpath` and
  `[tool.coverage.run].source`. Add
  `"RUF012", "RUF059"` to test per-file-ignores.

- [ ] **Step 7:** Create `scripts/no-commit-to-main.sh`
  (executable). Add to `.pre-commit-config.yaml` as
  `no-commit-to-main` hook. Run
  `uv run pre-commit install`.

- [ ] **Step 8:** Run `uv sync` to install navigator
  dependencies.

- [ ] **Step 9: Commit.**

  ```bash
  git add services/tello-navigator/ pyproject.toml .pre-commit-config.yaml scripts/
  git commit -m "feat(tello-navigator): scaffold package, config, pre-commit hook"
  ```

---

## Chunk 2: Domain Layer (Repository + Events + Planner)

### Task 4: Implement MissionRepository

Per spec Section 7.

**Files:**

- Create: `services/tello-navigator/src/tello_navigator/repository.py`
- Test: `services/tello-navigator/tests/test_repository.py`

- [ ] **Step 1: Write failing tests** —
  `test_repository.py` with fixtures for mock Neo4j
  driver/session. Test classes: `TestCreateMission`
  (creates node, passes params),
  `TestSaveWaypoints` (creates linked nodes),
  `TestUpdateMissionStatus` (updates status +
  timestamps), `TestGetMission` (found/not found),
  `TestListMissions` (returns list, filters by status),
  `TestGetMissionWaypoints` (ordered by sequence),
  `TestRoomGraphQueries` (get\_rooms, get\_room\_pads),
  `TestSeedRoomGraph` (seeds rooms + pads +
  connections). ~13 tests.

- [ ] **Step 2: Run tests to verify failure.**

  ```bash
  uv run --package tello-navigator pytest services/tello-navigator/tests/test_repository.py -v
  ```

  Expected: ImportError.

- [ ] **Step 3: Implement `repository.py`** —
  `MissionRepository` class with sync Neo4j driver.
  All methods per spec Section 7.1. Use `MERGE` for
  seed operations. Follow `SessionRepository` patterns
  from tello-telemetry.

- [ ] **Step 4: Run tests to verify pass.**

  ```bash
  uv run --package tello-navigator pytest services/tello-navigator/tests/test_repository.py -v
  ```

  Expected: 13 passing.

- [ ] **Step 5: Commit.**

  ```bash
  git add services/tello-navigator/src/tello_navigator/repository.py services/tello-navigator/tests/test_repository.py
  git commit -m "feat(tello-navigator): add MissionRepository (Neo4j CRUD)"
  ```

---

### Task 5: Implement MissionEventPublisher

Per spec Section 9.

**Files:**

- Create: `services/tello-navigator/src/tello_navigator/events.py`
- Test: `services/tello-navigator/tests/test_events.py`

- [ ] **Step 1: Write failing tests** —
  `test_events.py` with async mock Redis. Test each
  lifecycle method: `mission_created`,
  `mission_started`, `waypoint_reached`,
  `mission_completed`, `mission_aborted`. Verify XADD
  called with correct stream and stringified fields.
  ~7 tests.

- [ ] **Step 2: Run tests to verify failure.**

- [ ] **Step 3: Implement `events.py`** —
  `MissionEventPublisher` class. Follow
  `TelemetryPublisher.publish_event()` pattern.

- [ ] **Step 4: Run tests to verify pass.**

  ```bash
  uv run --package tello-navigator pytest services/tello-navigator/tests/test_events.py -v
  ```

  Expected: 7 passing.

- [ ] **Step 5: Commit.**

  ```bash
  git add services/tello-navigator/src/tello_navigator/events.py services/tello-navigator/tests/test_events.py
  git commit -m "feat(tello-navigator): add MissionEventPublisher (Redis Stream)"
  ```

---

### Task 6: Implement MissionPlanner

Per spec Section 6.

**Files:**

- Create: `services/tello-navigator/src/tello_navigator/planner.py`
- Test: `services/tello-navigator/tests/test_planner.py`

- [ ] **Step 1: Write failing tests** —
  `test_planner.py` with mock repo and config. Test
  each graph node independently: `TestFetchRooms`,
  `TestValidateRooms` (valid + missing room error),
  `TestGenerateWaypoints` (single room with pads,
  multi-room, room without pads fallback),
  `TestValidatePlan` (passes + exceeds max waypoints),
  `TestFinalize`. Test full graph: `TestFullGraph`
  (happy path, unknown room error). ~10 tests.

- [ ] **Step 2: Run tests to verify failure.**

- [ ] **Step 3: Implement `planner.py`** —
  `PlannerState` TypedDict, `MissionPlanner` class.
  Build `StateGraph` with 5 nodes + conditional edges.
  `plan()` method wraps `graph.ainvoke()` in
  `asyncio.wait_for(config.planning_timeout_s)`.
  Accept optional `checkpointer` param (pass `None`
  in tests, `AsyncRedisSaver` in production).

- [ ] **Step 4: Run tests to verify pass.**

  ```bash
  uv run --package tello-navigator pytest services/tello-navigator/tests/test_planner.py -v
  ```

  Expected: 10 passing.

- [ ] **Step 5: Commit.**

  ```bash
  git add services/tello-navigator/src/tello_navigator/planner.py services/tello-navigator/tests/test_planner.py
  git commit -m "feat(tello-navigator): add MissionPlanner (LangGraph StateGraph)"
  ```

---

## Chunk 3: MCP Tools + Server + Finalization

### Task 7: Implement Mission Lifecycle Tools

Per spec Sections 10.1, 10.3, 10.4, 6.2, 6.4.

**Files:**

- Create: `services/tello-navigator/src/tello_navigator/tools/missions.py`
- Test: `services/tello-navigator/tests/test_tools/test_missions.py`

- [ ] **Step 1: Write failing tests** —
  `test_missions.py`. Setup fixture: mock mcp, register
  tools, mock\_ctx with
  `lifespan_context = {planner, repo, events}`.
  Tests: `TestCreateMission` (happy path + planning
  error), `TestStartMission` (valid + not found +
  invalid transition), `TestAdvanceMission` (next
  waypoint + completion + invalid state),
  `TestAbortMission` (from executing + from planned +
  from completed errors). ~11 tests.

- [ ] **Step 2: Run tests to verify failure.**

- [ ] **Step 3: Implement `tools/missions.py`** —
  `register(mcp)` function with 4 tools. Add
  `_suggested_command()` helper per spec Section 6.4.
  All tools: `ctx: Context` first param,
  `asyncio.to_thread()` for sync repo calls,
  structured error returns, `ToolAnnotations`.

- [ ] **Step 4: Run tests to verify pass.**

  ```bash
  uv run --package tello-navigator pytest services/tello-navigator/tests/test_tools/test_missions.py -v
  ```

  Expected: 11 passing.

- [ ] **Step 5: Commit.**

  ```bash
  git add services/tello-navigator/src/tello_navigator/tools/missions.py services/tello-navigator/tests/test_tools/test_missions.py
  git commit -m "feat(tello-navigator): add mission lifecycle MCP tools"
  ```

---

### Task 8: Implement Query Tools

Per spec Sections 10.2, 10.5.

**Files:**

- Create: `services/tello-navigator/src/tello_navigator/tools/queries.py`
- Test: `services/tello-navigator/tests/test_tools/test_queries.py`

- [ ] **Step 1: Write failing tests** —
  `test_queries.py`. Tests: `TestGetMission` (found +
  not found), `TestListMissions` (returns list +
  filters by status), `TestSeedRoomGraph` (calls repo,
  returns counts). ~5 tests.

- [ ] **Step 2: Run tests to verify failure.**

- [ ] **Step 3: Implement `tools/queries.py`** —
  `register(mcp)` with `get_mission`, `list_missions`,
  `seed_room_graph`. All use
  `ctx.lifespan_context["repo"]` +
  `asyncio.to_thread()`.

- [ ] **Step 4: Run tests to verify pass.**

  ```bash
  uv run --package tello-navigator pytest services/tello-navigator/tests/test_tools/test_queries.py -v
  ```

  Expected: 5 passing.

- [ ] **Step 5: Commit.**

  ```bash
  git add services/tello-navigator/src/tello_navigator/tools/queries.py services/tello-navigator/tests/test_tools/test_queries.py
  git commit -m "feat(tello-navigator): add query MCP tools + seed_room_graph"
  ```

---

### Task 9: Implement Server + Entry Point

Per spec Section 11.

**Files:**

- Create: `services/tello-navigator/src/tello_navigator/server.py`
- Create: `services/tello-navigator/src/tello_navigator/__main__.py`

- [ ] **Step 1: Implement `server.py`** — lifespan
  context manager per spec Section 11 code.
  `AsyncRedisSaver.from_conn_string()` as async
  context manager. Register `missions` and `queries`
  tool modules. `main()` with argparse (transport +
  port 8300).

- [ ] **Step 2: Implement `__main__.py`** —
  `from tello_navigator.server import main; main()`.

- [ ] **Step 3: Verify import works.**

  ```bash
  uv run python -c "from tello_navigator.server import mcp; print(mcp.name)"
  ```

  Expected: `tello-navigator`

- [ ] **Step 4: Commit.**

  ```bash
  git add services/tello-navigator/src/tello_navigator/server.py services/tello-navigator/src/tello_navigator/__main__.py
  git commit -m "feat(tello-navigator): add FastMCP server + entry point"
  ```

---

### Task 10: Final Verification + CI Updates

**Files:**

- Create: `scripts/seed_data/4309_donny_martel_way.json`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Verify seed data file** — confirm
  `scripts/seed_data/4309_donny_martel_way.json`
  exists and contains valid room graph data (5 rooms,
  8 pads, 4 connections). This file was created during
  the design phase.

- [ ] **Step 2:** Run full test suite per-package.

  ```bash
  uv run --package tello-core pytest packages/tello-core/tests/ -v
  uv run --package tello-mcp pytest services/tello-mcp/tests/ -v
  uv run --package tello-navigator pytest services/tello-navigator/tests/ -v
  uv run --package tello-telemetry pytest services/tello-telemetry/tests/ -v
  ```

  Expected: 160+ total
  (50 core + 30 mcp + 50+ navigator + 45 telemetry).

- [ ] **Step 3:** Lint and format.

  ```bash
  uv run ruff check . --fix && uv run ruff format .
  ```

  Expected: All checks passed, all formatted.

- [ ] **Step 4:** Add `tello-navigator` to CI test
  matrix in `.github/workflows/ci.yml`.

- [ ] **Step 5: Commit.**

  ```bash
  git add .github/workflows/ci.yml scripts/seed_data/
  git commit -m "ci: add tello-navigator to test matrix + seed data"
  ```

- [ ] **Step 6:** Push branch and open PR.

  ```bash
  git push -u origin <branch-name>
  gh pr create --title "feat: add tello-navigator service (Phase 3)" --body "Closes #5"
  ```
