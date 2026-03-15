"""Tests for drone auto-discovery."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tello_mcp.discovery import discover_tello, get_local_subnet
from tello_mcp.drone import DroneAdapter


class TestGetLocalSubnet:
    def test_returns_subnet_prefix(self):
        with patch("tello_mcp.discovery.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="192.168.68.42\n")
            assert get_local_subnet() == "192.168.68"

    def test_returns_none_on_failure(self):
        with patch("tello_mcp.discovery.subprocess.run") as mock_run:
            from subprocess import CalledProcessError

            mock_run.side_effect = CalledProcessError(1, "ipconfig")
            assert get_local_subnet() is None


class TestDiscoverTello:
    def test_finds_drone(self):
        mock_sock = MagicMock()
        mock_sock.recvfrom.side_effect = [
            TimeoutError,
            (b"ok", ("192.168.68.107", 8889)),
        ]
        with patch("tello_mcp.discovery.socket.socket", return_value=mock_sock):
            result = discover_tello(subnet="192.168.68", range_start=100, range_end=101)
            assert result == "192.168.68.107"

    def test_returns_none_when_not_found(self):
        mock_sock = MagicMock()
        mock_sock.recvfrom.side_effect = TimeoutError
        with patch("tello_mcp.discovery.socket.socket", return_value=mock_sock):
            result = discover_tello(subnet="192.168.68", range_start=100, range_end=102)
            assert result is None

    def test_returns_none_when_no_subnet(self):
        with patch("tello_mcp.discovery.get_local_subnet", return_value=None):
            assert discover_tello() is None


class TestDroneAdapterAutoDiscovery:
    def test_host_auto_uses_discovery(self):
        with (
            patch("tello_mcp.drone.discover_tello", return_value="192.168.68.107"),
            patch("tello_mcp.drone.Tello") as mock_tello_cls,
        ):
            adapter = DroneAdapter(host="auto")
            mock_tello_cls.assert_called_once_with(host="192.168.68.107")
            assert adapter._host == "192.168.68.107"

    def test_host_auto_falls_back_on_failure(self):
        with (
            patch("tello_mcp.drone.discover_tello", return_value=None),
            patch("tello_mcp.drone.Tello") as mock_tello_cls,
        ):
            adapter = DroneAdapter(host="auto")
            mock_tello_cls.assert_called_once_with(host="192.168.10.1")
            assert adapter._host == "192.168.10.1"

    def test_explicit_host_unchanged(self):
        with patch("tello_mcp.drone.Tello") as mock_tello_cls:
            adapter = DroneAdapter(host="10.0.0.5")
            mock_tello_cls.assert_called_once_with(host="10.0.0.5")
            assert adapter._host == "10.0.0.5"
