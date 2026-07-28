#!/bin/sh
#
# Start the usage readout in the best form the installed herdr supports.
#
# herdr 0.7.5+ renders named metadata tokens in the sidebar, which costs no
# rows, so that is preferred. Older herdr gets the bottom split pane instead.
# `--report --once` is the capability probe: it succeeds only when the binary is
# new enough and the credentials work, and publishing one update is harmless.
#
# Any reporter left over from a previous session restore is stopped first, so
# repeated startup hooks do not stack up background pollers.

set -eu

HERDR="${HERDR_BIN_PATH:-herdr}"
ROOT="${HERDR_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
STATE="${HERDR_PLUGIN_STATE_DIR:-${TMPDIR:-/tmp}/herdr-usage-pane}"
READOUT="$ROOT/bin/herdr-usage-pane"
PIDFILE="$STATE/reporter.pid"

mkdir -p "$STATE"

if [ -f "$PIDFILE" ]; then
	previous=$(cat "$PIDFILE" 2>/dev/null || true)
	if [ -n "$previous" ] && kill -0 "$previous" 2>/dev/null; then
		kill "$previous" 2>/dev/null || true
	fi
	rm -f "$PIDFILE"
fi

# Which sidebar section renders the tokens must match where they are published:
# `pane` feeds [ui.sidebar.agents], `workspace` feeds [ui.sidebar.spaces].
TARGET="${HERDR_USAGE_TARGET:-pane}"

if "$READOUT" --report --once --all-windows --target "$TARGET" >/dev/null 2>&1; then
	nohup "$READOUT" --report --all-windows --target "$TARGET" >>"$STATE/reporter.log" 2>&1 &
	echo $! >"$PIDFILE"
	exit 0
fi

exec sh "$ROOT/scripts/open-pane.sh"
