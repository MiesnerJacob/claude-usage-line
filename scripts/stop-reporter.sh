#!/bin/sh
#
# Stop the background reporter and clear its sidebar tokens.
#
# The reporter clears its own tokens on SIGTERM, but the explicit clear covers
# the case where it was killed less politely and the TTL has not yet expired.

set -eu

ROOT="${HERDR_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
STATE="${HERDR_PLUGIN_STATE_DIR:-${TMPDIR:-/tmp}/herdr-usage-pane}"
PIDFILE="$STATE/reporter.pid"

if [ -f "$PIDFILE" ]; then
	pid=$(cat "$PIDFILE" 2>/dev/null || true)
	if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
		kill "$pid" 2>/dev/null || true
	fi
	rm -f "$PIDFILE"
fi
