# Claude Usage Line

A Claude Code status line for your rate limits, context, model, and git branch.

```
[fix/ment-458-narrow-exception-handling] │ Opus 5 (1M context) │ effort medium │ +2213 -314 │ ctx 549k/1M 55%
Session █████████░░░  77% 37m │ Week █████░░░░░░░  42% 1d23h │ Fable ███░░░░░░░░  28% 1d23h
```

## Setup

```
/plugin marketplace add MiesnerJacob/claude-usage-line
/plugin install claude-usage-line
```

That is it. A hook writes the `statusLine` entry into `~/.claude/settings.json`
for you on session start or first prompt, and repoints it after a plugin update,
since the plugin cache is versioned. If you already have a status line of your own, the
hook leaves it alone — run the installer explicitly to replace it:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install-statusline.py"
```

Requires Python 3.10+. No dependencies, no build step.

To customise, add flags to the `statusLine` command in
`~/.claude/settings.json`, or pass them to the installer to have it write them.

## Options

Append any of these to the `statusLine` command.

| Flag | Effect |
| --- | --- |
| `--info-row` | Second row: branch, model, effort, line counts |
| `--info-position above\|below` | Which row the info sits on |
| `--row-gap N` | Blank rows between the two rows |
| `--context off\|bar\|count` | Context as a bar, a token count, or hidden |
| `--all-windows` | Include per-model limits such as `Week (Fable)` |
| `--short-labels` | Abbreviate labels so the bars keep their width |
| `--branch-source activity\|cwd` | Label from edited files, or the shell directory |
| `--color auto\|always\|never` | `always` is required: a status line is a pipe, not a tty |
| `--interval SECONDS` | Before a cached snapshot is refetched (default 60) |
| `--probe` | Dump the raw usage endpoint payload |

## How it works

Claude Code sends a JSON payload on stdin that already contains `rate_limits`,
`context_window`, `model`, `effort`, `cost`, and `transcript_path`. Those cost
nothing to read and are never stale.

Per-model windows such as `Week (Fable)` are not in that payload, so they come
from `api.anthropic.com/api/oauth/usage`, cached for a minute. A cache miss
refreshes in the background rather than blocking the redraw, so that window can
briefly be absent. Requests reuse the OAuth token Claude Code already stored and
never start a login flow.

Bars are coloured by the severity the server reports, not by local thresholds.
The branch is read straight from `.git`, never by running `git`, and labels the
directory the session has been *editing* — so an agent that creates a worktree
and then edits it from the main checkout still shows the worktree. Worktrees are
bracketed and recoloured.

## Limitations

- Per-model windows can briefly disappear after a cache expiry.
- `--row-gap` is whole rows. Terminal rows are atomic; there is no half row.
- `activity` branch detection follows the last file edited, so a one-off edit
  outside the project relabels the line until the next edit.
- Subscription plans only, including Team. Nothing to report for API-key billing.

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Licence

MIT
