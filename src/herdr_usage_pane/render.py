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

_RESET = "\033[0m"
_DIM = "\033[2m"
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
