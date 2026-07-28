"""Tests for reading usage from the statusline payload.

The payload shape here was captured from Claude Code 2.1.220.
"""

from __future__ import annotations

import unittest

from herdr_usage_pane.model import UsageSnapshot, UsageWindow
from herdr_usage_pane.statusline import (
    merge_scoped,
    snapshot_from_payload,
)

LIVE_PAYLOAD = {
    "session_id": "f4895cc0",
    "model": {"id": "claude-opus-5[1m]", "display_name": "Opus 5 (1M context)"},
    "context_window": {"used_percentage": 42},
    "rate_limits": {
        "five_hour": {"used_percentage": 72, "resets_at": 1_785_261_600},
        "seven_day": {"used_percentage": 41, "resets_at": 1_785_430_800},
    },
}


class SnapshotFromPayloadTest(unittest.TestCase):
    def test_reads_both_windows(self) -> None:
        snapshot = snapshot_from_payload(LIVE_PAYLOAD, now=0.0)
        assert snapshot is not None
        self.assertEqual(
            [w.label for w in snapshot.windows],
            ["Current Session", "Week (all)"],
        )
        self.assertEqual(snapshot.windows[0].used_percentage, 72.0)
        self.assertEqual(snapshot.windows[1].resets_at, 1_785_430_800)

    def test_payload_without_rate_limits_is_none(self) -> None:
        self.assertIsNone(snapshot_from_payload({"model": {}}, now=0.0))

    def test_empty_rate_limits_is_none(self) -> None:
        self.assertIsNone(snapshot_from_payload({"rate_limits": {}}, now=0.0))

    def test_skips_window_missing_a_percentage(self) -> None:
        payload = {"rate_limits": {"five_hour": {"resets_at": 1}, "seven_day": {"used_percentage": 5}}}
        snapshot = snapshot_from_payload(payload, now=0.0)
        assert snapshot is not None
        self.assertEqual([w.label for w in snapshot.windows], ["Week (all)"])

    def test_ignores_boolean_percentage(self) -> None:
        payload = {"rate_limits": {"five_hour": {"used_percentage": True}}}
        self.assertIsNone(snapshot_from_payload(payload, now=0.0))


class MergeScopedTest(unittest.TestCase):
    def _live(self) -> UsageSnapshot:
        snapshot = snapshot_from_payload(LIVE_PAYLOAD, now=100.0)
        assert snapshot is not None
        return snapshot

    def test_appends_windows_absent_from_the_payload(self) -> None:
        cached = UsageSnapshot(
            windows=(UsageWindow("Week (Fable)", 28.0),), captured_at=0.0
        )
        merged = merge_scoped(self._live(), cached)
        self.assertEqual(
            [w.label for w in merged.windows],
            ["Current Session", "Week (all)", "Week (Fable)"],
        )

    def test_live_values_win_over_cached_duplicates(self) -> None:
        cached = UsageSnapshot(
            windows=(UsageWindow("Current Session", 5.0),), captured_at=0.0
        )
        merged = merge_scoped(self._live(), cached)
        self.assertEqual(len(merged.windows), 2)
        self.assertEqual(merged.windows[0].used_percentage, 72.0)

    def test_no_cache_returns_the_payload_unchanged(self) -> None:
        merged = merge_scoped(self._live(), None)
        self.assertEqual(len(merged.windows), 2)

    def test_keeps_the_live_capture_time(self) -> None:
        cached = UsageSnapshot(
            windows=(UsageWindow("Week (Fable)", 28.0),), captured_at=0.0
        )
        self.assertEqual(merge_scoped(self._live(), cached).captured_at, 100.0)


if __name__ == "__main__":
    unittest.main()
