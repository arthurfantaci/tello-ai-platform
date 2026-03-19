"""Integration tests — real Redis + real Neo4j.

Requires: docker compose up -d (Redis + Neo4j healthy).
Run: uv run --package tello-telemetry pytest services/tello-telemetry/tests/test_integration.py -v
"""

from __future__ import annotations

import os

import pytest
import redis.asyncio as aioredis
from neo4j import GraphDatabase

from tello_telemetry.config import TelloTelemetryConfig
from tello_telemetry.consumer import StreamConsumer
from tello_telemetry.detector import AnomalyDetector
from tello_telemetry.session_repo import SessionRepository

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7689")
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "claude-code-memory")

# Use a unique stream name to avoid collisions
TEST_STREAM = "tello:events:integration-test"

# Skip all tests in this module if SKIP_INTEGRATION is set
pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="Integration tests disabled",
)


@pytest.fixture()
async def setup_integration():
    """Set up real Redis + Neo4j for integration testing."""
    r = aioredis.from_url(REDIS_URL, decode_responses=True)

    # Skip if infrastructure is not available (e.g. CI without Docker)
    try:
        await r.ping()
    except Exception:
        await r.aclose()
        pytest.skip("Redis not available — skipping integration test")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        driver.verify_connectivity()
    except Exception:
        await r.aclose()
        driver.close()
        pytest.skip("Neo4j not available — skipping integration test")

    # Clean up test data
    await r.delete(TEST_STREAM)
    with driver.session() as s:
        s.run("""
            MATCH (n)-[r]->(fs:FlightSession)
            WHERE fs.room_id = 'integration-test-room'
            DELETE r, n
        """)
        s.run("MATCH (fs:FlightSession {room_id: 'integration-test-room'}) DELETE fs")

    yield r, driver

    # Cleanup
    await r.delete(TEST_STREAM)
    with driver.session() as s:
        s.run("""
            MATCH (n)-[r]->(fs:FlightSession)
            WHERE fs.room_id = 'integration-test-room'
            DELETE r, n
        """)
        s.run("MATCH (fs:FlightSession {room_id: 'integration-test-room'}) DELETE fs")
    await r.aclose()
    driver.close()


def _make_config() -> TelloTelemetryConfig:
    return TelloTelemetryConfig(
        neo4j_uri=NEO4J_URI,
        neo4j_username=NEO4J_USER,
        neo4j_password=NEO4J_PASS,
        redis_url=REDIS_URL,
        service_name="integration-test",
        stream_name=TEST_STREAM,
        consumer_group="test-group",
        consumer_name="test-worker",
    )


class TestObstaclePipelineEndToEnd:
    async def test_obstacle_event_reaches_neo4j(self, setup_integration):
        r, driver = setup_integration
        config = _make_config()
        repo = SessionRepository(driver)
        detector = AnomalyDetector(config)
        consumer = StreamConsumer(r, config, detector, repo)

        # Set up consumer group
        await consumer.ensure_consumer_group()

        # Publish takeoff → obstacle → land
        await r.xadd(
            TEST_STREAM,
            {"event_type": "takeoff", "room_id": "integration-test-room"},
        )
        await r.xadd(
            TEST_STREAM,
            {
                "event_type": "obstacle_danger",
                "forward_distance_mm": "185",
                "forward_distance_in": "7.3",
                "height_cm": "80",
                "zone": "DANGER",
                "response": "RETURN_TO_HOME",
                "outcome": "returned",
                "mission_id": "",
                "room_id": "integration-test-room",
                "reversed_direction": "back",
            },
        )
        await r.xadd(TEST_STREAM, {"event_type": "land"})

        # Process all messages (read new messages with ">")
        await consumer._read_and_process(message_id=">")

        # Verify in Neo4j
        with driver.session() as s:
            result = s.run(
                """
                MATCH (oi:ObstacleIncident)-[:TRIGGERED_DURING]->(fs:FlightSession)
                WHERE fs.room_id = 'integration-test-room'
                RETURN oi.forward_distance_mm AS distance,
                       oi.height_cm AS height,
                       oi.response AS response,
                       fs.end_time IS NOT NULL AS session_closed
                """,
            ).single()
            assert result is not None, "ObstacleIncident not found in Neo4j"
            assert result["distance"] == 185
            assert result["height"] == 80
            assert result["response"] == "RETURN_TO_HOME"
            assert result["session_closed"] is True
