from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from typing import Callable, TextIO

from .poller import UsagePoller
from .render import render_line, render_message

FALLBACK_WIDTH = 80


@dataclass(frozen=True)
class LineOptions:
    """Appearance of a single rendered line."""

    color: bool = True


class UsageLine:
    """Renders one usage line, fetching only if the cache cannot serve it."""

    def __init__(
        self,
        poller: UsagePoller,
        options: LineOptions,
        stream: TextIO,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._poller = poller
        self._options = options
        self._stream = stream
        self._clock = clock

    def run_once(self) -> int:
        """Print one line and exit. Non-zero when there was nothing to show."""
        self._poller.poll_if_due()
        self._stream.write(self._current_line() + "\n")
        self._stream.flush()
        return 0 if self._poller.snapshot else 1

    def _current_line(self) -> str:
        snapshot = self._poller.snapshot
        width = terminal_width()
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


def terminal_width() -> int:
    """Column budget for a rendered line.

    Claude Code sets COLUMNS before running a status line command, and
    `get_terminal_size` prefers it, so this is correct even though stdout is a
    pipe rather than a terminal.
    """
    return shutil.get_terminal_size((FALLBACK_WIDTH, 1)).columns
