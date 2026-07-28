"""Render a usage snapshot as one condensed terminal line.

The pane is one row tall, so every renderer here is width-budgeted: the layout
degrades from bars to percentages to bare numbers rather than wrapping.
"""

from __future__ import annotations

from .model import Severity, UsageSnapshot, UsageWindow

FILLED_GLYPH = "█"
EMPTY_GLYPH = "░"
SEPARATOR = " │ "
MIN_BAR_WIDTH = 4
MAX_BAR_WIDTH = 12
BAR_LAYOUT_MIN_WIDTH = 46
COMPACT_WIDTH = 22

PANEL_TITLE = "✳ Claude Code Usage"
PANEL_MIN_HEIGHT = 2

_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_SEVERITY_COLORS = {
    Severity.NOMINAL: "\033[32m",
    Severity.ELEVATED: "\033[33m",
    Severity.CRITICAL: "\033[31m",
}


def render_line(
    snapshot: UsageSnapshot,
    width: int,
    now: float,
    color: bool = True,
    stale: bool = False,
) -> str:
    """Render a snapshot to a single line no wider than `width` columns."""
    if not snapshot.windows:
        return render_message("no usage windows reported", width, color)
    bar_width = _bar_width(width, snapshot.windows, now)
    segments = [
        _render_window(window, bar_width, now, color)
        for window in snapshot.windows
    ]
    line = SEPARATOR.join(segments)
    if stale:
        line = f"{line} {_paint('(stale)', _DIM, color)}"
    return _fit(line, width)


def render_message(text: str, width: int, color: bool = True) -> str:
    """Render a status or error message in place of the usage line."""
    return _fit(_paint(f"claude usage — {text}", _DIM, color), width)


def render_panel(
    snapshot: UsageSnapshot,
    width: int,
    now: float,
    color: bool = True,
    stale: bool = False,
    height: int | None = None,
) -> list[str]:
    """Render a titled multi-row panel, one row per usage window.

    Bars stretch to the pane width rather than being capped, since here the
    space exists to use. When `height` cannot fit the header plus every window,
    the header is dropped first: a truncated set of numbers is worse than a
    missing title, because a missing row reads as a missing limit.
    """
    if not snapshot.windows:
        return [render_message("no usage windows reported", width, color)]
    label_width = max(len(window.label) for window in snapshot.windows)
    rows = [
        _render_panel_row(window, width, label_width, color)
        for window in snapshot.windows
    ]
    if height is not None and height < len(rows) + 1:
        return rows[:height]
    return [_render_header(snapshot, width, now, color, stale), *rows]


def _render_header(
    snapshot: UsageSnapshot,
    width: int,
    now: float,
    color: bool,
    stale: bool,
) -> str:
    title = _paint(PANEL_TITLE, _BOLD, color)
    suffix = "(stale)" if stale else _soonest_reset(snapshot, now)
    if not suffix or _visible_length(title) + len(suffix) + 1 > width:
        return _fit(title, width)
    padding = width - _visible_length(title) - len(suffix)
    return title + " " * padding + _paint(suffix, _DIM, color)


def _soonest_reset(snapshot: UsageSnapshot, now: float) -> str:
    countdowns = [
        seconds
        for seconds in (
            window.seconds_until_reset(now) for window in snapshot.windows
        )
        if seconds is not None
    ]
    if not countdowns:
        return ""
    return f"resets {format_duration(min(countdowns))}"


def _render_panel_row(
    window: UsageWindow,
    width: int,
    label_width: int,
    color: bool,
) -> str:
    tint = _SEVERITY_COLORS[window.severity]
    label = window.label.ljust(label_width)
    percent = f"{round(window.used_percentage):>3d}%"
    bar = width - (label_width + 2 + len(percent) + 2)
    if bar < MIN_BAR_WIDTH:
        return _fit(f"{_paint(label, _DIM, color)} {_paint(percent, tint, color)}", width)
    return (
        f"{_paint(label, _DIM, color)}  "
        f"{_render_bar(window.used_percentage, bar, tint, color)}  "
        f"{_paint(percent, tint, color)}"
    )


def render_compact(
    window: UsageWindow,
    width: int = COMPACT_WIDTH,
    label_width: int | None = None,
) -> str:
    """Render one window as short plain text for a herdr sidebar token.

    Pass `label_width` when rendering several windows as stacked sidebar rows:
    padding every label to the widest one lines the bars and percentages up
    into columns instead of ragged text.

    No ANSI: sidebar tokens are styled by herdr's own config, so emitting escape
    codes here would fight the user's theme rather than honour it.
    """
    label = window.label.ljust(label_width or len(window.label))
    percent = f"{round(window.used_percentage):>3d}%"
    bar = width - (len(label) + 1 + len(percent) + 1)
    if bar < MIN_BAR_WIDTH:
        return f"{label} {percent}"[:width] if label_width else (
            f"{label} {round(window.used_percentage)}%"[:width]
        )
    bar = min(MAX_BAR_WIDTH, bar)
    filled = min(bar, max(0, round(window.used_percentage / 100 * bar)))
    return (
        f"{label} {FILLED_GLYPH * filled}{EMPTY_GLYPH * (bar - filled)} {percent}"
    )


def render_summary(snapshot: UsageSnapshot, width: int = COMPACT_WIDTH) -> str:
    """Render every window that fits as one short line, e.g. `5h 35% · 7d 32%`.

    Windows are dropped whole rather than cut, because a truncated `7d 3` reads
    as a real number and would misinform at a glance.
    """
    parts: list[str] = []
    for window in snapshot.windows:
        piece = f"{window.label} {round(window.used_percentage)}%"
        if parts and len(" · ".join([*parts, piece])) > width:
            break
        parts.append(piece)
    summary = " · ".join(parts)
    return summary if len(summary) <= width else summary[:width].rstrip()


def format_duration(seconds: int | None) -> str:
    """Format a reset countdown compactly, e.g. `2h14m`, `3d4h`, `<1m`."""
    if seconds is None:
        return ""
    if seconds < 60:
        return "<1m"
    minutes, hours = (seconds // 60) % 60, seconds // 3600
    if hours >= 24:
        days, remaining_hours = hours // 24, hours % 24
        return f"{days}d{remaining_hours}h"
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


def _render_window(
    window: UsageWindow,
    bar_width: int,
    now: float,
    color: bool,
) -> str:
    tint = _SEVERITY_COLORS[window.severity]
    parts = [_paint(window.label, _DIM, color)]
    if bar_width:
        parts.append(_render_bar(window.used_percentage, bar_width, tint, color))
    parts.append(_paint(f"{round(window.used_percentage):>3d}%", tint, color))
    countdown = format_duration(window.seconds_until_reset(now))
    if countdown:
        parts.append(_paint(countdown, _DIM, color))
    return " ".join(parts)


def _render_bar(percentage: float, width: int, tint: str, color: bool) -> str:
    filled = min(width, max(0, round(percentage / 100 * width)))
    return _paint(FILLED_GLYPH * filled, tint, color) + _paint(
        EMPTY_GLYPH * (width - filled), _DIM, color
    )


def _bar_width(width: int, windows: tuple[UsageWindow, ...], now: float) -> int:
    """Columns to give each bar, or 0 when the line must drop bars to fit.

    Budgeted against the real label and countdown text rather than a worst-case
    guess, so a `7d opus` window does not silently push the line over `width`.
    """
    if width < BAR_LAYOUT_MIN_WIDTH:
        return 0
    fixed = sum(_fixed_segment_width(window, now) for window in windows)
    overhead = fixed + len(SEPARATOR) * (len(windows) - 1)
    available = (width - overhead) // len(windows)
    if available < MIN_BAR_WIDTH:
        return 0
    return min(MAX_BAR_WIDTH, available)


def _fixed_segment_width(window: UsageWindow, now: float) -> int:
    """Columns a segment needs for everything except its bar."""
    countdown = format_duration(window.seconds_until_reset(now))
    trailing = len(countdown) + 1 if countdown else 0
    return len(window.label) + 1 + len("100%") + 1 + trailing


def _paint(text: str, code: str, color: bool) -> str:
    if not color or not text:
        return text
    return f"{code}{text}{_RESET}"


def _fit(line: str, width: int) -> str:
    """Truncate to `width` visible columns, ignoring ANSI escapes.

    The reset is re-appended only when an escape survived truncation; adding it
    unconditionally would pad an uncoloured line with invisible bytes that still
    count against callers measuring raw length.
    """
    if width <= 0 or _visible_length(line) <= width:
        return line
    result: list[str] = []
    visible, index, emitted_escape = 0, 0, False
    while index < len(line) and visible < width:
        if line[index] == "\033":
            end = line.find("m", index)
            if end == -1:
                break
            result.append(line[index : end + 1])
            emitted_escape = True
            index = end + 1
            continue
        result.append(line[index])
        visible += 1
        index += 1
    truncated = "".join(result)
    return truncated + _RESET if emitted_escape else truncated


def _visible_length(line: str) -> int:
    length, index = 0, 0
    while index < len(line):
        if line[index] == "\033":
            end = line.find("m", index)
            if end == -1:
                break
            index = end + 1
            continue
        length += 1
        index += 1
    return length
