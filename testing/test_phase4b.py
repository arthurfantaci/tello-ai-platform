#!/usr/bin/env python3
"""Phase 4b Physical Test Script — Obstacle Avoidance.

Automated test harness with structured JSON data capture, following the
established pattern from scripts/test_tof.py.

Three stages:
  Stage 1: Lock verification — concurrent ObstacleMonitor + movements
  Stage 2: RETURN_TO_HOME trigger — fly toward wall, verify reverse + land
  Stage 3: Pipeline verification — confirm Neo4j ObstacleIncident

Prerequisites:
  1. docker compose up -d (Redis + Neo4j healthy)
  2. Start tello-telemetry: uv run --package tello-telemetry python -m tello_telemetry.server
  3. Drone powered on and connected (Router Mode, DHCP)
  4. Clear flight area with a wall ~3ft (90cm) in front of the drone

Run: uv run python testing/test_phase4b.py [--host IP|auto]

Output: testing/phase4b-obstacle-avoidance-results-YYYY-MM-DD.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from neo4j import GraphDatabase

from tello_core.models import TelemetryFrame
from tello_mcp.drone import DroneAdapter
from tello_mcp.obstacle import ObstacleConfig, ObstacleMonitor, ObstacleResponseHandler
from tello_mcp.strategies import SimpleReverseRTH

# -- Configuration --
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7689")
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "")

TAKEOFF_DELAY = 3.0
COMMAND_DELAY = 0.5
MONITOR_SETTLE_MS = 500
OUT_OF_RANGE_MIN = 8000


def mm_to_imperial(mm: int) -> str:
    """Convert mm to approximate imperial string for operator display."""
    inches = mm / 25.4
    if inches >= 36:
        return f"~{inches / 12:.1f}ft"
    return f"~{inches:.1f}in"


def prompt(msg: str) -> None:
    """Print a prompt and wait for Enter."""
    input(f"\n{msg} Press Enter to continue...")


def read_distance(drone: DroneAdapter) -> dict:
    """Single forward ToF reading."""
    return drone.get_forward_distance()


# ── Stage 1: Lock Verification ──────────────────────────────────────


async def run_stage1(drone: DroneAdapter, monitor: ObstacleMonitor) -> dict:
    """Lock verification — concurrent monitor + movements.

    Starts the ObstacleMonitor (which polls get_forward_distance at 3.2Hz
    via asyncio.to_thread), then executes 5 forward/back movement pairs.
    The RLock should serialize all SDK calls — zero crossed responses.
    """
    print("\n" + "=" * 60)
    print("  STAGE 1: Lock Verification")
    print("=" * 60)
    print()
    print("  The ObstacleMonitor will poll the forward ToF sensor continuously")
    print("  while the drone executes forward/back movements. The RLock should")
    print("  prevent UDP response crossing (no 'tof' in move responses, no 'ok'")
    print("  in sensor responses).")
    prompt("Drone must be airborne or on the ground connected. Confirm ready.")

    # Start monitor — it will poll concurrently with our commands
    await monitor.start()
    await asyncio.sleep(MONITOR_SETTLE_MS / 1000)

    move_results = []
    sensor_results = []
    crossed_responses = 0

    for i in range(5):
        print(f"\n  [{i + 1}/5] Moving forward 30cm (~12in)...")
        move_result = await asyncio.to_thread(drone.move, "forward", 30)
        move_ok = move_result.get("status") == "ok" or "error" in move_result
        move_crossed = "tof" in str(move_result).lower() and "status" not in move_result
        if move_crossed:
            crossed_responses += 1
        move_results.append(
            {
                "iteration": i + 1,
                "direction": "forward",
                "result": move_result,
                "ok": move_ok,
                "crossed": move_crossed,
            }
        )
        print(f"    Move result: {move_result}")

        await asyncio.sleep(COMMAND_DELAY)

        # Sensor check between moves
        sensor_result = await asyncio.to_thread(drone.get_forward_distance)
        sensor_ok = sensor_result.get("status") == "ok" or "error" in sensor_result
        sensor_crossed = sensor_result.get("status") == "ok" and "distance_mm" not in sensor_result
        if sensor_crossed:
            crossed_responses += 1
        sensor_results.append(
            {
                "iteration": i + 1,
                "result": sensor_result,
                "ok": sensor_ok,
                "crossed": sensor_crossed,
            }
        )
        print(f"    Sensor: {sensor_result}")

        await asyncio.sleep(COMMAND_DELAY)

        print(f"  [{i + 1}/5] Moving back 30cm (~12in)...")
        back_result = await asyncio.to_thread(drone.move, "back", 30)
        move_results.append(
            {
                "iteration": i + 1,
                "direction": "back",
                "result": back_result,
                "ok": back_result.get("status") == "ok" or "error" in back_result,
                "crossed": False,
            }
        )
        print(f"    Move result: {back_result}")
        await asyncio.sleep(COMMAND_DELAY)

    await monitor.stop()

    status = "pass" if crossed_responses == 0 else "fail"
    notes = "" if status == "pass" else f"{crossed_responses} crossed response(s) detected"

    print(f"\n  Crossed responses: {crossed_responses}")
    print(f"  {status.upper()}" + (f" ({notes})" if notes else ""))

    return {
        "name": "lock_verification",
        "status": status,
        "crossed_responses": crossed_responses,
        "move_results": move_results,
        "sensor_results": sensor_results,
        "notes": notes,
    }


# ── Stage 2: RETURN_TO_HOME Trigger ─────────────────────────────────


async def run_stage2(
    drone: DroneAdapter,
    monitor: ObstacleMonitor,
    config: ObstacleConfig,
) -> dict:
    """RTH trigger — fly toward wall, verify stop → reverse → land.

    The ObstacleMonitor runs with the on_obstacle_reading callback wired
    to SimpleReverseRTH. When DANGER is detected (<200mm / ~8in), the
    drone should automatically: stop → reverse → land.
    """
    print("\n" + "=" * 60)
    print("  STAGE 2: RETURN_TO_HOME Trigger")
    print("=" * 60)
    print()
    print("  Place drone ~3ft (90cm) from a wall or solid object.")
    print("  Ensure clear space behind the drone for reverse movement.")
    print(f"  DANGER threshold: <{config.danger_mm}mm ({mm_to_imperial(config.danger_mm)})")
    print()
    print("  The drone will:")
    print("    1. Take off")
    print("    2. Advance in 20cm (~8in) increments toward the wall")
    print("    3. When DANGER triggers, auto-RTH: stop → reverse → land")

    # Battery check
    telemetry = drone.get_telemetry()
    battery = telemetry.battery_pct if isinstance(telemetry, TelemetryFrame) else None
    if battery is not None and battery < 30:
        print(f"\n  WARNING: Battery is {battery}% (< 30%)")
        resp = input("  Continue anyway? (y/n): ").strip().lower()
        if resp != "y":
            return {
                "name": "rth_trigger",
                "status": "skipped",
                "notes": f"Low battery ({battery}%)",
                "battery_pct": battery,
            }

    # Pre-flight distance check
    pre = read_distance(drone)
    if pre.get("status") != "ok":
        print(f"  ABORT — cannot read sensor: {pre}")
        return {
            "name": "rth_trigger",
            "status": "fail",
            "notes": f"Pre-flight sensor error: {pre}",
        }

    pre_mm = pre["distance_mm"]
    if pre_mm < 500 and pre_mm < OUT_OF_RANGE_MIN:
        print(
            f"  ABORT — too close to wall ({pre_mm}mm / {mm_to_imperial(pre_mm)}). Move drone back."
        )
        return {
            "name": "rth_trigger",
            "status": "fail",
            "pre_flight_distance_mm": pre_mm,
            "notes": "Too close to wall",
        }

    resp = input("\n  Ready to fly? (y/n): ").strip().lower()
    if resp != "y":
        return {"name": "rth_trigger", "status": "skipped", "notes": "User declined"}

    # Set up RTH wiring — same as server.py but local
    last_command: dict = {}
    strategy = SimpleReverseRTH()
    handler = ObstacleResponseHandler(
        drone=drone,
        rth_strategy=strategy,
        telemetry=None,  # No Redis in physical test — capture data locally
        last_command=last_command,
    )
    monitor.on_reading(handler.on_obstacle_reading)

    distance_checks = [
        {
            "phase": "pre_flight",
            "timestamp": datetime.now(UTC).isoformat(),
            "distance_mm": pre_mm,
            "zone": monitor.classify_zone(pre_mm).value,
        },
    ]

    rth_triggered = False
    total_moved_cm = 0
    increment_cm = 20
    max_blind_increments = 3
    sensor_contacted = False
    takeoff_result = None

    try:
        # Takeoff
        print("  Taking off...")
        takeoff_result = drone.takeoff()
        if takeoff_result.get("status") != "ok":
            # Check if airborne despite error (djitellopy retry race)
            height_result = drone.get_height()
            height = height_result.get("height_cm", 0) if height_result.get("status") == "ok" else 0
            if height > 0:
                print(f"  NOTE: takeoff() error but drone airborne (height={height}cm)")
            else:
                print(f"  FAIL — takeoff failed: {takeoff_result}")
                return {
                    "name": "rth_trigger",
                    "status": "fail",
                    "takeoff_result": takeoff_result,
                    "notes": "Takeoff failed",
                }

        # Update last_command for RTH context
        last_command["direction"] = "forward"
        last_command["distance_cm"] = increment_cm

        print(f"  Stabilizing ({TAKEOFF_DELAY}s)...")
        time.sleep(TAKEOFF_DELAY)

        # Start monitor — RTH callback is wired
        await monitor.start()
        await asyncio.sleep(MONITOR_SETTLE_MS / 1000)

        # Incremental approach
        blind_increments = 0
        prompt("Drone hovering. Will advance in 20cm (~8in) increments.")

        while not rth_triggered:
            total_moved_cm += increment_cm
            print(f"  Moving forward {increment_cm}cm ({mm_to_imperial(increment_cm * 10)})...")

            # Update last_command before move (RTH needs this)
            last_command["direction"] = "forward"
            last_command["distance_cm"] = increment_cm

            drone.move("forward", increment_cm)
            time.sleep(COMMAND_DELAY)

            # Check if RTH was triggered by the monitor during/after the move
            # (the monitor runs in the background via asyncio)
            await asyncio.sleep(0.3)  # Give monitor time to react

            # Discrete sensor check
            r = read_distance(drone)
            ts = datetime.now(UTC).isoformat()
            if r.get("status") == "ok":
                mm = r["distance_mm"]
                zone = monitor.classify_zone(mm)
                distance_checks.append(
                    {
                        "phase": f"after_{total_moved_cm}cm",
                        "timestamp": ts,
                        "distance_mm": mm,
                        "zone": zone.value,
                    }
                )
                print(
                    f"  After {total_moved_cm}cm: {mm}mm "
                    f"({mm_to_imperial(mm)}) ({zone.value.upper()})"
                )
                if mm < OUT_OF_RANGE_MIN:
                    sensor_contacted = True
                    blind_increments = 0
                    if zone.value == "danger":
                        rth_triggered = True
                        print("\n  DANGER DETECTED — RTH should auto-trigger")
                        # Give the monitor callback time to execute RTH
                        await asyncio.sleep(2.0)
                        break
                else:
                    blind_increments += 1
            else:
                blind_increments += 1
                distance_checks.append(
                    {
                        "phase": f"after_{total_moved_cm}cm",
                        "timestamp": ts,
                        "distance_mm": None,
                        "zone": "error",
                    }
                )

            # Safety: stop if sensor blind too long
            if not sensor_contacted and blind_increments >= max_blind_increments:
                print(
                    f"\n  SENSOR BLIND — {blind_increments} consecutive "
                    f"increments with no wall detection. Landing safely."
                )
                drone.safe_land()
                break

        await monitor.stop()

    except KeyboardInterrupt:
        print("\n  Interrupted! Emergency landing...")
        drone.safe_land()
        await monitor.stop()
        return {
            "name": "rth_trigger",
            "status": "interrupted",
            "distance_checks": distance_checks,
            "total_moved_cm": total_moved_cm,
            "notes": "User interrupted",
        }
    except Exception as e:
        print(f"\n  ERROR: {e}")
        print("  Emergency landing...")
        drone.safe_land()
        await monitor.stop()
        return {
            "name": "rth_trigger",
            "status": "fail",
            "distance_checks": distance_checks,
            "total_moved_cm": total_moved_cm,
            "notes": f"Flight error: {e}",
        }

    # Determine outcome
    if rth_triggered:
        # Ask operator to confirm observed behavior
        print()
        reversed_ok = (
            input("  Did the drone reverse direction (move back)? (y/n): ").strip().lower() == "y"
        )
        landed_ok = input("  Did the drone land safely? (y/n): ").strip().lower() == "y"
        status = "pass" if reversed_ok and landed_ok else "partial"
        notes = ""
        if not reversed_ok:
            notes += "Reverse not observed. "
        if not landed_ok:
            notes += "Landing not observed. "
    elif not sensor_contacted:
        status = "sensor_blind"
        notes = "Sensor returned OOR at altitude — VL53L0X FOV limitation"
        reversed_ok = False
        landed_ok = False
    else:
        status = "needs_adjustment"
        notes = "Sensor detected wall but DANGER never triggered"
        reversed_ok = False
        landed_ok = False

    print(f"\n  {status.upper()}" + (f" ({notes})" if notes else ""))

    return {
        "name": "rth_trigger",
        "status": status,
        "pre_flight_distance_mm": pre_mm,
        "total_moved_cm": total_moved_cm,
        "sensor_contacted": sensor_contacted,
        "rth_triggered": rth_triggered,
        "reversed_observed": reversed_ok if rth_triggered else None,
        "landed_observed": landed_ok if rth_triggered else None,
        "distance_checks": distance_checks,
        "takeoff_result": takeoff_result,
        "battery_pct": battery,
        "notes": notes,
    }


# ── Stage 3: Pipeline Verification ──────────────────────────────────


def run_stage3() -> dict:
    """Pipeline verification — query Neo4j for ObstacleIncident nodes."""
    print("\n" + "=" * 60)
    print("  STAGE 3: Pipeline Verification (Neo4j)")
    print("=" * 60)
    print()

    if not NEO4J_PASS:
        print("  SKIP — NEO4J_PASSWORD not set. Set it to query Neo4j.")
        return {
            "name": "pipeline_verification",
            "status": "skipped",
            "notes": "NEO4J_PASSWORD not set",
        }

    print("  Querying Neo4j for ObstacleIncident nodes...\n")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        with driver.session() as s:
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
                print("  No ObstacleIncident nodes found.")
                print("  Check that tello-telemetry was running during Stage 2.")
                return {
                    "name": "pipeline_verification",
                    "status": "fail",
                    "incident_count": 0,
                    "incidents": [],
                    "notes": "No incidents in Neo4j",
                }

            incidents_data = []
            for rec in records:
                inc = rec["incident"]
                entry = {
                    "session_id": rec["session_id"],
                    "session_closed": rec["session_closed"],
                    "forward_distance_mm": inc.get("forward_distance_mm"),
                    "forward_distance_in": inc.get("forward_distance_in"),
                    "height_cm": inc.get("height_cm"),
                    "zone": inc.get("zone"),
                    "response": inc.get("response"),
                    "outcome": inc.get("outcome"),
                    "reversed_direction": inc.get("reversed_direction"),
                }
                incidents_data.append(entry)
                print(f"    Session:  {entry['session_id']}")
                dist_mm = entry["forward_distance_mm"]
                dist_in = entry["forward_distance_in"]
                print(f"    Distance: {dist_mm}mm ({dist_in}in)")
                print(f"    Height:   {entry['height_cm']}cm")
                print(f"    Response: {entry['response']} → {entry['outcome']}")
                print(f"    Reversed: {entry['reversed_direction']}")
                print(f"    Session closed: {entry['session_closed']}")
                print()

            any_closed = any(r["session_closed"] for r in records)
            status = "pass" if any_closed else "partial"
            notes = (
                ""
                if status == "pass"
                else "Incidents found but no session closed (land event missing?)"
            )

            print(f"  Found {len(records)} incident(s). Session closed: {any_closed}")
            print(f"  {status.upper()}" + (f" ({notes})" if notes else ""))

            return {
                "name": "pipeline_verification",
                "status": status,
                "incident_count": len(records),
                "incidents": incidents_data,
                "any_session_closed": any_closed,
                "notes": notes,
            }
    finally:
        driver.close()


# ── Main ─────────────────────────────────────────────────────────────


def save_results(output: dict) -> None:
    """Save results to testing/ as timestamped JSON."""
    testing_dir = Path("testing")
    testing_dir.mkdir(exist_ok=True)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    path = testing_dir / f"phase4b-obstacle-avoidance-results-{date_str}.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {path}")


def print_summary(results: list[dict]) -> None:
    """Print console summary."""
    print("\n" + "=" * 60)
    print("  TEST SUMMARY")
    print("=" * 60)
    icons = {
        "pass": "PASS",
        "fail": "FAIL",
        "skipped": "SKIP",
        "partial": "WARN",
        "sensor_blind": "BLIND",
    }
    for t in results:
        icon = icons.get(t["status"], "????")
        print(f"  [{icon}] {t['name']}: {t['status'].upper()}")
        if t.get("notes"):
            print(f"         → {t['notes']}")
    print("=" * 60)


async def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Phase 4b obstacle avoidance test")
    parser.add_argument("--host", default="auto", help="Drone IP or 'auto' for discovery")
    parsed = parser.parse_args()

    print("=" * 60)
    print("  Phase 4b: Obstacle Avoidance — Physical Test Suite")
    print("=" * 60)
    print()
    print("  Prerequisites:")
    print("    1. docker compose up -d (Redis + Neo4j)")
    print("    2. tello-telemetry running (for Stage 3)")
    print("    3. Drone powered on and connected")
    print("    4. Clear flight area with wall ~3ft (90cm) ahead")

    prompt("Confirm prerequisites met.")

    # Connect
    print(f"\nConnecting to drone (host={parsed.host})...")
    drone = DroneAdapter(host=parsed.host)
    result = drone.connect()
    if "error" in result:
        print(f"Connection failed: {result}")
        sys.exit(1)
    print("Connected.")

    # Setup
    config = ObstacleConfig.from_env()
    monitor = ObstacleMonitor(drone, config)

    # Battery
    telemetry = drone.get_telemetry()
    battery_start = telemetry.battery_pct if isinstance(telemetry, TelemetryFrame) else None
    print(f"Battery: {battery_start}%")
    print(
        f"Thresholds: CAUTION <{config.caution_mm}mm ({mm_to_imperial(config.caution_mm)}), "
        f"WARNING <{config.warning_mm}mm ({mm_to_imperial(config.warning_mm)}), "
        f"DANGER <{config.danger_mm}mm ({mm_to_imperial(config.danger_mm)})"
    )

    results: list[dict] = []

    try:
        # Stage 1: Lock verification (ground-based, no flight)
        s1 = await run_stage1(drone, monitor)
        results.append(s1)

        # Stage 2: RTH trigger (flight test)
        # Create a fresh monitor since Stage 1 used it
        monitor2 = ObstacleMonitor(drone, config)
        s2 = await run_stage2(drone, monitor2, config)
        results.append(s2)

        # Stage 3: Pipeline verification (Neo4j query)
        s3 = run_stage3()
        results.append(s3)

    except KeyboardInterrupt:
        print("\n\nInterrupted! Attempting safe landing...")
        drone.safe_land()

    # Final battery
    telemetry = drone.get_telemetry()
    battery_end = telemetry.battery_pct if isinstance(telemetry, TelemetryFrame) else None

    # Build output
    output = {
        "date": datetime.now(UTC).isoformat(),
        "phase": "4b",
        "test_name": "obstacle_avoidance",
        "drone_host": parsed.host,
        "battery_start": battery_start,
        "battery_end": battery_end,
        "obstacle_config": {
            "caution_mm": config.caution_mm,
            "warning_mm": config.warning_mm,
            "danger_mm": config.danger_mm,
            "out_of_range_min": config.out_of_range_min,
            "required_clear_readings": config.required_clear_readings,
            "poll_interval_ms": config.poll_interval_ms,
        },
        "tests": results,
    }

    save_results(output)
    print_summary(results)

    drone.disconnect()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
