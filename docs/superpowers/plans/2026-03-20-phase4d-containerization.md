# Phase 4d: Containerization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Containerize tello-telemetry in Docker Compose and switch both MCP services to HTTP transport, eliminating the manual multi-step startup that blocks physical testing.

**Architecture:** tello-telemetry runs in Docker alongside Neo4j and Redis (bridge network). tello-mcp stays local (macOS Docker can't reach the drone via UDP). Both services use streamable-http transport. Claude Code connects to both via HTTP URLs in `.mcp.json`.

**Tech Stack:** Docker, Docker Compose, uv (multi-stage build), FastMCP 3.1.0 custom_route, Starlette

**Spec:** `docs/superpowers/specs/2026-03-20-phase4d-containerization-design.md`

---

### Task 1: Make Neo4j optional in BaseServiceConfig (TDD)

**Files:**
- Modify: `packages/tello-core/src/tello_core/config.py:1-78`
- Modify: `packages/tello-core/tests/test_config.py:1-84`
- Modify: `packages/tello-core/tests/conftest.py:1-17`

- [ ] **Step 1: Write failing tests for optional Neo4j**

Add to `packages/tello-core/tests/test_config.py`:

```python
class TestBaseServiceConfigOptionalNeo4j:
    """Tests for require_neo4j=False subclasses."""

    def test_subclass_without_neo4j_from_env(self, monkeypatch):
        """A subclass with require_neo4j=False should not require NEO4J_* vars."""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        monkeypatch.delenv("NEO4J_URI", raising=False)
        monkeypatch.delenv("NEO4J_USERNAME", raising=False)
        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

        @dataclass(frozen=True, slots=True)
        class NoNeo4jConfig(BaseServiceConfig):
            require_neo4j: ClassVar[bool] = False

        config = NoNeo4jConfig.from_env(service_name="test")
        assert config.neo4j_uri is None
        assert config.neo4j_username is None
        assert config.neo4j_password is None
        assert config.redis_url == "redis://localhost:6379"

    def test_subclass_without_neo4j_accepts_neo4j_if_provided(self, env_vars):
        """When Neo4j vars ARE set, they should still be loaded."""
        @dataclass(frozen=True, slots=True)
        class NoNeo4jConfig(BaseServiceConfig):
            require_neo4j: ClassVar[bool] = False

        config = NoNeo4jConfig.from_env(service_name="test")
        assert config.neo4j_uri == "bolt://localhost:7687"

    def test_base_class_still_requires_neo4j(self, monkeypatch):
        """Default require_neo4j=True behavior unchanged."""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        monkeypatch.delenv("NEO4J_URI", raising=False)
        with pytest.raises(ConfigurationError, match="NEO4J_URI"):
            BaseServiceConfig.from_env(service_name="test")
```

Add imports at top of test file:
```python
from dataclasses import dataclass
from typing import ClassVar
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package tello-core pytest packages/tello-core/tests/test_config.py::TestBaseServiceConfigOptionalNeo4j -v`
Expected: FAIL — `ClassVar` not recognized, fields are required

- [ ] **Step 3: Implement optional Neo4j in BaseServiceConfig**

Modify `packages/tello-core/src/tello_core/config.py`:

```python
from typing import ClassVar, Self

@dataclass(frozen=True, slots=True)
class BaseServiceConfig:
    """Base configuration shared by all platform services."""

    require_neo4j: ClassVar[bool] = True

    redis_url: str
    service_name: str
    neo4j_uri: str | None = None
    neo4j_username: str | None = None
    neo4j_password: str | None = None
    neo4j_max_connection_pool_size: int = 5
    neo4j_connection_acquisition_timeout: float = 30.0

    @classmethod
    def from_env(cls, **overrides: str | int | float | bool) -> Self:
        """Load configuration from environment variables."""
        values: dict[str, str | None] = {}

        # Redis is always required
        if "redis_url" in overrides:
            values["redis_url"] = overrides.pop("redis_url")
        else:
            val = os.environ.get("REDIS_URL")
            if val is None:
                msg = "Required environment variable REDIS_URL is not set"
                raise ConfigurationError(msg)
            values["redis_url"] = val

        # Neo4j is conditional on require_neo4j
        neo4j_fields = {
            "neo4j_uri": "NEO4J_URI",
            "neo4j_username": "NEO4J_USERNAME",
            "neo4j_password": "NEO4J_PASSWORD",
        }
        for field, env_var in neo4j_fields.items():
            if field in overrides:
                values[field] = overrides.pop(field)
            else:
                val = os.environ.get(env_var)
                if val is None and cls.require_neo4j:
                    msg = f"Required environment variable {env_var} is not set"
                    raise ConfigurationError(msg)
                values[field] = val

        return cls(**values, **overrides)

    def __post_init__(self) -> None:
        """Fail-fast validation."""
        if self.neo4j_uri is not None:
            if not any(self.neo4j_uri.startswith(s) for s in VALID_NEO4J_SCHEMES):
                msg = f"Neo4j URI must start with one of {VALID_NEO4J_SCHEMES}, got: {self.neo4j_uri}"
                raise ConfigurationError(msg)
        if not any(self.redis_url.startswith(s) for s in VALID_REDIS_SCHEMES):
            msg = f"Redis URL must start with one of {VALID_REDIS_SCHEMES}, got: {self.redis_url}"
            raise ConfigurationError(msg)
        if not self.service_name:
            msg = "service_name must be non-empty"
            raise ConfigurationError(msg)
```

- [ ] **Step 4: Verify existing tests and downstream code**

The field order changed: `redis_url` and `service_name` are now before the Neo4j fields. Verify:
- All `BaseServiceConfig(...)` constructor calls use keyword arguments (they already do — confirm no positional args)
- The `mock_config` fixture in `services/tello-mcp/tests/conftest.py` still works (it passes Neo4j values via kwargs — should be fine)
- No downstream code calls `config.neo4j_uri` without handling `None` when `require_neo4j=False` (tello-mcp never opens a Neo4j connection, so this should be safe)

- [ ] **Step 5: Run all tello-core tests**

Run: `uv run --package tello-core pytest packages/tello-core/tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Set require_neo4j = False on TelloMcpConfig**

Modify `services/tello-mcp/src/tello_mcp/config.py`, add import and class var:

```python
from typing import ClassVar, Self
```

Add to `TelloMcpConfig` class body:
```python
    require_neo4j: ClassVar[bool] = False
```

- [ ] **Step 7: Run tello-mcp tests to verify no regression**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/ -v`
Expected: ALL PASS

- [ ] **Step 8: Run all tests across workspace**

Run: `uv run --package tello-core pytest packages/tello-core/tests/ -v && uv run --package tello-mcp pytest services/tello-mcp/tests/ -v && uv run --package tello-telemetry pytest services/tello-telemetry/tests/ -v && uv run --package tello-navigator pytest services/tello-navigator/tests/ -v`
Expected: ALL PASS (334+ tests)

- [ ] **Step 9: Commit**

```bash
git add packages/tello-core/src/tello_core/config.py packages/tello-core/tests/test_config.py services/tello-mcp/src/tello_mcp/config.py
git commit -m "refactor: make Neo4j optional in BaseServiceConfig"
```

---

### Task 2: Add health endpoint to tello-telemetry (TDD)

**Files:**
- Modify: `services/tello-telemetry/src/tello_telemetry/server.py:1-95`
- Create: `services/tello-telemetry/tests/test_health.py`

- [ ] **Step 1: Write failing test for health endpoint**

Create `services/tello-telemetry/tests/test_health.py`:

```python
"""Tests for tello-telemetry health endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from tello_telemetry.server import mcp


class TestHealthEndpoint:
    @pytest.fixture()
    def client(self):
        """Create a Starlette test client from the FastMCP HTTP app."""
        app = mcp.http_app()
        return TestClient(app)

    def test_health_returns_200_when_healthy(self, client, monkeypatch):
        """Health endpoint returns 200 with redis=true, neo4j=true."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_neo4j = MagicMock()
        mock_neo4j.verify_connectivity = MagicMock(return_value=None)

        monkeypatch.setattr(
            "tello_telemetry.server._health_deps",
            lambda: (mock_redis, mock_neo4j),
        )

        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["redis"] is True
        assert data["neo4j"] is True

    def test_health_returns_503_when_redis_down(self, client, monkeypatch):
        """Health endpoint returns 503 when Redis is unreachable."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("refused"))
        mock_neo4j = MagicMock()
        mock_neo4j.verify_connectivity = MagicMock(return_value=None)

        monkeypatch.setattr(
            "tello_telemetry.server._health_deps",
            lambda: (mock_redis, mock_neo4j),
        )

        response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["redis"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_health.py -v`
Expected: FAIL — `_health_deps` does not exist, no `/health` route

- [ ] **Step 3: Implement health endpoint**

Modify `services/tello-telemetry/src/tello_telemetry/server.py`. Add imports at top:

```python
from starlette.requests import Request
from starlette.responses import JSONResponse
```

Add a module-level variable and helper after the `mcp` definition:

```python
_redis_client = None
_neo4j_driver = None


def _health_deps():
    """Return (redis, neo4j) clients for health check. Overridable for testing."""
    return (_redis_client, _neo4j_driver)
```

Add the health route after `queries.register(mcp)`:

```python
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for Docker healthcheck."""
    redis, neo4j = _health_deps()
    redis_ok = False
    neo4j_ok = False

    if redis is not None:
        try:
            await redis.ping()
            redis_ok = True
        except Exception:
            pass

    if neo4j is not None:
        try:
            # verify_connectivity() is sync but fast; acceptable for infrequent health checks
            neo4j.verify_connectivity()
            neo4j_ok = True
        except Exception:
            pass

    healthy = redis_ok and neo4j_ok
    status_code = 200 if healthy else 503
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", "redis": redis_ok, "neo4j": neo4j_ok},
        status_code=status_code,
    )
```

Update the `lifespan` function to set and clean up module-level clients:

```python
    redis = create_redis_client(config.redis_url)
    global _redis_client  # noqa: PLW0603
    _redis_client = redis
    async with neo4j_lifespan(config) as neo4j_driver:
        global _neo4j_driver  # noqa: PLW0603
        _neo4j_driver = neo4j_driver
        # ... existing yield and finally ...
        # Add to the finally block, after await redis.aclose():
        _redis_client = None
        _neo4j_driver = None
```

- [ ] **Step 4: Run health tests**

Run: `uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_health.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run all tello-telemetry tests**

Run: `uv run --package tello-telemetry pytest services/tello-telemetry/tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add services/tello-telemetry/src/tello_telemetry/server.py services/tello-telemetry/tests/test_health.py
git commit -m "feat: add /health endpoint to tello-telemetry"
```

---

### Task 3: Create Dockerfile and .dockerignore

**Files:**
- Create: `services/tello-telemetry/Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Create .dockerignore**

Create `.dockerignore` at repo root:

```
.git/
.venv/
__pycache__/
*.pyc
*.pyo
.claude/
docs/
.env
.mcp.json
.ruff_cache/
.pytest_cache/
*.egg-info/
**/tests/
**/test_*/
.gitignore
*.md
LICENSE
```

- [ ] **Step 2: Create Dockerfile for tello-telemetry**

Create `services/tello-telemetry/Dockerfile`:

```dockerfile
# Stage 1: Build dependencies with uv
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

# Copy workspace root files for dependency resolution
COPY pyproject.toml uv.lock ./

# Copy only the packages needed by tello-telemetry
COPY packages/tello-core/ packages/tello-core/
COPY services/tello-telemetry/ services/tello-telemetry/

# Install production dependencies only
RUN uv sync --package tello-telemetry --frozen --no-dev

# Stage 2: Slim runtime image
FROM python:3.13-slim-bookworm

WORKDIR /app

# Install curl for Docker healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy source code
COPY packages/tello-core/src/ packages/tello-core/src/
COPY services/tello-telemetry/src/ services/tello-telemetry/src/

# Activate venv
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8200

ENTRYPOINT ["python", "-m", "tello_telemetry.server", "--transport", "streamable-http", "--port", "8200"]
```

- [ ] **Step 3: Test the Docker build**

Run: `docker compose build tello-telemetry`
Expected: Build succeeds (will fail because compose doesn't have the service yet — that's Task 4. Build standalone instead.)

Run: `docker build -f services/tello-telemetry/Dockerfile -t tello-telemetry:test .`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add .dockerignore services/tello-telemetry/Dockerfile
git commit -m "feat: add Dockerfile and .dockerignore for tello-telemetry"
```

---

### Task 4: Add tello-telemetry to docker-compose.yml

**Files:**
- Modify: `docker-compose.yml:1-31`

- [ ] **Step 1: Add tello-telemetry service to docker-compose.yml**

Add after the `redis` service block, before the `volumes` block:

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

- [ ] **Step 2: Build and start all services**

Run: `docker compose up -d --build`
Expected: All 3 services start. tello-telemetry waits for redis + neo4j health.

- [ ] **Step 3: Verify tello-telemetry is healthy**

Run: `docker compose ps`
Expected: tello-telemetry shows "healthy" status

Run: `curl -s http://localhost:8200/health | python3 -m json.tool`
Expected: `{"status": "ok", "redis": true, "neo4j": true}`

- [ ] **Step 4: Verify tello-telemetry MCP endpoint responds**

Run: `curl -s -X POST http://localhost:8200/mcp -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}},"id":1}'`
Expected: JSON response with server capabilities

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add tello-telemetry to Docker Compose"
```

---

### Task 5: Update .mcp.json to HTTP transport

**Files:**
- Modify: `.mcp.json:1-37`

- [ ] **Step 1: Update .mcp.json**

Replace entire file content:

```json
{
  "mcpServers": {
    "neo4j": {
      "type": "stdio",
      "command": "neo4j-mcp",
      "args": ["--neo4j-read-only", "true"],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "${NEO4J_PASSWORD:-claude-code-memory}"
      }
    },
    "memory": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-neo4j-memory"],
      "env": {
        "NEO4J_URI": "bolt://localhost:7689",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "${NEO4J_PASSWORD:-claude-code-memory}"
      }
    },
    "tello-mcp": {
      "type": "http",
      "url": "http://localhost:8100/mcp"
    },
    "tello-telemetry": {
      "type": "http",
      "url": "http://localhost:8200/mcp"
    }
  }
}
```

- [ ] **Step 2: Verify .env contains all tello-mcp env vars**

Since `.mcp.json` no longer passes env vars to tello-mcp, they must be in `.env`. Verify `.env` contains:
- `REDIS_URL=redis://localhost:6379`
- `TELLO_HOST=auto` (critical — without this, tello-mcp falls back to `192.168.10.1` which is the direct WiFi default, not Router Mode)

- [ ] **Step 3: Commit**

```bash
git add .mcp.json
git commit -m "feat: switch tello-mcp to HTTP, add tello-telemetry to .mcp.json"
```

---

### Task 6: Reduce keepalive interval (opportunistic)

**Files:**
- Modify: `services/tello-mcp/src/tello_mcp/server.py:30-35`

- [ ] **Step 1: Change keepalive interval**

In `services/tello-mcp/src/tello_mcp/server.py`, change line 33:

```python
# Before
        await asyncio.sleep(10)
# After
        await asyncio.sleep(5)
```

Also update the docstring on line 31:
```python
# Before
    """Send keepalive every 10s to prevent 15s auto-land timeout."""
# After
    """Send keepalive every 5s to prevent 15s auto-land timeout."""
```

- [ ] **Step 2: Run tello-mcp tests**

Run: `uv run --package tello-mcp pytest services/tello-mcp/tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add services/tello-mcp/src/tello_mcp/server.py
git commit -m "fix: reduce keepalive interval from 10s to 5s for safety margin"
```

---

### Task 7: Full verification

**Files:** None (verification only)

- [ ] **Step 1: Run all tests across workspace**

Run: `uv run --package tello-core pytest packages/tello-core/tests/ -v && uv run --package tello-mcp pytest services/tello-mcp/tests/ -v && uv run --package tello-telemetry pytest services/tello-telemetry/tests/ -v && uv run --package tello-navigator pytest services/tello-navigator/tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Run lint**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: Clean

- [ ] **Step 3: Rebuild and verify Docker stack**

Run: `docker compose down && docker compose up -d --build`
Expected: All 3 services healthy

Run: `docker compose ps`
Expected: neo4j (healthy), redis (healthy), tello-telemetry (healthy)

Run: `curl -s http://localhost:8200/health | python3 -m json.tool`
Expected: `{"status": "ok", "redis": true, "neo4j": true}`

- [ ] **Step 4: Verify tello-telemetry logs**

Run: `docker compose logs tello-telemetry --tail 20`
Expected: structlog JSON output showing startup, Redis connection, Neo4j connection, consumer group creation

---

### Task 8: Create PR

- [ ] **Step 1: Create PR**

Include the spec document in the PR branch (unstash or re-add if needed).

```bash
git add docs/superpowers/specs/2026-03-20-phase4d-containerization-design.md docs/superpowers/plans/2026-03-20-phase4d-containerization.md
git commit -m "docs: Phase 4d spec and implementation plan"
```

Create PR:
```bash
gh pr create --title "feat: Phase 4d — containerize tello-telemetry + HTTP transport" --body "$(cat <<'EOF'
## Summary

- Add tello-telemetry to Docker Compose (Dockerfile + health endpoint)
- Switch tello-mcp to HTTP transport in .mcp.json (eliminates branch/cwd problem)
- Add tello-telemetry query tools to .mcp.json
- Make Neo4j optional in BaseServiceConfig (tello-mcp doesn't use it)
- Reduce keepalive interval from 10s to 5s

Closes #TBD

## Post-merge startup

```bash
docker compose up -d    # Neo4j + Redis + tello-telemetry
export $(grep -v '^#' .env | xargs)
uv run --package tello-mcp python -m tello_mcp.server --transport streamable-http
# Then start Claude Code
```

## Test plan

- [ ] All unit tests pass (334+)
- [ ] Lint clean
- [ ] `docker compose up -d --build` starts all 3 services healthy
- [ ] `curl http://localhost:8200/health` returns 200
- [ ] tello-telemetry MCP endpoint responds
- [ ] Physical flight test: FlightSession + ObstacleIncident in Neo4j

EOF
)"
```

Expected: PR created, CI runs
