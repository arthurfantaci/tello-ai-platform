"""CLI test tool for physical drone testing.

Bypasses MCP entirely — uses DroneAdapter directly.
Built-in delays between commands to prevent "Not joystick" errors.

Usage:
    uv run python scripts/fly.py [--host IP|auto] COMMAND [ARGS...]
    uv run python scripts/fly.py --host auto repl

Commands:
    connect               Connect to drone
    telemetry             Show telemetry snapshot
    takeoff               Take off and hover
    land                  Land (with emergency fallback)
    emergency             Kill motors immediately
    move DIR DIST         Move in direction (forward/back/left/right/up/down) by DIST cm
    rotate DEG            Rotate by DEG degrees (positive=CW, negative=CCW)
    led R G B             Set LED color (0-255 each)
    text MSG              Scroll text on LED matrix
    pad                   Detect mission pad
    goto X Y Z SPD MID    Fly to mission pad coordinates
    battery               Show battery percentage
    repl                  Interactive command mode
"""

from __future__ import annotations

import argparse
import sys
import time

from tello_mcp.drone import DroneAdapter

# Delay after takeoff (drone needs time to stabilize)
TAKEOFF_DELAY = 3.0
# Delay between normal commands
COMMAND_DELAY = 0.5


def run_command(drone: DroneAdapter, cmd: str, args: list[str]) -> bool:
    """Execute a single command. Returns False to exit REPL."""
    match cmd:
        case "connect":
            result = drone.connect()
            print(result)

        case "telemetry":
            result = drone.get_telemetry()
            if isinstance(result, dict):
                print(result)
            else:
                print(result.model_dump_json(indent=2))

        case "takeoff":
            result = drone.takeoff()
            print(result)
            if result.get("status") == "ok":
                print(f"Stabilizing... ({TAKEOFF_DELAY}s)")
                time.sleep(TAKEOFF_DELAY)

        case "land":
            result = drone.safe_land()
            print(result)

        case "emergency":
            result = drone.emergency()
            print(result)

        case "move":
            if len(args) < 2:
                print("Usage: move DIRECTION DISTANCE_CM")
                return True
            result = drone.move(args[0], int(args[1]))
            print(result)

        case "rotate":
            if len(args) < 1:
                print("Usage: rotate DEGREES")
                return True
            result = drone.rotate(int(args[0]))
            print(result)

        case "led":
            if len(args) < 3:
                print("Usage: led R G B")
                return True
            result = drone.set_led(int(args[0]), int(args[1]), int(args[2]))
            print(result)

        case "text":
            if len(args) < 1:
                print("Usage: text MESSAGE")
                return True
            result = drone.display_scroll_text(" ".join(args))
            print(result)

        case "pad":
            result = drone.detect_mission_pad()
            print(result)

        case "goto":
            if len(args) < 5:
                print("Usage: goto X Y Z SPEED MID")
                return True
            result = drone.go_xyz_speed_mid(
                int(args[0]),
                int(args[1]),
                int(args[2]),
                int(args[3]),
                int(args[4]),
            )
            print(result)

        case "battery":
            result = drone.get_telemetry()
            if isinstance(result, dict):
                print(result)
            else:
                print(f"Battery: {result.battery_pct}%")

        case "quit" | "exit" | "q":
            return False

        case _:
            print(f"Unknown command: {cmd}")
            print("Commands: connect, telemetry, takeoff, land, emergency, move, rotate,")
            print("          led, text, pad, goto, battery, repl, quit")

    return True


def repl(drone: DroneAdapter) -> None:
    """Interactive command loop."""
    print("Tello REPL — type 'quit' to exit")
    print("Commands: connect, telemetry, takeoff, land, emergency, move, rotate,")
    print("          led, text, pad, goto, battery, quit")
    print()

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            break

        if not line:
            continue

        parts = line.split()
        cmd, args = parts[0], parts[1:]

        if not run_command(drone, cmd, args):
            break

        # Inter-command delay (except after takeoff which has its own)
        if cmd not in ("takeoff", "quit", "exit", "q", "connect"):
            time.sleep(COMMAND_DELAY)


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Tello TT flight test CLI")
    parser.add_argument("--host", default="auto", help="Drone IP or 'auto' for discovery")
    parser.add_argument("command", nargs="?", help="Command to run (or 'repl')")
    parser.add_argument("args", nargs="*", help="Command arguments")
    parsed = parser.parse_args()

    if not parsed.command:
        parser.print_help()
        sys.exit(1)

    print(f"Connecting to drone (host={parsed.host})...")
    drone = DroneAdapter(host=parsed.host)

    if parsed.command == "repl":
        # Auto-connect in REPL mode
        print("Auto-connecting...")
        result = drone.connect()
        print(result)
        if "error" in result:
            print("Connect failed — you can retry with 'connect' in the REPL")
        repl(drone)
    else:
        # Single command mode
        if parsed.command != "connect":
            # Auto-connect for non-connect commands
            result = drone.connect()
            if "error" in result:
                print(f"Connect failed: {result}")
                sys.exit(1)
        run_command(drone, parsed.command, parsed.args)

    # Clean disconnect
    drone.disconnect()
    print("Done.")


if __name__ == "__main__":
    main()
