"""One-time setup: configure Tello TT to join your home WiFi (Router Mode).

Prerequisites:
    1. Expansion board switch set to DIRECT MODE
    2. Drone powered on with expansion board mounted
    3. Mac WiFi connected to RMTT-XXXXXX network

Usage:
    uv run python scripts/setup_router_mode.py "YourWifiSSID" "YourWifiPassword"

After running:
    1. Drone will reboot and connect to your home WiFi
    2. Reconnect your Mac to home WiFi
    3. Flip expansion board switch to ROUTER MODE
    4. Find drone IP in your router's DHCP table (or run: scripts/find_drone.py)
"""

from __future__ import annotations

import socket
import sys
import time


def send_command(sock: socket.socket, command: str, timeout: float = 10.0) -> str:
    """Send a command to the Tello and wait for response."""
    sock.settimeout(timeout)
    sock.sendto(command.encode(), ("192.168.10.1", 8889))
    try:
        response, _ = sock.recvfrom(1024)
        return response.decode().strip()
    except TimeoutError:
        return "TIMEOUT"


def main() -> None:
    """Configure Tello TT to join home WiFi via Router Mode setup."""
    if len(sys.argv) != 3:
        print("Usage: uv run python scripts/setup_router_mode.py <wifi_ssid> <wifi_password>")
        print('Example: uv run python scripts/setup_router_mode.py "MyNetwork" "MyPassword"')
        sys.exit(1)

    ssid = sys.argv[1]
    password = sys.argv[2]

    print("=" * 60)
    print("Tello TT Router Mode Setup")
    print("=" * 60)
    print()
    print("Checklist:")
    print("  [ ] Expansion board switch is on DIRECT MODE")
    print("  [ ] Drone is powered on with expansion board mounted")
    print(f"  [ ] Mac WiFi is connected to RMTT-XXXXXX (not {ssid})")
    print()

    confirm = input("Ready? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        sys.exit(0)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", 8889))

    print("\n1. Entering SDK mode...")
    response = send_command(sock, "command")
    print(f"   Response: {response}")
    if response != "ok":
        print("   ERROR: Could not enter SDK mode. Is the drone on and connected?")
        sys.exit(1)

    print(f'\n2. Sending: ap "{ssid}" "{password}"')
    print("   (Drone will reboot after this — response may timeout, that's normal)")
    time.sleep(1)
    response = send_command(sock, f"ap {ssid} {password}", timeout=15.0)
    print(f"   Response: {response}")

    sock.close()

    print()
    print("=" * 60)
    print("Setup command sent!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Wait 15-20 seconds for the drone to reboot")
    print(f"  2. Reconnect your Mac to '{ssid}'")
    print("  3. Flip the expansion board switch to ROUTER MODE")
    print("  4. Find the drone's IP on your router's DHCP table")
    print("     Or run: uv run python scripts/find_drone.py")
    print("  5. Add TELLO_HOST=<drone-ip> to your .env file")
    print()
    print("From now on, the drone will auto-join your WiFi on every power-on.")


if __name__ == "__main__":
    main()
