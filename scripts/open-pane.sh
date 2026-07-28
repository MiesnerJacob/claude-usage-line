#!/bin/sh
#
# Open the usage readout as a short split pinned along the bottom of the current
# tab. Used by both the `show` action and the startup hook, so reopening after a
# session restore takes the identical path as opening it by hand.
#
# Two behaviours are deliberate:
#
#   --no-focus  the pane is a passive readout, and stealing focus from an agent
#               pane on every session restore would be hostile.
#
#   the resize  herdr ignores `height` on [[panes]] and opens splits at ratio
#               0.5, which is enormous for a one-line readout. The ratio is
#               clamped to 0.9 by herdr, so this asks for more than it can get
#               and accepts the resulting floor of roughly four rows.

set -eu

HERDR="${HERDR_BIN_PATH:-herdr}"
PLUGIN="${HERDR_PLUGIN_ID:-miesnerjacob.usage-pane}"

opened=$("$HERDR" plugin pane open \
	--plugin "$PLUGIN" \
	--entrypoint usage \
	--placement split \
	--direction down \
	--no-focus)

pane_id=$(printf '%s' "$opened" | python3 -c '
import json, sys

try:
    payload = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
pane = payload.get("result", {}).get("plugin_pane", {}).get("pane", {})
print(pane.get("pane_id", ""))
')

if [ -n "$pane_id" ]; then
	python3 "$(dirname "$0")/fit-panel.py" "$pane_id" 2 >/dev/null 2>&1 || true
fi
