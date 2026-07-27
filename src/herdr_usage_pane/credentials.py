"""Locate the Claude Code OAuth access token already stored on this machine.

The plugin never authenticates on its own behalf. It reuses the token Claude
Code wrote when the user logged in, reading the same three locations Claude Code
itself supports. The file is tried before the Keychain so that the common case
does not raise an interactive Keychain prompt.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

TOKEN_ENV_VAR = "CLAUDE_CODE_OAUTH_TOKEN"
KEYCHAIN_SERVICE = "Claude Code-credentials"
CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"
KEYCHAIN_TIMEOUT_SECONDS = 5.0


class CredentialsError(RuntimeError):
    """Raised when no usable access token can be found."""


def resolve_access_token() -> str:
    """Return the first access token found, preferring the cheapest source.

    Raises CredentialsError with remediation guidance when every source fails.
    """
    for source in (_from_env, _from_credentials_file, _from_keychain):
        token = source()
        if token:
            return token
    raise CredentialsError(
        "No Claude Code OAuth token found. Log in with `claude` first, "
        f"or export {TOKEN_ENV_VAR}."
    )


def _from_env() -> str | None:
    return os.environ.get(TOKEN_ENV_VAR) or None


def _from_credentials_file() -> str | None:
    try:
        payload = json.loads(CREDENTIALS_FILE.read_text())
    except (OSError, ValueError):
        return None
    return _find_access_token(payload)


def _from_keychain() -> str | None:
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            text=True,
            timeout=KEYCHAIN_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    try:
        return _find_access_token(json.loads(raw))
    except ValueError:
        return raw


def _find_access_token(payload: Any) -> str | None:
    """Recursively search a decoded credentials blob for an access token.

    Claude Code has nested this value under different wrapper keys across
    versions, so the shape is discovered rather than assumed.
    """
    if isinstance(payload, dict):
        for key in ("accessToken", "access_token"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        for value in payload.values():
            found = _find_access_token(value)
            if found:
                return found
    return None
