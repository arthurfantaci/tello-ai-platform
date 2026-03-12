"""Shared Redis client factory for the tello-ai-platform."""

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger("tello_core.redis")


def create_redis_client(url: str) -> aioredis.Redis:
    """Create an async Redis client.

    Args:
        url: Redis connection URL (redis:// or rediss://).
    """
    logger.info("Creating Redis client for %s", url.split("@")[-1])
    return aioredis.from_url(url, decode_responses=True)


async def redis_health_check(client: aioredis.Redis) -> bool:
    """Check Redis connectivity.

    Returns:
        True if Redis responds to PING.
    """
    try:
        return await client.ping()
    except Exception:
        logger.exception("Redis health check failed")
        return False
