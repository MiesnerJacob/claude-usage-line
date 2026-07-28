"""Tests for the condensed single-line renderer."""

from __future__ import annotations

import unittest

from herdr_usage_pane.model import UsageSnapshot, UsageWindow
from herdr_usage_pane.render import (
    BAR_LAYOUT_MIN_WIDTH,
    render_panel,
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


class CompactRenderTest(unittest.TestCase):
    def test_compact_window_has_no_ansi(self) -> None:
        text = render_compact(UsageWindow("5h", 35.0), width=18)
        self.assertNotIn("\033", text)

    def test_compact_aligns_percent_column_when_padded(self) -> None:
        windows = (UsageWindow("5h", 35.0), UsageWindow("Fable", 28.0))
        rendered = [render_compact(w, 20, label_width=8) for w in windows]
        self.assertEqual(len({line.index("%") for line in rendered}), 1, rendered)

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
            UsageWindow("Week (Opus)", 100.0),
        )
        for width in range(6, 40):
            with self.subTest(width=width):
                self.assertLessEqual(len(render_summary(snapshot, width)), width)


class RenderPanelTest(unittest.TestCase):
    def _panel(self, width: int, **kwargs: object) -> list[str]:
        snapshot = _snapshot(
            UsageWindow("Current Session", 58.0, resets_at=8_760),
            UsageWindow("Week (all)", 40.0, resets_at=200_000),
            UsageWindow("Week (Fable)", 28.0, resets_at=200_000),
        )
        return render_panel(
            snapshot, width=width, now=0.0, color=False, **kwargs
        )  # type: ignore[arg-type]

    def test_one_row_per_window_and_no_title_row(self) -> None:
        rows = self._panel(60)
        self.assertEqual(len(rows), 3)
        self.assertIn("Current Session", rows[0])

    def test_each_row_carries_its_own_reset_countdown(self) -> None:
        rows = self._panel(60)
        self.assertIn("2h26m", rows[0])
        self.assertIn("2d7h", rows[1])

    def test_single_row_height_collapses_to_one_line(self) -> None:
        rows = self._panel(115, height=1)
        self.assertEqual(len(rows), 1)
        for label in ("Current Session", "Week (all)", "Week (Fable)"):
            self.assertIn(label, rows[0])

    def test_labels_are_aligned_into_a_column(self) -> None:
        rows = self._panel(60)
        self.assertEqual(len({row.index("█") for row in rows}), 1, rows)

    def test_no_row_exceeds_width(self) -> None:
        for width in range(12, 120):
            with self.subTest(width=width):
                for row in self._panel(width):
                    self.assertLessEqual(_visible_length(row), width)

    def test_empty_snapshot_yields_one_message_row(self) -> None:
        lines = render_panel(_snapshot(), width=60, now=0.0, color=False)
        self.assertEqual(len(lines), 1)
        self.assertIn("no usage windows", lines[0])

    def test_coloured_panel_respects_width(self) -> None:
        snapshot = _snapshot(
            UsageWindow("Current Session", 99.0, resets_at=60),
            UsageWindow("Week (Fable)", 28.0),
        )
        for width in range(12, 90):
            with self.subTest(width=width):
                for row in render_panel(snapshot, width=width, now=0.0, color=True):
                    self.assertLessEqual(_visible_length(row), width)


class RenderMessageTest(unittest.TestCase):
    def test_message_is_width_limited(self) -> None:
        message = render_message("a" * 200, width=30, color=False)
        self.assertLessEqual(len(message), 30)


if __name__ == "__main__":
    unittest.main()
