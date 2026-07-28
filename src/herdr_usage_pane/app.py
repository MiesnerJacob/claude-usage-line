"""Application layer: the long-running display modes.

`UsagePane` paints a line into a terminal pane. `SidebarPublisher` pushes the
same reading into herdr's sidebar as metadata tokens. Both drive the shared
`UsagePoller`, so polling behaviour cannot drift between them.
"""

from __future__ import annotations

import os
import shutil
import signal
import threading
import time
from dataclasses import dataclass
from typing import Callable, TextIO

from .poller import DEFAULT_POLL_INTERVAL, UsagePoller
from .render import PANEL_MIN_HEIGHT, render_line, render_message, render_panel
from .reporter import ReporterError, SidebarReporter

DEFAULT_TICK_INTERVAL = 1.0
FALLBACK_WIDTH = 80
FALLBACK_HEIGHT = 4

_HIDE_CURSOR = "\033[?25l"
_SHOW_CURSOR = "\033[?25h"
_CLEAR_LINE = "\r\033[2K"
_CLEAR_BELOW = "\033[J"
_DISABLE_WRAP = "\033[?7l"
_ENABLE_WRAP = "\033[?7h"


@dataclass(frozen=True)
class PaneOptions:
    """Tunables for the pane's refresh behaviour and appearance."""

    poll_interval: float = DEFAULT_POLL_INTERVAL
    tick_interval: float = DEFAULT_TICK_INTERVAL
    color: bool = True


class _InterruptibleLoop:
    """Base for loops that must stop promptly on SIGINT and SIGTERM.

    Waiting goes through an Event rather than `time.sleep`: per PEP 475 a sleep
    resumes after a signal handler returns, so a long-sleeping loop would ignore
    SIGTERM until the sleep elapsed. `Event.wait` returns as soon as it is set.
    """

    def __init__(self) -> None:
        self._stop_requested = threading.Event()

    @property
    def _stopped(self) -> bool:
        return self._stop_requested.is_set()

    def _wait(self, seconds: float) -> None:
        self._stop_requested.wait(seconds)

    def _install_signal_handlers(self) -> None:
        for received in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(received, self._handle_stop)
            except (OSError, ValueError):
                continue

    def _handle_stop(self, _signum: int, _frame: object) -> None:
        self._stop_requested.set()


class UsagePane(_InterruptibleLoop):
    """Keeps one usage line painted in a terminal pane."""

    def __init__(
        self,
        poller: UsagePoller,
        options: PaneOptions,
        stream: TextIO,
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__()
        self._poller = poller
        self._options = options
        self._stream = stream
        self._clock = clock

    def run(self) -> int:
        """Paint until interrupted. Returns a process exit status."""
        self._install_signal_handlers()
        self._write(_HIDE_CURSOR + _DISABLE_WRAP)
        try:
            while not self._stopped:
                self._poller.poll_if_due()
                self._paint()
                self._wait(self._options.tick_interval)
        finally:
            self._write(_ENABLE_WRAP + _SHOW_CURSOR + "\n")
        return 0

    def _paint(self) -> None:
        """Draw the panel when the pane is tall enough, else one line."""
        columns, rows = _terminal_size(self._stream)
        if rows < PANEL_MIN_HEIGHT:
            self._write(_CLEAR_LINE + self._current_line(columns))
            return
        self._write(_paint_rows(self._panel_lines(columns, rows), rows))

    def _panel_lines(self, columns: int, rows: int) -> list[str]:
        snapshot = self._poller.snapshot
        if snapshot is None:
            return [self._current_line(columns)]
        return render_panel(
            snapshot,
            width=columns,
            now=self._clock(),
            color=self._options.color,
            stale=self._poller.is_stale,
            height=rows,
        )[:rows]

    def run_once(self) -> int:
        """Poll once, print a single line, and exit. Suitable for statuslines."""
        self._poller.poll_if_due()
        self._stream.write(self._current_line() + "\n")
        self._stream.flush()
        return 0 if self._poller.snapshot else 1

    def _current_line(self, width: int | None = None) -> str:
        if width is None:
            width = _terminal_size(self._stream)[0]
        snapshot = self._poller.snapshot
        if snapshot is None:
            return render_message(
                self._poller.error or "loading…", width, self._options.color
            )
        return render_line(
            snapshot,
            width=width,
            now=self._clock(),
            color=self._options.color,
            stale=self._poller.is_stale,
        )

    def _write(self, text: str) -> None:
        try:
            self._stream.write(text)
            self._stream.flush()
        except (OSError, ValueError):
            self._stop_requested.set()


class SidebarPublisher(_InterruptibleLoop):
    """Keeps herdr's sidebar tokens current, occupying no pane."""

    def __init__(
        self,
        poller: UsagePoller,
        reporter: SidebarReporter,
        publish_interval: float = DEFAULT_POLL_INTERVAL,
        on_error: Callable[[str], None] | None = None,
        resolve_target: Callable[[], object] | None = None,
    ) -> None:
        super().__init__()
        self._poller = poller
        self._reporter = reporter
        self._publish_interval = publish_interval
        self._on_error = on_error
        self._resolve_target = resolve_target

    def run(self) -> int:
        """Publish until interrupted, clearing the tokens on the way out."""
        self._install_signal_handlers()
        try:
            while not self._stopped:
                self._publish_if_possible()
                self._wait(self._publish_interval)
        finally:
            self._clear_quietly()
        return 0

    def run_once(self) -> int:
        """Publish a single update and exit."""
        self._poller.poll_if_due()
        snapshot = self._poller.snapshot
        if snapshot is None:
            self._report(self._poller.error or "usage unavailable")
            return 1
        try:
            self._reporter.publish(snapshot)
        except ReporterError as error:
            self._report(str(error))
            return 1
        return 0

    def _publish_if_possible(self) -> None:
        self._poller.poll_if_due()
        snapshot = self._poller.snapshot
        if snapshot is None or self._poller.is_stale:
            return
        try:
            self._follow_target()
            self._reporter.publish(snapshot)
        except ReporterError as error:
            self._report(str(error))

    def _follow_target(self) -> None:
        """Track the anchor entity, which moves as panes open and close."""
        if self._resolve_target is None:
            return
        try:
            self._reporter.retarget(self._resolve_target())  # type: ignore[arg-type]
        except ReporterError:
            pass

    def _clear_quietly(self) -> None:
        try:
            self._reporter.clear()
        except ReporterError:
            pass

    def _report(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)


def _terminal_size(stream: TextIO) -> tuple[int, int]:
    """Columns and rows of the pane, from its own descriptor where possible."""
    try:
        size = os.get_terminal_size(stream.fileno())
    except (OSError, ValueError, AttributeError):
        size = shutil.get_terminal_size((FALLBACK_WIDTH, FALLBACK_HEIGHT))
    return size.columns, size.lines


def _paint_rows(lines: list[str], rows: int) -> str:
    """Redraw rows at absolute positions, clearing anything left below.

    Deliberately no newlines: emitting one after the last line of a full-height
    pane scrolls the buffer up and takes the header off screen. Addressing each
    row directly keeps the panel anchored.
    """
    painted = "".join(
        f"\033[{row};1H\033[2K{line}" for row, line in enumerate(lines, start=1)
    )
    # Clear leftover rows only when there are any. `ED 0` erases from the cursor
    # cell *inclusive*, and parking past the final row clamps back onto it, so
    # clearing when the content fills the pane wipes the last row just drawn.
    if len(lines) >= rows:
        return painted
    return f"{painted}\033[{len(lines) + 1};1H{_CLEAR_BELOW}"
