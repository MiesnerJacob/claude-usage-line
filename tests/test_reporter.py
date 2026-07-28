"""Tests for sidebar token publication.

The herdr CLI is not invoked; the command argv it would receive is asserted
instead, which is the contract that matters.
"""

from __future__ import annotations

import unittest

from herdr_usage_pane.model import UsageSnapshot, UsageWindow
from herdr_usage_pane.reporter import (
    MIN_TOKEN_VERSION,
    ReporterTarget,
    SidebarReporter,
    parse_version,
    token_name,
)


def _snapshot(scoped: bool = False) -> UsageSnapshot:
    windows = [
        UsageWindow("5h", 35.0, resets_at=8_040),
        UsageWindow("7d", 32.0, resets_at=200_000),
    ]
    if scoped:
        windows.append(UsageWindow("Fable", 28.0, resets_at=200_000))
    return UsageSnapshot(windows=tuple(windows), captured_at=0.0)


class RecordingReporter(SidebarReporter):
    """Captures argv instead of shelling out to herdr."""

    def __init__(self, target: ReporterTarget, **kwargs: object) -> None:
        super().__init__(target=target, **kwargs)  # type: ignore[arg-type]
        self.commands: list[list[str]] = []

    def _run(self, args: list[str]) -> None:
        self.commands.append(args)


class PublishTest(unittest.TestCase):
    def setUp(self) -> None:
        self.reporter = RecordingReporter(
            ReporterTarget(kind="workspace", entity_id="wA"), ttl_ms=90_000
        )

    def _tokens(self) -> dict[str, str]:
        args = self.reporter.commands[0]
        pairs = [args[i + 1] for i, a in enumerate(args) if a == "--token"]
        return dict(pair.split("=", 1) for pair in pairs)

    def test_publishes_summary_and_per_window_tokens(self) -> None:
        self.reporter.publish(_snapshot())
        self.assertEqual(
            set(self._tokens()), {"usage", "usage_5h", "usage_7d"}
        )

    def test_summary_token_is_compact(self) -> None:
        self.reporter.publish(_snapshot())
        self.assertEqual(self._tokens()["usage"], "5h 35% · 7d 32%")

    def test_window_tokens_contain_no_ansi(self) -> None:
        self.reporter.publish(_snapshot())
        for value in self._tokens().values():
            self.assertNotIn("\033", value)

    def test_tokens_respect_width_budget(self) -> None:
        reporter = RecordingReporter(
            ReporterTarget(kind="workspace", entity_id="wA"), token_width=12
        )
        reporter.publish(_snapshot())
        args = reporter.commands[0]
        pairs = [args[i + 1] for i, a in enumerate(args) if a == "--token"]
        for pair in pairs:
            self.assertLessEqual(len(pair.split("=", 1)[1]), 12)

    def test_publish_includes_source_and_ttl(self) -> None:
        self.reporter.publish(_snapshot())
        args = self.reporter.commands[0]
        self.assertEqual(args[0], "wA")
        self.assertIn("--source", args)
        self.assertEqual(args[args.index("--ttl-ms") + 1], "90000")

    def test_clear_removes_every_published_token(self) -> None:
        self.reporter.publish(_snapshot(scoped=True))
        self.reporter.clear()
        args = self.reporter.commands[-1]
        cleared = {args[i + 1] for i, a in enumerate(args) if a == "--clear-token"}
        self.assertEqual(
            cleared, {"usage", "usage_5h", "usage_7d", "usage_fable"}
        )

    def test_scoped_window_gets_its_own_token(self) -> None:
        self.reporter.publish(_snapshot(scoped=True))
        self.assertIn("usage_fable", self._tokens())

    def test_stacked_labels_are_padded_for_alignment(self) -> None:
        self.reporter.publish(_snapshot(scoped=True))
        tokens = self._tokens()
        widths = {
            name: value.index("%")
            for name, value in tokens.items()
            if name != "usage"
        }
        self.assertEqual(len(set(widths.values())), 1, widths)


class TokenNameTest(unittest.TestCase):
    def test_simple_label(self) -> None:
        self.assertEqual(token_name("5h"), "usage_5h")

    def test_scoped_label_is_slugified(self) -> None:
        self.assertEqual(token_name("7d Fable"), "usage_7d_fable")

    def test_punctuation_collapses_to_underscores(self) -> None:
        self.assertEqual(token_name("7d Claude-Opus"), "usage_7d_claude_opus")

    def test_adjacent_punctuation_does_not_double_underscore(self) -> None:
        self.assertEqual(token_name("Week (all)"), "usage_week_all")
        self.assertEqual(token_name("Week (Fable)"), "usage_week_fable")
        self.assertEqual(token_name("Current Session"), "usage_current_session")


class TargetTest(unittest.TestCase):
    def test_workspace_target_uses_workspace_command(self) -> None:
        self.assertEqual(
            ReporterTarget(kind="workspace", entity_id="wA").command, "workspace"
        )

    def test_pane_target_uses_pane_command(self) -> None:
        self.assertEqual(
            ReporterTarget(kind="pane", entity_id="wA:p1").command, "pane"
        )


class ParseVersionTest(unittest.TestCase):
    def test_parses_herdr_version_output(self) -> None:
        self.assertEqual(parse_version("herdr 0.7.5"), (0, 7, 5))

    def test_returns_none_without_a_version(self) -> None:
        self.assertIsNone(parse_version("no version here"))

    def test_installed_floor_is_ordered_correctly(self) -> None:
        self.assertLess(parse_version("herdr 0.7.1"), MIN_TOKEN_VERSION)
        self.assertGreaterEqual(parse_version("herdr 0.7.5"), MIN_TOKEN_VERSION)
        self.assertGreaterEqual(parse_version("herdr 0.8.0"), MIN_TOKEN_VERSION)


if __name__ == "__main__":
    unittest.main()
