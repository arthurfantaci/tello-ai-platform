"""tello-mcp — FastMCP hardware abstraction server for DJI Tello TT.

Run:
    stdio:            python -m tello_mcp.server
    streamable-http:  python -m tello_mcp.server --transport streamable-http --port 8100
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

from fastmcp import FastMCP

from tello_core.config import configure_structlog
from tello_core.redis_client import create_redis_client
from tello_mcp.config import TelloMcpConfig
from tello_mcp.drone import DroneAdapter
from tello_mcp.obstacle import ObstacleConfig, ObstacleMonitor, ObstacleResponseHandler
from tello_mcp.queue import CommandQueue
from tello_mcp.strategies import SimpleReverseRTH
from tello_mcp.telemetry import TelemetryPublisher
from tello_mcp.tools import connection, expansion, flight, sensors

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


async def _keepalive_loop(drone: DroneAdapter) -> None:
    """Send keepalive every 10s to prevent 15s auto-land timeout."""
    while True:
        await asyncio.sleep(10)
        if drone.is_connected:
            await asyncio.to_thread(drone.keepalive)


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Manage service lifecycle.

    Yields a dict of shared resources for ``ctx.lifespan_context``.
    """
    config = TelloMcpConfig.from_env(service_name="tello-mcp")
    configure_structlog(config.service_name)

    redis = create_redis_client(config.redis_url)
    drone = DroneAdapter(host=config.tello_host)
    queue = CommandQueue()
    obstacle_config = ObstacleConfig.from_env()
    monitor = ObstacleMonitor(drone, obstacle_config)
    telemetry = TelemetryPublisher(
        redis_client=redis,
        channel=config.telemetry_channel,
        stream=config.events_stream,
    )

    # Wire obstacle avoidance: strategy → handler → monitor callback
    last_command: dict[str, str | int] = {}
    strategy = SimpleReverseRTH()
    handler = ObstacleResponseHandler(
        drone=drone,
        rth_strategy=strategy,
        telemetry=telemetry,
        last_command=last_command,
    )
    monitor.on_reading(handler.on_obstacle_reading)

    # Start queue consumer — without this, all enqueue() calls hang forever
    queue_task = asyncio.create_task(queue.start())

    # Best-effort auto-connect — warn on failure, don't block startup
    result = drone.connect()
    if "error" in result:
        import structlog

        structlog.get_logger("tello_mcp.server").warning(
            "Auto-connect failed — use connect_drone tool to retry",
            detail=result.get("detail"),
        )

    keepalive_task = asyncio.create_task(_keepalive_loop(drone))
    await monitor.start()
    try:
        yield {
            "drone": drone,
            "queue": queue,
            "redis": redis,
            "telemetry": telemetry,
            "config": config,
            "monitor": monitor,
            "handler": handler,
            "last_command": last_command,
        }
    finally:
        await monitor.stop()
        keepalive_task.cancel()
        with suppress(asyncio.CancelledError):
            await keepalive_task
        await queue.stop()
        queue_task.cancel()
        with suppress(asyncio.CancelledError):
            await queue_task
        drone.disconnect()
        await redis.aclose()


mcp = FastMCP(
    name="tello-mcp",
    instructions=(
        "Hardware abstraction for DJI Tello TT drone. "
        "All flight commands are serialized through an async queue. "
        "Sensor tools are read-only and return current telemetry."
    ),
    lifespan=lifespan,
)

# Register tool modules
connection.register(mcp)
flight.register(mcp)
sensors.register(mcp)
expansion.register(mcp)


def main() -> None:
    """Entry point for tello-mcp server."""
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
