"""Publish the usage readout into herdr's sidebar as named metadata tokens.

herdr 0.7.5 added `report-metadata --token NAME=VALUE` on both panes and
workspaces, and renders arbitrary named tokens wherever the user's sidebar row
config references them as `$name`. That lets the readout live in the left pane
without occupying a pane of its own.

Tokens are published with a TTL. If this reporter dies, herdr expires the row on
its own rather than leaving a frozen number on screen.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from .model import UsageSnapshot
from .render import COMPACT_WIDTH, render_compact, render_summary

MIN_TOKEN_VERSION = (0, 7, 5)
SOURCE_ID = "usage"
SUMMARY_TOKEN = "usage"
COMMAND_TIMEOUT_SECONDS = 10.0

TOKEN_PREFIX = "usage"


class ReporterError(RuntimeError):
    """Raised when the sidebar cannot be updated."""


@dataclass(frozen=True)
class ReporterTarget:
    """Which herdr entity carries the tokens.

    `workspace` puts the row in the spaces section (upper sidebar) and appears
    exactly once. `pane` puts it in the agent panel (lower sidebar, so
    bottom-left) attached to a single agent entry.
    """

    kind: str
    entity_id: str

    @property
    def command(self) -> str:
        return "workspace" if self.kind == "workspace" else "pane"


class SidebarReporter:
    """Pushes usage tokens onto a herdr entity for the sidebar to render."""

    def __init__(
        self,
        target: ReporterTarget,
        herdr_binary: str = "herdr",
        ttl_ms: int = 90_000,
        token_width: int = COMPACT_WIDTH,
    ) -> None:
        self._target = target
        self._herdr = herdr_binary
        self._ttl_ms = ttl_ms
        self._token_width = token_width
        self._published: set[str] = set()

    @property
    def target(self) -> ReporterTarget:
        """The entity currently carrying the tokens."""
        return self._target

    def retarget(self, target: ReporterTarget) -> None:
        """Move to a new entity, clearing tokens off the old one first."""
        if target == self._target:
            return
        try:
            self.clear()
        except ReporterError:
            pass
        self._target = target
        self._published.clear()

    def publish(self, snapshot: UsageSnapshot) -> None:
        """Push one token per window, plus a combined summary token."""
        tokens = self._tokens(snapshot)
        self._published.update(tokens)
        self._run(self._publish_args(tokens))

    def clear(self) -> None:
        """Remove every token this reporter has published."""
        names = {SUMMARY_TOKEN, *self._published}
        args = [self._target.entity_id, "--source", SOURCE_ID]
        for name in sorted(names):
            args.extend(["--clear-token", name])
        self._run(args)

    def _tokens(self, snapshot: UsageSnapshot) -> dict[str, str]:
        label_width = max((len(w.label) for w in snapshot.windows), default=0)
        tokens = {SUMMARY_TOKEN: render_summary(snapshot, self._token_width)}
        for window in snapshot.windows:
            tokens[token_name(window.label)] = render_compact(
                window, self._token_width, label_width
            )
        return tokens

    def _publish_args(self, tokens: dict[str, str]) -> list[str]:
        args = [
            self._target.entity_id,
            "--source",
            SOURCE_ID,
            "--ttl-ms",
            str(self._ttl_ms),
        ]
        for name, value in tokens.items():
            args.extend(["--token", f"{name}={value}"])
        return args

    def _run(self, args: list[str]) -> None:
        command = [self._herdr, self._target.command, "report-metadata", *args]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ReporterError(f"could not run herdr: {error}") from error
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise ReporterError(detail or "herdr rejected the metadata update")


def token_name(label: str) -> str:
    """Token name for a window label, e.g. `7d Fable` -> `usage_7d_fable`.

    Derived from the label rather than a fixed table so scoped per-model limits
    get tokens automatically as Anthropic adds them.
    """
    slug = "".join(
        character if character.isalnum() else "_" for character in label.lower()
    )
    while "__" in slug:
        slug = slug.replace("__", "_")
    return f"{TOKEN_PREFIX}_{slug.strip('_')}"


def supports_tokens(herdr_binary: str = "herdr") -> bool:
    """Whether the installed herdr is new enough to render metadata tokens."""
    version = detect_herdr_version(herdr_binary)
    return version is not None and version >= MIN_TOKEN_VERSION


def detect_herdr_version(herdr_binary: str = "herdr") -> tuple[int, ...] | None:
    """Parse `herdr --version` into a comparable tuple."""
    try:
        result = subprocess.run(
            [herdr_binary, "--version"],
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return parse_version(result.stdout)


def parse_version(text: str) -> tuple[int, ...] | None:
    """Extract a dotted numeric version from arbitrary CLI output."""
    for token in text.split():
        parts = token.split(".")
        if len(parts) >= 2 and all(part.isdigit() for part in parts):
            return tuple(int(part) for part in parts)
    return None


def resolve_default_target(
    kind: str = "workspace", herdr_binary: str = "herdr"
) -> ReporterTarget:
    """Pick the entity to attach tokens to.

    `workspace` uses the focused workspace. `pane` uses the lowest pane id in
    that workspace, which is deliberately not the *focused* pane: the readout
    would otherwise hop between sidebar entries as you move around.
    """
    workspace_id = _focused_workspace_id(herdr_binary)
    if kind == "workspace":
        return ReporterTarget(kind="workspace", entity_id=workspace_id)
    return ReporterTarget(
        kind="pane", entity_id=_anchor_pane_id(herdr_binary, workspace_id)
    )


def _focused_workspace_id(herdr_binary: str) -> str:
    payload = _run_json([herdr_binary, "workspace", "list"])
    workspaces = payload.get("result", {}).get("workspaces", [])
    if not workspaces:
        raise ReporterError("no herdr workspaces found — is a session running?")
    focused = next((w for w in workspaces if w.get("focused")), workspaces[0])
    workspace_id = focused.get("workspace_id")
    if not workspace_id:
        raise ReporterError("herdr returned a workspace without an id")
    return workspace_id


def _anchor_pane_id(herdr_binary: str, workspace_id: str) -> str:
    """The last entry in the agent panel, so the rows render beneath the others.

    `herdr agent list` returns entries in the panel's own display order, which
    is what determines visual position; `pane list` order does not match it once
    grouping or attention sorting is in play. Falls back to pane order only if
    the agent panel is empty.
    """
    for pane_id in reversed(_agent_panel_pane_ids(herdr_binary, workspace_id)):
        return pane_id
    payload = _run_json([herdr_binary, "pane", "list"])
    panes = sorted(
        pane["pane_id"]
        for pane in payload.get("result", {}).get("panes", [])
        if pane.get("workspace_id") == workspace_id and pane.get("pane_id")
    )
    if not panes:
        raise ReporterError(f"no panes found in workspace {workspace_id}")
    return panes[-1]


def _agent_panel_pane_ids(herdr_binary: str, workspace_id: str) -> list[str]:
    payload = _run_json([herdr_binary, "agent", "list"])
    result = payload.get("result", {})
    for value in result.values():
        if not isinstance(value, list):
            continue
        return [
            entry["pane_id"]
            for entry in value
            if isinstance(entry, dict)
            and entry.get("pane_id")
            and entry.get("workspace_id") == workspace_id
        ]
    return []


def _run_json(command: list[str]) -> dict:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ReporterError(f"could not run herdr: {error}") from error
    if result.returncode != 0:
        raise ReporterError((result.stderr or "herdr command failed").strip())
    try:
        return json.loads(result.stdout)
    except ValueError as error:
        raise ReporterError("herdr returned malformed JSON") from error
