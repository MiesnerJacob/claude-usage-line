"""Command-line entry point for the herdr usage readout."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from typing import Sequence

from . import __version__

# U+2800 BRAILLE PATTERN BLANK: renders as empty space but is not whitespace, so
# a consumer that trims blank lines still treats the gap row as content.
GAP_ROW = "\u2800"
from .app import PaneOptions, SidebarPublisher, UsagePane
from .cache import read_snapshot, spawn_background_refresh
from .client import UsageClient, UsageUnavailable
from .credentials import CredentialsError, resolve_access_token
from .poller import DEFAULT_POLL_INTERVAL, UsagePoller
from .render import COMPACT_WIDTH, render_info_row, render_line
from .model import UsageSnapshot
from .statusline import (
    context_window_from_payload,
    git_label,
    info_segments,
    shorten_labels,
    merge_scoped,
    read_stdin_payload,
    snapshot_from_payload,
)
from .reporter import (
    MIN_TOKEN_VERSION,
    ReporterError,
    ReporterTarget,
    SidebarReporter,
    detect_herdr_version,
    resolve_default_target,
    supports_tokens,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, build the requested display mode, and run it."""
    args = _build_parser().parse_args(argv)
    if args.once and not args.report and not args.probe:
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
    if args.once:
        poller.prime_from_cache()
    if args.report:
        return _run_reporter(poller, args)
    return _run_pane(poller, args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="herdr-usage-pane",
        description="Condensed Claude Code usage-vs-limits readout.",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="publish into herdr's sidebar as metadata tokens instead of drawing a pane",
    )
    parser.add_argument(
        "--target",
        choices=("workspace", "pane"),
        default="workspace",
        help="which herdr entity carries the tokens (default: workspace)",
    )
    parser.add_argument(
        "--target-id",
        metavar="ID",
        help="explicit workspace or pane id; defaults to the focused workspace",
    )
    parser.add_argument(
        "--token-width",
        type=int,
        default=COMPACT_WIDTH,
        metavar="COLUMNS",
        help=f"width budget for sidebar tokens (default: {COMPACT_WIDTH})",
    )
    parser.add_argument(
        "--ttl-ms",
        type=int,
        default=90_000,
        metavar="MS",
        help="how long herdr keeps a token if this process dies (default: 90000)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="do one update and exit, for statuslines and scripts",
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
        "--branch",
        action="store_true",
        help="prefix the line with the git branch, or worktree:branch",
    )
    parser.add_argument(
        "--context",
        action="store_true",
        help="also show the session's context-window usage",
    )
    parser.add_argument(
        "--info-row",
        action="store_true",
        help="print a context row above the bars: branch, model, effort, lines",
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
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="shorthand for --color never",
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

    if args.context:
        context = context_window_from_payload(payload)
        if context is not None:
            snapshot = UsageSnapshot(
                windows=(context, *snapshot.windows),
                captured_at=snapshot.captured_at,
            )
    if args.short_labels:
        snapshot = shorten_labels(snapshot)
    width = shutil.get_terminal_size((80, 1)).columns
    color = _should_colorize(args)
    bars = render_line(
        snapshot,
        width=width,
        now=now,
        color=color,
        prefix=git_label(payload.get("cwd")) if args.branch else None,
    )
    if not args.info_row:
        return bars
    info = render_info_row(info_segments(payload), width, color)
    if not info:
        return bars
    rows = [bars, info] if args.info_position == "below" else [info, bars]
    gap = [GAP_ROW] * max(0, args.row_gap)
    return "\n".join([rows[0], *gap, rows[1]])


def _refresh_cache(client: UsageClient, args: argparse.Namespace) -> int:
    """Fetch once and persist to the cache. Nothing is printed."""
    poller = UsagePoller(client=client, poll_interval=args.interval)
    return 0 if poller.poll_if_due() else 1


def _run_pane(poller: UsagePoller, args: argparse.Namespace) -> int:
    pane = UsagePane(
        poller=poller,
        options=PaneOptions(
            poll_interval=args.interval,
            color=_should_colorize(args),
        ),
        stream=sys.stdout,
    )
    return pane.run_once() if args.once else pane.run()


def _run_reporter(poller: UsagePoller, args: argparse.Namespace) -> int:
    if not supports_tokens():
        return _fail(_version_hint())
    try:
        target = _resolve_target(args)
    except ReporterError as error:
        return _fail(str(error))

    publisher = SidebarPublisher(
        poller=poller,
        reporter=SidebarReporter(
            target=target,
            ttl_ms=args.ttl_ms,
            token_width=args.token_width,
        ),
        publish_interval=args.interval,
        on_error=lambda message: _fail(message),
        resolve_target=None if args.target_id else lambda: _resolve_target(args),
    )
    return publisher.run_once() if args.once else publisher.run()


def _resolve_target(args: argparse.Namespace) -> ReporterTarget:
    if args.target_id:
        return ReporterTarget(kind=args.target, entity_id=args.target_id)
    return resolve_default_target(args.target)


def _version_hint() -> str:
    found = detect_herdr_version()
    required = ".".join(str(part) for part in MIN_TOKEN_VERSION)
    current = ".".join(str(part) for part in found) if found else "unknown"
    return (
        f"sidebar tokens need herdr {required}+ (found {current}); "
        "run `herdr update`, or use the pane or --once statusline mode"
    )


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
    if args.no_color or args.color == "never" or os.environ.get("NO_COLOR"):
        return False
    if args.color == "always":
        return True
    return sys.stdout.isatty()


def _fail(message: str) -> int:
    sys.stderr.write(f"herdr-usage-pane: {message}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
