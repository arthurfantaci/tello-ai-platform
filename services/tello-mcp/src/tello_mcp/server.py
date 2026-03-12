"""tello-mcp — FastMCP hardware abstraction server for DJI Tello TT.

Run:
    stdio:            python -m tello_mcp.server
    streamable-http:  python -m tello_mcp.server --transport streamable-http --port 8100
"""

from __future__ import annotations

import asyncio
import sys

from fastmcp import FastMCP

from tello_core.config import configure_structlog
from tello_core.redis_client import create_redis_client

from tello_mcp.config import TelloMcpConfig
from tello_mcp.drone import DroneAdapter
from tello_mcp.queue import CommandQueue
from tello_mcp.telemetry import TelemetryPublisher
from tello_mcp.tools import expansion, flight, sensors

mcp = FastMCP(
    name="tello-mcp",
    instructions=(
        "Hardware abstraction for DJI Tello TT drone. "
        "All flight commands are serialized through an async queue. "
        "Sensor tools are read-only and return current telemetry."
    ),
)

# Register tool modules
flight.register(mcp)
sensors.register(mcp)
expansion.register(mcp)


def main() -> None:
    """Entry point for tello-mcp server."""
    config = TelloMcpConfig.from_env(service_name="tello-mcp")
    configure_structlog(config.service_name)

    # Initialize components and store in server state
    mcp.state["drone"] = DroneAdapter()
    mcp.state["queue"] = CommandQueue()
    mcp.state["redis"] = create_redis_client(config.redis_url)
    mcp.state["telemetry"] = TelemetryPublisher(
        redis_client=mcp.state["redis"],
        channel=config.telemetry_channel,
        stream=config.events_stream,
    )
    mcp.state["config"] = config

    # Parse transport from CLI args
    import argparse

    parser = argparse.ArgumentParser(description="tello-mcp server")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http", "sse"])
    parser.add_argument("--port", type=int, default=8100)
    parsed = parser.parse_args()
    transport = parsed.transport
    port = parsed.port

    mcp.run(transport=transport, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
