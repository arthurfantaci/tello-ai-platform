# Phase 3: tello-navigator — LangGraph Mission Planner

## 1. Goal

The drone platform can fly and record telemetry, but has no concept of *missions* — multi-step, goal-oriented flight plans. tello-navigator adds the planning layer: it receives high-level mission goals (e.g., "patrol rooms A and B"), decomposes them into ordered waypoints, persists plans in Neo4j, and tracks execution state via LangGraph with Redis checkpointing. This is the "brain" that turns intent into structured action sequences.

## 2. Scope

### In scope (this iteration)

- **Mission models** — new Pydantic models in tello-core: `Mission`, `Waypoint`, `MissionStatus`
- **MissionRepository** — Neo4j CRUD for missions, waypoints, room graph queries
- **MissionPlanner** — LangGraph `StateGraph` that plans routes through known rooms/mission pads
- **Redis checkpointing** — `langgraph-checkpoint-redis` for durable graph state
- **Mission lifecycle events** — publish to Redis Stream (`tello:missions`) for observability
- **MCP tools** (5-6 tools):
  - `create_mission` — plan a mission from a goal description and room list
  - `get_mission` — retrieve mission details by ID
  - `list_missions` — list recent missions with status filters
  - `start_mission` — transition mission to "executing" state, return first waypoint
  - `advance_mission` — mark current waypoint done, return next (or complete mission)
  - `abort_mission` — cancel an in-progress mission
- **FastMCP server** — same patterns as tello-mcp/tello-telemetry (lifespan, transport, structlog)
- **Room graph seeding** — tool or utility to populate rooms + mission pads in Neo4j

### Out of scope (future iterations)

- Autonomous execution (navigator calling tello-mcp tools directly)
- Real-time replanning from live telemetry (subscribe to `tello:telemetry`)
- LLM-powered goal decomposition (missions are rule-based for now)
- Multi-drone coordination
- Visual waypoint detection (tello-vision dependency)

## 3. Design

### 3.1 Data Flow

```
User / tello-voice (future)
    │
    ▼
tello-navigator MCP tools
    │
    ├─── MissionPlanner (LangGraph StateGraph)
    │       │
    │       ├── query_rooms ──► Neo4j (room graph)
    │       ├── plan_route ──► waypoint generation
    │       ├── validate ──► safety checks (battery, room bounds)
    │       └── checkpoint ──► Redis (langgraph-checkpoint-redis)
    │
    ├─── MissionRepository ──► Neo4j (mission CRUD)
    │
    └─── Redis Stream (tello:missions)
            │
            ▼
        tello-telemetry (future: link sessions to missions)
```

### 3.2 Module Boundaries

```
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
│       └── queries.py           # Read-only query tools (get, list, room graph)
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

### 3.3 LangGraph StateGraph Design

The planner is a **deterministic** graph (no LLM calls in v1). It uses LangGraph for structured state management, checkpointing, and future extensibility (LLM-powered planning in v2).

#### Graph State

```python
class PlannerState(TypedDict):
    mission_id: str
    goal: str                          # Human-readable goal
    room_ids: list[str]                # Target rooms to visit
    rooms: list[dict]                  # Fetched room data from Neo4j
    mission_pads: list[dict]           # Available pads in target rooms
    waypoints: list[dict]              # Generated waypoint sequence
    current_waypoint_idx: int          # Execution progress tracker
    status: str                        # planning | planned | executing | completed | aborted
    error: str | None                  # Set if planning fails
```

#### Graph Nodes

```
START
  │
  ▼
fetch_rooms ─── Query Neo4j for room dimensions + mission pads
  │
  ▼
validate_rooms ─── Check all requested rooms exist, have pads
  │              │
  │ (valid)      │ (invalid)
  ▼              ▼
plan_route      set_error ──► END
  │
  ▼
generate_waypoints ─── Create ordered waypoint list with commands
  │
  ▼
validate_plan ─── Safety checks (reasonable distances, pad coverage)
  │            │
  │ (pass)     │ (fail)
  ▼            ▼
finalize      set_error ──► END
  │
  ▼
END (status = "planned", waypoints populated)
```

#### Why LangGraph for a deterministic graph?

1. **Checkpointing** — mission state survives service restarts (Redis-backed)
2. **State machine semantics** — clear node/edge contracts, easy to test each node
3. **Future LLM integration** — swap `plan_route` for an LLM-powered node without restructuring
4. **Human-in-the-loop** — add approval breakpoints between plan and execute (LangGraph native feature)
5. **Observability** — LangGraph provides execution traces

### 3.4 Neo4j Schema Additions

```cypher
// New node types
(:Mission {id, goal, status, created_at, started_at, completed_at, error})
(:Waypoint {id, sequence, room_id, pad_id, action, distance_cm, direction})

// New relationships
(:Mission)-[:CONTAINS_WAYPOINT {sequence: int}]->(:Waypoint)
(:Mission)-[:TARGETS_ROOM]->(:RoomNode)
(:Mission)-[:LINKED_TO_SESSION]->(:FlightSession)  // future: link execution
(:Waypoint)-[:AT_PAD]->(:MissionPad)

// Existing nodes reused
(:RoomNode {id, name, width_cm, depth_cm, height_cm})
(:MissionPad {id, room_id, x_cm, y_cm})
(:RoomNode)-[:HAS_PAD]->(:MissionPad)
(:RoomNode)-[:CONNECTS_TO {via_pad: int}]->(:RoomNode)  // doorway/transition
```

### 3.5 Config

```python
@dataclass(frozen=True, slots=True)
class TelloNavigatorConfig(BaseServiceConfig):
    missions_stream: str = "tello:missions"       # Redis Stream for events
    max_waypoints_per_mission: int = 20            # Safety limit
    default_move_distance_cm: int = 100            # Default step size
    planning_timeout_s: float = 30.0               # Max time for planning graph
    checkpoint_ttl_hours: int = 24                  # Redis checkpoint expiry
```

### 3.6 Mission Lifecycle

```
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

Events published to `tello:missions` stream at each transition:
- `mission_created` — `{mission_id, goal, room_ids}`
- `mission_started` — `{mission_id}`
- `waypoint_reached` — `{mission_id, waypoint_id, sequence}`
- `mission_completed` — `{mission_id, duration_s}`
- `mission_aborted` — `{mission_id, reason}`

### 3.7 Server Lifespan

```python
@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[None]:
    config = TelloNavigatorConfig.from_env(service_name="tello-navigator")
    configure_structlog(config.service_name)

    redis = create_redis_client(config.redis_url)
    checkpointer = RedisSaver.from_conn_string(config.redis_url)
    checkpointer.setup()

    async with neo4j_lifespan(config) as neo4j_driver:
        repo = MissionRepository(neo4j_driver)
        events = MissionEventPublisher(redis, config.missions_stream)
        planner = MissionPlanner(repo, checkpointer, config)

        server.state["repo"] = repo
        server.state["planner"] = planner
        server.state["events"] = events
        server.state["config"] = config

        try:
            yield
        finally:
            await redis.aclose()
```

## 4. Models (New in tello-core)

```python
# ── Navigation Layer (additions) ─────────────────────────────────────

class Waypoint(BaseModel):
    """A single step in a mission plan."""
    id: str
    sequence: int = Field(ge=0)
    room_id: str
    pad_id: int | None = None            # Target mission pad (if applicable)
    action: Literal["takeoff", "move", "rotate", "land", "hover", "goto_pad"]
    direction: Literal["up", "down", "left", "right", "forward", "back"] | None = None
    distance_cm: int | None = Field(default=None, ge=20, le=500)
    degrees: int | None = Field(default=None, ge=-360, le=360)


class MissionStatus(str, Enum):
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
    room_ids: list[str]                    # Rooms this mission targets
    waypoints: list[Waypoint] = []
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
```

## 5. Testing Strategy

### Unit tests (~40 tests targeting 60%+ coverage)

| Module | What to test | How |
|---|---|---|
| `config.py` | Defaults, env override, validation | Direct instantiation, mock env |
| `planner.py` | Each graph node independently + full graph run | Mock repository, invoke nodes with test state |
| `repository.py` | CRUD operations, query correctness | Mock Neo4j driver/session |
| `events.py` | Event publishing, field serialization | Mock Redis, verify XADD calls |
| `tools/missions.py` | Tool return shapes, status transitions, error cases | Mock planner/repo/events in `mcp.state` |
| `tools/queries.py` | Query tools return correct structures | Mock repo |

### Key test scenarios

- **Happy path**: create mission with valid rooms → status = planned, waypoints generated
- **Unknown room**: create mission referencing non-existent room → structured error
- **State transitions**: planned → executing → completed, planned → aborted, executing → aborted
- **Invalid transitions**: completed → executing (should error)
- **Waypoint limit**: mission exceeding `max_waypoints_per_mission` → error
- **Empty rooms**: room with no mission pads → planner handles gracefully
- **Checkpoint persistence**: planner state survives mock restart (test checkpointer integration)

### Infrastructure updates

- Add `services/tello-navigator/src` to root `pyproject.toml` (pythonpath + coverage source)
- Add `tello-navigator` to CI test matrix
- Target: 45+ tests, 60%+ coverage

## 6. Dependencies

```toml
# services/tello-navigator/pyproject.toml
dependencies = [
    "tello-core",
    "langgraph>=0.4",
    "langgraph-checkpoint-redis>=0.3",
    "redis>=5.0",
    "mcp[cli]>=1.9",
    "structlog>=24.0",
]
```

## 7. Open Questions

1. **Room graph bootstrap**: How should rooms and mission pads be seeded into Neo4j? Options:
   - (a) An MCP tool `seed_room_graph(rooms, pads)` on tello-navigator
   - (b) A standalone script `scripts/seed_rooms.py`
   - (c) A Cypher file `scripts/seed_rooms.cypher` loaded via Neo4j Browser
   - **Recommendation**: (a) — keeps it in the MCP tool ecosystem, Claude can call it

2. **Execution model**: This iteration makes the navigator a *planner only* — `advance_mission` just tracks state, it doesn't send commands to the drone. Should we:
   - (a) Keep it pure planning (user/voice service calls tello-mcp separately)
   - (b) Add a `execute_waypoint` tool that returns the tello-mcp command to run (advisory)
   - (c) Have navigator call tello-mcp via MCP client (autonomous execution)
   - **Recommendation**: (b) for this iteration — advisory commands, no direct drone control

3. **Room connectivity**: How do we represent room-to-room transitions? The current `RoomNode` model has no "connects to" relationship. Options:
   - (a) `(:RoomNode)-[:CONNECTS_TO {via_pad: int, direction: str}]->(:RoomNode)` in Neo4j
   - (b) Explicit `RoomConnection` model in tello-core
   - **Recommendation**: (a) — Neo4j relationship, no extra model needed

4. **Mission pad detection integration**: Currently `detect_mission_pad()` is a tello-mcp tool. Should navigator query pad detection results from telemetry, or is static room graph data enough for v1?
   - **Recommendation**: Static data for v1. Live pad detection feeds into v2 replanning.

5. **LangGraph async vs sync**: LangGraph supports both. tello-navigator is async throughout (like other services). Use `AsyncRedisSaver` if available, or wrap sync `RedisSaver` with `asyncio.to_thread()`.

## 8. Estimated Scope

- **New files**: ~12 (src + tests)
- **Modified files**: ~3 (tello-core models.py, root pyproject.toml, CI config)
- **New tests**: ~45
- **New dependencies**: langgraph, langgraph-checkpoint-redis
