"""Find the Tello TT on your local network after Router Mode setup.

Scans common local subnets for the Tello's UDP command port (8889).
Uses the shared discovery module from tello_mcp.

Usage:
    uv run python scripts/find_drone.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from tello_mcp.discovery import discover_tello, get_local_subnet

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


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

    # Full range scan (1-254) for standalone script; discovery module uses 100-200
    drone_ip = discover_tello(subnet=subnet, timeout_per_host=0.3, range_start=1, range_end=254)
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
