"""Tests for tello_core Neo4j client factory."""

from unittest.mock import MagicMock, patch

import pytest

from tello_core.neo4j_client import create_neo4j_driver, neo4j_lifespan


class TestCreateNeo4jDriver:
    @patch("tello_core.neo4j_client.GraphDatabase")
    def test_creates_driver(self, mock_gdb):
        mock_gdb.driver.return_value = MagicMock()
        driver = create_neo4j_driver("bolt://localhost:7687", "neo4j", "password")
        mock_gdb.driver.assert_called_once_with(
            "bolt://localhost:7687",
            auth=("neo4j", "password"),
            max_connection_pool_size=5,
            connection_acquisition_timeout=30.0,
        )
        assert driver is not None

    @patch("tello_core.neo4j_client.GraphDatabase")
    def test_custom_pool_settings(self, mock_gdb):
        mock_gdb.driver.return_value = MagicMock()
        create_neo4j_driver(
            "bolt://localhost:7687",
            "neo4j",
            "pw",
            max_connection_pool_size=10,
            connection_acquisition_timeout=60.0,
        )
        mock_gdb.driver.assert_called_once_with(
            "bolt://localhost:7687",
            auth=("neo4j", "pw"),
            max_connection_pool_size=10,
            connection_acquisition_timeout=60.0,
        )


class TestNeo4jLifespan:
    @pytest.mark.asyncio
    @patch("tello_core.neo4j_client.GraphDatabase")
    async def test_lifespan_creates_and_closes_driver(self, mock_gdb):
        mock_driver = MagicMock()
        mock_gdb.driver.return_value = mock_driver

        mock_config = MagicMock()
        mock_config.neo4j_uri = "bolt://localhost:7687"
        mock_config.neo4j_username = "neo4j"
        mock_config.neo4j_password = "password"
        mock_config.neo4j_max_connection_pool_size = 5
        mock_config.neo4j_connection_acquisition_timeout = 30.0

        async with neo4j_lifespan(mock_config) as driver:
            assert driver is mock_driver

        mock_driver.close.assert_called_once()
