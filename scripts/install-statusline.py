"""Add or update this readout as Claude Code's status line.

A plugin cannot set `statusLine` itself -- plugin `settings.json` supports only
the `agent` and `subagentStatusLine` keys -- so the entry has to be written into
the user's own settings. This resolves the readout's absolute path from its own
location, which is what makes the plugin installable anywhere.

Idempotent: rerunning updates the command in place. The previous value is kept in
`_statusLineReplacedByClaudeUsageLine` on first write so nothing is lost.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

DEFAULT_FLAGS = [
    "--once",
    "--all-windows",
    "--context",
    "count",
    "--short-labels",
    "--info-row",
    "--color",
    "always",
]
BACKUP_KEY = "_statusLineReplacedByClaudeUsageLine"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    launcher = _launcher_path()
    if launcher is None:
        print("cannot locate the readout launcher", file=sys.stderr)
        return 1

    settings_path = Path(args.settings).expanduser()
    settings = _load(settings_path)
    if settings is None:
        print(f"{settings_path} is not valid JSON; refusing to overwrite", file=sys.stderr)
        return 1

    command = " ".join([str(launcher), *DEFAULT_FLAGS, *args.extra])
    existing = settings.get("statusLine")
    if isinstance(existing, dict) and existing.get("command") == command:
        print("status line already configured")
        return 0
    if isinstance(existing, dict) and BACKUP_KEY not in settings:
        previous = existing.get("command")
        if isinstance(previous, str) and previous:
            settings[BACKUP_KEY] = previous

    if args.dry_run:
        print(f"would set statusLine.command to:\n  {command}")
        return 0

    settings["statusLine"] = {"type": "command", "command": command, "padding": 0}
    _save(settings_path, settings)
    print(f"status line set in {settings_path}\n  {command}")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="install-statusline.py",
        description="Write this readout into Claude Code's statusLine setting.",
    )
    parser.add_argument(
        "--settings",
        default="~/.claude/settings.json",
        help="settings file to modify (default: ~/.claude/settings.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the command that would be set and exit",
    )
    parser.add_argument(
        "extra",
        nargs="*",
        help="additional flags to append, e.g. --branch-source cwd",
    )
    return parser.parse_args(argv)


def _launcher_path() -> Path | None:
    """The readout launcher, preferring the plugin root when installed."""
    candidates = []
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if root:
        candidates.append(Path(root) / "bin" / "herdr-usage-pane")
    candidates.append(Path(__file__).resolve().parents[1] / "bin" / "herdr-usage-pane")
    found = shutil.which("herdr-usage-pane")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def _load(path: Path) -> dict | None:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _save(path: Path, settings: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(main())
