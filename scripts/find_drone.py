"""Find the Tello TT on your local network after Router Mode setup.

Scans common local subnets for the Tello's UDP command port (8889).

Usage:
    uv run python scripts/find_drone.py
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


def get_local_subnet() -> str | None:
    """Get the local subnet from the default route interface."""
    try:
        result = subprocess.run(
            ["/usr/sbin/ipconfig", "getifaddr", "en0"],
            capture_output=True,
            text=True,
            check=True,
        )
        ip = result.stdout.strip()
        # Return the /24 subnet prefix
        return ".".join(ip.split(".")[:3])
    except (subprocess.CalledProcessError, IndexError):
        return None


def scan_for_tello(subnet: str) -> str | None:
    """Scan subnet for a Tello responding on UDP 8889."""
    print(f"Scanning {subnet}.0/24 for Tello TT...")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.3)

    for i in range(1, 255):
        ip = f"{subnet}.{i}"
        try:
            sock.sendto(b"command", (ip, 8889))
            response, addr = sock.recvfrom(1024)
            if response.decode().strip() == "ok":
                sock.close()
                return addr[0]
        except (TimeoutError, OSError):
            continue

    sock.close()
    return None


def update_env_file(ip: str) -> None:
    """Write or update TELLO_HOST in .env file.

    If .env doesn't exist, copies from .env.example first.
    If TELLO_HOST exists, updates it. Otherwise appends it.
    """
    if not ENV_FILE.exists():
        if ENV_EXAMPLE.exists():
            ENV_FILE.write_text(ENV_EXAMPLE.read_text())
            print("Created .env from .env.example")
        else:
            ENV_FILE.write_text("")
            print("Created empty .env")

    content = ENV_FILE.read_text()
    new_line = f"TELLO_HOST={ip}"

    if re.search(r"^TELLO_HOST=.*$", content, re.MULTILINE):
        content = re.sub(
            r"^TELLO_HOST=.*$",
            new_line,
            content,
            flags=re.MULTILINE,
        )
        print(f"Updated TELLO_HOST={ip} in .env")
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += f"\n# Tello drone IP (auto-discovered)\n{new_line}\n"
        print(f"Added TELLO_HOST={ip} to .env")

    ENV_FILE.write_text(content)


def main() -> None:
    """Scan local network for Tello TT and update .env with its IP."""
    print("Tello TT Network Scanner")
    print("=" * 40)

    subnet = get_local_subnet()
    if not subnet:
        print("Could not determine local subnet. Check your WiFi connection.")
        sys.exit(1)

    print(f"Local subnet: {subnet}.0/24")
    print()

    drone_ip = scan_for_tello(subnet)
    if drone_ip:
        print(f"\nFound Tello TT at: {drone_ip}")
        update_env_file(drone_ip)
    else:
        print("\nTello TT not found on the network.")
        print("Make sure:")
        print("  - The drone is powered on")
        print("  - The expansion board switch is on ROUTER MODE")
        print("  - The drone has successfully connected to your WiFi")
        print("  - You're on the same network as the drone")


if __name__ == "__main__":
    main()
