from __future__ import annotations

import datetime as dt
import unittest

from claude_usage_line.client import (
    UsageUnavailable,
    humanize_kind,
    parse_snapshot,
)
from claude_usage_line.model import Severity


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
        self.assertEqual([w.label for w in snapshot.windows], ["Current Session", "Week (all)"])
        self.assertEqual(snapshot.windows[0].used_percentage, 33.0)
        self.assertEqual(snapshot.windows[1].used_percentage, 31.0)

    def test_scoped_window_included_on_request(self) -> None:
        snapshot = parse_snapshot(LIVE_PAYLOAD, now=0.0, include_scoped=True)
        self.assertEqual(
            [w.label for w in snapshot.windows], ["Current Session", "Week (all)", "Week (Fable)"]
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
        self.assertNotIn("Week (Opus)", [w.label for w in snapshot.windows])

    def test_falls_back_to_legacy_keys_when_limits_absent(self) -> None:
        payload = {
            key: value
            for key, value in LIVE_PAYLOAD.items()
            if key != "limits"
        }
        snapshot = parse_snapshot(payload, now=0.0)
        self.assertEqual([w.label for w in snapshot.windows], ["Current Session", "Week (all)"])

    def test_falls_back_when_limits_is_empty(self) -> None:
        payload = {**LIVE_PAYLOAD, "limits": []}
        snapshot = parse_snapshot(payload, now=0.0)
        self.assertEqual([w.label for w in snapshot.windows], ["Current Session", "Week (all)"])

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
        self.assertEqual(snapshot.windows[0].label, "Current Session")
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
        self.assertEqual([w.label for w in snapshot.windows], ["Current Session"])

    def test_includes_opus_window_when_present(self) -> None:
        snapshot = parse_snapshot(
            {
                "five_hour": {"utilization": 1},
                "seven_day": {"utilization": 2},
                "seven_day_opus": {"utilization": 3},
            },
            now=0.0,
            include_scoped=True,
        )
        self.assertEqual([w.label for w in snapshot.windows], ["Current Session", "Week (all)", "Week (Opus)"])

    def test_raises_when_no_windows_recognised(self) -> None:
        with self.assertRaises(UsageUnavailable):
            parse_snapshot({"unexpected": True}, now=0.0)

    def test_ignores_boolean_masquerading_as_number(self) -> None:
        with self.assertRaises(UsageUnavailable):
            parse_snapshot({"five_hour": {"utilization": True}}, now=0.0)


class DynamicWindowTest(unittest.TestCase):
    """New limit types must appear without a code change."""

    def test_unknown_kind_is_labelled_not_dropped(self) -> None:
        payload = {"limits": [{"kind": "monthly_all", "percent": 12}]}
        snapshot = parse_snapshot(payload, now=0.0, include_scoped=True)
        self.assertEqual([w.label for w in snapshot.windows], ["Month (All)"])

    def test_unknown_scoped_kind_keeps_its_model_name(self) -> None:
        payload = {
            "limits": [
                {
                    "kind": "weekly_scoped",
                    "percent": 9,
                    "scope": {"model": {"display_name": "Sonnet 5"}},
                }
            ]
        }
        snapshot = parse_snapshot(payload, now=0.0, include_scoped=True)
        self.assertEqual([w.label for w in snapshot.windows], ["Week (Sonnet 5)"])

    def test_unreleased_codename_kind_still_renders(self) -> None:
        payload = {"limits": [{"kind": "nimbus_quill", "percent": 3}]}
        snapshot = parse_snapshot(payload, now=0.0, include_scoped=True)
        self.assertEqual([w.label for w in snapshot.windows], ["Nimbus Quill"])

    def test_unknown_legacy_key_is_discovered(self) -> None:
        payload = {
            "five_hour": {"utilization": 1},
            "seven_day": {"utilization": 2},
            "seven_day_cowork": {"utilization": 7},
        }
        snapshot = parse_snapshot(payload, now=0.0, include_scoped=True)
        self.assertIn("Week (Cowork)", [w.label for w in snapshot.windows])

    def test_universal_windows_come_first(self) -> None:
        payload = {
            "seven_day_cowork": {"utilization": 7},
            "seven_day": {"utilization": 2},
            "five_hour": {"utilization": 1},
        }
        snapshot = parse_snapshot(payload, now=0.0, include_scoped=True)
        self.assertEqual(
            [w.label for w in snapshot.windows][:2],
            ["Current Session", "Week (all)"],
        )


class HumanizeKindTest(unittest.TestCase):
    def test_known_duration_prefixes(self) -> None:
        self.assertEqual(humanize_kind("seven_day"), "Week")
        self.assertEqual(humanize_kind("five_hour"), "Session")

    def test_qualified_duration(self) -> None:
        self.assertEqual(humanize_kind("weekly_opus"), "Week (Opus)")
        self.assertEqual(humanize_kind("monthly_all"), "Month (All)")

    def test_unrecognised_kind_is_title_cased(self) -> None:
        self.assertEqual(humanize_kind("iguana_necktie"), "Iguana Necktie")

    def test_hyphens_are_normalised(self) -> None:
        self.assertEqual(humanize_kind("weekly-sonnet"), "Week (Sonnet)")


if __name__ == "__main__":
    unittest.main()
