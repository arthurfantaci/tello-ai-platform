"""tello-navigator — FastMCP mission planner server.

Run:
    stdio:            python -m tello_navigator.server
    streamable-http:  python -m tello_navigator.server --transport streamable-http --port 8300
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastmcp import FastMCP

from tello_core.config import configure_structlog
from tello_core.neo4j_client import neo4j_lifespan
from tello_core.redis_client import create_redis_client
from tello_navigator.config import TelloNavigatorConfig
from tello_navigator.events import MissionEventPublisher
from tello_navigator.planner import MissionPlanner
from tello_navigator.repository import MissionRepository
from tello_navigator.tools import missions, queries

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Manage service lifecycle.

    Startup: Config → structlog → Redis → Neo4j → repo → planner → events
    Shutdown: Close Neo4j (via lifespan) → close Redis
    """
    config = TelloNavigatorConfig.from_env(service_name="tello-navigator")
    configure_structlog(config.service_name)

    redis = create_redis_client(config.redis_url)

    async with neo4j_lifespan(config) as neo4j_driver:
        repo = MissionRepository(neo4j_driver)
        events = MissionEventPublisher(redis, config.missions_stream)
        planner = MissionPlanner(repo, config)

        try:
            yield {
                "repo": repo,
                "planner": planner,
                "events": events,
                "config": config,
            }
        finally:
            await redis.aclose()


mcp = FastMCP(
    name="tello-navigator",
    instructions=(
        "Mission planning service for the Tello drone. "
        "Create, manage, and track multi-step flight missions. "
        "Missions are planned as waypoint sequences through rooms."
    ),
    lifespan=lifespan,
)

# Register tool modules
missions.register(mcp)
queries.register(mcp)


def main() -> None:
    """Entry point for tello-navigator server."""
    import argparse

    parser = argparse.ArgumentParser(description="tello-navigator server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "streamable-http", "sse"],
    )
    parser.add_argument("--port", type=int, default=8300)
    parsed = parser.parse_args()

    mcp.run(
        transport=parsed.transport,
        host="0.0.0.0",
        port=parsed.port,
    )


if __name__ == "__main__":
    main()
