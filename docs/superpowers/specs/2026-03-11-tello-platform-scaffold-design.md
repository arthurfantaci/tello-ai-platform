# Tello AI Platform — Project Scaffold & Claude Code Configuration Design

**Date:** 2026-03-11
**Author:** Arthur Fantaci + Claude
**Status:** Approved (2026-03-12)
**Scope:** Monorepo scaffold (root + tello-core + tello-mcp) and Claude Code
configuration with phased evolution plan

---

## 1. Overview

Stand up the tello-ai-platform as a uv workspace monorepo with:

- Root workspace infrastructure (pyproject.toml, docker-compose, CI, dev tooling)
- `tello-core` shared library (models, config, exceptions, Redis/Neo4j factories)
- `tello-mcp` fully scaffolded service (FastMCP hardware abstraction)
- Placeholder pyproject.toml for the remaining 4 services
- Complete Claude Code configuration (CLAUDE.md, skills, commands, MCP servers, hooks)
- VS Code workspace configuration adapted from the reference implementation

**Reference implementation:** `~/Projects/requirements-graphrag-api` — carries over
dev experience (uv, Ruff, ty, pytest, structlog, VS Code, pre-commit, CI patterns)
but NOT application architecture.

**What does NOT carry over:** routes/core/guardrails directory structure,
GraphRAG-specific patterns, auth system, evaluation pipeline.
Each service's internal layout matches its actual architecture.

---

## 2. Design Decisions

| Decision | Choice | Rationale |
| -------- | ------ | --------- |
| Monorepo structure | Adapted template (B) | Services have different architectures; shared conventions, per-service layouts |
| tello-core scope | Hybrid observability (C) | Base config helpers + exceptions in core; services extend with domain-specific config |
| Docker strategy | Infrastructure only (A) | Neo4j + Redis in Docker; services run locally via `uv run` for fast iteration |
| Claude Code config | Interleaved with plan (C) | CLAUDE.md exists before implementation; MCP servers/skills added per-phase |
| Python toolchain | All-Astral | uv (packages) + Ruff (lint/format) + ty (type checker) |
| Type checking | ty advisory → blocking | Start with `continue-on-error: true` in CI, tighten as codebase matures |

---

## 3. Monorepo Root Structure

```text
tello-ai-platform/
├── pyproject.toml              # uv workspace root
├── uv.lock                     # single lockfile for entire workspace
├── docker-compose.yml          # Neo4j 5.x + Redis 8.0 (infrastructure only)
├── .env.example                # template for required environment variables
├── .gitignore                  # monorepo-adapted (see Section 15)
├── .mcp.json                   # MCP server configuration (see Section 8.3)
├── .pre-commit-config.yaml     # Ruff + standard hooks (workspace-aware)
├── CLAUDE.md                   # global behavioral conventions
├── MEMORY.md                   # current working state
│
├── .vscode/
│   ├── settings.json           # workspace Python + Ruff + pytest
│   ├── extensions.json         # recommended extensions
│   └── launch.json             # debug configs per service
│
├── .claude/
│   ├── settings.json           # plugins, hooks
│   ├── commands/               # implement, plan, review, test
│   └── skills/                 # project-specific skills
│
├── .github/
│   └── workflows/
│       └── ci.yml              # lint + test (matrix per service)
│
├── mission-pads/               # printable TT pad layouts (SVG)
│
├── packages/
│   └── tello-core/             # shared library
│       ├── pyproject.toml
│       └── src/tello_core/
│           ├── __init__.py
│           ├── models.py       # shared Pydantic models
│           ├── config.py       # BaseServiceConfig + configure_structlog()
│           ├── exceptions.py   # TelloError hierarchy
│           ├── redis_client.py # shared AsyncRedis factory
│           └── neo4j_client.py # shared driver lifespan helper
│
├── services/
│   ├── tello-mcp/              # ← fully scaffolded
│   │   ├── pyproject.toml
│   │   ├── src/tello_mcp/
│   │   └── tests/
│   ├── tello-navigator/        # ← placeholder only
│   │   └── pyproject.toml
│   ├── tello-vision/           # ← placeholder only
│   │   └── pyproject.toml
│   ├── tello-voice/            # ← placeholder only
│   │   └── pyproject.toml
│   └── tello-telemetry/        # ← placeholder only
│       └── pyproject.toml
│
└── docs/
    └── architecture.md         # platform overview generated from plan v2.0 (service roles, Neo4j schemas, Redis capabilities, build order)
```

---

## 4. Root pyproject.toml

```toml
[project]
name = "tello-ai-platform"
version = "0.1.0"
requires-python = ">=3.13"

[tool.uv.workspace]
members = [
    "packages/tello-core",
    "services/tello-mcp",
    "services/tello-navigator",
    "services/tello-vision",
    "services/tello-voice",
    "services/tello-telemetry",
]

[tool.uv]
dev-dependencies = [
    "ruff>=0.6.0",
    "ty>=0.0.8",
    "pre-commit>=4.0.0",
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0",
    "pytest-mock>=3.12.0",
]

[tool.ruff]
line-length = 100
target-version = "py313"
src = ["packages/*/src", "services/*/src", "services/*/tests"]

[tool.ruff.lint]
select = [
    "E", "W", "F", "I", "N", "D", "UP", "ANN", "S", "B",
    "C4", "SIM", "TCH", "RUF", "TRY", "EM", "PIE", "PT",
    "RET", "ARG", "PL",
]
ignore = [
    "D100", "D104", "D107", "ANN401", "S101",
    "TRY003", "TRY300", "TRY400", "TRY401",
    "EM101", "EM102", "RET504",
    "PLR0913", "PLR0911", "PLR0912", "PLR0915", "PLR2004",
    "PLC0415", "PLW0603", "PLR1714", "ARG001",
]

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.lint.per-file-ignores]
"**/tests/**/*.py" = [
    "S101", "S105", "S311", "SIM117",
    "ANN", "D", "PLR2004", "ARG", "PT",
]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.ty]
python-version = "3.13"

[tool.pytest.ini_options]
testpaths = ["packages", "services"]
asyncio_mode = "auto"
addopts = ["-ra", "-q"]

[tool.coverage.run]
source = ["packages/tello-core/src", "services/tello-mcp/src"]  # expand as services are added
branch = true

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise NotImplementedError",
    "if TYPE_CHECKING:",
]
fail_under = 60
```

---

## 5. tello-core Shared Package

### 5.1 Package Dependencies

```toml
[project]
name = "tello-core"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "pydantic>=2.0.0",
    "structlog>=24.0.0",
    "neo4j>=5.15.0",
    "redis>=5.0.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tello_core"]
```

### 5.2 Shared Pydantic Models (models.py)

**Hardware Layer:**

- `FlightCommand` — direction (Literal), distance_cm, speed
- `TelemetryFrame` — battery_pct, height_cm, tof_cm, temp_c, pitch, roll, yaw, flight_time_s, timestamp

**Navigation Layer:**

- `RoomNode` — id, name, width_cm, depth_cm, height_cm
- `MissionPad` — id (1-8), room_id, x_cm, y_cm, last_tof_approach_cm, last_visited

**Vision Layer:**

- `VisualEntity` — name, type, confidence, position, room_id, last_seen
- `ObservationEvent` — deferred to Phase 4 (tello-vision); defined in plan v2 scene graph schema

**Telemetry Layer:**

- `FlightSession` — id, start_time, end_time, room_id, mission_id
- `TelemetrySample` — battery_pct, height_cm, tof_cm, temp_c, timestamp
- `Anomaly` — type, severity (Literal["warning", "critical"]), detail, timestamp

**Deferred to future phases:**

- `ObservationEvent` — Phase 4 (tello-vision scene graph)
- `GuardrailLog` — Phase 5 (tello-voice guardrail audit logging)

### 5.3 Base Configuration (config.py)

```python
@dataclass(frozen=True, slots=True)
class BaseServiceConfig:
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    redis_url: str
    service_name: str
    neo4j_max_connection_pool_size: int = 5
    neo4j_connection_acquisition_timeout: float = 30.0

    @classmethod
    def from_env(cls, **overrides) -> Self:
        """Load from environment with fail-fast validation.

        Reads: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, REDIS_URL.
        Raises ConfigurationError for missing required vars.
        """
        ...

    def __post_init__(self):
        """Fail-fast validation rules:
        - Neo4j URI must start with bolt://, bolt+s://, neo4j://, or neo4j+s://
        - Redis URL must start with redis:// or rediss://
        - service_name must be non-empty
        """
        ...

def configure_structlog(service_name: str) -> None:
    """Consistent JSON logging across all services."""
    ...
```

### 5.4 Exception Hierarchy (exceptions.py)

```text
TelloError (root)
├── ConfigurationError    # Invalid config, missing env vars
├── ConnectionError       # Neo4j, Redis, or drone connection failures
├── CommandError          # Failed to execute a command
└── ValidationError       # Invalid input data
```

Services extend: `DroneNotConnectedError(ConnectionError)`,
`GuardrailBlockedError(ValidationError)`,
`MissionAbortedError(CommandError)`.

### 5.5 Infrastructure Factories

- `redis_client.py` — `create_redis_client(url) -> redis.asyncio.Redis` +
  health check helper (`async def redis_health_check(client) -> bool`)
- `neo4j_client.py` —
  `create_neo4j_driver(uri, user, password) -> neo4j.Driver`
  (sync driver; async not needed since neo4j-graphrag uses sync).
  Includes connection pool settings from reference
  (pool_size=5, acquisition_timeout=30s).
  Provides `neo4j_lifespan(config)` as an `@asynccontextmanager`
  for FastAPI/FastMCP lifespan integration
  (creates driver on enter, closes on exit).

---

## 6. tello-mcp Service Scaffold

### 6.1 Service Layout

```text
services/tello-mcp/
├── pyproject.toml
└── src/tello_mcp/
    ├── __init__.py
    ├── server.py           # FastMCP server + tool registration
    ├── config.py           # TelloMcpConfig(BaseServiceConfig)
    ├── tools/
    │   ├── __init__.py
    │   ├── flight.py       # takeoff, land, emergency_stop, move, rotate, flip, go_to_xyz, curve
    │   ├── sensors.py      # get_telemetry, get_tof_distance, detect_mission_pad [readOnlyHint]
    │   └── expansion.py    # set_led_color, set_led_pattern, display_matrix_*, send_esp32_command
    ├── drone.py            # DroneAdapter wrapping djitellopy.Tello
    ├── queue.py            # asyncio.Queue command serialization
    └── telemetry.py        # Redis PUBLISH + XADD publisher

tests/
├── conftest.py             # mock_drone, mock_redis, mock_config
├── test_config.py
├── test_tools/
│   ├── test_flight.py
│   ├── test_sensors.py
│   └── test_expansion.py
├── test_drone.py
├── test_queue.py
└── test_telemetry.py
```

### 6.2 Dependencies

```toml
[project]
name = "tello-mcp"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "tello-core",
    "fastmcp>=3.0.0",           # 3.1.0 current; >=3.0 for stable ToolAnnotations + http_app()
    "djitellopy>=2.5.0",
    "redis>=5.0.0",             # explicit despite tello-core transitive dep (PEP 735 best practice)
]

# Dev dependencies are declared at the workspace root ([tool.uv] dev-dependencies).
# No per-service [project.optional-dependencies] dev section — avoids version drift.

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tello_mcp"]

[tool.uv.sources]
tello-core = { workspace = true }
```

### 6.3 Architecture

**Command flow:** Agent/Claude → `server.py` (FastMCP tools) →
`queue.py` (asyncio.Queue) → `drone.py` (djitellopy) →
Tello TT (UDP :8889)

**Telemetry flow:** `drone.py` (poll) → `telemetry.py` (publisher) →
Redis (PUBLISH tello:telemetry + XADD tello:events)

### 6.4 Key Patterns

- **Tool registration (project convention):** Each tool module exports
  `register(mcp: FastMCP)` which uses `@mcp.tool()` decorators internally.
  This is a project pattern (not a FastMCP built-in) that keeps server.py
  clean by organizing tools into category modules.
  Tools use `ToolAnnotations` for `readOnlyHint`/`destructiveHint`.
- **DroneAdapter isolation:** djitellopy imported in exactly one file. Frozen SDK concern addressed.
- **Command Queue:** `asyncio.Queue` serializes all hardware calls. Prevents concurrent flight commands.
- **Structured errors:** `{"error": "DRONE_NOT_CONNECTED", "detail": "..."}` — never raw exceptions.
- **Transports:** stdio (default for MCP clients) and streamable-http (for network access).

---

## 7. Docker Compose

```yaml
services:
  neo4j:
    image: neo4j:5-community    # LTS line (5.26.x); stable for dev project
    ports: ["7474:7474", "7687:7687"]
    environment:
      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD:-tello-dev}
      NEO4J_PLUGINS: '["apoc"]'
      NEO4J_server_memory_heap_initial__size: 256m
      NEO4J_server_memory_heap_max__size: 512m
    volumes: [neo4j_data:/data, neo4j_logs:/logs]
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:8.0-alpine
    ports: ["6379:6379"]
    command: redis-server --appendonly yes
    volumes: [redis_data:/data]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  neo4j_data:
  neo4j_logs:
  redis_data:
```

---

## 8. Claude Code Configuration

### 8.1 CLAUDE.md Sections

- **Project Layout** — uv workspace, packages/ vs services/, single uv.lock
- **Commands** — `docker compose up -d`, `uv sync`,
  per-service run/test/lint, workspace-wide commands
- **Conventions** — conventional commits, Issue → Branch → PR, CLAUDE.md bundled into next PR
- **Logging** — structlog everywhere, printf-style, named loggers, `capture_logs()` in tests
- **Error Handling** — fail loud on config, wrap runtime calls,
  `logger.exception()`, structured MCP errors
- **Testing** — pytest + pytest-asyncio, mock djitellopy/Redis, 60% coverage floor
- **Shared Models** — all cross-service types in tello-core/models.py

### 8.2 .claude/ Directory

**commands/** (4 files, adapted from reference):

- `implement.md` — TDD workflow, workspace-aware paths
- `plan.md` — Feature planning (no code)
- `review.md` — Code review delegation
- `test.md` — Pytest guide, AAA pattern, async fixtures

**skills/** (Phase 1):

- `drone-patterns/SKILL.md` — djitellopy conventions, command queue, telemetry
- `mcp-tool-patterns/SKILL.md` — FastMCP tool registration, annotations, Context, errors
- `pr-workflow/skill.md` — PR creation/merge (carried from reference)

### 8.3 .mcp.json (Phase 1)

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
        "NEO4J_PASSWORD": { "secret": "NEO4J_PASSWORD" }
      }
    },
    "memory": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-neo4j-memory"],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": { "secret": "NEO4J_PASSWORD" }
      }
    },
    "tello-mcp": {
      "command": "uv",
      "args": ["run", "--package", "tello-mcp", "python", "-m", "tello_mcp.server"],
      "cwd": "."
    }
  }
}
```

### 8.4 .claude/settings.json

```json
{
  "enabledPlugins": {
    "context7@claude-plugins-official": true
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "$(git rev-parse --show-toplevel)/.claude/hooks/validate-workspace.sh \"$TOOL_INPUT\"",
            "description": "Warns when Bash commands target wrong working directory (e.g., running uv commands outside a service dir) or attempt to modify files in other services during focused work"
          }
        ]
      }
    ]
  }
}
```

---

## 9. VS Code Configuration

### 9.1 settings.json — Key Adaptations

- `python.defaultInterpreterPath`: `${workspaceFolder}/.venv/bin/python`
- Ruff format-on-save, configuration points to root `pyproject.toml`
- pytest discovers all packages/ and services/
- PYTHONPATH includes tello-core/src and tello-mcp/src
- `python.analysis.typeCheckingMode`: `"off"`
  (ty handles type checking, Pylance provides IntelliSense)
- Same from reference: rulers at 100, 4-space indent,
  trim whitespace, file/search exclusions

### 9.2 extensions.json

Recommended: ms-python.python, ms-python.vscode-pylance,
charliermarsh.ruff, ms-python.debugpy,
jakeboone02.cypher-query-language, tamasfe.even-better-toml,
mikestead.dotenv, eamodio.gitlens, mhutchie.git-graph,
usernamehw.errorlens, christian-kohler.path-intellisense

Unwanted: ms-python.black-formatter, ms-python.isort, ms-python.flake8

### 9.3 launch.json

- `tello-mcp (stdio)` — module: tello_mcp.server
- `tello-mcp (HTTP)` — module: tello_mcp.server, args: --transport streamable-http
- `Test: Current File` — module: pytest, args: ${file}
- `Test: tello-mcp` — module: pytest, args: services/tello-mcp/tests/

---

## 10. CI/CD

```yaml
# .github/workflows/ci.yml
jobs:
  lint:
    # Ruff from root (workspace-wide)
    - uv sync --frozen
    - uv run ruff check . --output-format=github
    - uv run ruff format --check .

  test:
    strategy:
      matrix:
        service: [tello-core, tello-mcp]
    steps:
      - uv sync --frozen
      - uv run --package ${{ matrix.service }} pytest --cov --tb=short

  type-check:
    continue-on-error: true  # advisory initially
    steps:
      - uv run ty check packages/ services/
```

---

## 11. Phase Evolution — Claude Code Configuration

| Phase | Service | CLAUDE.md Additions | New Skills | New MCP Servers | CI Changes |
| ----- | ------- | ----------------- | ---------- | -------------- | ---------- |
| 1 | tello-mcp | Base conventions, commands, error patterns | drone-patterns, mcp-tool-patterns | neo4j, memory, tello-mcp | lint + test (core, mcp) |
| 2 | tello-telemetry | Redis Streams patterns, anomaly rules | redis-streams-patterns | — | + tello-telemetry |
| 3 | tello-navigator | LangGraph conventions, room graph schema | langgraph-patterns | langsmith | + tello-navigator |
| 4 | tello-vision | CV pipeline patterns, scene graph schema | cv-pipeline-patterns | tello-vision-mcp | + tello-vision |
| 5 | tello-voice | Guardrail layers, dual-interface patterns | guardrail-patterns | tello-voice-mcp | + tello-voice |

---

## 12. Pre-commit Configuration

```yaml
repos:
  - repo: local
    hooks:
      - id: ruff-check
        name: ruff check
        entry: uv run ruff check --fix
        language: system
        types: [python]
        pass_filenames: false  # runs workspace-wide; acceptable for early monorepo size
      - id: ruff-format
        name: ruff format
        entry: uv run ruff format
        language: system
        types: [python]
        pass_filenames: false  # switch to pass_filenames: true if commit hooks become slow

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: ['--maxkb=1000']
      - id: check-merge-conflict
```

---

## 13. Environment Configuration

### .env.example (committed)

```bash
# Infrastructure
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=tello-dev
REDIS_URL=redis://localhost:6379

# Tello Drone
TELLO_WIFI_SSID=RMTT-xxxxxx

# LLM (future phases)
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...

# Observability (future)
# LANGSMITH_API_KEY=lsv2_...
# LANGSMITH_PROJECT=tello-ai
# LANGSMITH_TRACING=false
```

---

## 14. Placeholder Services

Each placeholder service gets a minimal pyproject.toml with workspace
dependency on tello-core so `uv sync` works from day one:

```toml
[project]
name = "tello-<service>"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = ["tello-core"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv.sources]
tello-core = { workspace = true }
```

No `src/` or `tests/` directories until that service's implementation phase begins.

---

## 15. .gitignore

```gitignore
# Environment and secrets
.env
.env.local
.env.*.local

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
build/
dist/
*.egg-info/
*.egg

# Virtual environments
.venv/
venv/

# IDE
.idea/
*.swp
*.swo
*~

# Testing
.pytest_cache/
.coverage
htmlcov/

# Astral tooling caches
.ruff_cache/
.ty_cache/

# Brainstorm companion
.superpowers/

# OS
.DS_Store
Thumbs.db

# Logs
*.log
logs/

# Docker volumes (if local)
neo4j_data/
redis_data/

# Playwright MCP
.playwright-mcp/
```
