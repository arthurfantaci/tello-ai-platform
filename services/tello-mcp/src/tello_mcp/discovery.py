"""Auto-discover Tello TT on the local network.

Scans the local /24 subnet for a Tello responding on UDP 8889.
Focused on the common DHCP range (100-200) for speed.
"""

from __future__ import annotations

import socket
import subprocess

import structlog

logger = structlog.get_logger("tello_mcp.discovery")


def get_local_subnet() -> str | None:
    """Get the /24 subnet prefix from the default interface (macOS)."""
    try:
        result = subprocess.run(
            ["/usr/sbin/ipconfig", "getifaddr", "en0"],
            capture_output=True,
            text=True,
            check=True,
        )
        ip = result.stdout.strip()
        return ".".join(ip.split(".")[:3])
    except (subprocess.CalledProcessError, IndexError):
        return None


def discover_tello(
    subnet: str | None = None,
    timeout_per_host: float = 0.15,
    range_start: int = 100,
    range_end: int = 200,
) -> str | None:
    """Scan subnet for a Tello responding on UDP 8889.

    Args:
        subnet: Subnet prefix (e.g. "192.168.68"). Auto-detected if None.
        timeout_per_host: Socket timeout per host in seconds.
        range_start: First host octet to scan.
        range_end: Last host octet to scan (inclusive).

    Returns:
        The discovered drone IP, or None if not found.
    """
    if subnet is None:
        subnet = get_local_subnet()
    if subnet is None:
        logger.warning("Could not determine local subnet")
        return None

    logger.info("Scanning for Tello", subnet=subnet, range=f"{range_start}-{range_end}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout_per_host)

    try:
        for i in range(range_start, range_end + 1):
            ip = f"{subnet}.{i}"
            try:
                sock.sendto(b"command", (ip, 8889))
                response, addr = sock.recvfrom(1024)
                if response.decode().strip() == "ok":
                    logger.info("Found Tello", ip=addr[0])
                    return addr[0]
            except (TimeoutError, OSError):
                continue
    finally:
        sock.close()

    logger.warning("Tello not found on subnet", subnet=subnet)
    return None
