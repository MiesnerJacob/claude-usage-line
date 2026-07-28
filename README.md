# Claude Usage Pane

A condensed Claude Code usage-vs-limits readout for [herdr](https://github.com/ogulcancelik/herdr).

```
5h ████░░░░░░░░  35% 3h05m │ 7d ████░░░░░░░░  32% 2d20h
```

Each window shows how much of the cap is consumed, as a bar and a percentage,
with a countdown to the next reset. Colour tracks severity, using the grading
the server itself reports rather than locally guessed thresholds.

## Display modes

The readout can live in three places, and the `[[startup]]` hook picks the best
one the installed herdr supports.

**Sidebar (herdr 0.7.5+, preferred).** herdr renders named metadata tokens
wherever your sidebar row config references them, so the readout sits in the
left pane and costs no rows. Requires `report-metadata --token`, added in 0.7.5.

**Split pane (herdr 0.7.0+).** A short split pinned along the bottom of the tab.
Works on older herdr, but see the row floor under Known limitations.

**Claude Code statusline (any herdr, or none).** `--once` prints one line and
exits, putting the readout inside every Claude Code pane in every tab.

Plugins cannot draw the sidebar chrome directly — the extension points are
`[[build]]`, `[[startup]]`, `[[actions]]`, `[[events]]`, `[[panes]]`, and
`[[link_handlers]]`. The sidebar mode works by *pushing data* that the user's own
row config renders, which is why it needs no upstream change.

## Install

Requires herdr 0.7.0+ and Python 3.10+. No build step and no dependencies —
the plugin is pure standard library.

```sh
herdr plugin install <owner>/herdr-usage-pane
```

For local development, from a checkout:

```sh
herdr plugin link .
```

You must already be logged in to Claude Code (`claude`). The plugin reuses the
OAuth token Claude Code stored; it never starts its own login flow.

## Setting up the sidebar mode

Start the background reporter — the `Claude Usage: show in sidebar` action, the
`[[startup]]` hook, or by hand:

```sh
herdr-usage-pane --report
```

It publishes three tokens, so your config chooses the layout:

| Token | Example |
| --- | --- |
| `$usage` | `5h 35% · 7d 32%` |
| `$usage_5h` | `5h ████░░░░ 35%` |
| `$usage_7d` | `7d ███░░░░░ 32%` |

Reference them in your sidebar rows in `~/.config/herdr/config.toml`. Rows whose
tokens are all absent are dropped, so the readout appears only on the entry that
carries the tokens:

```toml
[ui.sidebar.agents]
rows = [["state_icon", "workspace", "tab"], ["agent"], ["$usage"]]
```

Then `herdr server reload-config`.

Placement is your choice. `[ui.sidebar.agents]` is the lower sidebar section, so
a row there lands bottom-left; `[ui.sidebar.spaces]` is the upper section. By
default the reporter attaches tokens to the focused *workspace*, which appears
exactly once; use `--target pane --target-id <pane>` to attach to a single agent
entry instead.

Tokens carry a TTL (default 90s). If the reporter dies, herdr drops the row
rather than leaving a stale number on screen.

## Setting up the statusline mode

`--once` prints a single line and exits, which gets the readout inside *every*
Claude Code pane in every tab, consuming no rows. Add to
`~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/plugins/miesnerjacob.usage-pane/bin/herdr-usage-pane --once"
  }
}
```

The two modes complement each other: the statusline covers Claude panes, the
herdr pane covers tabs running something else.

## Options

| Flag | Effect |
| --- | --- |
| `--report` | Publish to herdr's sidebar instead of drawing a pane (0.7.5+) |
| `--target` | `workspace` (default) or `pane` — which entity carries the tokens |
| `--target-id ID` | Explicit workspace or pane id; defaults to the focused workspace |
| `--token-width N` | Column budget for sidebar tokens (default 18) |
| `--ttl-ms N` | How long herdr keeps a token if the reporter dies (default 90000) |
| `--once` | Do one update and exit, for statuslines and scripts |
| `--all-windows` | Also show per-model scoped weekly limits (e.g. `7d Fable`) |
| `--interval SECONDS` | Seconds between polls (default 60) |
| `--no-color` | Disable ANSI colour; `NO_COLOR` is also honoured |
| `--probe` | Dump the raw endpoint payload, for debugging schema drift |

## How it gets the data

`GET https://api.anthropic.com/api/oauth/usage`, authorised with the local OAuth
token and sent with a `claude-code/<version>` User-Agent. That header matters:
without it the request lands in an aggressively throttled bucket and returns
persistent 429s.

The response's `limits` array is the preferred source, because it carries `kind`,
`percent`, `severity`, and `scope` as data — new limit types show up without a
client change. The flat `five_hour` / `seven_day` keys are parsed as a fallback
for older responses.

Polling and repainting run on separate cadences: the endpoint is polled once a
minute, while the line repaints every second so reset countdowns tick without
extra requests. Failures back off from 30s to a 5-minute ceiling, and the last
good reading is kept on screen and marked `(stale)` rather than blanking.

The token is read from the environment, then `~/.claude/.credentials.json`, then
the macOS Keychain. It is sent only to `api.anthropic.com` and is never written
to disk or passed on a command line.

## Known limitations

- **Split-pane row floor.** herdr ignores `height` on `[[panes]]` and clamps
  split ratios to 0.9, so the pane cannot be shrunk below roughly four rows even
  though it draws one line. The sidebar mode has no such cost.
- **Split panes are per-tab.** A herdr split belongs to its tab. The sidebar and
  statusline modes both avoid this.
- **Sidebar mode needs herdr 0.7.5+.** `report-metadata --token` does not exist
  on earlier releases; `--report` refuses with a version hint rather than
  failing obscurely.
- **Subscription accounts only.** The endpoint serves Claude subscription plans
  (including Team). It has nothing to report for pure API-key billing.
- **`claude.ai` does not work.** The commonly cited `claude.ai/api/oauth/usage`
  returns 403; the working host is `api.anthropic.com`.

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

The suite covers severity thresholds and server-reported grading, tolerant
payload parsing against the real observed schema, and a width sweep asserting
the rendered line never exceeds its column budget in either colour mode.

## Publishing

The herdr marketplace indexes public GitHub repositories tagged with the topic
`herdr-plugin`, refreshing every 30 minutes. Add that topic to the repository;
there is no separate submission step.

## Licence

MIT
