# Claude Usage Line

A Claude Code status line showing your usage against Anthropic's rate limits,
plus context, model, and git branch or worktree.

```
[fix/ment-458-narrow-exception-handling] │ Opus 5 (1M context) │ effort medium │ +2213 -314 │ ctx 549k/1M 55%
Session █████████░░░  77% 37m │ Week █████░░░░░░░  42% 1d23h │ Fable ███░░░░░░░░  28% 1d23h
```

Each window shows how much of the cap is consumed, as a bar and a percentage,
with a countdown to the next reset. Colour tracks severity, using the grading
the server itself reports rather than locally guessed thresholds.

In status line mode the numbers are free: Claude Code puts a `rate_limits` object
in the payload it sends on stdin, so there is no token to configure, no HTTP
request, and nothing to go stale. Only per-model windows (`Fable`) come from the
API, cached in the background.

## What it shows

The bars row carries one window per rate limit, coloured by severity, with a
countdown to each reset. The info row carries the branch — bracketed and
recoloured when it is a linked worktree — plus the model, effort level, session
line counts, and the context window as a token count.

Both rows are optional and independently positioned; see Options.

## Install

Python 3.10+. No build step, no dependencies — pure standard library.

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

It is idempotent, keeps any previous command under
`_statusLineReplacedByClaudeUsageLine`, and refuses to write over invalid JSON.
The change applies to new sessions.

Per-model windows such as `Week (Fable)` need a Claude login, because they come
from the API rather than the status line payload. Everything else works without
one.

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
| `--once` | Render one line and exit; how a status line invokes it |
| `--info-row` | Add the row with branch, model, effort and line counts |
| `--info-position above\|below` | Which row the info sits on |
| `--row-gap N` | Blank rows between the two rows (whole rows only) |
| `--context off\|bar\|count` | Context window as a bar, a token count, or hidden |
| `--branch-source activity\|cwd` | Label from edited files, or the shell directory |
| `--all-windows` | Include per-model weekly limits such as `Week (Fable)` |
| `--short-labels` | Abbreviate labels so the bars keep their width |
| `--color auto\|always\|never` | `always` for pipes that render ANSI, such as a status line |
| `--interval SECONDS` | Seconds before a cached snapshot is refetched (default 60) |
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
  refresh lands.
- **No sub-row spacing.** A terminal row is atomic, so `--row-gap` is whole rows:
  adjacent or one blank line, nothing between.
- **The branch is a guess about intent.** `activity` reads the files the session
  edited, which is right for an agent working in a worktree from elsewhere, but
  a one-off edit outside the project relabels the line until the next edit.
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

`.claude-plugin/plugin.json` plus `skills/` make this a Claude Code plugin. List
it in a [plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces)
entry to make it installable by name.

## Licence

MIT
