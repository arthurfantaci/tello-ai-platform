"""Anomaly detection -- config-driven threshold checks.

The AnomalyDetector is stateless: a pure function from
(TelemetryFrame, config) -> list[Anomaly]. No I/O, no side
effects. This is the "Pure Core" in the Pure Core / Imperative
Shell architecture. The consumer (imperative shell) handles
I/O; the detector (pure core) handles logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tello_core.models import Anomaly

if TYPE_CHECKING:
    from tello_core.models import TelemetryFrame
    from tello_telemetry.config import TelloTelemetryConfig


class AnomalyDetector:
    """Runs threshold checks against telemetry frames.

    Args:
        config: Service config containing threshold values.
    """

    def __init__(self, config: TelloTelemetryConfig) -> None:
        self._config = config

    def check(self, frame: TelemetryFrame) -> list[Anomaly]:
        """Run all threshold checks on a telemetry frame.

        Returns an empty list if all values are nominal.

        Args:
            frame: Current telemetry snapshot.
        """
        anomalies: list[Anomaly] = []
        self._check_battery(frame, anomalies)
        self._check_temperature(frame, anomalies)
        self._check_altitude(frame, anomalies)
        return anomalies

    def _check_battery(
        self,
        frame: TelemetryFrame,
        anomalies: list[Anomaly],
    ) -> None:
        if frame.battery_pct < self._config.battery_critical_pct:
            anomalies.append(
                Anomaly(
                    type="battery_low",
                    severity="critical",
                    detail=f"Battery at {frame.battery_pct}%",
                    timestamp=frame.timestamp,
                ),
            )
        elif frame.battery_pct < self._config.battery_warning_pct:
            anomalies.append(
                Anomaly(
                    type="battery_low",
                    severity="warning",
                    detail=f"Battery at {frame.battery_pct}%",
                    timestamp=frame.timestamp,
                ),
            )

    def _check_temperature(
        self,
        frame: TelemetryFrame,
        anomalies: list[Anomaly],
    ) -> None:
        if frame.temp_c > self._config.temp_critical_c:
            anomalies.append(
                Anomaly(
                    type="high_temperature",
                    severity="critical",
                    detail=f"Temperature at {frame.temp_c}\u00b0C",
                    timestamp=frame.timestamp,
                ),
            )
        elif frame.temp_c > self._config.temp_warning_c:
            anomalies.append(
                Anomaly(
                    type="high_temperature",
                    severity="warning",
                    detail=f"Temperature at {frame.temp_c}\u00b0C",
                    timestamp=frame.timestamp,
                ),
            )

    def _check_altitude(
        self,
        frame: TelemetryFrame,
        anomalies: list[Anomaly],
    ) -> None:
        if frame.height_cm > self._config.altitude_max_cm:
            anomalies.append(
                Anomaly(
                    type="altitude_exceeded",
                    severity="critical",
                    detail=(
                        f"Altitude {frame.height_cm}cm exceeds max {self._config.altitude_max_cm}cm"
                    ),
                    timestamp=frame.timestamp,
                ),
            )
