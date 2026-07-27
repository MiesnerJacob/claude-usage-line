"""Command-line entry point for the herdr usage pane."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Sequence

from . import __version__
from .app import DEFAULT_POLL_INTERVAL, PaneOptions, UsagePane
from .client import UsageClient, UsageUnavailable
from .credentials import CredentialsError, resolve_access_token


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, build the pane, and run the requested mode."""
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

    pane = UsagePane(
        client=client,
        options=PaneOptions(
            poll_interval=args.interval,
            color=_should_colorize(args.no_color),
        ),
        stream=sys.stdout,
    )
    return pane.run_once() if args.once else pane.run()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="herdr-usage-pane",
        description="Condensed Claude Code usage-vs-limits readout.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="print one line and exit, for statuslines and scripts",
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
