# Phase 4d: Containerization — tello-telemetry + HTTP Transport

**Date:** 2026-03-20
**Phase:** 4d
**Status:** Draft
**Depends on:** Phase 4c (merged, PR #25)

## Problem Statement

Physical testing of the drone requires multiple services running simultaneously: Neo4j, Redis, tello-mcp, and tello-telemetry. The current startup process is entirely manual and has caused repeated test failures:

1. **Forgotten telemetry** — tello-telemetry must be started in a separate terminal with manual env var export. It has been forgotten in multiple test sessions, resulting in zero flight data captured.
2. **Wrong branch** — `.mcp.json` runs tello-mcp from `cwd: "."`, so it executes whatever code is checked out. During Phase 4c testing, the MCP server ran main-branch code instead of the PR branch, invalidating the test.
3. **Battery drain** — Each manual startup failure burns drone battery time during troubleshooting. The battery went from 42% to 18% during today's failed test setup before a single test maneuver could complete.
4. **Env var duplication** — `.env`, `.mcp.json`, and `docker-compose.yml` contain overlapping env vars with inconsistent defaults.

## Constraints

- **Docker Desktop on macOS cannot reach the drone.** Tested and confirmed: `docker run --network host --rm alpine ping -c 3 <drone-ip>` shows 100% packet loss. Docker Desktop runs containers in a Linux VM whose host network is the VM's network, not the Mac's physical LAN. tello-mcp needs UDP access to the drone on the LAN, so it must run locally.
- **tello-mcp stays local.** Runs via `uv run` on the host, not in Docker. Communicates with Claude Code over HTTP (port 8100) instead of stdio.
- **tello-telemetry moves into Docker.** It only needs Redis and Neo4j — both already in Docker on the bridge network.
- **Scope is friction elimination, not portfolio polish.** Multi-stage Dockerfiles and health checks are included because they're best practice, but resource limits, log aggregation, and image registry publishing are deferred to a later polish pass after Phases 5 + 6.

## Design

### 1. Dockerfile for tello-telemetry

Location: `services/tello-telemetry/Dockerfile`

Multi-stage build:

**Stage 1 (builder):** Base image `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`. Copies `pyproject.toml`, `uv.lock`, `packages/tello-core/`, and `services/tello-telemetry/`. Runs `uv sync --package tello-telemetry --frozen --no-dev` to produce a `.venv` with production dependencies only.

**Stage 2 (runtime):** Base image `python:3.13-slim-bookworm`. Copies `.venv` from builder and source code from `packages/tello-core/src/` and `services/tello-telemetry/src/`. Installs `curl` for Docker healthcheck. Sets entrypoint: `python -m tello_telemetry.server --transport streamable-http --port 8200`.

### 2. .dockerignore

New file at repo root. Excludes `.git/`, `.venv/`, `__pycache__/`, `.claude/`, `docs/`, `*.pyc`, `.env`, `.mcp.json`, and test directories. Keeps the Docker build context small and prevents sensitive files from entering images.

Note: `.env` is excluded from the *build context* (not baked into the image) but is still loaded at *runtime* via `env_file: .env` in docker-compose.yml. These are independent mechanisms — `.dockerignore` controls what files Docker can see during `docker build`, while `env_file` injects environment variables when the container starts.

### 3. docker-compose.yml — add tello-telemetry

Neo4j and Redis services are unchanged. Add:

```yaml
tello-telemetry:
  build:
    context: .
    dockerfile: services/tello-telemetry/Dockerfile
  ports:
    - "8200:8200"
  env_file: .env
  environment:
    REDIS_URL: redis://redis:6379
    NEO4J_URI: bolt://neo4j:7687
  depends_on:
    redis:
      condition: service_healthy
    neo4j:
      condition: service_healthy
  healthcheck:
    test: ["CMD", "curl", "-sf", "http://localhost:8200/health"]
    interval: 10s
    timeout: 5s
    retries: 3
  restart: unless-stopped
```

`env_file: .env` loads base vars. The `environment:` block overrides `REDIS_URL` and `NEO4J_URI` to use Docker service names instead of `localhost`. This means `.env` stays unchanged for local development.

`depends_on` with `condition: service_healthy` ensures tello-telemetry starts only after Redis and Neo4j pass their existing healthchecks.

`restart: unless-stopped` auto-restarts the container on crash.

### 4. Health endpoint for tello-telemetry

Add an HTTP `/health` endpoint to the FastMCP server's ASGI app. Checks:

1. **Redis** — calls `redis_health_check()` (exists in tello-core)
2. **Neo4j** — calls `driver.verify_connectivity()`

Returns HTTP 200 `{"status": "ok", "redis": true, "neo4j": true}` when healthy, HTTP 503 when either dependency is down.

Implementation: Use FastMCP's `@mcp.custom_route("/health", methods=["GET"])` decorator to register the endpoint on the ASGI app.

### 5. .mcp.json changes

**tello-mcp:** Replace stdio config with HTTP:

```json
"tello-mcp": {
  "type": "http",
  "url": "http://localhost:8100/mcp"
}
```

tello-mcp runs locally via `uv run --package tello-mcp python -m tello_mcp.server --transport streamable-http`. Claude Code connects over HTTP. This eliminates the cwd/branch problem — the HTTP URL is branch-independent.

**Trade-off: manual startup.** With stdio, Claude Code auto-spawned tello-mcp. With HTTP, the operator must start tello-mcp before launching Claude Code. This is acceptable because a missing tello-mcp produces an immediate, visible connection error in Claude Code — unlike tello-telemetry, which fails silently (no flight data captured, no error shown).

**Env vars for manual tello-mcp startup:** Load from `.env` using the project's existing convention: `export $(grep -v '^#' .env | xargs)` before running `uv run`. The `.mcp.json` entry no longer carries env vars — they must be in the shell environment.

**tello-telemetry:** Add new entry:

```json
"tello-telemetry": {
  "type": "http",
  "url": "http://localhost:8200/mcp"
}
```

Exposes tello-telemetry's 5 query tools (flight sessions, obstacle incidents, anomalies) to Claude Code.

**neo4j and memory:** Unchanged.

### 6. BaseServiceConfig — make Neo4j optional

`BaseServiceConfig` currently requires `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` for all services. tello-mcp never opens a Neo4j connection — these vars are dead weight.

Implementation details (the `BaseServiceConfig` dataclass uses `frozen=True, slots=True`, which constrains how this works):

1. **Add `require_neo4j: ClassVar[bool] = True`** to `BaseServiceConfig`. `ClassVar` is excluded from `__slots__` generation by dataclasses, so this works with `slots=True`.
2. **Change Neo4j field types** from `str` to `str | None` with default `None`. Move them after `service_name` in field order (fields with defaults must follow fields without).
3. **Update `__post_init__`** to conditionally validate Neo4j fields: only check URI scheme and require non-empty values when `require_neo4j` is `True`.
4. **Update `from_env`** to conditionally read Neo4j env vars: when `require_neo4j` is `False`, skip `os.environ[]` lookups for `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` (pass `None` instead).

`TelloMcpConfig` overrides: `require_neo4j: ClassVar[bool] = False`.

All other service configs inherit the default `True` — no behavior change for tello-telemetry or tello-navigator.

### 7. Keepalive interval reduction (opportunistic)

Unrelated to containerization, but included as a low-risk safety improvement while touching tello-mcp config.

Change `_keepalive_loop` sleep interval in tello-mcp's `server.py` from 10 seconds to 5 seconds. The drone auto-lands after 15 seconds without a command. Reducing from 10s to 5s provides more safety margin against system load or other delays.

One-line change: `await asyncio.sleep(10)` → `await asyncio.sleep(5)`.

## Post-Phase 4d Startup

```bash
docker compose up -d    # Starts Neo4j + Redis + tello-telemetry
# Power on the drone
# Start Claude Code — connects to tello-mcp (HTTP :8100) + tello-telemetry (HTTP :8200)
```

tello-mcp must be started manually before launching Claude Code:
```bash
export $(grep -v '^#' .env | xargs)
uv run --package tello-mcp python -m tello_mcp.server --transport streamable-http
```

## Out of Scope

- **tello-mcp Dockerfile** — not needed until Linux deployment or CI. Can be added in ~30 minutes when needed.
- **Resource limits** — deferred to portfolio polish pass after Phases 5 + 6.
- **Image registry (GHCR)** — deferred. Build locally for now.
- **Log aggregation** — `docker compose logs -f` is sufficient for development.
- **Startup convenience script** — deferred. Two commands (`docker compose up -d` + Claude Code) is acceptable.
- **Phase 4e (Unified Command Path)** — separate phase, unrelated to containerization.

## Extension Points

**Phase 5 (tello-vision):** Add a new service running locally (like tello-mcp) for UDP 11111 camera stream access. Same Docker Desktop macOS limitation applies — container can't reach the drone's video stream. Same Dockerfile pattern is available for Linux deployment.

**Phase 6 (tello-voice):** Add as a bridge-network compose service. Connects to tello-mcp via HTTP — no drone network access needed.

Both phases add services to the existing compose file without rearchitecting.

## Testing

- `docker compose up -d` starts all three services, all report healthy
- `docker compose ps` shows tello-telemetry as healthy
- Claude Code connects to both HTTP MCP servers
- Fly the drone → verify FlightSession created in Neo4j with `end_time` set
- Verify tello-telemetry query tools accessible from Claude Code
