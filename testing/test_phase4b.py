#!/usr/bin/env python3
"""Phase 4b Physical Test Script — Obstacle Avoidance.

Three-stage test:
  Stage 1: Lock verification — concurrent monitor + movements
  Stage 2: RETURN_TO_HOME trigger — fly toward wall, verify reverse + land
  Stage 3: Pipeline verification — confirm Neo4j ObstacleIncident

Prerequisites:
  1. docker compose up -d (Redis + Neo4j healthy)
  2. Start tello-telemetry: uv run --package tello-telemetry python -m tello_telemetry.server
  3. Start tello-mcp: uv run --package tello-mcp python -m tello_mcp.server
  4. Drone powered on and connected (Router Mode, DHCP)
  5. Clear flight area with a wall or object for RTH testing

Run: uv run python testing/test_phase4b.py
"""

from __future__ import annotations

import asyncio
import os
import sys

from neo4j import GraphDatabase

# -- Configuration (from environment, with defaults) --
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7689")
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "")


def banner(msg: str) -> None:
    """Print a visible stage banner."""
    print(f"\n{'=' * 60}")
    print(f"  {msg}")
    print(f"{'=' * 60}\n")


def result_line(label: str, ok: bool, detail: str = "") -> None:
    """Print a pass/fail result line."""
    icon = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{icon}] {label}{suffix}")


async def stage1_lock_verification() -> bool:
    """Stage 1: Verify RLock prevents crossed responses.

    Sends 5 forward/back movements while ObstacleMonitor is polling.
    All responses should be 'ok' (no crossed 'tof' readings).

    NOTE: This requires the MCP server to be running and the drone
    to be connected. The ObstacleMonitor runs automatically.
    """
    banner("STAGE 1: Lock Verification (concurrent monitor + movements)")
    print("This stage verifies that the RLock prevents UDP response crossing.")
    print("The ObstacleMonitor polls the forward ToF sensor concurrently with")
    print("flight movement commands. With the lock, responses should never cross.\n")
    print("Requires: MCP server running, drone connected, ObstacleMonitor active.\n")
    print("Manual verification steps:")
    print("  1. Open a Claude Code session connected to tello-mcp")
    print("  2. Use the move tool: move forward 50, move back 50 (5 times)")
    print("  3. After each move, call get_forward_distance")
    print("  4. Verify: move responses are always 'ok' or error dicts")
    print("  5. Verify: forward distance responses are always numeric, never 'ok'\n")
    print("If any move returns a 'tof' reading, or any sensor query returns 'ok',")
    print("the lock is not working — responses are crossing.\n")

    input("Press Enter after completing the manual verification... ")
    passed = input("Did all responses match expected types? (y/n): ").strip().lower() == "y"
    result_line("Lock prevents crossed responses", passed)
    return passed


async def stage2_rth_trigger() -> bool:
    """Stage 2: Trigger RETURN_TO_HOME by flying toward a wall.

    The drone should:
    1. Take off
    2. Fly forward toward a wall/object
    3. When forward ToF reads <200mm (~8in), ObstacleMonitor triggers DANGER
    4. Drone stops (immediate), reverses last movement, and lands

    Watch for:
    - Drone stops before hitting the wall
    - Drone reverses direction (moves back)
    - Drone lands safely
    - tello:events Redis stream receives obstacle_danger and land events
    """
    banner("STAGE 2: RETURN_TO_HOME Trigger")
    print("This stage tests the full RTH pipeline with a real obstacle.\n")
    print("Setup:")
    print("  - Place drone ~3ft (90cm) from a wall or solid object")
    print("  - Ensure clear space behind the drone for reverse movement")
    print("  - tello-telemetry must be running (Redis → Neo4j pipeline)\n")
    print("Procedure:")
    print("  1. Use Claude Code to call: takeoff")
    print("  2. Use Claude Code to call: move forward 100")
    print("  3. Observe: drone should stop at ~8in (200mm) from the wall")
    print("  4. Observe: drone should reverse (move back) and land")
    print("  5. Check MCP server logs for 'obstacle.danger' and RTH messages\n")

    input("Press Enter after completing the RTH test... ")
    stopped = input("Did the drone stop before hitting the wall? (y/n): ").strip().lower() == "y"
    reversed_moved = input("Did the drone reverse direction? (y/n): ").strip().lower() == "y"
    landed = input("Did the drone land safely? (y/n): ").strip().lower() == "y"

    result_line("Drone stopped at DANGER threshold", stopped)
    result_line("Drone reversed last movement", reversed_moved)
    result_line("Drone landed safely", landed)

    return stopped and reversed_moved and landed


async def stage3_pipeline_verification() -> bool:
    """Stage 3: Verify obstacle incident persisted in Neo4j.

    Query Neo4j for ObstacleIncident nodes created during Stage 2.
    Requires tello-telemetry to have been running during Stage 2.
    """
    banner("STAGE 3: Pipeline Verification (Neo4j)")
    print("Querying Neo4j for ObstacleIncident nodes...\n")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        with driver.session() as s:
            # Find recent obstacle incidents
            result = s.run("""
                MATCH (oi:ObstacleIncident)-[:TRIGGERED_DURING]->(fs:FlightSession)
                RETURN oi {.*} AS incident,
                       fs.id AS session_id,
                       fs.end_time IS NOT NULL AS session_closed
                ORDER BY oi.timestamp DESC
                LIMIT 5
            """)
            records = [r.data() for r in result]

            if not records:
                result_line("ObstacleIncident found in Neo4j", False, "No incidents found")
                print("\n  Check that tello-telemetry was running during Stage 2.")
                print("  Run: docker compose logs neo4j | tail -20")
                return False

            print(f"  Found {len(records)} obstacle incident(s):\n")
            for rec in records:
                inc = rec["incident"]
                print(f"    Session: {rec['session_id']}")
                print(f"    Distance: {inc.get('forward_distance_mm')}mm")
                print(f"             ({inc.get('forward_distance_in')}in)")
                print(f"    Height:   {inc.get('height_cm')}cm")
                print(f"    Zone:     {inc.get('zone')}")
                print(f"    Response: {inc.get('response')}")
                print(f"    Outcome:  {inc.get('outcome')}")
                print(f"    Reversed: {inc.get('reversed_direction')}")
                print(f"    Session closed: {rec['session_closed']}")
                print()

            result_line("ObstacleIncident found in Neo4j", True, f"{len(records)} incident(s)")

            # Check session was closed (land event worked)
            any_closed = any(r["session_closed"] for r in records)
            result_line("FlightSession has end_time", any_closed)

            return True
    finally:
        driver.close()


async def main() -> None:
    """Run all three stages."""
    banner("Phase 4b Physical Test — Obstacle Avoidance")
    print("This script guides you through three test stages.\n")
    print("Prerequisites:")
    print("  1. docker compose up -d")
    print("  2. tello-telemetry running")
    print("  3. tello-mcp running")
    print("  4. Drone powered on and connected\n")

    ready = input("Are all prerequisites met? (y/n): ").strip().lower()
    if ready != "y":
        print("\nPlease set up prerequisites first.")
        sys.exit(1)

    results = {}

    results["stage1"] = await stage1_lock_verification()
    results["stage2"] = await stage2_rth_trigger()
    results["stage3"] = await stage3_pipeline_verification()

    # Summary
    banner("TEST SUMMARY")
    result_line("Stage 1: Lock Verification", results["stage1"])
    result_line("Stage 2: RTH Trigger", results["stage2"])
    result_line("Stage 3: Pipeline Verification", results["stage3"])

    all_passed = all(results.values())
    print(f"\n  Overall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
