# Tello AI Platform

## Project Layout

uv workspace monorepo. Single `uv.lock` at root.

- `packages/tello-core/` — shared Pydantic models, config, exceptions, Redis/Neo4j factories
- `services/tello-mcp/` — FastMCP hardware abstraction (djitellopy wrapper)
- `services/tello-navigator/` — LangGraph mission planner
- `services/tello-vision/` — CV pipeline (placeholder)
- `services/tello-voice/` — NL controller, dual-interface (placeholder)
- `services/tello-telemetry/` — Flight session intelligence

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
uv run --package tello-navigator pytest services/tello-navigator/tests/ -v  # tello-navigator tests
uv run --package tello-telemetry pytest services/tello-telemetry/tests/ -v  # tello-telemetry tests
# NOTE: no flat "uv run pytest packages/ services/" command — uv workspaces
# require --package to resolve each service's dependencies correctly.

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

## Git Operations

- PR body MUST contain `Closes #N` for every issue it delivers — parenthetical `(#N)` in titles is just a mention, not a closing keyword
- **Merge strategy** — choose per-situation, explain the tradeoff to the user, and walk them through it:
  - `--squash`: clean history (1 commit per PR). Use for simple PRs and solo work. **Caution**: breaks stacked PR branch linkage — downstream branches need cherry-pick rebase
  - `--merge`: preserves branch topology. Use for stacked PRs when you want to avoid the rebase tax
  - `--rebase`: linear history without merge commits. Use when commit-by-commit history matters
- **Stacked PRs after squash-merge**: cherry-pick each phase's commit onto updated main (`git checkout -B <branch> origin/main && git cherry-pick <sha> && git push --force-with-lease`), then retarget PR (`gh pr edit <n> --base main`)
- **After every merge**, verify issues closed: `gh issue view <N> --json state`. If not, close manually with `gh issue close <N> --comment "Delivered in PR #X"`
- Always explain git/GitHub mechanics to the user — they are learning professional workflows
- Branch protection ruleset requires PRs + status checks (lint, test) for `main`
- Force push requires temporarily disabling the ruleset via `gh api --method PUT repos/.../rulesets/<id>`
- This repo is **public on GitHub** — treat all committed content as portfolio-visible

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
- **15-second SDK timeout:** drone auto-lands if no command received for 15s. tello-mcp runs a background keepalive task to prevent this.

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
