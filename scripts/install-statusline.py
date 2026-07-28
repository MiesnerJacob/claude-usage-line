from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

DEFAULT_FLAGS = [
    "--all-windows",
    "--context",
    "count",
    "--short-labels",
    "--info-row",
    "--color",
    "always",
]
BACKUP_KEY = "_statusLineReplacedByClaudeUsageLine"
LAUNCHER_NAME = "claude-usage-line"


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
        if not args.auto:
            print("status line already configured")
        return 0
    if args.auto and not _is_ours(existing):
        # Someone else's status line, or one the user hand-wrote. Leave it.
        return 0
    if isinstance(existing, dict) and BACKUP_KEY not in settings:
        previous = existing.get("command")
        if isinstance(previous, str) and previous:
            settings[BACKUP_KEY] = previous

    if args.auto and isinstance(existing, dict):
        # Refreshing our own entry, most likely a path from an older plugin
        # version. Do not record it as a "previous" command worth restoring.
        settings.pop(BACKUP_KEY, None)

    if args.dry_run:
        print(f"would set statusLine.command to:\n  {command}")
        return 0

    settings["statusLine"] = {"type": "command", "command": command, "padding": 0}
    _save(settings_path, settings)
    if not args.auto:
        print(f"status line set in {settings_path}\n  {command}")
    return 0


def _is_ours(existing: object) -> bool:
    """Whether an existing statusLine entry is one we wrote.

    The plugin cache is versioned, so our own command from an older version
    carries a stale path. Matching on the launcher name lets the hook repoint it
    after an update while never touching a status line somebody else set up.
    """
    if existing is None:
        return True
    if not isinstance(existing, dict):
        return False
    command = existing.get("command")
    return isinstance(command, str) and LAUNCHER_NAME in command


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
        "--auto",
        action="store_true",
        help="used by the SessionStart hook: adopt or refresh only our own entry",
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
        candidates.append(Path(root) / "bin" / "claude-usage-line")
    candidates.append(Path(__file__).resolve().parents[1] / "bin" / "claude-usage-line")
    found = shutil.which("claude-usage-line")
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
