"""Tests for the condensed single-line renderer."""

from __future__ import annotations

import unittest

from claude_usage_line.model import UsageSnapshot, UsageWindow
from claude_usage_line.render import (
    BAR_LAYOUT_MIN_WIDTH,
    _visible_length,
    format_duration,
    render_line,
    render_message,
)


def _snapshot(*windows: UsageWindow) -> UsageSnapshot:
    return UsageSnapshot(windows=windows, captured_at=0.0)


class FormatDurationTest(unittest.TestCase):
    def test_formats_sub_minute_as_placeholder(self) -> None:
        self.assertEqual(format_duration(42), "<1m")

    def test_formats_minutes_only(self) -> None:
        self.assertEqual(format_duration(19 * 60), "19m")

    def test_formats_hours_and_minutes(self) -> None:
        self.assertEqual(format_duration(2 * 3600 + 14 * 60), "2h14m")

    def test_pads_minutes_within_hours(self) -> None:
        self.assertEqual(format_duration(3 * 3600 + 4 * 60), "3h04m")

    def test_formats_days_and_hours(self) -> None:
        self.assertEqual(format_duration(3 * 86400 + 4 * 3600), "3d4h")

    def test_unknown_duration_is_empty(self) -> None:
        self.assertEqual(format_duration(None), "")


class RenderLineTest(unittest.TestCase):
    def test_wide_layout_includes_bars_and_percentages(self) -> None:
        line = render_line(
            _snapshot(
                UsageWindow("5h", 68.0, resets_at=8_040),
                UsageWindow("7d", 23.0),
            ),
            width=80,
            now=0.0,
            color=False,
        )
        self.assertIn("█", line)
        self.assertIn("68%", line)
        self.assertIn("23%", line)
        self.assertIn("2h14m", line)

    def test_narrow_layout_drops_bars_but_keeps_numbers(self) -> None:
        line = render_line(
            _snapshot(UsageWindow("5h", 68.0), UsageWindow("7d", 23.0)),
            width=BAR_LAYOUT_MIN_WIDTH - 1,
            now=0.0,
            color=False,
        )
        self.assertNotIn("█", line)
        self.assertIn("68%", line)

    def test_never_exceeds_requested_width(self) -> None:
        snapshot = _snapshot(
            UsageWindow("5h", 68.0, resets_at=8_040),
            UsageWindow("7d", 23.0, resets_at=200_000),
        )
        for width in range(10, 120):
            with self.subTest(width=width):
                line = render_line(snapshot, width=width, now=0.0, color=False)
                self.assertLessEqual(len(line), width)

    def test_coloured_output_also_respects_width(self) -> None:
        snapshot = _snapshot(
            UsageWindow("5h", 68.0, resets_at=8_040),
            UsageWindow("Week (Opus)", 23.0, resets_at=200_000),
        )
        for width in range(10, 120):
            with self.subTest(width=width):
                line = render_line(snapshot, width=width, now=0.0, color=True)
                self.assertLessEqual(_visible_length(line), width)

    def test_colour_disabled_emits_no_escape_codes(self) -> None:
        line = render_line(
            _snapshot(UsageWindow("5h", 99.0)), width=80, now=0.0, color=False
        )
        self.assertNotIn("\033", line)

    def test_colour_enabled_emits_escape_codes(self) -> None:
        line = render_line(
            _snapshot(UsageWindow("5h", 99.0)), width=80, now=0.0, color=True
        )
        self.assertIn("\033[31m", line)

    def test_stale_marker_appended(self) -> None:
        line = render_line(
            _snapshot(UsageWindow("5h", 10.0)),
            width=80,
            now=0.0,
            color=False,
            stale=True,
        )
        self.assertIn("(stale)", line)

    def test_full_window_renders_all_bar_cells_filled(self) -> None:
        line = render_line(
            _snapshot(UsageWindow("5h", 100.0)), width=80, now=0.0, color=False
        )
        self.assertNotIn("░", line)

    def test_empty_snapshot_falls_back_to_message(self) -> None:
        line = render_line(_snapshot(), width=80, now=0.0, color=False)
        self.assertIn("no usage windows", line)


class RenderMessageTest(unittest.TestCase):
    def test_message_is_width_limited(self) -> None:
        message = render_message("a" * 200, width=30, color=False)
        self.assertLessEqual(len(message), 30)


if __name__ == "__main__":
    unittest.main()
