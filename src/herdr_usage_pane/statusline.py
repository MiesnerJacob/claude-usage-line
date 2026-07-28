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
from pathlib import Path

from .model import UsageSnapshot, UsageWindow

STDIN_TIMEOUT_SECONDS = 0.15
MAX_PAYLOAD_BYTES = 1 << 20
CONTEXT_LABEL = "Context"
WORKTREE_PREFIX = "wt"
MIN_SHARED_SUFFIX = 6

SHORT_LABELS: dict[str, str] = {
    "Context": "Ctx",
    "Current Session": "Session",
    "Week (all)": "Week",
}

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


def info_segments(payload: dict) -> list[tuple[str, str]]:
    """Session context for the row above the bars, as (text, style) pairs.

    Styles are names, not escape codes, so this stays a payload reader and the
    renderer keeps sole responsibility for ANSI.

    Line counts are the session totals the payload provides, not a per-branch
    diff: scoping them to the branch would need a `git diff` against a base ref
    that cannot be inferred reliably, and a subprocess on every redraw.
    """
    segments: list[tuple[str, str]] = []
    branch = git_label(payload.get("cwd"))
    if branch:
        segments.append((branch, "branch"))
    model = _nested_str(payload, "model", "display_name")
    if model:
        segments.append((model, "dim"))
    effort = _nested_str(payload, "effort", "level")
    if effort:
        segments.append((f"effort {effort}", "dim"))
    segments.extend(_line_count_segments(payload))
    return segments


def _line_count_segments(payload: dict) -> list[tuple[str, str]]:
    cost = payload.get("cost")
    if not isinstance(cost, dict):
        return []
    added = cost.get("total_lines_added")
    removed = cost.get("total_lines_removed")
    if not isinstance(added, int) or not isinstance(removed, int):
        return []
    return [(f"+{added}", "added"), (f"-{removed}", "removed")]


def _nested_str(payload: dict, outer: str, inner: str) -> str | None:
    section = payload.get(outer)
    if not isinstance(section, dict):
        return None
    value = section.get(inner)
    return value if isinstance(value, str) and value else None


def shorten_labels(snapshot: UsageSnapshot) -> UsageSnapshot:
    """Abbreviate labels so a one-line statusline keeps room for bars.

    On a single line the labels compete with the bars for columns, and the bars
    carry the at-a-glance signal. `Week (Fable)` becomes `Fable`, which stays
    unambiguous because it sits beside `Week`.
    """
    return UsageSnapshot(
        windows=tuple(
            UsageWindow(
                label=_short_label(window.label),
                used_percentage=window.used_percentage,
                resets_at=window.resets_at,
                reported_severity=window.reported_severity,
            )
            for window in snapshot.windows
        ),
        captured_at=snapshot.captured_at,
    )


def _short_label(label: str) -> str:
    """Abbreviate any label, including window types not seen before.

    A qualified label like `Week (Fable)` reduces to its qualifier, so a
    per-model window keeps working when the model changes or a new one appears.
    """
    if label in SHORT_LABELS:
        return SHORT_LABELS[label]
    if label.endswith(")") and "(" in label:
        qualifier = label[label.index("(") + 1 : -1].strip()
        if qualifier and qualifier.lower() != "all":
            return qualifier
    return label


def context_window_from_payload(payload: dict) -> UsageWindow | None:
    """The session's context-window fill, which the payload also carries."""
    context = payload.get("context_window")
    if not isinstance(context, dict):
        return None
    percentage = context.get("used_percentage")
    if isinstance(percentage, bool) or not isinstance(percentage, (int, float)):
        return None
    return UsageWindow(label=CONTEXT_LABEL, used_percentage=float(percentage))


def git_label(cwd: str | None) -> str | None:
    """Branch name, or `worktree:branch` when inside a linked worktree.

    Reads the git metadata directly instead of shelling out to `git`: this runs
    on every statusline redraw, where a subprocess costs more than everything
    else combined.
    """
    if not cwd:
        return None
    git_path = _find_git_path(Path(cwd))
    if git_path is None:
        return None
    worktree = _worktree_name(git_path)
    branch = _head_branch(git_path)
    if worktree is None:
        return branch
    if branch is None:
        return f"{WORKTREE_PREFIX} {worktree}"
    if _names_overlap(worktree, branch):
        return f"{WORKTREE_PREFIX} {branch}"
    return f"{WORKTREE_PREFIX} {worktree}:{branch}"


def _names_overlap(worktree: str, branch: str) -> bool:
    """Whether the worktree directory and branch say the same thing.

    Directories are conventionally named after the branch but with the repo name
    prepended and the ref type dropped, so `mentality-ment-210-form-cancel` and
    `feature/ment-210-form-cancel` differ at the front and agree at the back.
    A shared suffix is therefore the signal; containment is not.
    """
    left = _alphanumeric(worktree)
    right = _alphanumeric(branch)
    if not left or not right:
        return False
    if left in right or right in left:
        return True
    shared = _common_suffix_length(left, right)
    return shared >= max(MIN_SHARED_SUFFIX, min(len(left), len(right)) // 2)


def _common_suffix_length(left: str, right: str) -> int:
    length = 0
    for first, second in zip(reversed(left), reversed(right)):
        if first != second:
            break
        length += 1
    return length


def _alphanumeric(text: str) -> str:
    return "".join(character for character in text.lower() if character.isalnum())


def _find_git_path(start: Path) -> Path | None:
    for directory in (start, *start.parents):
        candidate = directory / ".git"
        if candidate.exists():
            return candidate
    return None


def _worktree_name(git_path: Path) -> str | None:
    """The linked-worktree name, or None in the main working tree."""
    if git_path.is_dir():
        return None
    try:
        content = git_path.read_text().strip()
    except OSError:
        return None
    if not content.startswith("gitdir:"):
        return None
    gitdir = Path(content.split(":", 1)[1].strip())
    return gitdir.name if gitdir.parent.name == "worktrees" else None


def _head_branch(git_path: Path) -> str | None:
    head = _resolve_head_file(git_path)
    if head is None:
        return None
    try:
        content = head.read_text().strip()
    except OSError:
        return None
    if content.startswith("ref:"):
        ref = content.split(":", 1)[1].strip()
        # Keep the full branch name: `refs/heads/feature/x` is the branch
        # `feature/x`, and taking only the last segment loses the prefix that
        # distinguishes feature/x from fix/x.
        for prefix in ("refs/heads/", "refs/remotes/"):
            if ref.startswith(prefix):
                return ref[len(prefix) :] or None
        return ref or None
    return content[:7] or None


def _resolve_head_file(git_path: Path) -> Path | None:
    if git_path.is_dir():
        return git_path / "HEAD"
    try:
        content = git_path.read_text().strip()
    except OSError:
        return None
    if not content.startswith("gitdir:"):
        return None
    return Path(content.split(":", 1)[1].strip()) / "HEAD"


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
