"""Tests for tello_core Redis client factory."""

from unittest.mock import AsyncMock

import pytest

from tello_core.redis_client import create_redis_client, redis_health_check


class TestCreateRedisClient:
    def test_creates_client(self):
        client = create_redis_client("redis://localhost:6379")
        assert client is not None

    def test_returns_redis_instance(self):
        import redis.asyncio as aioredis

        client = create_redis_client("redis://localhost:6379")
        assert isinstance(client, aioredis.Redis)


class TestRedisHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy_redis(self):
        mock_client = AsyncMock()
        mock_client.ping.return_value = True
        result = await redis_health_check(mock_client)
        assert result is True

    @pytest.mark.asyncio
    async def test_unhealthy_redis(self):
        mock_client = AsyncMock()
        mock_client.ping.side_effect = ConnectionError("refused")
        result = await redis_health_check(mock_client)
        assert result is False
