---
name: drone-patterns
description: "DJI Tello TT drone conventions for tello-ai-platform"
---

# Drone Development Patterns

## DroneAdapter
- Single point of djitellopy dependency (`services/tello-mcp/src/tello_mcp/drone.py`)
- All methods return structured dicts: `{"status": "ok"}` or `{"error": "CODE", "detail": "..."}`
- Never raise exceptions from drone commands

## Command Queue
- All hardware calls go through `CommandQueue.enqueue(callable)`
- Queue serializes execution — one command at a time
- Exception handling built into the queue consumer

## Telemetry
- `TelemetryPublisher.publish_frame(frame)` → Redis PUBLISH + XADD
- Channel: `tello:telemetry` (real-time pub/sub)
- Stream: `tello:events` (durable, ordered)

## Testing
- Always mock `djitellopy.Tello` — never import the real SDK in tests
- Use `conftest.py` mock_drone fixture
- Test both success paths and error paths
