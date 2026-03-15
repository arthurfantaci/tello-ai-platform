"""Tests for connection management MCP tools."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tello_mcp.drone import DroneAdapter


class TestConnectDrone:
    @pytest.fixture()
    def adapter(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            return DroneAdapter()

    def test_connect_when_disconnected(self, adapter):
        result = adapter.connect()
        assert result["status"] == "ok"
        assert adapter.is_connected

    def test_connect_already_connected(self, adapter):
        adapter.connect()
        assert adapter.is_connected
        # Second connect still succeeds (idempotent at SDK level)
        result = adapter.connect()
        assert result["status"] == "ok"

    def test_connect_failure(self, mock_drone):
        mock_drone.connect.side_effect = Exception("no WiFi")
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            result = adapter.connect()
            assert result["error"] == "CONNECTION_FAILED"
            assert not adapter.is_connected


class TestDisconnectDrone:
    def test_disconnect_when_connected(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.connect()
            adapter.disconnect()
            assert not adapter.is_connected
            mock_drone.end.assert_called_once()

    def test_disconnect_when_not_connected(self, mock_drone):
        with patch("tello_mcp.drone.Tello", return_value=mock_drone):
            adapter = DroneAdapter()
            adapter.disconnect()  # should not raise
            mock_drone.end.assert_not_called()
