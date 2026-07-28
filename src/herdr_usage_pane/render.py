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

PANEL_MIN_HEIGHT = 2

_RESET = "\033[0m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_MAGENTA = "\033[35m"
_INFO_STYLES = {
    "branch": _CYAN,
    "worktree": _MAGENTA,
    "dim": _DIM,
    "added": _GREEN,
    "removed": _RED,
}
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
    prefix: str | None = None,
) -> str:
    """Render a snapshot to a single line no wider than `width` columns.

    `prefix` is unmetered context shown ahead of the windows, such as a git
    branch. It is charged against the width budget so the bars shrink to make
    room rather than the line overflowing.
    """
    if not snapshot.windows:
        return render_message("no usage windows reported", width, color)
    lead = f"{_paint(prefix, _DIM, color)}{SEPARATOR}" if prefix else ""
    width -= _visible_length(lead)
    bar_width = _bar_width(width, snapshot.windows, now)
    segments = [
        _render_window(window, bar_width, now, color)
        for window in snapshot.windows
    ]
    line = SEPARATOR.join(segments)
    if stale:
        line = f"{line} {_paint('(stale)', _DIM, color)}"
    return lead + _fit(line, width)


def render_info_row(
    segments: list[tuple[str, str]],
    width: int,
    color: bool = True,
) -> str:
    """Render (text, style) pairs as one dim context row above the bars.

    Adjacent line counts are joined with a space rather than the separator, so
    `+120 -8` reads as one figure instead of two unrelated facts.
    """
    if not segments:
        return ""
    rendered: list[str] = []
    for text, style in segments:
        painted = _paint(text, _INFO_STYLES.get(style, _DIM), color)
        if style == "removed" and rendered:
            rendered[-1] = f"{rendered[-1]} {painted}"
        else:
            rendered.append(painted)
    return _fit(SEPARATOR.join(rendered), width)


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
    """Render one row per usage window, sized to the pane.

    No title row: herdr already draws the pane's label on its border, so a
    header here would repeat it. At `height == 1` the windows collapse onto a
    single horizontal line instead of being truncated away.
    """
    if not snapshot.windows:
        return [render_message("no usage windows reported", width, color)]
    if height is not None and height < len(snapshot.windows):
        return _render_folded(snapshot, width, now, color, stale, height)
    label_width = max(len(window.label) for window in snapshot.windows)
    reset_width = max(
        len(format_duration(window.seconds_until_reset(now)))
        for window in snapshot.windows
    )
    rows = [
        _render_panel_row(window, width, label_width, reset_width, now, color)
        for window in snapshot.windows
    ]
    return rows[:height] if height is not None else rows


def _render_folded(
    snapshot: UsageSnapshot,
    width: int,
    now: float,
    color: bool,
    stale: bool,
    height: int,
) -> list[str]:
    """Fit every window into fewer rows than there are windows.

    Windows are folded across the available rows rather than dropped, because a
    missing row reads as a missing limit. herdr clamps split ratios to 0.9, so a
    pane cannot be shorter than two usable rows; folding uses both instead of
    leaving one blank.
    """
    windows = list(snapshot.windows)
    per_row = -(-len(windows) // max(1, height))
    lines = []
    for start in range(0, len(windows), per_row):
        group = UsageSnapshot(
            windows=tuple(windows[start : start + per_row]),
            captured_at=snapshot.captured_at,
        )
        lines.append(render_line(group, width, now, color, stale and not lines))
    return lines[:height]


def _render_panel_row(
    window: UsageWindow,
    width: int,
    label_width: int,
    reset_width: int,
    now: float,
    color: bool,
) -> str:
    """One window as `label  bar  pct  resets`, columns aligned across rows."""
    tint = _SEVERITY_COLORS[window.severity]
    label = window.label.ljust(label_width)
    percent = f"{round(window.used_percentage):>3d}%"
    countdown = format_duration(window.seconds_until_reset(now)).rjust(reset_width)
    trailing = len(countdown) + 2 if reset_width else 0
    bar = width - (label_width + 2 + len(percent) + 2 + trailing)
    if bar < MIN_BAR_WIDTH:
        return _fit(
            f"{_paint(label, _DIM, color)} {_paint(percent, tint, color)}", width
        )
    row = (
        f"{_paint(label, _DIM, color)}  "
        f"{_render_bar(window.used_percentage, bar, tint, color)}  "
        f"{_paint(percent, tint, color)}"
    )
    return f"{row}  {_paint(countdown, _DIM, color)}" if trailing else row


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
