# claude-usage-line

A Claude Code status line for rate limits, context, model, and git branch.

Read [AGENTS.md](AGENTS.md) before changing anything here. It covers the release
step that is easy to miss, why the status line fails silently, which data is free
from stdin versus which needs the API, and the fixture convention that has hidden
two bugs.

## Layout

| Path | Holds |
| --- | --- |
| `src/claude_usage_line/statusline.py` | Reads the stdin payload; git branch and worktree resolution |
| `src/claude_usage_line/render.py` | All ANSI and every width budget |
| `src/claude_usage_line/client.py` | Usage endpoint, only for per-model windows |
| `src/claude_usage_line/cache.py` | On-disk snapshot, background refresh |
| `src/claude_usage_line/__main__.py` | Flags and the render path |
| `scripts/install-statusline.py` | Writes the `statusLine` entry into user settings |
| `skills/usage-line/SKILL.md` | The `/usage-line` skill: setup and diagnosis |

Keep ANSI in `render.py`. Other modules return text and style *names* so the
renderer stays the only place that knows escape codes.

## Checks

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
claude plugin validate .claude-plugin/plugin.json
claude plugin validate .claude-plugin/marketplace.json --strict
```

`plugin.json` warns that this file is not loaded as plugin context. That is
expected — it is here for contributors, not for plugin users. See AGENTS.md.
