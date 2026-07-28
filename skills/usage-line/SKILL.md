---
name: usage-line
description: Set up, change, or remove the Claude usage status line - the row showing rate-limit bars, context, model and git branch. Use when the user asks to install, configure, reconfigure, or uninstall the usage status line, or asks why it is not appearing.
---

# Usage line setup

This plugin ships a status line that renders Claude's rate limits as bars, plus
context, model, effort, session line counts, and the git branch or worktree.

A plugin cannot set `statusLine` on its own — plugin `settings.json` supports
only `agent` and `subagentStatusLine` — so setup writes the entry into the user's
own settings once.

## Install

Setup is automatic: a `SessionStart` hook adopts the status line on first run and
repoints it after a plugin update. Run the installer explicitly only to replace a
status line the user already had, or to bake in different flags:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/install-statusline.py"
```

Add `--dry-run` to show the command without writing. Pass extra flags through to
the readout, for example `--branch-source cwd`.

The change takes effect in new sessions.

## Verify

Run the readout by hand with a sample payload. It prints two rows and exits:

```sh
echo '{"cwd":"'"$PWD"'","rate_limits":{"five_hour":{"used_percentage":50}}}' \
  | "${CLAUDE_PLUGIN_ROOT}/bin/claude-usage-line" --info-row --color never
```

## Options

Flags for the `statusLine` command in `~/.claude/settings.json`:

| Flag | Effect |
| --- | --- |
| `--info-row` | Second row with branch, model, effort, line counts |
| `--info-position above\|below` | Which row the info sits on |
| `--row-gap N` | Blank rows between the two rows |
| `--context off\|bar\|count` | Context window as a bar, a token count, or hidden |
| `--all-windows` | Include per-model weekly limits |
| `--short-labels` | Abbreviate labels so the bars keep their width |
| `--branch-source activity\|cwd` | Label the branch from edited files, or the shell directory |
| `--color auto\|always\|never` | `always` is needed: a status line is a pipe, not a tty |

## If it is not appearing

Check in this order:

1. `python3 -c "import json,pathlib; print(json.loads(pathlib.Path.home().joinpath('.claude/settings.json').read_text())['statusLine'])"`
   — confirms the entry exists and the JSON parses.
2. Run the configured command by hand. A missing file or a non-zero exit renders
   as a blank row with no error.
3. Confirm `--color always` is present. Without it the row renders unstyled
   because `isatty()` is false on a pipe.
4. Start a new session. The command is read at session start.

## Uninstall

Remove the `statusLine` key from `~/.claude/settings.json`. If
`_statusLineReplacedByClaudeUsageLine` is present, that was the previous command;
restore it and delete the backup key.
