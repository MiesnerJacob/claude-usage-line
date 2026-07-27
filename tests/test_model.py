"""Tests for the usage domain model."""

from __future__ import annotations

import unittest

from herdr_usage_pane.model import Severity, UsageSnapshot, UsageWindow


class UsageWindowTest(unittest.TestCase):
    def test_clamps_percentage_above_one_hundred(self) -> None:
        self.assertEqual(UsageWindow("5h", 104.2).used_percentage, 100.0)

    def test_clamps_negative_percentage(self) -> None:
        self.assertEqual(UsageWindow("5h", -3.0).used_percentage, 0.0)

    def test_severity_thresholds(self) -> None:
        cases = {
            0.0: Severity.NOMINAL,
            59.9: Severity.NOMINAL,
            60.0: Severity.ELEVATED,
            84.9: Severity.ELEVATED,
            85.0: Severity.CRITICAL,
            100.0: Severity.CRITICAL,
        }
        for percentage, expected in cases.items():
            with self.subTest(percentage=percentage):
                self.assertEqual(UsageWindow("5h", percentage).severity, expected)

    def test_seconds_until_reset(self) -> None:
        window = UsageWindow("5h", 10.0, resets_at=1_000)
        self.assertEqual(window.seconds_until_reset(now=400), 600)

    def test_seconds_until_reset_never_negative(self) -> None:
        window = UsageWindow("5h", 10.0, resets_at=1_000)
        self.assertEqual(window.seconds_until_reset(now=5_000), 0)

    def test_seconds_until_reset_unknown(self) -> None:
        self.assertIsNone(UsageWindow("5h", 10.0).seconds_until_reset(now=1))


class UsageSnapshotTest(unittest.TestCase):
    def test_worst_severity_picks_most_severe(self) -> None:
        snapshot = UsageSnapshot(
            windows=(UsageWindow("5h", 10.0), UsageWindow("7d", 92.0)),
            captured_at=0.0,
        )
        self.assertEqual(snapshot.worst_severity, Severity.CRITICAL)

    def test_worst_severity_of_empty_snapshot_is_nominal(self) -> None:
        snapshot = UsageSnapshot(windows=(), captured_at=0.0)
        self.assertEqual(snapshot.worst_severity, Severity.NOMINAL)


if __name__ == "__main__":
    unittest.main()
