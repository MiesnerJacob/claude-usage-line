"""Application layer: keep a condensed usage line current inside a herdr pane.

Polling and repainting run on separate cadences. The endpoint is throttled, so
it is polled infrequently, while the line repaints every second to keep reset
countdowns ticking without extra requests.
"""

from __future__ import annotations

import os
import shutil
import signal
import time
from dataclasses import dataclass
from typing import Callable, TextIO

from .client import UsageClient, UsageUnavailable
from .model import UsageSnapshot
from .render import render_line, render_message

DEFAULT_POLL_INTERVAL = 60.0
DEFAULT_TICK_INTERVAL = 1.0
INITIAL_BACKOFF = 30.0
MAX_BACKOFF = 300.0
STALE_AFTER_POLLS = 3
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


class UsagePane:
    """Long-running renderer that keeps one usage line painted in a pane."""

    def __init__(
        self,
        client: UsageClient,
        options: PaneOptions,
        stream: TextIO,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client = client
        self._options = options
        self._stream = stream
        self._clock = clock
        self._snapshot: UsageSnapshot | None = None
        self._error: str | None = None
        self._backoff = INITIAL_BACKOFF
        self._next_poll_at = 0.0
        self._stopped = False

    def run(self) -> int:
        """Paint until interrupted. Returns a process exit status."""
        self._install_signal_handlers()
        self._write(_HIDE_CURSOR)
        try:
            while not self._stopped:
                self._poll_if_due()
                self._paint()
                time.sleep(self._options.tick_interval)
        finally:
            self._write(_SHOW_CURSOR + "\n")
        return 0

    def run_once(self) -> int:
        """Poll once, print a single line, and exit. Suitable for statuslines."""
        self._poll_if_due()
        self._stream.write(self._current_line() + "\n")
        self._stream.flush()
        return 0 if self._snapshot else 1

    def _poll_if_due(self) -> None:
        now = self._clock()
        if now < self._next_poll_at:
            return
        try:
            self._snapshot = self._client.fetch(now)
            self._error = None
            self._backoff = INITIAL_BACKOFF
            self._next_poll_at = now + self._options.poll_interval
        except UsageUnavailable as error:
            self._error = str(error)
            self._next_poll_at = now + self._backoff
            self._backoff = min(MAX_BACKOFF, self._backoff * 2)

    def _paint(self) -> None:
        self._write(_CLEAR_LINE + self._current_line())

    def _current_line(self) -> str:
        width = _terminal_width(self._stream)
        if self._snapshot is None:
            return render_message(
                self._error or "loading…", width, self._options.color
            )
        return render_line(
            self._snapshot,
            width=width,
            now=self._clock(),
            color=self._options.color,
            stale=self._is_stale(),
        )

    def _is_stale(self) -> bool:
        if self._snapshot is None:
            return False
        age = self._clock() - self._snapshot.captured_at
        return age > self._options.poll_interval * STALE_AFTER_POLLS

    def _install_signal_handlers(self) -> None:
        for received in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(received, self._handle_stop)
            except (OSError, ValueError):
                continue

    def _handle_stop(self, _signum: int, _frame: object) -> None:
        self._stopped = True

    def _write(self, text: str) -> None:
        try:
            self._stream.write(text)
            self._stream.flush()
        except (OSError, ValueError):
            self._stopped = True


def _terminal_width(stream: TextIO) -> int:
    """Width of the pane, measured from its own descriptor where possible."""
    try:
        return os.get_terminal_size(stream.fileno()).columns
    except (OSError, ValueError, AttributeError):
        return shutil.get_terminal_size((FALLBACK_WIDTH, 1)).columns
