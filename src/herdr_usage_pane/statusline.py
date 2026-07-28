"""Read usage straight from the JSON Claude Code hands a statusline on stdin.

Claude Code includes a `rate_limits` object in the statusline payload, so in that
mode the numbers are free: no OAuth token, no HTTP request, no cache, and never
stale. It carries only the session and all-model weekly windows, so a per-model
scoped window (`Week (Fable)`) still has to come from the cached API snapshot.
"""

from __future__ import annotations

import json
import os
import select
import sys

from .model import UsageSnapshot, UsageWindow

STDIN_TIMEOUT_SECONDS = 0.15
MAX_PAYLOAD_BYTES = 1 << 20

STDIN_WINDOW_LABELS: dict[str, str] = {
    "five_hour": "Current Session",
    "seven_day": "Week (all)",
}


def read_stdin_payload(timeout: float = STDIN_TIMEOUT_SECONDS) -> dict | None:
    """Decode the statusline payload, or None when stdin carries no JSON.

    Never blocks. `sys.stdin.read()` would wait for EOF, which never arrives when
    stdin is an inherited pipe that nobody closes — that hangs the caller
    indefinitely. Instead this waits briefly for readability and takes one
    bounded read, which is how the payload arrives anyway.
    """
    if sys.stdin.isatty():
        return None
    try:
        descriptor = sys.stdin.fileno()
        ready, _, _ = select.select([descriptor], [], [], timeout)
        if not ready:
            return None
        raw = os.read(descriptor, MAX_PAYLOAD_BYTES)
    except (OSError, ValueError):
        return None
    if not raw.strip():
        return None
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def snapshot_from_payload(payload: dict, now: float) -> UsageSnapshot | None:
    """Build a snapshot from a statusline payload's `rate_limits`."""
    limits = payload.get("rate_limits")
    if not isinstance(limits, dict):
        return None
    windows = []
    for key, label in STDIN_WINDOW_LABELS.items():
        window = _window(limits.get(key), label)
        if window is not None:
            windows.append(window)
    if not windows:
        return None
    return UsageSnapshot(windows=tuple(windows), captured_at=now)


def merge_scoped(
    snapshot: UsageSnapshot, cached: UsageSnapshot | None
) -> UsageSnapshot:
    """Append windows the statusline payload does not carry, such as per-model.

    Matched by label so a cached copy of a window already present is not shown
    twice, and so the authoritative live values always win.
    """
    if cached is None:
        return snapshot
    present = {window.label for window in snapshot.windows}
    extra = tuple(
        window for window in cached.windows if window.label not in present
    )
    if not extra:
        return snapshot
    return UsageSnapshot(
        windows=snapshot.windows + extra, captured_at=snapshot.captured_at
    )


def _window(raw: object, label: str) -> UsageWindow | None:
    if not isinstance(raw, dict):
        return None
    percentage = raw.get("used_percentage")
    if isinstance(percentage, bool) or not isinstance(percentage, (int, float)):
        return None
    resets_at = raw.get("resets_at")
    return UsageWindow(
        label=label,
        used_percentage=float(percentage),
        resets_at=resets_at if isinstance(resets_at, int) else None,
    )
