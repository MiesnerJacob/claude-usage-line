"""Tests for parsing the usage endpoint payload.

The parser is deliberately tolerant of field-name drift, so these tests pin the
spellings that must keep working rather than one canonical shape.
"""

from __future__ import annotations

import datetime as dt
import unittest

from herdr_usage_pane.client import UsageUnavailable, parse_snapshot
from herdr_usage_pane.model import Severity


LIVE_PAYLOAD = {
    "five_hour": {
        "utilization": 33.0,
        "resets_at": "2026-07-27T23:10:00.285968+00:00",
        "limit_dollars": None,
    },
    "seven_day": {
        "utilization": 31.0,
        "resets_at": "2026-07-30T17:00:00.285985+00:00",
        "limit_dollars": None,
    },
    "seven_day_opus": None,
    "tangelo": None,
    "limits": [
        {
            "kind": "session",
            "group": "session",
            "percent": 33,
            "severity": "normal",
            "resets_at": "2026-07-27T23:10:00.674244+00:00",
            "scope": None,
            "is_active": True,
        },
        {
            "kind": "weekly_all",
            "group": "weekly",
            "percent": 31,
            "severity": "normal",
            "resets_at": "2026-07-30T17:00:00.674263+00:00",
            "scope": None,
            "is_active": False,
        },
        {
            "kind": "weekly_scoped",
            "group": "weekly",
            "percent": 25,
            "severity": "normal",
            "resets_at": "2026-07-30T16:59:59.674504+00:00",
            "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None},
            "is_active": False,
        },
    ],
    "member_dashboard_available": False,
}


class LivePayloadTest(unittest.TestCase):
    """Pins the schema observed from api.anthropic.com/api/oauth/usage."""

    def test_prefers_limits_array_over_legacy_keys(self) -> None:
        snapshot = parse_snapshot(LIVE_PAYLOAD, now=0.0)
        self.assertEqual([w.label for w in snapshot.windows], ["5h", "7d"])
        self.assertEqual(snapshot.windows[0].used_percentage, 33.0)
        self.assertEqual(snapshot.windows[1].used_percentage, 31.0)

    def test_scoped_window_included_on_request(self) -> None:
        snapshot = parse_snapshot(LIVE_PAYLOAD, now=0.0, include_scoped=True)
        self.assertEqual(
            [w.label for w in snapshot.windows], ["5h", "7d", "7d Fable"]
        )

    def test_server_severity_is_trusted_over_thresholds(self) -> None:
        payload = {
            "limits": [
                {"kind": "session", "percent": 95, "severity": "normal"},
            ]
        }
        snapshot = parse_snapshot(payload, now=0.0)
        self.assertEqual(snapshot.windows[0].severity, Severity.NOMINAL)

    def test_unknown_server_severity_falls_back_to_thresholds(self) -> None:
        payload = {
            "limits": [
                {"kind": "session", "percent": 95, "severity": "banana"},
            ]
        }
        snapshot = parse_snapshot(payload, now=0.0)
        self.assertEqual(snapshot.windows[0].severity, Severity.CRITICAL)

    def test_microsecond_offset_reset_parsed(self) -> None:
        snapshot = parse_snapshot(LIVE_PAYLOAD, now=0.0)
        expected = int(
            dt.datetime(
                2026, 7, 27, 23, 10, 0, 674244, tzinfo=dt.timezone.utc
            ).timestamp()
        )
        self.assertEqual(snapshot.windows[0].resets_at, expected)

    def test_null_windows_are_ignored(self) -> None:
        snapshot = parse_snapshot(LIVE_PAYLOAD, now=0.0)
        self.assertNotIn("7d opus", [w.label for w in snapshot.windows])

    def test_falls_back_to_legacy_keys_when_limits_absent(self) -> None:
        payload = {
            key: value
            for key, value in LIVE_PAYLOAD.items()
            if key != "limits"
        }
        snapshot = parse_snapshot(payload, now=0.0)
        self.assertEqual([w.label for w in snapshot.windows], ["5h", "7d"])

    def test_falls_back_when_limits_is_empty(self) -> None:
        payload = {**LIVE_PAYLOAD, "limits": []}
        snapshot = parse_snapshot(payload, now=0.0)
        self.assertEqual([w.label for w in snapshot.windows], ["5h", "7d"])

    def test_unrecognised_limit_kind_skipped(self) -> None:
        payload = {"limits": [{"kind": "iguana_necktie", "percent": 50}]}
        with self.assertRaises(UsageUnavailable):
            parse_snapshot(payload, now=0.0)


class ParseSnapshotTest(unittest.TestCase):
    def test_parses_utilization_spelling(self) -> None:
        snapshot = parse_snapshot(
            {
                "five_hour": {"utilization": 68, "resets_at": 1_700_000_000},
                "seven_day": {"utilization": 23, "resets_at": 1_700_500_000},
            },
            now=0.0,
        )
        self.assertEqual(len(snapshot.windows), 2)
        self.assertEqual(snapshot.windows[0].label, "5h")
        self.assertEqual(snapshot.windows[0].used_percentage, 68.0)
        self.assertEqual(snapshot.windows[1].resets_at, 1_700_500_000)

    def test_parses_used_percentage_spelling(self) -> None:
        snapshot = parse_snapshot(
            {"five_hour": {"used_percentage": 41.5}}, now=0.0
        )
        self.assertEqual(snapshot.windows[0].used_percentage, 41.5)

    def test_parses_iso_reset_timestamp(self) -> None:
        expected = int(
            dt.datetime(2026, 7, 27, 12, 0, tzinfo=dt.timezone.utc).timestamp()
        )
        snapshot = parse_snapshot(
            {"five_hour": {"utilization": 5, "resets_at": "2026-07-27T12:00:00Z"}},
            now=0.0,
        )
        self.assertEqual(snapshot.windows[0].resets_at, expected)

    def test_parses_naive_iso_reset_as_utc(self) -> None:
        expected = int(
            dt.datetime(2026, 7, 27, 12, 0, tzinfo=dt.timezone.utc).timestamp()
        )
        snapshot = parse_snapshot(
            {"five_hour": {"utilization": 5, "resets_at": "2026-07-27T12:00:00"}},
            now=0.0,
        )
        self.assertEqual(snapshot.windows[0].resets_at, expected)

    def test_finds_windows_nested_under_wrapper_key(self) -> None:
        snapshot = parse_snapshot(
            {"usage": {"five_hour": {"utilization": 12}}}, now=0.0
        )
        self.assertEqual(snapshot.windows[0].used_percentage, 12.0)

    def test_skips_windows_missing_utilization(self) -> None:
        snapshot = parse_snapshot(
            {"five_hour": {"utilization": 12}, "seven_day": {"resets_at": 5}},
            now=0.0,
        )
        self.assertEqual([w.label for w in snapshot.windows], ["5h"])

    def test_includes_opus_window_when_present(self) -> None:
        snapshot = parse_snapshot(
            {
                "five_hour": {"utilization": 1},
                "seven_day": {"utilization": 2},
                "seven_day_opus": {"utilization": 3},
            },
            now=0.0,
        )
        self.assertEqual([w.label for w in snapshot.windows], ["5h", "7d", "7d opus"])

    def test_raises_when_no_windows_recognised(self) -> None:
        with self.assertRaises(UsageUnavailable):
            parse_snapshot({"unexpected": True}, now=0.0)

    def test_ignores_boolean_masquerading_as_number(self) -> None:
        with self.assertRaises(UsageUnavailable):
            parse_snapshot({"five_hour": {"utilization": True}}, now=0.0)


if __name__ == "__main__":
    unittest.main()
