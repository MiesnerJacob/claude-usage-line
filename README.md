# Claude Usage Line

A Claude Code status line showing your usage against Anthropic's rate limits,
plus context, model, and git branch. It also renders in a
[herdr](https://github.com/ogulcancelik/herdr) pane.

```
wt fix/ment-458-narrow-exception-handling │ Opus 5 (1M context) │ effort medium │ +2213 -314 │ ctx 549k/1M 55%
Session █████████░░░  77% 37m │ Week █████░░░░░░░  42% 1d23h │ Fable ███░░░░░░░░  28% 1d23h
```

Each window shows how much of the cap is consumed, as a bar and a percentage,
with a countdown to the next reset. Colour tracks severity, using the grading
the server itself reports rather than locally guessed thresholds.

In status line mode the numbers are free: Claude Code puts a `rate_limits` object
in the payload it sends on stdin, so there is no token to configure, no HTTP
request, and nothing to go stale. Only per-model windows (`Fable`) come from the
API, cached in the background.

## Display modes

**Claude Code status line (primary).** One or two rows inside every Claude pane,
in every tab, costing no pane. This is the mode most people want, and the only one
that needs nothing but Claude Code.

**herdr split pane.** A short split pinned along the bottom of a herdr tab, for
tabs not running Claude. Opened by `prefix+u`, an action, or the `[[startup]]`
hook.

**herdr sidebar tokens (0.7.5+).** Publishes named metadata tokens that your own
sidebar row config renders, so the readout sits in herdr's left pane and costs no
rows. Opt-in, because it cannot draw a header or full-width bars and it changes
the height of an agent card.

## Install

Python 3.10+. No build step and no dependencies — pure standard library.

The repository is both a Claude Code plugin and a herdr plugin; Claude Code
ignores `herdr-plugin.toml` and herdr ignores `.claude-plugin/`.

**As a Claude Code plugin** (the status line):

```sh
/plugin install <owner>/claude-usage-line
```

Then run the `usage-line` skill, or the installer directly. A plugin cannot set
`statusLine` itself — plugin settings support only `agent` and
`subagentStatusLine` — so this writes the entry into your own settings once,
resolving the absolute path from wherever the plugin landed:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install-statusline.py"
```

**As a herdr plugin** (the pane):

```sh
herdr plugin install <owner>/claude-usage-line
```

For local development of either, `herdr plugin link .`, or symlink the checkout
into your skills directory to load it as `claude-usage-line@skills-dir`.

Per-model windows need a Claude login (`claude`); the plugin reuses the OAuth
token Claude Code already stored and never starts its own login flow. The status
line works without it.

## Setting up the herdr sidebar mode (optional)

Start the background reporter — the `Claude Usage: show in sidebar` action or by
hand:

```sh
herdr-usage-pane --report --all-windows --target pane
```

It publishes one token per window plus a combined summary. Token names follow the
window labels, so new limit types appear without a code change:

| Token | Example |
| --- | --- |
| `$usage` | `Session 77% · Week 42%` |
| `$usage_current_session` | `Current Session  ███░░ 77%` |
| `$usage_week_all` | `Week (all)       ██░░░ 42%` |
| `$usage_week_fable` | `Week (Fable)     █░░░░ 28%` |

Reference them in `~/.config/herdr/config.toml`. Rows whose tokens are all absent
are dropped, so the readout appears only on the entry carrying the tokens:

```toml
[ui.sidebar.agents]
row_gap = 1
rows = [
	["state_icon", "workspace", "tab"],
	["agent"],
	[{ token = "$usage_current_session", dim = true }],
]
```

Then `herdr server reload-config`.

`[ui.sidebar.agents]` is the lower sidebar section; `[ui.sidebar.spaces]` is the
upper one. `--target pane` attaches to the last agent entry and follows it as
panes open and close; `--target workspace` attaches to the workspace instead.

Tokens carry a TTL (default 90s), so if the reporter dies herdr drops the row
rather than leaving a stale number on screen.

## Setting up the status line

Use the `usage-line` skill, or run the installer, which resolves its own path and
is safe to rerun:

```sh
python3 scripts/install-statusline.py            # or --dry-run
```

It writes `statusLine` into `~/.claude/settings.json`, preserving any previous
command under `_statusLineReplacedByClaudeUsageLine`. The change applies to new
sessions.

`--color always` is not optional here: a status line receives stdout on a pipe,
so `isatty()` is false and auto-detection would suppress colour.

## Options

| Flag | Effect |
| --- | --- |
| `--once` | Do one update and exit; how a status line invokes it |
| `--info-row` | Add the row with branch, model, effort and line counts |
| `--info-position above\|below` | Which row the info sits on |
| `--row-gap N` | Blank rows between the two rows (whole rows only) |
| `--context off\|bar\|count` | Context window as a bar, a token count, or hidden |
| `--branch-source activity\|cwd` | Label the branch from edited files, or the shell directory |
| `--all-windows` | Include per-model weekly limits such as `Week (Fable)` |
| `--short-labels` | Abbreviate labels so the bars keep their width |
| `--color auto\|always\|never` | `always` for pipes that render ANSI, such as a status line |
| `--report` | Publish to herdr's sidebar instead of drawing (herdr 0.7.5+) |
| `--target workspace\|pane` | Which herdr entity carries the tokens |
| `--target-id ID` | Explicit workspace or pane id |
| `--token-width N` | Column budget for sidebar tokens (default 22) |
| `--ttl-ms N` | How long herdr keeps a token if the reporter dies (default 90000) |
| `--interval SECONDS` | Seconds between polls (default 60) |
| `--refresh-cache` | Fetch and cache a snapshot, then exit |
| `--probe` | Dump the raw endpoint payload, for debugging schema drift |

## How it gets the data

**Status line mode reads stdin.** Claude Code sends a JSON payload that already
contains `rate_limits`, `context_window`, `model`, `effort`, `cost`, and
`transcript_path`. No token, no request, never stale.

**Per-model windows come from the API.** `Week (Fable)` is not in that payload, so
it is fetched from `GET https://api.anthropic.com/api/oauth/usage` and cached. A
cache miss triggers a detached refresh rather than blocking the redraw, so that
window can briefly be absent. The `claude-code/<version>` User-Agent is required:
without it the request lands in an aggressively throttled bucket and 429s.

The response's `limits` array is preferred, because it carries `kind`, `percent`,
`severity`, and `scope` as data — unknown limit types are labelled from the kind
rather than dropped. The flat `five_hour` / `seven_day` keys are a fallback.

The branch is read from `.git` directly, never by running `git`. By default it
labels the directory the session has been *editing* (from `transcript_path`),
falling back to `cwd`, because an agent that creates a worktree and then edits it
by absolute path has a `cwd` of the main checkout.

The token is read from the environment, then `~/.claude/.credentials.json`, then
the macOS Keychain. It is sent only to `api.anthropic.com`, and never written to
disk or passed on a command line.

## Known limitations

- **Per-model windows can blink out.** They come from the cached API snapshot, so
  after a cache expiry the next redraw may omit `Week (Fable)` until a background
  refresh lands. Running the pane or `--report` keeps the cache warm.
- **No sub-row spacing.** A terminal row is atomic, so `--row-gap` is whole rows:
  adjacent or one blank line, nothing between.
- **Split-pane row floor.** herdr ignores `height` on `[[panes]]` and clamps split
  ratios to 0.9, so a bottom split cannot go below about two usable rows.
- **Split panes are per-tab.** The status line covers every Claude pane instead.
- **Sidebar tokens need herdr 0.7.5+.** `report-metadata --token` does not exist
  earlier; `--report` refuses with a version hint rather than failing obscurely.
- **Subscription accounts only.** The endpoint serves Claude subscription plans
  including Team. It has nothing to report for pure API-key billing.
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

The repository serves both plugin systems from one checkout:

- **Claude Code**: `.claude-plugin/plugin.json` plus `skills/`. List it in a
  [plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces) entry.
- **herdr**: `herdr-plugin.toml`. The marketplace indexes public repositories
  tagged with the topic `herdr-plugin`, refreshing every 30 minutes.

Each ignores the other's manifest, so no separate branches or repos are needed.

## Licence

MIT
