"""Tests for the condensed single-line renderer."""

from __future__ import annotations

import unittest

from herdr_usage_pane.model import UsageSnapshot, UsageWindow
from herdr_usage_pane.render import (
    BAR_LAYOUT_MIN_WIDTH,
    _visible_length,
    format_duration,
    render_compact,
    render_line,
    render_message,
    render_summary,
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
            UsageWindow("7d opus", 23.0, resets_at=200_000),
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


class CompactRenderTest(unittest.TestCase):
    def test_compact_window_has_no_ansi(self) -> None:
        text = render_compact(UsageWindow("5h", 35.0), width=18)
        self.assertNotIn("\033", text)

    def test_compact_window_respects_width(self) -> None:
        for width in range(6, 40):
            with self.subTest(width=width):
                text = render_compact(UsageWindow("5h", 35.0), width=width)
                self.assertLessEqual(len(text), width)

    def test_compact_drops_bar_when_too_narrow(self) -> None:
        self.assertEqual(render_compact(UsageWindow("5h", 35.0), width=8), "5h 35%")

    def test_summary_drops_whole_windows_rather_than_cutting(self) -> None:
        snapshot = _snapshot(UsageWindow("5h", 35.0), UsageWindow("7d", 32.0))
        self.assertEqual(render_summary(snapshot, width=10), "5h 35%")

    def test_summary_fits_both_windows_when_room_allows(self) -> None:
        snapshot = _snapshot(UsageWindow("5h", 35.0), UsageWindow("7d", 32.0))
        self.assertEqual(render_summary(snapshot, width=18), "5h 35% · 7d 32%")

    def test_summary_never_exceeds_width(self) -> None:
        snapshot = _snapshot(
            UsageWindow("5h", 100.0),
            UsageWindow("7d", 100.0),
            UsageWindow("7d opus", 100.0),
        )
        for width in range(6, 40):
            with self.subTest(width=width):
                self.assertLessEqual(len(render_summary(snapshot, width)), width)


class RenderMessageTest(unittest.TestCase):
    def test_message_is_width_limited(self) -> None:
        message = render_message("a" * 200, width=30, color=False)
        self.assertLessEqual(len(message), 30)


if __name__ == "__main__":
    unittest.main()
