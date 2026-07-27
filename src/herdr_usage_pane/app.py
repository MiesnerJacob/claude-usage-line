"""Application layer: the long-running display modes.

`UsagePane` paints a line into a terminal pane. `SidebarPublisher` pushes the
same reading into herdr's sidebar as metadata tokens. Both drive the shared
`UsagePoller`, so polling behaviour cannot drift between them.
"""

from __future__ import annotations

import os
import shutil
import signal
import time
from dataclasses import dataclass
from typing import Callable, TextIO

from .poller import DEFAULT_POLL_INTERVAL, UsagePoller
from .render import render_line, render_message
from .reporter import ReporterError, SidebarReporter

DEFAULT_TICK_INTERVAL = 1.0
FALLBACK_WIDTH = 80

_HIDE_CURSOR = "\033[?25l"
_SHOW_CURSOR = "\033[?25h"
_CLEAR_LINE = "\r\033[2K"


@dataclass(frozen=True)
class PaneOptions:
    """Tunables for the pane's refresh behaviour and appearance."""

    poll_interval: float = DEFAULT_POLL_INTERVAL
    tick_interval: float = DEFAULT_TICK_INTERVAL
    color: bool = True


class _InterruptibleLoop:
    """Base for loops that must stop cleanly on SIGINT and SIGTERM."""

    def __init__(self) -> None:
        self._stopped = False

    def _install_signal_handlers(self) -> None:
        for received in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(received, self._handle_stop)
            except (OSError, ValueError):
                continue

    def _handle_stop(self, _signum: int, _frame: object) -> None:
        self._stopped = True


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
        self._write(_HIDE_CURSOR)
        try:
            while not self._stopped:
                self._poller.poll_if_due()
                self._write(_CLEAR_LINE + self._current_line())
                time.sleep(self._options.tick_interval)
        finally:
            self._write(_SHOW_CURSOR + "\n")
        return 0

    def run_once(self) -> int:
        """Poll once, print a single line, and exit. Suitable for statuslines."""
        self._poller.poll_if_due()
        self._stream.write(self._current_line() + "\n")
        self._stream.flush()
        return 0 if self._poller.snapshot else 1

    def _current_line(self) -> str:
        width = _terminal_width(self._stream)
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
            self._stopped = True


class SidebarPublisher(_InterruptibleLoop):
    """Keeps herdr's sidebar tokens current, occupying no pane."""

    def __init__(
        self,
        poller: UsagePoller,
        reporter: SidebarReporter,
        publish_interval: float = DEFAULT_POLL_INTERVAL,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self._poller = poller
        self._reporter = reporter
        self._publish_interval = publish_interval
        self._on_error = on_error

    def run(self) -> int:
        """Publish until interrupted, clearing the tokens on the way out."""
        self._install_signal_handlers()
        try:
            while not self._stopped:
                self._publish_if_possible()
                time.sleep(self._publish_interval)
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
            self._reporter.publish(snapshot)
        except ReporterError as error:
            self._report(str(error))

    def _clear_quietly(self) -> None:
        try:
            self._reporter.clear()
        except ReporterError:
            pass

    def _report(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)


def _terminal_width(stream: TextIO) -> int:
    """Width of the pane, measured from its own descriptor where possible."""
    try:
        return os.get_terminal_size(stream.fileno()).columns
    except (OSError, ValueError, AttributeError):
        return shutil.get_terminal_size((FALLBACK_WIDTH, 1)).columns
