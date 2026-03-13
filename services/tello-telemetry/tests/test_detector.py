"""Tests for anomaly detection.

AnomalyDetector is a pure function -- no mocks needed.
Input: TelemetryFrame + config thresholds -> Output: list[Anomaly]
"""

from __future__ import annotations

from datetime import UTC, datetime

from tello_core.models import TelemetryFrame
from tello_telemetry.config import TelloTelemetryConfig
from tello_telemetry.detector import AnomalyDetector


def _make_frame(**overrides) -> TelemetryFrame:
    """Create a TelemetryFrame with sensible defaults."""
    defaults = {
        "battery_pct": 80,
        "height_cm": 100,
        "tof_cm": 95,
        "temp_c": 40.0,
        "pitch": 0.0,
        "roll": 0.0,
        "yaw": 0.0,
        "flight_time_s": 30,
        "timestamp": datetime(2026, 3, 12, 10, 0, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    return TelemetryFrame(**defaults)


def _make_config(**overrides) -> TelloTelemetryConfig:
    """Create a TelloTelemetryConfig with test defaults."""
    defaults = {
        "neo4j_uri": "bolt://localhost:7687",
        "neo4j_username": "neo4j",
        "neo4j_password": "test",
        "redis_url": "redis://localhost:6379",
        "service_name": "test",
    }
    defaults.update(overrides)
    return TelloTelemetryConfig(**defaults)


class TestAnomalyDetector:
    def setup_method(self):
        self.config = _make_config()
        self.detector = AnomalyDetector(self.config)

    # -- Nominal (no anomalies) --

    def test_nominal_frame_returns_empty(self):
        frame = _make_frame()
        assert self.detector.check(frame) == []

    # -- Battery --

    def test_battery_warning(self):
        frame = _make_frame(battery_pct=18)
        anomalies = self.detector.check(frame)
        assert len(anomalies) == 1
        assert anomalies[0].type == "battery_low"
        assert anomalies[0].severity == "warning"
        assert "18%" in anomalies[0].detail

    def test_battery_critical(self):
        frame = _make_frame(battery_pct=8)
        anomalies = self.detector.check(frame)
        assert len(anomalies) == 1
        assert anomalies[0].type == "battery_low"
        assert anomalies[0].severity == "critical"

    def test_battery_at_exact_warning_threshold_is_nominal(self):
        frame = _make_frame(battery_pct=20)
        assert self.detector.check(frame) == []

    def test_battery_at_exact_critical_threshold_is_warning(self):
        """At exactly critical threshold (10%), it's still
        warning level (< 20 but not < 10)."""
        frame = _make_frame(battery_pct=10)
        anomalies = self.detector.check(frame)
        assert len(anomalies) == 1
        assert anomalies[0].severity == "warning"

    # -- Temperature --

    def test_temp_warning(self):
        frame = _make_frame(temp_c=87.0)
        anomalies = self.detector.check(frame)
        assert len(anomalies) == 1
        assert anomalies[0].type == "high_temperature"
        assert anomalies[0].severity == "warning"

    def test_temp_critical(self):
        frame = _make_frame(temp_c=92.0)
        anomalies = self.detector.check(frame)
        assert len(anomalies) == 1
        assert anomalies[0].type == "high_temperature"
        assert anomalies[0].severity == "critical"

    def test_temp_at_exact_warning_threshold_is_nominal(self):
        frame = _make_frame(temp_c=85.0)
        assert self.detector.check(frame) == []

    # -- Altitude --

    def test_altitude_critical(self):
        frame = _make_frame(height_cm=350)
        anomalies = self.detector.check(frame)
        assert len(anomalies) == 1
        assert anomalies[0].type == "altitude_exceeded"
        assert anomalies[0].severity == "critical"

    def test_altitude_at_exact_max_is_nominal(self):
        frame = _make_frame(height_cm=300)
        assert self.detector.check(frame) == []

    # -- Multiple simultaneous anomalies --

    def test_multiple_anomalies(self):
        frame = _make_frame(battery_pct=5, temp_c=92.0, height_cm=400)
        anomalies = self.detector.check(frame)
        types = {a.type for a in anomalies}
        assert types == {"battery_low", "high_temperature", "altitude_exceeded"}

    # -- Custom thresholds --

    def test_custom_battery_threshold(self):
        config = _make_config(battery_warning_pct=30)
        detector = AnomalyDetector(config)
        frame = _make_frame(battery_pct=25)
        anomalies = detector.check(frame)
        assert len(anomalies) == 1
        assert anomalies[0].severity == "warning"

    # -- Timestamp propagation --

    def test_anomaly_uses_frame_timestamp(self):
        ts = datetime(2026, 3, 12, 15, 30, 0, tzinfo=UTC)
        frame = _make_frame(battery_pct=5, timestamp=ts)
        anomalies = self.detector.check(frame)
        assert anomalies[0].timestamp == ts
