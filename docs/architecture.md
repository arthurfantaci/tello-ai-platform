# Tello AI Platform — Architecture Overview

## Platform Summary

A uv workspace monorepo for an AI-powered drone platform using a DJI Tello drone. The system is structured as one shared library plus five specialized services, communicating over Redis pub/sub and streams, with Neo4j as the graph memory layer.

## Services and Roles

### `packages/tello-core`
Shared library consumed by all services. Contains domain models, Redis client utilities, Neo4j session helpers, and shared type definitions. Not deployed independently.

### `services/tello-mcp`
**Hardware abstraction layer.** Exposes drone control as MCP tools that Claude can call directly. Manages the UDP socket connection to the Tello, translates MCP tool calls into Tello SDK commands, and publishes telemetry to Redis streams. Acts as the single point of truth for drone state.

### `services/tello-navigator`
**LangGraph mission planner.** Receives high-level mission goals and decomposes them into sequences of primitive drone actions. Uses LangGraph for stateful multi-step planning with checkpointing via Redis. Subscribes to telemetry to inform planning decisions and adapt in-flight.

### `services/tello-vision`
**Computer vision pipeline.** Processes the Tello video stream using OpenCV and optional ML models. Publishes scene analysis results (object detection, room mapping, obstacle positions) to Redis. Feeds the scene graph in Neo4j for spatial memory.

### `services/tello-voice`
**Natural language controller — dual interface.** Accepts voice or text commands from the user, translates them into mission goals or direct MCP tool calls. Routes simple commands directly to tello-mcp and complex requests to tello-navigator. Provides the primary human-facing interface.

### `services/tello-telemetry`
**Flight session intelligence.** Consumes raw telemetry from Redis streams, aggregates metrics, detects anomalies, and writes structured session data to Neo4j. Enables post-flight analysis, performance trending, and session replay.

## Graph Schema Domains (Neo4j)

| Domain | Description |
|---|---|
| **Room graph** | Spatial layout of the environment — rooms, walls, doorways, landmarks |
| **Scene graph** | Objects detected during flight — type, position, confidence, timestamp |
| **Session graph** | Flight session metadata — start/end, waypoints, commands executed, anomalies |
| **Memory graph** | Long-term associations — learned locations, named objects, user preferences |

## Redis Capabilities

| Capability | Usage |
|---|---|
| **Pub/sub** | Real-time telemetry broadcast, command acknowledgment signals |
| **Streams** | Durable telemetry log consumed by tello-telemetry |
| **Checkpointing** | LangGraph state persistence for tello-navigator |
| **Semantic cache** | Cache LLM inference results for repeated commands |
| **Vector index** | Similarity search over scene descriptions (future) |
| **Rate limiting** | Guard the Tello SDK command rate (max ~100 cmd/s) |

## Recommended Build Order

```
tello-mcp → tello-telemetry → tello-navigator → tello-vision → tello-voice
```

**Rationale:**
1. `tello-mcp` — get the drone talking first; validates hardware integration
2. `tello-telemetry` — establish data pipeline before building consumers
3. `tello-navigator` — planning layer depends on reliable telemetry
4. `tello-vision` — CPU/GPU intensive; integrate once core loop is stable
5. `tello-voice` — user-facing; integrate last when all backend services are solid

## Technology Stack

| Layer | Technology |
|---|---|
| Package manager | uv (Astral) |
| Linting / formatting | Ruff (Astral) |
| Type checking | ty (Astral) |
| Testing | pytest + pytest-asyncio |
| Protocol | MCP (Model Context Protocol) |
| Graph database | Neo4j 5 Community + APOC |
| Message broker | Redis 8.0 |
| AI orchestration | LangGraph |
| Python version | 3.13 |
