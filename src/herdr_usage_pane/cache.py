"""On-disk snapshot cache shared by short-lived invocations.

`--once` is called by Claude Code's statusline on every redraw, which is far more
often than the usage endpoint should be polled. Each invocation is a fresh
process, so the freshness window has to live on disk rather than in memory.

The cache is advisory: a miss or a corrupt file simply means fetching again.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .model import UsageSnapshot, UsageWindow

DEFAULT_MAX_AGE_SECONDS = 60.0
CACHE_VERSION = 1


def cache_path() -> Path:
    """Location of the snapshot cache, honouring XDG_CACHE_HOME."""
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "herdr-usage-pane" / "snapshot.json"


def read_snapshot(
    now: float, max_age: float = DEFAULT_MAX_AGE_SECONDS
) -> UsageSnapshot | None:
    """Return the cached snapshot when it is younger than `max_age`."""
    try:
        payload = json.loads(cache_path().read_text())
    except (OSError, ValueError):
        return None
    if payload.get("version") != CACHE_VERSION:
        return None
    captured_at = payload.get("captured_at")
    if not isinstance(captured_at, (int, float)):
        return None
    if now - captured_at > max_age:
        return None
    windows = _decode_windows(payload.get("windows"))
    if not windows:
        return None
    return UsageSnapshot(windows=windows, captured_at=float(captured_at))


def write_snapshot(snapshot: UsageSnapshot) -> None:
    """Persist a snapshot, replacing any previous one atomically."""
    payload = {
        "version": CACHE_VERSION,
        "captured_at": snapshot.captured_at,
        "windows": [
            {
                "label": window.label,
                "used_percentage": window.used_percentage,
                "resets_at": window.resets_at,
                "reported_severity": (
                    window.reported_severity.value
                    if window.reported_severity is not None
                    else None
                ),
            }
            for window in snapshot.windows
        ],
    }
    path = cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomically(path, json.dumps(payload))
    except OSError:
        return


def _write_atomically(path: Path, text: str) -> None:
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except OSError:
        Path(temporary).unlink(missing_ok=True)
        raise


def _decode_windows(raw: object) -> tuple[UsageWindow, ...]:
    if not isinstance(raw, list):
        return ()
    windows = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        label = entry.get("label")
        percentage = entry.get("used_percentage")
        if not isinstance(label, str) or not isinstance(percentage, (int, float)):
            continue
        resets_at = entry.get("resets_at")
        windows.append(
            UsageWindow(
                label=label,
                used_percentage=float(percentage),
                resets_at=resets_at if isinstance(resets_at, int) else None,
                reported_severity=_decode_severity(entry.get("reported_severity")),
            )
        )
    return tuple(windows)


def _decode_severity(raw: object):
    from .model import Severity

    if not isinstance(raw, str):
        return None
    try:
        return Severity(raw)
    except ValueError:
        return None
