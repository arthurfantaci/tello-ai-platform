# Tello Telemetry Service — Design Specification

**Date:** 2026-03-12
**Author:** Arthur Fantaci + Claude
**Status:** Draft
**Scope:** Flight session intelligence service (Phase 2)

---

## 1. Overview

tello-telemetry is a FastMCP service that consumes the Redis Stream
written by tello-mcp, detects anomalies, persists flight session data
to Neo4j, and exposes template query tools for Claude to interrogate
session history.

**Data flow:**

```text
tello-mcp (TelemetryPublisher)
    │
    ├── PUBLISH tello:telemetry   ← real-time pub/sub (future consumers)
    └── XADD tello:events         ← durable stream
                │
        tello-telemetry (StreamConsumer)
                │
                ├── AnomalyDetector.check(frame) → [Anomaly, ...]
                ├── SessionRepository.add_sample()  ← every 5s
                ├── SessionRepository.add_anomaly()  ← on threshold breach
                └── XACK (acknowledge processed)
                        │
                    Neo4j (Session Graph)
                        │
                    Query Tools (FastMCP) → Claude
```

---

## 2. Design Decisions

| Decision | Choice | Rationale |
| -------- | ------ | --------- |
| Text2Cypher | Template queries now (C) | No LLM dependency; predefined queries become test fixtures for later Text2Cypher upgrade |
| Runtime model | FastMCP service (B) | Consumer + query tools in one process; consistent with tello-mcp pattern |
| Anomaly thresholds | Config-driven with defaults (B) | Follows `BaseServiceConfig.from_env()` pattern; tunable per-environment |
| Neo4j granularity | Session + sampled telemetry + anomalies (B) | ~120 samples + anomalies per 10-min flight; enables trends without flooding graph |
| Consumer group lifecycle | Auto-create on startup (A) | Idempotent `XGROUP CREATE`; no external setup required |
| Architecture | Monolithic consumer (A) | Right-sized for one drone at 10Hz, 10-min flights; classes still well-separated |
| Sync vs async Neo4j | Sync driver via `asyncio.to_thread()` | Sync driver more mature; `neo4j-graphrag` requires sync; infrequent writes |
| Session room_id | Optional param on tello-mcp takeoff tool | Stable interface across phases; caller gets smarter, parameter stays the same |

---

## 2.1 Room Context — Cross-Phase Integration

The `room_id` for a `FlightSession` originates as an optional parameter
on tello-mcp's `takeoff` tool (`room_id: str = "unknown"`). This design
provides a stable interface that accommodates increasing automation
across phases without breaking existing code:

| Phase | Who provides `room_id` | How |
| ----- | -------------------- | --- |
| 2 (telemetry) | User via Claude | "Take off in the living room" → Claude passes `room_id="living_room"` |
| 3 (navigator) | Mission planner | LangGraph plans a mission for room X → passes `room_id` automatically |
| 4 (vision) | CV pipeline | Drone recognizes room from visual landmarks → updates session context |
| 5 (voice) | NL parser | "Fly around the kitchen" → extracts room → routes to navigator with `room_id` |

The `room_id` flows from the takeoff tool through the Redis Stream
takeoff event into tello-telemetry's `FlightSession`. When no
`room_id` is provided, it defaults to `"unknown"`.

**Bundled change:** tello-mcp's takeoff tool gains an optional
`room_id` parameter as part of this phase (see Section 11.3).

---

## 3. Service Layout

```text
services/tello-telemetry/
├── pyproject.toml
├── src/tello_telemetry/
│   ├── __init__.py
│   ├── server.py           # FastMCP server, lifespan (starts consumer + Neo4j driver)
│   ├── config.py            # TelloTelemetryConfig(BaseServiceConfig)
│   ├── consumer.py          # Redis Stream consumer loop (XREADGROUP)
│   ├── detector.py          # Anomaly detection — threshold checks
│   ├── session_repo.py      # Neo4j read/write — sessions, samples, anomalies
│   └── tools/
│       ├── __init__.py
│       └── queries.py       # FastMCP query tools (template queries for Claude)
└── tests/
    ├── conftest.py           # mock_redis, mock_neo4j, mock_config fixtures
    ├── test_config.py
    ├── test_consumer.py
    ├── test_detector.py
    ├── test_session_repo.py
    └── test_tools/
        └── test_queries.py
```

---

## 4. Dependencies

```toml
[project]
name = "tello-telemetry"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "tello-core",
    "fastmcp>=3.0.0",
    "redis>=5.0.0",
    "neo4j>=5.15.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tello_telemetry"]

[tool.uv.sources]
tello-core = { workspace = true }
```

**Note on Pydantic:** Pydantic is not listed as a direct dependency
because it is a transitive dependency via tello-core. All shared models
(`TelemetryFrame`, `FlightSession`, `TelemetrySample`, `Anomaly`) are
Pydantic `BaseModel` subclasses defined in `tello_core.models` and
imported from there. tello-telemetry does not define new models — it
consumes the shared ones (per project convention: "Never duplicate
model definitions in services"). See Section 6.4 for how Pydantic is
used at the deserialization boundary.

---

## 5. Configuration (`config.py`)

```python
@dataclass(frozen=True, slots=True)
class TelloTelemetryConfig(BaseServiceConfig):
    # Anomaly thresholds
    battery_warning_pct: int = 20
    battery_critical_pct: int = 10
    temp_warning_c: float = 85.0
    temp_critical_c: float = 90.0
    altitude_max_cm: int = 300       # Tello TT indoor ceiling

    # Sampling
    neo4j_sample_interval_s: float = 5.0   # persist a TelemetrySample every N seconds

    # Consumer
    stream_name: str = "tello:events"
    consumer_group: str = "telemetry-service"
    consumer_name: str = "worker-1"
    batch_size: int = 10                    # messages per XREADGROUP call
    block_ms: int = 2000                    # XREADGROUP block timeout
```

All fields have sensible defaults. Override via environment variables
following `BaseServiceConfig.from_env()`.

---

## 6. Stream Consumer (`consumer.py`)

### 6.1 Class Interface

```python
class StreamConsumer:
    def __init__(
        self,
        redis: Redis,
        config: TelloTelemetryConfig,
        detector: AnomalyDetector,
        session_repo: SessionRepository,
    ):
        ...

    async def ensure_consumer_group(self) -> None:
        """Create consumer group if it doesn't exist (idempotent).

        Uses XGROUP CREATE with MKSTREAM. Catches BUSYGROUP error
        (group already exists) gracefully.
        """

    async def run(self) -> None:
        """Main consumer loop.

        1. ensure_consumer_group()
        2. Process pending messages (PEL recovery, ID=0)
        3. Read new messages (ID=>) in a loop
        """

    async def _process_message(self, msg_id: str, fields: dict) -> None:
        """Process a single stream message.

        - event_type "takeoff" → create FlightSession (fields are flat: room_id, etc.)
        - event_type "land" → end FlightSession (fields are flat)
        - event_type "telemetry" → parse frame from nested "data" JSON field,
          detect anomalies, sample to Neo4j
        """
```

### 6.2 Consumer Loop Detail

1. **`XREADGROUP`** — Read up to `batch_size` messages. Block for `block_ms` if empty.
2. **Parse** — Route on `event_type`: `"takeoff"` starts a session,
   `"land"` ends it, `"telemetry"` drives detection and sampling.
3. **Anomaly detection** — Pass each `TelemetryFrame` to `AnomalyDetector.check()`.
4. **Sampling** — If `neo4j_sample_interval_s` has elapsed since last
   persist, write `TelemetrySample` to Neo4j.
5. **Persist anomalies** — Write `Anomaly` nodes linked to current session.
6. **`XACK`** — Acknowledge after successful processing.

### 6.3 Crash Recovery

On startup, before reading new messages (`>`), the consumer reads its
Pending Entries List (PEL) by issuing `XREADGROUP` with ID `0`. This
re-delivers any messages that were received but not acknowledged before
a crash. After processing and ACKing the pending messages, it switches
to reading new messages.

### 6.4 Pydantic at the Deserialization Boundary

The Redis Stream carries raw strings. The consumer is the
**deserialization boundary** where raw data becomes validated Python
objects via Pydantic. This is where data integrity is enforced — if
tello-mcp publishes malformed data, Pydantic catches it here rather
than letting corrupt data propagate into Neo4j.

**Telemetry events** — The `data` field contains a JSON string
produced by `TelemetryFrame.model_dump_json()` in tello-mcp's
publisher. The consumer deserializes it back:

```python
frame = TelemetryFrame.model_validate_json(fields["data"])
```

`model_validate_json()` parses the JSON and validates every field
against the model's type annotations and constraints (e.g.,
`battery_pct: int`, `timestamp: datetime`). If validation fails,
Pydantic raises `ValidationError` with a detailed report of which
fields failed and why.

**Lifecycle events** (takeoff, land) — These have flat fields in the
stream entry. The consumer constructs models directly:

```python
session = FlightSession(
    id=str(uuid4()),
    start_time=datetime.now(UTC),
    room_id=fields.get("room_id", "unknown"),
)
```

Pydantic validates on construction — `room_id: str` must be a string,
`start_time: datetime` must be a valid datetime.

**Anomaly creation** — The detector returns validated Pydantic objects:

```python
Anomaly(type="battery_low", severity="warning", detail="Battery at 18%", timestamp=frame.timestamp)
```

The `severity: Literal["warning", "critical"]` constraint means
Pydantic will reject any other value at construction time — a
compile-time-like guarantee enforced at runtime.

**Error handling:** If `model_validate_json()` raises
`ValidationError`, the consumer logs the error with the raw message
data (for debugging), skips the message, and ACKs it to prevent
infinite re-delivery of a permanently invalid message. This is a
deliberate choice — a malformed message will never become valid on
retry, so re-delivery would just create an infinite loop.

---

## 7. Anomaly Detection (`detector.py`)

```python
class AnomalyDetector:
    def __init__(self, config: TelloTelemetryConfig):
        ...

    def check(self, frame: TelemetryFrame) -> list[Anomaly]:
        """Run all threshold checks. Returns empty list if nominal."""
```

**Threshold checks:**

| Check | Warning | Critical |
| ----- | ------- | -------- |
| Battery | `< battery_warning_pct` (20%) | `< battery_critical_pct` (10%) |
| Temperature | `> temp_warning_c` (85°C) | `> temp_critical_c` (90°C) |
| Altitude | — | `> altitude_max_cm` (300cm) |

The detector is stateless — a pure function (input → output, no I/O).
This follows the "Pure Core, Imperative Shell" pattern. The consumer
(imperative shell) handles I/O; the detector (pure core) handles logic.

---

## 8. Session Repository (`session_repo.py`)

### 8.1 Class Interface

```python
class SessionRepository:
    def __init__(self, driver: neo4j.Driver):
        ...

    # ── Writes (called by consumer) ────────────────────────
    def create_session(self, session: FlightSession) -> None:
    def end_session(self, session_id: str, end_time: datetime) -> None:
    def add_sample(self, session_id: str, sample: TelemetrySample) -> None:
    def add_anomaly(self, session_id: str, anomaly: Anomaly) -> None:

    # ── Reads (called by query tools) ──────────────────────
    def get_session(self, session_id: str) -> dict | None:
    def list_sessions(self, limit: int = 10) -> list[dict]:
    def get_session_samples(self, session_id: str) -> list[dict]:
    def get_session_anomalies(self, session_id: str) -> list[dict]:
    def get_anomaly_summary(self) -> list[dict]:
```

### 8.2 Neo4j Graph Schema

```text
(:FlightSession {id, start_time, end_time, duration_s, room_id, mission_id,
                  min_battery_pct, max_temp_c, anomaly_count})
    ↑                           ↑
    │ :BELONGS_TO               │ :OCCURRED_DURING
    │                           │
(:TelemetrySample             (:Anomaly
  {battery_pct, height_cm,     {type, severity,
   tof_cm, temp_c,              detail, timestamp})
   timestamp})
```

All Neo4j calls use the sync driver. The consumer invokes repository
methods via `asyncio.to_thread()` to avoid blocking the event loop.

---

## 9. Query Tools (`tools/queries.py`)

Template queries exposed as FastMCP tools with `readOnlyHint=True`:

| Tool | Description |
| ---- | ----------- |
| `list_flight_sessions(limit)` | Recent sessions with summary stats |
| `get_flight_session(session_id)` | Detailed info for one session |
| `get_session_telemetry(session_id)` | Sampled telemetry curve (battery, altitude, temp) |
| `get_session_anomalies(session_id)` | Anomalies detected during a session |
| `get_anomaly_summary()` | Anomaly counts by type across all sessions |

Tools follow the `register(mcp: FastMCP)` pattern. Each tool accesses
`SessionRepository` via `ctx.server.context["session_repo"]` and wraps
sync calls with `asyncio.to_thread()`.

---

## 10. Server & Lifespan (`server.py`)

```python
@asynccontextmanager
async def lifespan(server: FastMCP):
    config = TelloTelemetryConfig.from_env(service_name="tello-telemetry")
    configure_structlog(config.service_name)

    redis = create_redis_client(config.redis_url)
    async with neo4j_lifespan(config) as neo4j_driver:
        detector = AnomalyDetector(config)
        session_repo = SessionRepository(neo4j_driver)
        consumer = StreamConsumer(redis, config, detector, session_repo)

        server.context["session_repo"] = session_repo

        task = asyncio.create_task(consumer.run())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await redis.aclose()
```

**Lifecycle:**

1. **Startup:** Config → structlog → Redis → Neo4j → domain objects →
   background consumer task
2. **Running:** FastMCP serves query tools; consumer reads stream independently
3. **Shutdown:** Cancel consumer → close Neo4j (via lifespan) → close Redis

---

## 11. Bundled Items

Items delivered alongside tello-telemetry in the Phase 2 PR:

### 11.1 `scripts/find_drone.py` Enhancement

Auto-update `.env` with discovered drone IP. If `.env` doesn't exist,
create from `.env.example`. If `TELLO_HOST` already exists in `.env`,
update its value. Print confirmation of the change.

### 11.2 `scripts/setup_router_mode.py`

Commit as-is (currently uncommitted utility for one-time Router Mode WiFi setup).

### 11.3 tello-mcp Updates

**`TelloMcpConfig.tello_host` field:** Add
`tello_host: str = "192.168.10.1"` to tello-mcp's config. Read from
`TELLO_HOST` env var. Default is Direct Mode IP; Router Mode users
override via `.env`.

**Takeoff tool `room_id` parameter:** Add
`room_id: str = "unknown"` as an optional parameter to the takeoff
tool. Include `room_id` in the takeoff event published to the Redis
Stream. This enables tello-telemetry to tag `FlightSession` nodes
with the originating room (see Section 2.1).

### 11.4 `.env.example` Update

Add `TELLO_HOST=192.168.10.1` with comment explaining Direct Mode
(default) vs Router Mode (set to drone's IP on your network).

### 11.5 CI Matrix Update

Add `tello-telemetry` to the test matrix in `.github/workflows/ci.yml`.

### 11.6 Coverage Source Update

Add `services/tello-telemetry/src` to `[tool.coverage.run].source`
in root `pyproject.toml`.

---

## 12. Testing Strategy

All tests use mocked Redis and Neo4j — no real connections in unit tests.

| Module | Key test cases |
| ------ | ------------- |
| `test_config.py` | Defaults, env var overrides, threshold validation |
| `test_consumer.py` | Message routing (takeoff/land/telemetry), PEL recovery, XACK after processing, group auto-creation |
| `test_detector.py` | Each threshold (warning/critical), nominal frames return empty list, multiple simultaneous anomalies |
| `test_session_repo.py` | CRUD operations, session summary stats, list ordering |
| `test_queries.py` | Tool functions return expected shapes, missing session returns structured error |

The `AnomalyDetector` tests need zero mocks (pure function). Consumer
and repo tests mock the Redis client and Neo4j driver respectively.
