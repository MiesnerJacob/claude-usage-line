"""Read subscription usage from Claude's OAuth usage endpoint.

The endpoint requires a `claude-code/<version>` User-Agent. Without it, requests
land in an aggressively throttled bucket and return persistent 429s, so the
header is treated as mandatory rather than cosmetic.

Response field names have shifted between Claude Code releases, so the parser
discovers whichever spelling is present instead of hard-coding one shape. Use
`fetch_raw` (exposed as `--probe`) to inspect the live payload.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from typing import Any

from .model import Severity, UsageSnapshot, UsageWindow
from .transport import HttpError, TransportError, get_bytes

USAGE_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
FALLBACK_CLAUDE_VERSION = "2.0.0"
VERSION_TIMEOUT_SECONDS = 5.0

# Only the two universal windows are named; any other key the endpoint grows is
# humanised from the key itself so new limit types appear without a code change.
LEGACY_WINDOW_LABELS: dict[str, str] = {
    "five_hour": "Current Session",
    "seven_day": "Week (all)",
}
LEGACY_PRIMARY_KEYS = ("five_hour", "seven_day")
DURATION_PREFIXES: dict[str, str] = {
    "five_hour": "Session",
    "seven_day": "Week",
    "weekly": "Week",
    "monthly": "Month",
    "daily": "Day",
}

KIND_LABELS: dict[str, str] = {
    "session": "Current Session",
    "weekly_all": "Week (all)",
    "weekly_scoped": "Week",
}
PRIMARY_KINDS = ("session", "weekly_all")

SERVER_SEVERITIES: dict[str, Severity] = {
    "normal": Severity.NOMINAL,
    "warning": Severity.ELEVATED,
    "elevated": Severity.ELEVATED,
    "critical": Severity.CRITICAL,
    "exceeded": Severity.CRITICAL,
}

_UTILIZATION_KEYS = ("percent", "utilization", "used_percentage", "usedPercentage")
_RESET_KEYS = ("resets_at", "reset_at", "resetsAt", "resetAt")


class UsageUnavailable(RuntimeError):
    """Raised when usage cannot be retrieved or understood."""


class UsageClient:
    """Fetches and parses the subscription usage endpoint."""

    def __init__(
        self,
        access_token: str,
        include_scoped: bool = False,
        user_agent: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._access_token = access_token
        self._include_scoped = include_scoped
        self._user_agent = user_agent or default_user_agent()
        self._timeout = timeout

    def fetch(self, now: float) -> UsageSnapshot:
        """Retrieve current usage and parse it into a snapshot."""
        return parse_snapshot(self.fetch_raw(), now, self._include_scoped)

    def fetch_raw(self) -> dict[str, Any]:
        """Retrieve the raw decoded JSON payload, for schema inspection."""
        try:
            raw = get_bytes(USAGE_ENDPOINT, self._headers(), self._timeout)
        except HttpError as error:
            raise UsageUnavailable(_describe_status(error.status)) from error
        except TransportError as error:
            raise UsageUnavailable(str(error)) from error
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            raise UsageUnavailable("endpoint returned malformed JSON") from error
        if not isinstance(payload, dict):
            raise UsageUnavailable("endpoint returned an unexpected shape")
        return payload

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "User-Agent": self._user_agent,
            "Accept": "application/json",
        }


def default_user_agent() -> str:
    """Build the required User-Agent, detecting the installed Claude Code."""
    return f"claude-code/{_detect_claude_code_version()}"


def parse_snapshot(
    payload: dict[str, Any],
    now: float,
    include_scoped: bool = False,
) -> UsageSnapshot:
    """Convert a raw usage payload into a UsageSnapshot.

    The `limits` array is preferred: it carries kind, severity, and scope as
    data, so new limit types appear without a client change. The flat
    `five_hour`/`seven_day` keys are a legacy fallback for older responses.

    Windows absent from the payload are skipped rather than defaulted, so a
    partial response degrades to a shorter line instead of showing a false 0%.
    """
    windows = _parse_limits(payload.get("limits"), include_scoped)
    if not windows:
        windows = _parse_legacy_windows(payload, include_scoped)
    if not windows:
        raise UsageUnavailable("no recognisable usage windows in response")
    return UsageSnapshot(windows=tuple(windows), captured_at=now)


def _parse_limits(raw: Any, include_scoped: bool) -> list[UsageWindow]:
    if not isinstance(raw, list):
        return []
    windows = []
    for entry in raw:
        window = _parse_limit_entry(entry, include_scoped)
        if window is not None:
            windows.append(window)
    return windows


def _parse_limit_entry(entry: Any, include_scoped: bool) -> UsageWindow | None:
    if not isinstance(entry, dict):
        return None
    kind = entry.get("kind")
    if not isinstance(kind, str) or not kind:
        return None
    if kind not in PRIMARY_KINDS and not include_scoped:
        return None
    percentage = _first_number(entry, _UTILIZATION_KEYS)
    if percentage is None:
        return None
    return UsageWindow(
        label=_limit_label(entry, kind),
        used_percentage=percentage,
        resets_at=_parse_reset(entry),
        reported_severity=_reported_severity(entry),
    )


def _limit_label(entry: dict[str, Any], kind: str) -> str:
    """Label for a limit, naming the model when the limit is model-scoped.

    Known kinds get wording that mirrors Claude Code's own `/usage` screen, so
    the two can be read against each other. Unknown kinds are humanised from the
    kind string rather than dropped: the endpoint already lists unreleased limit
    types (`seven_day_cowork`, `nimbus_quill`), and a limit that exists but is
    not displayed is worse than one with an awkward name.
    """
    base = KIND_LABELS.get(kind) or humanize_kind(kind)
    name = _scoped_model_name(entry)
    return f"{base} ({name})" if name else base


def _scoped_model_name(entry: dict[str, Any]) -> str | None:
    scope = entry.get("scope")
    if not isinstance(scope, dict):
        return None
    model = scope.get("model")
    if not isinstance(model, dict):
        return None
    name = model.get("display_name")
    return name if isinstance(name, str) and name else None


def humanize_kind(kind: str) -> str:
    """Turn an unfamiliar kind or key into a readable label.

    `weekly_opus` becomes `Weekly Opus`; the duration prefixes the endpoint uses
    for legacy keys are normalised so `seven_day_cowork` reads as `Week Cowork`.
    """
    text = kind.replace("-", "_")
    for prefix, replacement in DURATION_PREFIXES.items():
        if text == prefix:
            return replacement
        if text.startswith(f"{prefix}_"):
            remainder = text[len(prefix) + 1 :].replace("_", " ").title()
            return f"{replacement} ({remainder})"
    return text.replace("_", " ").title()


def _reported_severity(entry: dict[str, Any]) -> Severity | None:
    severity = entry.get("severity")
    if not isinstance(severity, str):
        return None
    return SERVER_SEVERITIES.get(severity.lower())


def _parse_legacy_windows(
    payload: dict[str, Any], include_scoped: bool = True
) -> list[UsageWindow]:
    """Parse the flat per-window keys, discovering unfamiliar ones.

    Keys are not enumerated from a fixed list: whatever carries a utilization
    number is treated as a window, so a limit type added upstream shows up.
    """
    container = _locate_windows(payload)
    windows = []
    for key in sorted(container, key=_legacy_key_order):
        if key not in LEGACY_PRIMARY_KEYS and not include_scoped:
            continue
        label = LEGACY_WINDOW_LABELS.get(key) or humanize_kind(key)
        window = _parse_window(container.get(key), label)
        if window is not None:
            windows.append(window)
    return windows


def _legacy_key_order(key: str) -> tuple[int, str]:
    """Sort the universal windows first, then everything else by name."""
    return (
        LEGACY_PRIMARY_KEYS.index(key) if key in LEGACY_PRIMARY_KEYS else len(LEGACY_PRIMARY_KEYS),
        key,
    )


def _locate_windows(payload: dict[str, Any]) -> dict[str, Any]:
    if any(key in payload for key in LEGACY_PRIMARY_KEYS):
        return payload
    for value in payload.values():
        if isinstance(value, dict) and any(
            key in value for key in LEGACY_PRIMARY_KEYS
        ):
            return value
    return payload


def _parse_window(raw: Any, label: str) -> UsageWindow | None:
    if not isinstance(raw, dict):
        return None
    utilization = _first_number(raw, _UTILIZATION_KEYS)
    if utilization is None:
        return None
    return UsageWindow(
        label=label,
        used_percentage=utilization,
        resets_at=_parse_reset(raw),
    )


def _first_number(raw: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _parse_reset(raw: dict[str, Any]) -> int | None:
    for key in _RESET_KEYS:
        value = raw.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            parsed = _parse_timestamp(value)
            if parsed is not None:
                return parsed
    return None


def _parse_timestamp(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return int(moment.timestamp())


def _describe_status(status: int) -> str:
    if status == 401:
        return "token rejected (401) — run `claude` to re-authenticate"
    if status == 403:
        return "access forbidden (403) — subscription usage may be unavailable"
    if status == 429:
        return "rate limited (429) — backing off"
    return f"endpoint returned HTTP {status}"


def _detect_claude_code_version() -> str:
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=VERSION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return FALLBACK_CLAUDE_VERSION
    if result.returncode != 0:
        return FALLBACK_CLAUDE_VERSION
    for token in result.stdout.split():
        if token and token[0].isdigit():
            return token
    return FALLBACK_CLAUDE_VERSION
