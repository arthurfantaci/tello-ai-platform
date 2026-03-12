---
name: mcp-tool-patterns
description: "FastMCP tool patterns for tello-ai-platform"
---

# MCP Tool Patterns

## Tool Registration
Each tool module exports `register(mcp: FastMCP)` which uses `@mcp.tool()` internally.
Tools are organized by category: flight, sensors, expansion.

## ToolAnnotations
- `readOnlyHint=True` for sensor/query tools
- `destructiveHint=True` for emergency_stop
- Default: `readOnlyHint=False, destructiveHint=False`

## State Access
Tools access shared components via `mcp.state`:
```python
drone = mcp.state["drone"]      # DroneAdapter
queue = mcp.state["queue"]      # CommandQueue
redis = mcp.state["redis"]      # Redis client
telemetry = mcp.state["telemetry"]  # TelemetryPublisher
```

## Error Returns
Never raise exceptions in tools. Always return structured dicts.
