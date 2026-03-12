---
description: "Run and analyze tests"
---

# Test Guide

```bash
# Run specific package
uv run --package tello-core pytest packages/tello-core/tests/ -v
uv run --package tello-mcp pytest services/tello-mcp/tests/ -v

# Run all tests
uv run pytest packages/ services/ -v

# With coverage
uv run --package tello-core pytest packages/tello-core/tests/ --cov --cov-report=term-missing
uv run --package tello-mcp pytest services/tello-mcp/tests/ --cov --cov-report=term-missing
```

Test patterns:
- AAA: Arrange, Act, Assert
- Mock external deps (djitellopy, Redis, Neo4j)
- Use `pytest.fixture()` for shared setup
- Async tests: just use `async def test_...` (asyncio_mode=auto)
