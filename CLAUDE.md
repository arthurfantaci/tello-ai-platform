# Tello AI Platform

## Project Layout

uv workspace monorepo. Single `uv.lock` at root.

- `packages/tello-core/` — shared Pydantic models, config, exceptions, Redis/Neo4j factories
- `services/tello-mcp/` — FastMCP hardware abstraction (djitellopy wrapper)
- `services/tello-navigator/` — LangGraph mission planner (placeholder)
- `services/tello-vision/` — CV pipeline (placeholder)
- `services/tello-voice/` — NL controller, dual-interface (placeholder)
- `services/tello-telemetry/` — Flight session intelligence (placeholder)

## Commands

```bash
# Infrastructure
docker compose up -d          # Start Neo4j + Redis
docker compose down           # Stop infrastructure

# Dependencies
uv sync                       # Install/update all workspace deps

# Run services
uv run --package tello-mcp python -m tello_mcp.server                          # stdio
uv run --package tello-mcp python -m tello_mcp.server --transport streamable-http  # HTTP

# Testing
uv run --package tello-core pytest packages/tello-core/tests/ -v    # tello-core tests
uv run --package tello-mcp pytest services/tello-mcp/tests/ -v      # tello-mcp tests
uv run pytest packages/ services/ -v                                 # all tests

# Lint & Format
uv run ruff check .             # lint
uv run ruff check --fix .       # lint + autofix
uv run ruff format .            # format
uv run ruff format --check .    # format check only

# Type checking
uv run ty check packages/ services/    # advisory (may have errors)
```

## Conventions

- **Commits:** conventional commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`)
- **Workflow:** Issue → Branch → PR. CLAUDE.md changes bundled into the next implementation PR.
- **Python:** 3.13+, type hints everywhere, `from __future__ import annotations` in all modules
- **Tooling:** Ruff (lint + format), ty (type check), pytest + pytest-asyncio

## Logging

- structlog everywhere — JSON output, printf-style formatting
- Named loggers: `structlog.get_logger("service.module")`
- `configure_structlog(service_name)` at service startup
- Tests: use structlog's `capture_logs()` fixture when testing log output

## Error Handling

- **Config errors:** Fail loud at startup — raise `ConfigurationError`, never catch
- **Runtime errors:** Wrap SDK calls, return structured dicts `{"error": "CODE", "detail": "..."}`
- **Logging:** `logger.exception()` for unexpected errors (includes traceback)
- **MCP tools:** Never expose raw exceptions — always structured error responses

## Testing

- pytest + pytest-asyncio (asyncio_mode = "auto")
- Mock djitellopy and Redis in unit tests — no real connections
- AAA pattern: Arrange, Act, Assert
- 60% coverage floor (`fail_under = 60` in pyproject.toml)
- Run tests per-package: `uv run --package <name> pytest ...`

## Shared Models

All cross-service data contracts live in `packages/tello-core/src/tello_core/models.py`.
Import from `tello_core.models` or directly from `tello_core` (re-exported in `__init__.py`).
Never duplicate model definitions in services.
