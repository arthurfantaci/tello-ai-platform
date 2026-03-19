"""tello-telemetry — FastMCP flight session intelligence server.

Run:
    stdio:            python -m tello_telemetry.server
    streamable-http:  python -m tello_telemetry.server --transport streamable-http --port 8200
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

from fastmcp import FastMCP

from tello_core.config import configure_structlog
from tello_core.neo4j_client import neo4j_lifespan
from tello_core.redis_client import create_redis_client
from tello_telemetry.config import TelloTelemetryConfig
from tello_telemetry.consumer import StreamConsumer
from tello_telemetry.detector import AnomalyDetector
from tello_telemetry.session_repo import SessionRepository
from tello_telemetry.tools import queries

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Manage service lifecycle.

    Yields a dict of shared resources for ``ctx.lifespan_context``.

    Startup: Config → structlog → Redis → Neo4j → domain objects →
        background consumer task
    Shutdown: Cancel consumer → close Neo4j (via lifespan) → close Redis
    """
    config = TelloTelemetryConfig.from_env(
        service_name="tello-telemetry",
    )
    configure_structlog(config.service_name)

    redis = create_redis_client(config.redis_url)
    async with neo4j_lifespan(config) as neo4j_driver:
        detector = AnomalyDetector(config)
        session_repo = SessionRepository(neo4j_driver)
        consumer = StreamConsumer(redis, config, detector, session_repo)

        task = asyncio.create_task(consumer.run())
        try:
            yield {"session_repo": session_repo}
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await redis.aclose()


mcp = FastMCP(
    name="tello-telemetry",
    instructions=(
        "Flight session intelligence service. "
        "Query flight sessions, telemetry curves, and anomaly history. "
        "All query tools are read-only."
    ),
    lifespan=lifespan,
)

queries.register(mcp)


def main() -> None:
    """Entry point for tello-telemetry server."""
    import argparse

    parser = argparse.ArgumentParser(description="tello-telemetry server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "streamable-http", "sse"],
    )
    parser.add_argument("--port", type=int, default=8200)
    parsed = parser.parse_args()

    kwargs: dict = {"transport": parsed.transport}
    if parsed.transport != "stdio":
        kwargs["host"] = "0.0.0.0"
        kwargs["port"] = parsed.port
    mcp.run(**kwargs)


if __name__ == "__main__":
    main()
