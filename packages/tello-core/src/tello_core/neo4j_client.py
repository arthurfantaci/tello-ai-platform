"""Shared Neo4j driver factory for the tello-ai-platform."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

import structlog
from neo4j import GraphDatabase

if TYPE_CHECKING:
    from neo4j import Driver

    from tello_core.config import BaseServiceConfig

logger = structlog.get_logger("tello_core.neo4j")


def create_neo4j_driver(
    uri: str,
    username: str,
    password: str,
    *,
    max_connection_pool_size: int = 5,
    connection_acquisition_timeout: float = 30.0,
) -> Driver:
    """Create a Neo4j driver instance.

    Args:
        uri: Neo4j connection URI (bolt:// or neo4j://).
        username: Database username.
        password: Database password.
        max_connection_pool_size: Maximum connections in pool.
        connection_acquisition_timeout: Seconds to wait for a connection.
    """
    logger.info("Creating Neo4j driver for %s", uri)
    return GraphDatabase.driver(
        uri,
        auth=(username, password),
        max_connection_pool_size=max_connection_pool_size,
        connection_acquisition_timeout=connection_acquisition_timeout,
    )


@asynccontextmanager
async def neo4j_lifespan(config: BaseServiceConfig) -> AsyncIterator[Driver]:
    """Async context manager for Neo4j driver lifecycle.

    Creates driver on enter, closes on exit. Designed for
    FastAPI/FastMCP lifespan integration.

    Args:
        config: Service configuration with Neo4j credentials.

    Yields:
        Neo4j Driver instance.
    """
    driver = create_neo4j_driver(
        config.neo4j_uri,
        config.neo4j_username,
        config.neo4j_password,
        max_connection_pool_size=config.neo4j_max_connection_pool_size,
        connection_acquisition_timeout=config.neo4j_connection_acquisition_timeout,
    )
    logger.info("Neo4j driver created")
    try:
        yield driver
    finally:
        driver.close()
        logger.info("Neo4j driver closed")
