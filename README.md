# Claude Usage Pane

A condensed Claude Code usage-vs-limits readout for [herdr](https://github.com/ogulcancelik/herdr).

```
5h ████░░░░░░░░  35% 3h05m │ 7d ████░░░░░░░░  32% 2d20h
```

Each window shows how much of the cap is consumed, as a bar and a percentage,
with a countdown to the next reset. Colour tracks severity, using the grading
the server itself reports rather than locally guessed thresholds.

## Why a pane and not the sidebar

Herdr 0.7.x plugins cannot draw inside the sidebar chrome. The plugin API's
extension points are `[[build]]`, `[[startup]]`, `[[actions]]`, `[[events]]`,
`[[panes]]`, and `[[link_handlers]]` — panes are the only rendering surface, and
`[ui]` in `config.toml` exposes only sidebar *width*, no content hook.

So the readout lives in a short split pinned along the bottom of the tab. A
bottom-left sidebar footer would need an upstream change to herdr itself.

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

## Two ways to display it

**As a herdr pane.** The `[[startup]]` hook opens it after each session restore,
or trigger `Claude Usage: show pane` from the action menu. Note that herdr
splits are per-tab, so this shows in one tab rather than session-wide.

**As a Claude Code statusline.** `--once` prints a single line and exits, which
gets the readout inside *every* Claude Code pane in every tab, consuming no
rows. Add to `~/.claude/settings.json`:

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
| `--once` | Print one line and exit, for statuslines and scripts |
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

- **Four-row floor.** herdr ignores `height` on `[[panes]]` and clamps split
  ratios to 0.9, so the pane cannot be shrunk below roughly four rows even
  though it draws one line. The extra rows are blank.
- **Per-tab, not session-wide.** A herdr split belongs to its tab. Use the
  statusline mode for coverage everywhere.
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
