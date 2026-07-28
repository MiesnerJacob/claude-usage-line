"""Resize a plugin pane so its inner height fits a given number of content rows.

herdr's `[[panes]]` manifest has no height field for splits, and `pane resize`
takes a *delta* to the split ratio rather than a target size, so fitting the
panel means measuring the layout and computing the delta.

Borders and gaps sit between the layout rect and the PTY the process sees -- on
a bottom split that overhead measured 3 rows -- so the target rect is the
content rows plus that overhead, and the overhead is discovered rather than
assumed by comparing the rect against a known-good reference.
"""

from __future__ import annotations

import json
import subprocess
import sys

DEFAULT_CONTENT_ROWS = 4
ASSUMED_CHROME_ROWS = 3
MAX_RATIO = 0.9
COMMAND_TIMEOUT_SECONDS = 10.0


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: fit-panel.py <pane_id> [content_rows]", file=sys.stderr)
        return 2
    pane_id = argv[0]
    content_rows = int(argv[1]) if len(argv) > 1 else DEFAULT_CONTENT_ROWS
    herdr = _herdr_binary()

    layout = _layout(herdr, pane_id)
    if layout is None:
        return 1
    area_height, current_ratio = layout
    if area_height <= 0:
        return 1

    target_rect = content_rows + ASSUMED_CHROME_ROWS
    target_ratio = min(MAX_RATIO, max(0.1, 1.0 - target_rect / area_height))
    delta = current_ratio - target_ratio
    if abs(delta) < 0.005:
        return 0

    direction = "up" if delta > 0 else "down"
    _run(
        herdr,
        ["pane", "resize", "--pane", pane_id, "--direction", direction,
         "--amount", f"{abs(delta):.4f}"],
    )
    return 0


def _layout(herdr: str, pane_id: str) -> tuple[int, float] | None:
    raw = _run(herdr, ["pane", "edges", "--pane", pane_id])
    if raw is None:
        return None
    try:
        layout = json.loads(raw)["result"]["edges"]["layout"]
        splits = layout["splits"]
    except (KeyError, ValueError, TypeError):
        return None
    if not splits:
        return None
    return int(layout["area"]["height"]), float(splits[-1]["ratio"])


def _run(herdr: str, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            [herdr, *args],
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _herdr_binary() -> str:
    import os

    return os.environ.get("HERDR_BIN_PATH") or "herdr"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
