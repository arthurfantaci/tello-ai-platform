---
description: "TDD implementation workflow for tello-ai-platform"
---

# Implement Feature

Follow this TDD workflow:

1. **Write failing test** in the appropriate `tests/` directory
2. **Run test** to confirm it fails: `uv run --package $PACKAGE pytest $TEST_FILE -v`
3. **Implement** the minimum code to make it pass
4. **Run test** to confirm it passes
5. **Refactor** if needed (tests must still pass)
6. **Lint**: `uv run ruff check . --fix && uv run ruff format .`
7. **Commit** with conventional commit message

Package paths:
- tello-core: `packages/tello-core/`
- tello-mcp: `services/tello-mcp/`
