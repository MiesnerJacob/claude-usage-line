from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Sequence

from . import __version__

# U+2800 BRAILLE PATTERN BLANK: renders as empty space but is not whitespace, so
# a consumer that trims blank lines still treats the gap row as content.
GAP_ROW = "\u2800"
from .app import LineOptions, UsageLine, terminal_width
from .cache import read_snapshot, spawn_background_refresh
from .client import UsageClient, UsageUnavailable
from .credentials import CredentialsError, resolve_access_token
from .poller import DEFAULT_POLL_INTERVAL, UsagePoller
from .render import render_info_row, render_line
from .model import UsageSnapshot
from .statusline import (
    context_window_from_payload,
    context_segment,
    info_segments,
    shorten_labels,
    merge_scoped,
    read_stdin_payload,
    snapshot_from_payload,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, build the requested display mode, and run it."""
    args = _build_parser().parse_args(argv)
    if not args.probe and not args.refresh_cache:
        cached = _render_cached(args)
        if cached is not None:
            sys.stdout.write(cached + "\n")
            return 0
    try:
        client = UsageClient(
            access_token=resolve_access_token(),
            include_scoped=args.all_windows,
        )
    except CredentialsError as error:
        return _fail(str(error))

    if args.probe:
        return _probe(client)

    if args.refresh_cache:
        return _refresh_cache(client, args)

    poller = UsagePoller(client=client, poll_interval=args.interval)
    return _run_line(poller, args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-usage-line",
        description="Condensed Claude Code usage-vs-limits readout.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="accepted for compatibility; rendering one line and exiting is the only mode",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="dump the raw usage endpoint payload and exit",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        metavar="SECONDS",
        help=f"seconds between polls (default: {DEFAULT_POLL_INTERVAL:.0f})",
    )
    parser.add_argument(
        "--all-windows",
        action="store_true",
        help="also show per-model scoped weekly limits",
    )
    parser.add_argument(
        "--context",
        choices=("off", "bar", "count"),
        default="off",
        help=(
            "context-window display: bar puts it beside the limits, count puts "
            "a token figure in the info row"
        ),
    )
    parser.add_argument(
        "--info-row",
        action="store_true",
        help="print a context row above the bars: branch, model, effort, lines",
    )
    parser.add_argument(
        "--branch-source",
        choices=("activity", "cwd"),
        default="activity",
        help=(
            "activity labels the branch from the files this session edited; "
            "cwd labels it from the last command's directory"
        ),
    )
    parser.add_argument(
        "--info-position",
        choices=("above", "below"),
        default="above",
        help="whether the info row sits above or below the bars",
    )
    parser.add_argument(
        "--row-gap",
        type=int,
        default=0,
        metavar="N",
        help="blank rows between the info row and the bars (statusline only)",
    )
    parser.add_argument(
        "--short-labels",
        action="store_true",
        help="abbreviate window labels so a one-line readout keeps its bars",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="fetch and cache a snapshot, then exit (used in the background)",
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help=(
            "auto colours only on a terminal; always is for consumers that "
            "render ANSI but are not a tty, such as a statusline"
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def _render_cached(args: argparse.Namespace) -> str | None:
    """Render without credentials, HTTP, or subprocesses when possible.

    Two free sources, in order: the `rate_limits` Claude Code puts in the
    statusline payload on stdin, which is always current; then the on-disk cache
    from a previous fetch. A statusline redraws constantly, so this path must
    avoid the Keychain lookup and the `claude --version` subprocess.
    """
    now = time.time()
    cached = read_snapshot(now, args.interval)
    payload = read_stdin_payload() or {}
    snapshot = snapshot_from_payload(payload, now) if payload else None

    if snapshot is None:
        snapshot = cached
    elif args.all_windows:
        snapshot = merge_scoped(snapshot, cached)
        if cached is None:
            spawn_background_refresh(args.interval)
    if snapshot is None:
        return None

    if args.context == "bar":
        context = context_window_from_payload(payload)
        if context is not None:
            snapshot = UsageSnapshot(
                windows=(context, *snapshot.windows),
                captured_at=snapshot.captured_at,
            )
    if args.short_labels:
        snapshot = shorten_labels(snapshot)
    width = terminal_width()
    color = _should_colorize(args)
    bars = render_line(
        snapshot,
        width=width,
        now=now,
        color=color,
    )
    if not args.info_row:
        return bars
    segments = info_segments(payload, args.branch_source)
    if args.context == "count":
        counted = context_segment(payload)
        if counted is not None:
            segments.append(counted)
    info = render_info_row(segments, width, color)
    if not info:
        return bars
    rows = [bars, info] if args.info_position == "below" else [info, bars]
    gap = [GAP_ROW] * max(0, args.row_gap)
    return "\n".join([rows[0], *gap, rows[1]])


def _refresh_cache(client: UsageClient, args: argparse.Namespace) -> int:
    """Fetch once and persist to the cache. Nothing is printed."""
    poller = UsagePoller(client=client, poll_interval=args.interval)
    return 0 if poller.poll_if_due() else 1


def _run_line(poller: UsagePoller, args: argparse.Namespace) -> int:
    line = UsageLine(
        poller=poller,
        options=LineOptions(color=_should_colorize(args)),
        stream=sys.stdout,
    )
    return line.run_once()


def _probe(client: UsageClient) -> int:
    try:
        payload = client.fetch_raw()
    except UsageUnavailable as error:
        return _fail(str(error))
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def _should_colorize(args: argparse.Namespace) -> bool:
    """Whether to emit ANSI.

    A statusline receives stdout on a pipe, so `isatty` is false even though it
    renders colour; `--color always` exists for exactly that case. NO_COLOR
    always wins, per the convention.
    """
    if args.color == "never" or os.environ.get("NO_COLOR"):
        return False
    if args.color == "always":
        return True
    return sys.stdout.isatty()


def _fail(message: str) -> int:
    sys.stderr.write(f"claude-usage-line: {message}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
