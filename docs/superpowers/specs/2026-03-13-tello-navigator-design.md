# Tello Navigator Service — Design Specification

**Date:** 2026-03-13
**Author:** Arthur Fantaci + Claude
**Status:** Draft
**Scope:** LangGraph mission planner (Phase 3)

---

## 1. Overview

The drone platform can fly and record telemetry, but has no concept of
*missions* — multi-step, goal-oriented flight plans. tello-navigator
adds the planning layer: it receives high-level mission goals (e.g.,
"patrol rooms A and B"), decomposes them into ordered waypoints,
persists plans in Neo4j, and tracks execution state via LangGraph with
Redis checkpointing. This is the "brain" that turns intent into
structured action sequences.

**Data flow:**

```text
User / tello-voice (future)
    │
    ▼
tello-navigator MCP tools
    │
    ├─── MissionPlanner (LangGraph StateGraph)
    │       │
    │       ├── fetch_rooms ──► Neo4j (room graph)
    │       ├── validate_rooms ──► check rooms exist
    │       ├── generate_waypoints ──► waypoint sequence
    │       ├── validate_plan ──► safety checks
    │       └── checkpoint ──► Redis (AsyncRedisSaver, 24h TTL)
    │
    ├─── MissionRepository ──► Neo4j (mission CRUD)
    │
    └─── Redis Stream (tello:missions)
            │
            ▼
        tello-telemetry (future: link sessions to missions)
```

---

## 2. Design Decisions

| Decision | Choice | Rationale |
| -------- | ------ | --------- |
| Room graph seeding | MCP tool `seed_room_graph` (A) | Keeps it in the MCP tool ecosystem; Claude and tello-voice can call it conversationally; supports multi-dwelling via re-seeding |
| Execution model | Advisory commands (B) | `advance_mission` returns `suggested_command` with exact tello-mcp tool name + args. tello-voice (Phase 5) can pass commands directly. Autonomous execution (C) becomes an additive `execute_mission` tool in v2 — no rework needed |
| Room connectivity | Neo4j `:CONNECTS_TO` relationship (A) | Graph relationship with properties (`via_pad`, `direction`, `passage_type`, `clearance_cm`). Enables `shortestPath` Cypher queries. tello-vision (Phase 4) can add `:BLOCKED_BY` relationships without schema changes |
| Mission pad detection | Static seeded data (A) | Pad positions seeded into Neo4j, trusted by planner. Live detection deferred to v2 after tello-vision (Phase 4) provides spatial awareness |
| LangGraph vs plain code | LangGraph deterministic StateGraph | No LLM in v1. LangGraph provides: Redis checkpointing (mission state survives restarts), state machine semantics (testable nodes), future LLM swap (replace `plan_route` node), human-in-the-loop breakpoints, execution traces |
| Checkpointing | AsyncRedisSaver with 24h TTL | Demonstrates Redis checkpointing + TTL patterns (portfolio value). Missions persist across server restarts. `checkpoint_ttl_hours` config field controls expiry |
| Async handling | Fully async — `AsyncRedisSaver`, `graph.ainvoke()` | Consistent with platform async-everywhere convention. Planning timeout enforced via `asyncio.wait_for(planning_timeout_s)` |
| State machine enforcement | Code-enforced with documented transition matrix | Invalid transitions (e.g., completed → executing) return `{"error": "INVALID_TRANSITION"}`. Full matrix in Section 6.2 |
| Waypoint generation algorithm | Room-order pad visitation with fallback | Visit rooms in `room_ids` order; within each room visit pads in seeded order; rooms with no pads get a forward move. Documented in Section 5.3 |
| Error handling | Structured dicts + transaction wrapping | Repository operations that span multiple writes (create mission + save waypoints) use explicit error handling. Tool errors follow `{"error": "CODE", "detail": "..."}` pattern |

---

## 2.1 Cross-Phase Integration

### Mission-to-Session Linking

The `mission_id` field on `FlightSession` (already in tello-core
models) enables linking flight executions to mission plans:

| Phase | Who links | How |
| ----- | --------- | --- |
| 3 (navigator) | Claude / user | After `start_mission`, Claude calls `takeoff(room_id=..., mission_id=...)` on tello-mcp. tello-telemetry records it on the session |
| 4 (vision) | CV pipeline | Vision confirms waypoint arrival via pad detection; updates mission progress |
| 5 (voice) | NL orchestrator | "Execute the kitchen patrol" → voice calls `start_mission`, then orchestrates tello-mcp calls using `suggested_command` |

**Bundled change:** tello-mcp's takeoff tool already accepts
`room_id`; no changes needed for Phase 3. The `mission_id` parameter
on `FlightSession` already exists in tello-core models.

### Event Flow: Navigator → Telemetry

Navigator publishes to `tello:missions` Redis Stream. tello-telemetry
does NOT consume this stream in Phase 3 — the linkage is via the
`mission_id` field on `FlightSession`, set by the caller at takeoff
time. Future: tello-telemetry could subscribe to `tello:missions` to
auto-correlate sessions and missions.

---

## 3. Service Layout

```text
services/tello-navigator/
├── pyproject.toml
├── src/tello_navigator/
│   ├── __init__.py
│   ├── __main__.py              # Entry point
│   ├── server.py                # FastMCP server + lifespan
│   ├── config.py                # TelloNavigatorConfig(BaseServiceConfig)
│   ├── planner.py               # MissionPlanner — LangGraph StateGraph
│   ├── repository.py            # MissionRepository — Neo4j CRUD
│   ├── events.py                # MissionEventPublisher — Redis Stream
│   └── tools/
│       ├── __init__.py
│       ├── missions.py          # Mission lifecycle tools (create, start, advance, abort)
│       └── queries.py           # Read-only query tools (get, list) + seed_room_graph
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_planner.py
    ├── test_repository.py
    ├── test_events.py
    └── test_tools/
        ├── test_missions.py
        └── test_queries.py
```

---

## 4. Dependencies

```toml
[project]
name = "tello-navigator"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "tello-core",
    "langgraph>=0.4",
    "langgraph-checkpoint-redis>=0.3",
    "fastmcp>=3.0.0",
    "redis>=5.0.0",
    "neo4j>=5.15.0",
    "structlog>=24.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tello_navigator"]

[tool.uv.sources]
tello-core = { workspace = true }
```

**Note on Pydantic:** Transitive via tello-core. Navigator adds
new models (`Mission`, `Waypoint`, `MissionStatus`, `Dwelling`) to
`tello_core.models` per project convention. Reuses existing
`RoomNode` and `MissionPad` models (already in tello-core). See Section 8.

**Entry point (`__main__.py`):** Delegates to `server.main()` which
uses argparse with `--transport` (stdio/streamable-http/sse) and
`--port` (default 8300). Same pattern as tello-mcp and tello-telemetry.

---

## 5. Configuration (`config.py`)

```python
@dataclass(frozen=True, slots=True)
class TelloNavigatorConfig(BaseServiceConfig):
    missions_stream: str = "tello:missions"       # Redis Stream for events
    max_waypoints_per_mission: int = 20            # Safety limit
    default_move_distance_cm: int = 100            # Fallback step size
    planning_timeout_s: float = 30.0               # Max time for planning graph
    checkpoint_ttl_hours: int = 24                  # Redis checkpoint expiry
```

All fields have sensible defaults. Override via environment variables
following `BaseServiceConfig.from_env()`.

---

## 6. Mission Planner (`planner.py`)

### 6.1 LangGraph StateGraph

The planner is a **deterministic** graph (no LLM calls in v1). It uses
LangGraph for structured state management, checkpointing, and future
extensibility (LLM-powered planning in v2).

**Graph state:**

```python
class PlannerState(TypedDict):
    mission_id: str
    goal: str                          # Human-readable goal
    room_ids: list[str]                # Target rooms to visit
    rooms: list[dict]                  # Fetched room data from Neo4j
    mission_pads: list[dict]           # Available pads in target rooms
    waypoints: list[dict]              # Generated waypoint sequence
    current_waypoint_idx: int          # Execution progress tracker
    status: str                        # planning | planned | error (internal to graph)
    error: str | None                  # Set if planning fails
```

**Note on `status` in `PlannerState` vs `MissionStatus`:**
`PlannerState.status` is internal to the planning graph — `"planning"`
and `"error"` are transient states that never reach Neo4j. Only
`"planned"` maps to `MissionStatus.PLANNED` in the persisted mission.
If the server crashes mid-planning, the mission was never created in
Neo4j (planner runs first, persistence happens after success).

**Graph flow:**

```text
START
  │
  ▼
fetch_rooms ─── Query Neo4j for room dimensions + mission pads
  │
  ▼
validate_rooms ─── Check all requested rooms exist
  │              │
  │ (valid)      │ (invalid)
  ▼              ▼
generate_waypoints    set error ──► END
  │
  ▼
validate_plan ─── Safety checks (waypoint count, distances)
  │            │
  │ (pass)     │ (fail)
  ▼            ▼
finalize      set error ──► END
  │
  ▼
END (status = "planned", waypoints populated)
```

**Conditional routing:** `validate_rooms` and `validate_plan` use
`add_conditional_edges` — if `state["error"]` is set, route to END;
otherwise continue to next node.

**Checkpointing:** Graph compiled with `AsyncRedisSaver` from
`langgraph.checkpoint.redis.aio`. State persisted at each node.
Missions survive server restarts.

**Planning timeout:** `planner.plan()` wraps `graph.ainvoke()` in
`asyncio.wait_for(timeout=config.planning_timeout_s)`. On timeout,
returns error state.

### 6.2 Mission Lifecycle & State Transitions

```text
                create_mission
                     │
                     ▼
              ┌─── planned ───┐
              │               │
         start_mission    abort_mission
              │               │
              ▼               ▼
          executing ──► aborted
              │
        advance_mission (loop)
              │
              ▼
          completed
```

**Transition matrix (enforced by tool code):**

| From | To | Via |
| ---- | -- | --- |
| `planned` | `executing` | `start_mission` |
| `planned` | `aborted` | `abort_mission` |
| `executing` | `completed` | `advance_mission` (last waypoint) |
| `executing` | `aborted` | `abort_mission` |

**Invalid transitions return:** `{"error": "INVALID_TRANSITION", "detail": "Cannot <action> mission in '<status>' state"}`

**Terminal states:** `completed` and `aborted` — no further transitions allowed.

### 6.3 Waypoint Generation Algorithm

Rooms are visited in `room_ids` order. Within each room:

1. If room has mission pads → generate `goto_pad` waypoint for each pad (seeded order)
2. If room has no pads → generate `move forward` waypoint (distance = `min(room.depth_cm // 2, 500)`, clamped to 20-500cm range)

Full sequence:
1. `takeoff` in first room
2. Room-by-room pad visitation (or forward move fallback)
3. `land` in last room

**Room transitions:** In v1, `:CONNECTS_TO` relationships are seeded
but NOT queried by the planner. The waypoint sequence assumes the user
physically moves the drone between rooms (or that rooms are connected
in a path). Room connectivity-aware routing is a v2 feature.

### 6.4 Advisory Command Pattern

`advance_mission` returns a `suggested_command` dict alongside the
next waypoint. This tells the caller exactly which tello-mcp tool to
invoke:

```python
# Mapping: waypoint action → tello-mcp tool
"takeoff"  → {"tool": "takeoff", "args": {"room_id": waypoint.room_id}}
"land"     → {"tool": "land", "args": {}}
"move"     → {"tool": "move", "args": {"direction": ..., "distance_cm": ...}}
"rotate"   → {"tool": "rotate", "args": {"degrees": ...}}
"goto_pad" → {"tool": "detect_mission_pad", "args": {}}
"hover"    → None (no tello-mcp action needed)
```

This is an advisory-only pattern — the caller decides whether to
execute the command. The navigator never calls tello-mcp directly.

---

## 7. Mission Repository (`repository.py`)

### 7.1 Class Interface

```python
class MissionRepository:
    def __init__(self, driver: neo4j.Driver):
        ...

    # ── Writes ────────────────────────────────────────────
    def create_mission(self, mission_id, goal, room_ids, status, created_at) -> None:
    def save_waypoints(self, mission_id, waypoints: list[Waypoint]) -> None:
    def update_mission_status(self, mission_id, status, *, started_at=None, completed_at=None, error=None) -> None:

    # ── Reads ─────────────────────────────────────────────
    def get_mission(self, mission_id) -> dict | None:
    def list_missions(self, limit=10, status=None) -> list[dict]:
    def get_mission_waypoints(self, mission_id) -> list[dict]:
    def get_rooms(self, room_ids) -> list[dict]:
    def get_room_pads(self, room_ids) -> list[dict]:

    # ── Room Graph Seeding ────────────────────────────────
    def seed_room_graph(self, rooms, pads, connections) -> None:
```

### 7.2 Neo4j Graph Schema

```text
(:Mission {id, goal, status, room_ids, created_at, started_at, completed_at, error})
    │
    ├── :CONTAINS_WAYPOINT {sequence} ──► (:Waypoint {id, sequence, room_id, pad_id,
    │                                         action, direction, distance_cm, degrees})
    └── :TARGETS_ROOM ──► (:RoomNode {id, name, width_cm, depth_cm, height_cm})
                               │
                               └── :HAS_PAD ──► (:MissionPad {id, room_id, x_cm, y_cm})

(:RoomNode)-[:CONNECTS_TO {via_pad, direction, passage_type, clearance_cm}]->(:RoomNode)
(:Mission)-[:LINKED_TO_SESSION]->(:FlightSession)  // future: set during execution
(:Waypoint)-[:AT_PAD]->(:MissionPad)
```

All Neo4j calls use the sync driver. Tools invoke repository methods
via `asyncio.to_thread()` to avoid blocking the event loop.

### 7.3 Error Handling in Repository

- `seed_room_graph` uses `MERGE` (idempotent) — safe to call multiple times
- `create_mission` + `save_waypoints` are called sequentially in `create_mission` tool. If `save_waypoints` fails partway, the mission exists without all waypoints. The tool catches this and returns a structured error. A future improvement could wrap both in a Neo4j transaction.

---

## 8. Models (New in tello-core)

```python
class Waypoint(BaseModel):
    """A single step in a mission plan."""
    id: str
    sequence: int = Field(ge=0)
    room_id: str
    pad_id: int | None = None
    action: Literal["takeoff", "move", "rotate", "land", "hover", "goto_pad"]
    direction: Literal["up", "down", "left", "right", "forward", "back"] | None = None
    distance_cm: int | None = Field(default=None, ge=20, le=500)
    degrees: int | None = Field(default=None, ge=-360, le=360)


class MissionStatus(StrEnum):
    """Mission lifecycle states."""
    PLANNED = "planned"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ABORTED = "aborted"


class Mission(BaseModel):
    """A multi-step flight mission."""
    id: str
    goal: str
    status: MissionStatus = MissionStatus.PLANNED
    room_ids: list[str]
    waypoints: list[Waypoint] = []
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class Dwelling(BaseModel):
    """A physical dwelling that groups rooms."""
    id: str
    name: str
    address: str | None = None
```

**Note:** `MissionStatus` uses `StrEnum` (not `str, Enum`) for
proper string comparison (`== "planned"`) and JSON serialization.

**Existing models reused:** `RoomNode` and `MissionPad` are already
defined in tello-core. Navigator uses them for Neo4j node types and
`seed_room_graph` input validation.

**On `Dwelling`:** Defined now for forward-compatibility — groups
rooms by physical location (e.g., `arthurs-apt`). Not referenced by
any tool or repository method in v1. Added because user may move
apartments; seeding a new dwelling's rooms should not require code
changes. If this proves unnecessary, remove in a future cleanup.

Re-export all new models from `tello_core.__init__` per convention.

---

## 9. Mission Event Publisher (`events.py`)

```python
class MissionEventPublisher:
    def __init__(self, redis_client, stream="tello:missions"):
        ...

    async def publish_event(self, event_type, data: dict) -> None:
    async def mission_created(self, mission_id, goal, room_ids) -> None:
    async def mission_started(self, mission_id) -> None:
    async def waypoint_reached(self, mission_id, waypoint_id, sequence) -> None:
    async def mission_completed(self, mission_id, duration_s) -> None:
    async def mission_aborted(self, mission_id, reason) -> None:
```

Events published to `tello:missions` Redis Stream at each lifecycle
transition. All values stringified for Redis Stream compatibility.
Follows the `TelemetryPublisher.publish_event()` pattern from tello-mcp.

---

## 10. MCP Tools

### 10.1 Mission Lifecycle Tools (`tools/missions.py`)

| Tool | Read-only | Destructive | Return shape |
| ---- | --------- | ----------- | ------------ |
| `create_mission(goal, room_ids)` | No | No | `{mission_id, status, waypoint_count, waypoints}` or `{error, detail}` |
| `start_mission(mission_id)` | No | No | `{status, mission_id, current_waypoint, suggested_command, total_waypoints}` or `{error, detail}` |
| `advance_mission(mission_id, current_waypoint_idx)` | No | No | `{status, mission_id, next_waypoint, suggested_command, waypoints_remaining}` or `{status: "completed"}` or `{error, detail}` |
| `abort_mission(mission_id, reason)` | No | Yes | `{status: "aborted", mission_id}` or `{error, detail}` |

### 10.2 Query Tools (`tools/queries.py`)

| Tool | Read-only | Return shape |
| ---- | --------- | ------------ |
| `get_mission(mission_id)` | Yes | `{mission, waypoints}` or `{error, detail}` |
| `list_missions(limit, status)` | Yes | `{missions, count}` |
| `seed_room_graph(rooms, pads, connections)` | No | `{status, rooms_seeded, pads_seeded, connections_seeded}` |

All tools follow the `register(mcp)` pattern. Each tool takes
`ctx: Context` as first parameter and accesses dependencies via
`ctx.lifespan_context["key"]` (FastMCP 3.x lifespan context pattern —
the lifespan yields a dict, tools receive it via `ctx`).

**Note on `ctx: Context` (FastMCP 3.x migration):** The Phase 2 spec
text references `mcp.state["key"]` and `server.context["key"]`, but
the actual codebase was migrated to the FastMCP 3.x lifespan context
pattern: lifespan yields a dict, tools access it via
`ctx.lifespan_context["key"]`. This migration (tello-mcp + tello-telemetry)
is a bundled prerequisite for Phase 3 (see Section 12.6).

The `Context` import MUST be a runtime import
(`from fastmcp import Context`), not under `TYPE_CHECKING`, because
FastMCP needs to resolve it at runtime for dependency injection. Ruff
`TC002` is suppressed for `**/tools/**/*.py` in the root pyproject.toml.

**Async/sync bridge in all tools:** Every tool that calls a sync
`MissionRepository` method wraps it with `asyncio.to_thread()` to
avoid blocking the event loop. This applies to `create_mission`,
`start_mission`, `advance_mission`, `abort_mission`, `get_mission`,
`list_missions`, and `seed_room_graph`.

### 10.3 `create_mission` Flow

1. Generate `mission_id` (UUID)
2. Call `planner.plan(mission_id, goal, room_ids)` — runs LangGraph
3. If planner returns `status == "error"` → return `{"error": "PLANNING_FAILED", "detail": ...}`. No Neo4j writes.
4. If planner returns `status == "planned"` with waypoints:
   a. `asyncio.to_thread(repo.create_mission, ...)` — persist mission node
   b. `asyncio.to_thread(repo.save_waypoints, ...)` — persist waypoint nodes
   c. `events.mission_created(...)` — publish to Redis Stream
   d. Return `{mission_id, status, waypoint_count, waypoints}`
5. If `save_waypoints` fails → return `{"error": "PERSISTENCE_FAILED", "detail": ...}`

### 10.4 `advance_mission` Index Semantics

The `current_waypoint_idx` parameter is **caller-provided** — it tells
the navigator which waypoint the caller just completed. The navigator
does NOT track execution progress internally (no state between calls).
This is stateless by design — the caller (Claude or tello-voice) is
the execution orchestrator.

The tool increments to `current_waypoint_idx + 1` to find the next
waypoint. If `next_idx >= len(waypoints)`, the mission is complete.

### 10.5 `seed_room_graph` Input Format

```python
rooms = [
    {"id": "living", "name": "Living Room", "width_cm": 400, "depth_cm": 500, "height_cm": 234},
]
pads = [
    {"id": 1, "room_id": "living", "x_cm": 200, "y_cm": 250},
]
connections = [
    {"from_room": "living", "to_room": "kitchen", "via_pad": 2, "direction": "east"},
]
```

Room dicts match `RoomNode` model fields. Pad dicts match `MissionPad`
model fields (except `last_tof_approach_cm` and `last_visited` which
are runtime-updated). Connection dicts define `:CONNECTS_TO`
relationships between rooms.

---

## 11. Server & Lifespan (`server.py`)

```python
@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    config = TelloNavigatorConfig.from_env(service_name="tello-navigator")
    configure_structlog(config.service_name)

    redis = create_redis_client(config.redis_url)

    async with (
        neo4j_lifespan(config) as neo4j_driver,
        AsyncRedisSaver.from_conn_string(config.redis_url) as checkpointer,
    ):
        repo = MissionRepository(neo4j_driver)
        events = MissionEventPublisher(redis, config.missions_stream)
        planner = MissionPlanner(repo, config, checkpointer)

        try:
            yield {
                "repo": repo,
                "planner": planner,
                "events": events,
                "config": config,
            }
        finally:
            await redis.aclose()
```

**Lifecycle:**

1. **Startup:** Config → structlog → Redis → Neo4j + AsyncRedisSaver →
   repo + events + planner → yield lifespan context
2. **Running:** FastMCP serves tools; planner uses checkpointed graph
3. **Shutdown:** Close Neo4j (via lifespan) → close AsyncRedisSaver
   (via context manager) → close Redis

**Key difference from Phase 2:** No background consumer task — navigator
is request/response only (tools called by Claude). tello-telemetry has a
background `StreamConsumer`; navigator does not.

---

## 12. Bundled Items

Items delivered alongside tello-navigator in the Phase 3 PR:

### 12.1 tello-core Model Additions

Add `Waypoint`, `MissionStatus`, `Mission`, `Dwelling` to
`tello_core.models`. Re-export from `tello_core.__init__`. Add to
`__all__`.

### 12.2 Root `pyproject.toml` Updates

- Add `services/tello-navigator/src` to `pythonpath`
- Add `services/tello-navigator/src` to `[tool.coverage.run].source`

### 12.3 `pyproject.toml` Lint Config

Add `"RUF012", "RUF059"` to test per-file-ignores (mutable class vars
and unpacked variables in test fixtures).

### 12.4 Pre-commit Hook

Add `scripts/no-commit-to-main.sh` — blocks direct commits to `main`
branch. Enforces Issue → Worktree → PR workflow.

### 12.5 CI Matrix Update

Add `tello-navigator` to the test matrix in `.github/workflows/ci.yml`.

### 12.6 FastMCP 3.x Migration (tello-mcp + tello-telemetry)

Prerequisite bundled change: migrate tello-mcp and tello-telemetry
from `mcp.state["key"]` to `ctx.lifespan_context["key"]` pattern.
This was completed locally but not yet pushed. Changes include:

- **tello-mcp server.py:** Add lifespan context manager that yields
  `{drone, queue, redis, telemetry, config}` dict
- **tello-mcp tools:** Add `ctx: Context` param to all tools, replace
  `mcp.state["key"]` with `ctx.lifespan_context["key"]`
- **tello-telemetry server.py:** Change lifespan to `yield {"session_repo": ...}`
  instead of `server.state["session_repo"] = ...`
- **tello-telemetry tools:** Add `ctx: Context`, use `ctx.lifespan_context`
- **Tests:** Update mocks from `mcp.state = {...}` to
  `mock_ctx.lifespan_context = {...}`
- **DroneAdapter:** Accept `host` parameter for router-mode connectivity
- **Expansion board:** Add `set_led()` and `display_text()` methods
- **pyproject.toml:** Migrate `[tool.uv] dev-dependencies` to
  PEP 735 `[dependency-groups]`

This bundled change ensures all services use the same `ctx.lifespan_context`
pattern before Phase 3 tools are built on it.

---

## 13. Testing Strategy

All tests use mocked Redis, Neo4j, and LangGraph — no real connections
in unit tests.

| Module | Key test cases |
| ------ | ------------- |
| `test_config.py` | Defaults, env var overrides, frozen immutability, missing env raises ConfigurationError |
| `test_planner.py` | Each graph node independently (fetch_rooms, validate_rooms, generate_waypoints, validate_plan, finalize); full graph happy path; unknown room error path; waypoint limit exceeded |
| `test_repository.py` | Create mission, save waypoints, update status with timestamps, get/list missions, get waypoints, get rooms/pads, seed room graph |
| `test_events.py` | Each lifecycle event publishes correct fields to correct stream; values stringified |
| `test_tools/test_missions.py` | create_mission happy path + planning error; start_mission valid/not found/invalid transition; advance_mission next waypoint/completion/invalid state; abort_mission from planned/executing/invalid state |
| `test_tools/test_queries.py` | get_mission found/not found; list_missions with/without status filter; seed_room_graph calls repository |

**Target:** 50+ tests, 60%+ coverage.

---

## 14. v2 Upgrade Paths (Post-Phase 5)

- **Advisory → Autonomous execution:** New `execute_mission` tool that
  calls tello-mcp via MCP client. Built on top of advisory commands — no
  rework needed.
- **Static pads → Live detection:** tello-vision (Phase 4) feeds
  position corrections via Redis pub/sub. Planner re-queries on
  each `advance_mission`.
- **Deterministic → LLM-powered planning:** Swap `plan_route` node for
  an LLM-powered node. Graph structure unchanged.
- **Room connectivity routing:** Planner queries `:CONNECTS_TO`
  relationships for multi-room pathfinding via `shortestPath` Cypher.
