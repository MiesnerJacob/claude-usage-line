"""Poll cadence and failure backoff, shared by every display mode.

The endpoint is throttled, so it is polled infrequently and the last good
reading is retained. Displays repaint faster than this polls, which is what
keeps reset countdowns ticking without extra requests.
"""

from __future__ import annotations

import time
from typing import Callable

from .client import UsageClient, UsageUnavailable
from .model import UsageSnapshot

DEFAULT_POLL_INTERVAL = 60.0
INITIAL_BACKOFF = 30.0
MAX_BACKOFF = 300.0
STALE_AFTER_POLLS = 3


class UsagePoller:
    """Holds the freshest usage reading, refreshing it on a schedule."""

    def __init__(
        self,
        client: UsageClient,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client = client
        self._poll_interval = poll_interval
        self._clock = clock
        self._snapshot: UsageSnapshot | None = None
        self._error: str | None = None
        self._backoff = INITIAL_BACKOFF
        self._next_poll_at = 0.0

    @property
    def snapshot(self) -> UsageSnapshot | None:
        """The most recent successful reading, if there has been one."""
        return self._snapshot

    @property
    def error(self) -> str | None:
        """Why the last attempt failed, if it did."""
        return self._error

    @property
    def is_stale(self) -> bool:
        """Whether the retained reading is too old to present as current."""
        if self._snapshot is None:
            return False
        age = self._clock() - self._snapshot.captured_at
        return age > self._poll_interval * STALE_AFTER_POLLS

    def poll_if_due(self) -> bool:
        """Refresh when the schedule allows. Returns True on a fresh reading."""
        now = self._clock()
        if now < self._next_poll_at:
            return False
        try:
            self._snapshot = self._client.fetch(now)
        except UsageUnavailable as error:
            self._error = str(error)
            self._next_poll_at = now + self._backoff
            self._backoff = min(MAX_BACKOFF, self._backoff * 2)
            return False
        self._error = None
        self._backoff = INITIAL_BACKOFF
        self._next_poll_at = now + self._poll_interval
        return True
