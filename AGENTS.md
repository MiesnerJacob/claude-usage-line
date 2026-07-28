# Working on this repo

Notes that are not obvious from reading the code. Most of these were bugs first.

## Releasing

`.claude-plugin/plugin.json` pins an explicit `version`. **Pushing a commit is not
enough to ship it** — Claude Code compares the version string and keeps its cached
copy, so `/plugin update` reports "already at the latest version". Bump `version`
on every change users should receive.

Delete the `version` field instead if you want updates to track the commit SHA,
which is better while iterating quickly.

Validate both manifests before pushing:

```sh
claude plugin validate .claude-plugin/plugin.json
claude plugin validate .claude-plugin/marketplace.json --strict
```

`plugin.json` is validated without `--strict` on purpose. It emits one warning —
*"CLAUDE.md at the plugin root is not loaded as project context"* — which is
accurate but irrelevant here: `CLAUDE.md` exists for people working on this
repository, not as context shipped to plugin users. Do not delete it to silence
the warning. Any *other* warning is a real one.

## Status line constraints

- **A status line is a pipe, not a tty.** `isatty()` is false, so `--color always`
  is required or the row renders unstyled.
- **Failure is silent.** A missing file, a non-zero exit, or an exception renders
  as a blank row with no error anywhere. When something "doesn't work", run the
  configured command by hand first.
- **The command is read at session start.** Config changes need a new session.
- **`COLUMNS` and `LINES` are set** by Claude Code before running the command
  (v2.1.153+), which is why `shutil.get_terminal_size()` works despite the pipe.
- **Terminal rows are atomic.** `--row-gap` is whole rows; there is no half row.
- **Never remove `--once`.** It is a no-op, but installed `settings.json` files
  pass it and argparse rejects unknown flags, which would blank the row.

## Data sources

Prefer the stdin payload. Claude Code already sends `rate_limits`,
`context_window`, `model`, `effort`, `cost`, `session_id`, and `transcript_path`.
Do not add an API call for anything already in there — an earlier version had a
whole HTTP client, OAuth lookup, and cache to obtain two numbers that arrive free.

The API is needed for exactly one thing: per-model windows such as
`Week (Fable)`, which the payload omits. Consequences:

- The host is **`api.anthropic.com/api/oauth/usage`**. The widely cited
  `claude.ai/api/oauth/usage` returns **403**.
- The `claude-code/<version>` User-Agent is **mandatory**. Without it requests
  land in a throttled bucket and return persistent 429s.
- Those windows can briefly disappear after a cache expiry, because a miss
  refreshes in a detached process rather than blocking the redraw.

Never block on stdin. `sys.stdin.read()` waits for EOF, which never arrives on an
inherited pipe, and hangs the caller forever. Use `select` then one bounded read.

Do not shell out to `git`. The branch is read from `.git` directly because this
runs on every redraw, where a subprocess costs more than everything else combined.

## Conventions

- No module-level docstrings. Rationale belongs on the function it explains.
- No inline comments. Comments that survive explain *why*, not *what*.
- Unknown data is labelled, not dropped. The usage endpoint already lists limit
  kinds that do not exist yet (`nimbus_quill`, `seven_day_cowork`); a fixed
  lookup table would silently hide a real limit.

## Testing

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

**Use real names in fixtures.** Two bugs hid behind invented test data, both in
worktree matching. Directory names prepend the repo name while branches prefix
the ref type, so `mentality-ment-458` and `fix/ment-458-narrow-exception-handling`
share a run in the *middle*, not at either end. Synthetic pairs like
`project-thing` / `feature/thing` pass tests the real ones fail.

Assert against visible width, not string length. ANSI escapes make `len()` lie;
`_visible_length` exists for this.
