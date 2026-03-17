"""Phase 4 ToF sensor physical test script.

Guided interactive test harness for validating the forward-facing
Time-of-Flight sensor and collecting characterization data.

Usage:
    uv run python scripts/test_tof.py [--host IP|auto]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tello_core.models import ObstacleReading, TelemetryFrame
from tello_mcp.drone import DroneAdapter
from tello_mcp.obstacle import (
    CLIResponseProvider,
    ObstacleConfig,
    ObstacleMonitor,
    ObstacleResponseHandler,
)

TAKEOFF_DELAY = 3.0
COMMAND_DELAY = 0.5
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
    """Single forward ToF reading. Returns the raw result dict."""
    return drone.get_forward_distance()


def run_test_1(drone: DroneAdapter, monitor: ObstacleMonitor) -> dict:
    """Test 1: Sensor Alive — verify get_forward_distance() works."""
    print("\n" + "─" * 60)
    print("TEST 1: Sensor Alive")
    print("─" * 60)
    prompt("Point drone forward at open room.")

    result = read_distance(drone)
    if result.get("status") != "ok":
        print(f"  FAIL — sensor returned error: {result}")
        return {
            "name": "sensor_alive",
            "status": "fail",
            "reading": None,
            "notes": str(result),
        }

    mm = result["distance_mm"]
    zone = monitor.classify_zone(mm)
    print(f"  Reading: {mm}mm ({mm_to_imperial(mm)}) ({zone.value.upper()})")
    print("  PASS")
    return {
        "name": "sensor_alive",
        "status": "pass",
        "reading": {"distance_mm": mm, "zone": zone.value},
        "notes": "",
    }


def run_test_2(drone: DroneAdapter, monitor: ObstacleMonitor) -> dict:
    """Test 2: Range Sweep — verify readings track movement."""
    print("\n" + "─" * 60)
    print("TEST 2: Range Sweep (10 seconds)")
    print("─" * 60)
    prompt("Slowly move your hand toward the sensor over 10 seconds.")

    readings = []
    for i in range(20):
        result = read_distance(drone)
        ts = datetime.now(UTC).isoformat()
        if result.get("status") == "ok":
            mm = result["distance_mm"]
            zone = monitor.classify_zone(mm)
            readings.append({"timestamp": ts, "distance_mm": mm, "zone": zone.value})
            print(f"  [{i + 1:2d}/20] {mm}mm ({mm_to_imperial(mm)}) ({zone.value.upper()})")
        else:
            readings.append({"timestamp": ts, "distance_mm": None, "zone": "error"})
            print(f"  [{i + 1:2d}/20] ERROR: {result}")
        time.sleep(0.5)

    valid = [
        r["distance_mm"]
        for r in readings
        if r["distance_mm"] is not None and r["distance_mm"] < OUT_OF_RANGE_MIN
    ]
    distinct = len(set(valid))
    mn = min(valid) if valid else None
    mx = max(valid) if valid else None

    status = "pass" if distinct >= 3 else "fail"
    notes = "" if status == "pass" else f"Only {distinct} distinct values"
    print(f"\n  Distinct values: {distinct}, Min: {mn}, Max: {mx}")
    print(f"  {status.upper()}")

    return {
        "name": "range_sweep",
        "status": status,
        "readings": readings,
        "stats": {"min": mn, "max": mx, "distinct_values": distinct},
        "notes": notes,
    }


def run_test_3(drone: DroneAdapter, monitor: ObstacleMonitor) -> dict:
    """Test 3: Close Object — verify DANGER zone at <200mm (~8in)."""
    print("\n" + "─" * 60)
    print("TEST 3: Close Object Detection")
    print("─" * 60)
    prompt("Hold your hand less than 200mm (~8in) from the sensor.")

    result = read_distance(drone)
    if result.get("status") != "ok":
        print(f"  FAIL — sensor error: {result}")
        return {
            "name": "close_object",
            "status": "fail",
            "reading": None,
            "notes": str(result),
        }

    mm = result["distance_mm"]
    zone = monitor.classify_zone(mm)
    print(f"  Reading: {mm}mm ({mm_to_imperial(mm)}) ({zone.value.upper()})")

    if zone.value == "danger":
        status = "pass"
        notes = ""
    elif zone.value == "warning":
        status = "pass"
        notes = "Marginal — WARNING zone, not DANGER. Hand may be >200mm (~8in)."
    else:
        status = "fail"
        notes = f"Expected DANGER (<200mm/~8in), got {zone.value} ({mm}mm)"

    print(f"  {status.upper()}" + (f" ({notes})" if notes else ""))
    return {
        "name": "close_object",
        "status": status,
        "reading": {"distance_mm": mm, "zone": zone.value},
        "notes": notes,
    }


def run_test_4(drone: DroneAdapter, monitor: ObstacleMonitor) -> dict:
    """Test 4: Stability — measure noise at fixed distance."""
    print("\n" + "─" * 60)
    print("TEST 4: Stability Test (6 seconds)")
    print("─" * 60)
    prompt("Point drone at a wall or flat surface ~1m (~3.3ft) away. Keep still.")

    readings = []
    for _i in range(30):
        result = read_distance(drone)
        ts = datetime.now(UTC).isoformat()
        if result.get("status") == "ok":
            mm = result["distance_mm"]
            readings.append({"timestamp": ts, "distance_mm": mm})
        else:
            readings.append({"timestamp": ts, "distance_mm": None})
        time.sleep(0.2)

    valid = [
        r["distance_mm"]
        for r in readings
        if r["distance_mm"] is not None and r["distance_mm"] < OUT_OF_RANGE_MIN
    ]

    if len(valid) < 5:
        print("  FAIL — too few valid readings for statistics")
        return {
            "name": "stability",
            "status": "fail",
            "readings": readings,
            "stats": None,
            "notes": f"Only {len(valid)} valid readings",
        }

    mean = statistics.mean(valid)
    std = statistics.stdev(valid) if len(valid) > 1 else 0.0
    mn = min(valid)
    mx = max(valid)

    print(f"  Samples: {len(valid)}/{len(readings)}")
    print(f"  Mean: {mean:.1f}mm, Std: {std:.1f}mm")
    print(f"  Min: {mn}mm, Max: {mx}mm")

    status = "pass" if std < 50 else "fail"
    notes = "" if status == "pass" else f"Std dev {std:.1f}mm exceeds 50mm"
    print(f"  {status.upper()}" + (f" ({notes})" if notes else ""))

    return {
        "name": "stability",
        "status": status,
        "readings": readings,
        "stats": {
            "mean": round(mean, 1),
            "std": round(std, 1),
            "min": mn,
            "max": mx,
        },
        "notes": notes,
    }


def run_test_5(drone: DroneAdapter) -> dict:
    """Test 5: Telemetry Integration — forward_tof_mm in TelemetryFrame."""
    print("\n" + "─" * 60)
    print("TEST 5: Telemetry Integration")
    print("─" * 60)

    result = drone.get_telemetry()
    if isinstance(result, dict):
        print(f"  FAIL — telemetry returned error: {result}")
        return {
            "name": "telemetry_integration",
            "status": "fail",
            "telemetry_snapshot": result,
            "notes": str(result),
        }

    snapshot = result.model_dump()
    # Convert datetime to string for JSON serialization
    snapshot["timestamp"] = snapshot["timestamp"].isoformat()
    fwd = result.forward_tof_mm
    print(f"  forward_tof_mm: {fwd}")
    print(f"  Battery: {result.battery_pct}%")

    status = "pass" if fwd is not None else "fail"
    notes = "" if status == "pass" else "forward_tof_mm is None"
    print(f"  {status.upper()}" + (f" ({notes})" if notes else ""))

    return {
        "name": "telemetry_integration",
        "status": status,
        "telemetry_snapshot": snapshot,
        "notes": notes,
    }


def run_test_6(
    drone: DroneAdapter,
    monitor: ObstacleMonitor,
    config: ObstacleConfig,
    battery: int | None,
    tello: Any,
) -> dict:
    """Test 6: Flight DANGER Stop — full safety pipeline."""
    print("\n" + "─" * 60)
    print("TEST 6: Flight DANGER Stop (OPTIONAL)")
    print("─" * 60)

    # Battery gate
    if battery is not None and battery < 30:
        print(f"  WARNING: Battery is {battery}% (< 30%)")
        resp = input("  Continue anyway? (y/n): ").strip().lower()
        if resp != "y":
            print("  SKIPPED (low battery)")
            return {
                "name": "flight_danger_stop",
                "status": "skipped",
                "notes": f"Low battery ({battery}%)",
            }

    resp = (
        input(
            "\n  FLIGHT TEST. Place drone on flat surface "
            "facing a wall (~2m / ~6.5ft away).\n"
            "  Ready to fly? (y/n): "
        )
        .strip()
        .lower()
    )
    if resp != "y":
        print("  SKIPPED (user declined)")
        return {
            "name": "flight_danger_stop",
            "status": "skipped",
            "notes": "User declined",
        }

    # Pre-flight distance gate
    pre = read_distance(drone)
    if pre.get("status") != "ok":
        print(f"  ABORT — cannot read sensor: {pre}")
        return {
            "name": "flight_danger_stop",
            "status": "fail",
            "notes": f"Pre-flight sensor error: {pre}",
        }

    pre_mm = pre["distance_mm"]
    if pre_mm < 500 and pre_mm < OUT_OF_RANGE_MIN:
        print(
            f"  ABORT — too close to wall ({pre_mm}mm / "
            f"{mm_to_imperial(pre_mm)} < 500mm / ~20in). "
            f"Move drone back and retry."
        )
        return {
            "name": "flight_danger_stop",
            "status": "fail",
            "pre_flight_distance_mm": pre_mm,
            "notes": "Too close to wall",
        }

    distance_checks = [
        {
            "phase": "pre_flight",
            "distance_mm": pre_mm,
            "zone": monitor.classify_zone(pre_mm).value,
        },
    ]

    # Takeoff with race condition detection
    print("  Taking off...")
    takeoff_result = drone.takeoff()
    takeoff_succeeded = False
    height_after_takeoff = None
    takeoff_race_condition = False

    if takeoff_result.get("status") == "ok":
        takeoff_succeeded = True
    else:
        # Takeoff reported failure — check if drone is actually airborne
        try:
            height_after_takeoff = tello.get_height()
            if height_after_takeoff > 0:
                print(
                    f"  NOTE: takeoff() returned error but drone is "
                    f"airborne (height={height_after_takeoff}cm)"
                )
                print("  Known djitellopy retry race condition — continuing test")
                takeoff_succeeded = True
                takeoff_race_condition = True
            else:
                print(f"  FAIL — takeoff genuinely failed: {takeoff_result}")
        except Exception:
            print(f"  FAIL — takeoff failed and height check unavailable: {takeoff_result}")

    if not takeoff_succeeded:
        return {
            "name": "flight_danger_stop",
            "status": "fail",
            "takeoff_raw_result": takeoff_result,
            "height_after_takeoff_cm": height_after_takeoff,
            "battery_at_takeoff": battery,
            "takeoff_race_condition_detected": False,
            "notes": f"Takeoff failed: {takeoff_result}",
        }

    print(f"  Stabilizing ({TAKEOFF_DELAY}s)...")
    time.sleep(TAKEOFF_DELAY)

    danger_triggered = False
    chosen_response = None
    action_result = None

    try:
        prompt("Drone is hovering. It will fly forward 100cm (~3.3ft).")

        # Check before move
        r = read_distance(drone)
        if r.get("status") == "ok":
            mm = r["distance_mm"]
            zone = monitor.classify_zone(mm)
            distance_checks.append({"phase": "pre_move", "distance_mm": mm, "zone": zone.value})
            print(f"  Pre-move: {mm}mm ({mm_to_imperial(mm)}) ({zone.value.upper()})")

        # Move 100cm forward
        print("  Moving forward 100cm (~3.3ft)...")
        drone.move("forward", 100)
        time.sleep(COMMAND_DELAY)

        # Check after first move
        r = read_distance(drone)
        if r.get("status") == "ok":
            mm = r["distance_mm"]
            zone = monitor.classify_zone(mm)
            distance_checks.append({"phase": "after_100cm", "distance_mm": mm, "zone": zone.value})
            print(f"  After 100cm: {mm}mm ({mm_to_imperial(mm)}) ({zone.value.upper()})")

            if zone.value == "danger":
                danger_triggered = True
            else:
                # Move another 50cm
                print("  Not DANGER yet. Moving forward 50cm (~20in)...")
                drone.move("forward", 50)
                time.sleep(COMMAND_DELAY)

                r = read_distance(drone)
                if r.get("status") == "ok":
                    mm = r["distance_mm"]
                    zone = monitor.classify_zone(mm)
                    distance_checks.append(
                        {
                            "phase": "after_150cm",
                            "distance_mm": mm,
                            "zone": zone.value,
                        }
                    )
                    print(f"  After 150cm: {mm}mm ({mm_to_imperial(mm)}) ({zone.value.upper()})")
                    if zone.value == "danger":
                        danger_triggered = True

        if danger_triggered:
            print("\n  DANGER DETECTED — presenting options menu")
            last_check = distance_checks[-1]
            reading = ObstacleReading(
                distance_mm=last_check["distance_mm"],
                zone=monitor.classify_zone(last_check["distance_mm"]),
                timestamp=datetime.now(UTC),
            )
            provider = CLIResponseProvider()
            choice = asyncio.run(provider.present_options(reading))
            chosen_response = choice.value
            handler = ObstacleResponseHandler(drone)
            action_result = asyncio.run(handler.execute(choice))
            print(f"  Action result: {action_result}")
        else:
            print("\n  No DANGER triggered after 150cm (~5ft). Landing safely.")
            drone.safe_land()

    except Exception as e:
        print(f"\n  ERROR during flight: {e}")
        print("  Emergency landing...")
        drone.safe_land()
        return {
            "name": "flight_danger_stop",
            "status": "fail",
            "distance_checks": distance_checks,
            "takeoff_raw_result": takeoff_result,
            "height_after_takeoff_cm": height_after_takeoff,
            "battery_at_takeoff": battery,
            "takeoff_race_condition_detected": takeoff_race_condition,
            "notes": f"Flight error: {e}",
        }

    status = "pass" if danger_triggered else "needs_adjustment"
    notes = "" if danger_triggered else "DANGER never triggered — thresholds may need tuning"
    print(f"\n  {status.upper()}" + (f" ({notes})" if notes else ""))

    return {
        "name": "flight_danger_stop",
        "status": status,
        "pre_flight_distance_mm": pre_mm,
        "distance_checks": distance_checks,
        "danger_triggered": danger_triggered,
        "chosen_response": chosen_response,
        "action_result": action_result,
        "takeoff_raw_result": takeoff_result,
        "height_after_takeoff_cm": height_after_takeoff,
        "battery_at_takeoff": battery,
        "takeoff_race_condition_detected": takeoff_race_condition,
        "notes": notes,
    }


def build_characterization(
    results: list[dict],
    all_readings: list[int],
) -> dict:
    """Compute sensor characterization from all test data."""
    valid = [r for r in all_readings if r < OUT_OF_RANGE_MIN]
    effective_min = min(valid) if valid else None
    effective_max = max(valid) if valid else None

    # Noise stats from Test 4 (stability)
    stability = next(
        (t for t in results if t["name"] == "stability"),
        None,
    )
    noise_mean = None
    noise_std = None
    if stability and stability.get("stats"):
        noise_mean = stability["stats"].get("mean")
        noise_std = stability["stats"].get("std")

    return {
        "effective_range_mm": {
            "min": effective_min,
            "max": effective_max,
        },
        "noise_std_mm": noise_std,
        "noise_mean_mm": noise_mean,
        "response_latency_note": "estimated from sampling interval",
    }


def save_results(output: dict) -> None:
    """Save results to testing/ as timestamped JSON."""
    testing_dir = Path("testing")
    testing_dir.mkdir(exist_ok=True)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    path = testing_dir / f"forward-tof-threshold-results-{date_str}.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {path}")


def print_summary(results: list[dict], characterization: dict) -> None:
    """Print a console summary of all test results."""
    print("\n" + "=" * 60)
    print("  TEST SUMMARY")
    print("=" * 60)
    for t in results:
        status = t["status"].upper()
        icon = {
            "pass": "✓",
            "fail": "✗",
            "skipped": "—",
            "needs_adjustment": "⚠",
        }.get(t["status"], "?")
        print(f"  {icon} {t['name']}: {status}")
        if t.get("notes"):
            print(f"    → {t['notes']}")

    print("\n  Sensor Characterization:")
    rng = characterization.get("effective_range_mm", {})
    if rng.get("min") is not None:
        print(f"    Range: {rng['min']}mm - {rng['max']}mm")
    if characterization.get("noise_std_mm") is not None:
        print(
            f"    Noise: mean={characterization['noise_mean_mm']}mm, "
            f"std={characterization['noise_std_mm']}mm"
        )
    print("=" * 60)


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Forward ToF threshold verification test script",
    )
    parser.add_argument(
        "--host",
        default="auto",
        help="Drone IP or 'auto' for discovery",
    )
    parsed = parser.parse_args()

    print("=" * 60)
    print("  Forward ToF Sensor — Threshold Verification Test Suite")
    print("=" * 60)

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

    # Run tests
    results: list[dict] = []
    all_readings: list[int] = []  # for sensor_characterization

    try:
        # Test 1 — gate for all others
        t1 = run_test_1(drone, monitor)
        results.append(t1)
        if t1.get("reading"):
            all_readings.append(t1["reading"]["distance_mm"])

        if t1["status"] != "pass":
            print("\nTest 1 FAILED — sensor unavailable. Skipping remaining tests.")
            for name in [
                "range_sweep",
                "close_object",
                "stability",
                "telemetry_integration",
                "flight_danger_stop",
            ]:
                results.append(
                    {
                        "name": name,
                        "status": "skipped",
                        "notes": "Skipped: sensor unavailable (Test 1 failed)",
                    }
                )
        else:
            t2 = run_test_2(drone, monitor)
            results.append(t2)
            for r in t2.get("readings", []):
                if r["distance_mm"] is not None and r["distance_mm"] < OUT_OF_RANGE_MIN:
                    all_readings.append(r["distance_mm"])

            t3 = run_test_3(drone, monitor)
            results.append(t3)
            if t3.get("reading"):
                all_readings.append(t3["reading"]["distance_mm"])

            t4 = run_test_4(drone, monitor)
            results.append(t4)
            for r in t4.get("readings", []):
                if r["distance_mm"] is not None and r["distance_mm"] < OUT_OF_RANGE_MIN:
                    all_readings.append(r["distance_mm"])

            t5 = run_test_5(drone)
            results.append(t5)

            t6 = run_test_6(drone, monitor, config, battery_start, drone._tello)
            results.append(t6)
            for check in t6.get("distance_checks", []):
                if check["distance_mm"] is not None and check["distance_mm"] < OUT_OF_RANGE_MIN:
                    all_readings.append(check["distance_mm"])

    except KeyboardInterrupt:
        print("\n\nInterrupted! Attempting safe landing...")
        drone.safe_land()

    # Final battery
    telemetry = drone.get_telemetry()
    battery_end = telemetry.battery_pct if isinstance(telemetry, TelemetryFrame) else None

    # Build output
    characterization = build_characterization(results, all_readings)

    output = {
        "date": datetime.now(UTC).isoformat(),
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
        "sensor_characterization": characterization,
    }

    save_results(output)
    print_summary(results, characterization)

    drone.disconnect()
    print("\nDone.")


if __name__ == "__main__":
    main()
