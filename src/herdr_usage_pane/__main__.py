"""Command-line entry point for the herdr usage readout."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Sequence

from . import __version__
from .app import PaneOptions, SidebarPublisher, UsagePane
from .client import UsageClient, UsageUnavailable
from .credentials import CredentialsError, resolve_access_token
from .poller import DEFAULT_POLL_INTERVAL, UsagePoller
from .render import COMPACT_WIDTH
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
    try:
        client = UsageClient(
            access_token=resolve_access_token(),
            include_scoped=args.all_windows,
        )
    except CredentialsError as error:
        return _fail(str(error))

    if args.probe:
        return _probe(client)

    poller = UsagePoller(client=client, poll_interval=args.interval)
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
        "--no-color",
        action="store_true",
        help="disable ANSI colour",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def _run_pane(poller: UsagePoller, args: argparse.Namespace) -> int:
    pane = UsagePane(
        poller=poller,
        options=PaneOptions(
            poll_interval=args.interval,
            color=_should_colorize(args.no_color),
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
    )
    return publisher.run_once() if args.once else publisher.run()


def _resolve_target(args: argparse.Namespace) -> ReporterTarget:
    if args.target_id:
        return ReporterTarget(kind=args.target, entity_id=args.target_id)
    if args.target == "pane":
        raise ReporterError("--target pane requires --target-id")
    return resolve_default_target()


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


def _should_colorize(no_color_flag: bool) -> bool:
    if no_color_flag or os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def _fail(message: str) -> int:
    sys.stderr.write(f"herdr-usage-pane: {message}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
