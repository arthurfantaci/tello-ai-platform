"""Shared test fixtures for tello-mcp."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tello_core.config import BaseServiceConfig


@pytest.fixture()
def mock_config():
    """Test configuration for tello-mcp."""
    return BaseServiceConfig(
        neo4j_uri="bolt://localhost:7687",
        neo4j_username="neo4j",
        neo4j_password="test",
        redis_url="redis://localhost:6379",
        service_name="tello-mcp-test",
    )


@pytest.fixture()
def mock_drone():
    """Mock djitellopy.Tello instance."""
    drone = MagicMock()
    drone.connect = MagicMock()
    drone.takeoff = MagicMock()
    drone.land = MagicMock()
    drone.emergency = MagicMock()
    drone.move_forward = MagicMock()
    drone.move_back = MagicMock()
    drone.move_left = MagicMock()
    drone.move_right = MagicMock()
    drone.move_up = MagicMock()
    drone.move_down = MagicMock()
    drone.rotate_clockwise = MagicMock()
    drone.rotate_counter_clockwise = MagicMock()
    drone.flip_forward = MagicMock()
    drone.get_battery = MagicMock(return_value=85)
    drone.get_height = MagicMock(return_value=120)
    drone.get_distance_tof = MagicMock(return_value=95)
    drone.get_temperature = MagicMock(return_value=42)
    drone.get_pitch = MagicMock(return_value=1)
    drone.get_roll = MagicMock(return_value=0)
    drone.get_yaw = MagicMock(return_value=180)
    drone.get_flight_time = MagicMock(return_value=45)
    drone.get_mission_pad_id = MagicMock(return_value=-1)
    return drone


@pytest.fixture()
def mock_redis():
    """Mock async Redis client."""
    client = AsyncMock()
    client.publish = AsyncMock(return_value=1)
    client.xadd = AsyncMock(return_value="1234-0")
    client.ping = AsyncMock(return_value=True)
    return client
