"""Tests for reading usage from the statusline payload.

The payload shape here was captured from Claude Code 2.1.220.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from herdr_usage_pane.model import UsageSnapshot, UsageWindow
from herdr_usage_pane.statusline import (
    _names_overlap,
    activity_dir,
    context_segment,
    git_label,
    info_segments,
    merge_scoped,
    shorten_labels,
    snapshot_from_payload,
)

LIVE_PAYLOAD = {
    "session_id": "f4895cc0",
    "model": {"id": "claude-opus-5[1m]", "display_name": "Opus 5 (1M context)"},
    "context_window": {"used_percentage": 42},
    "rate_limits": {
        "five_hour": {"used_percentage": 72, "resets_at": 1_785_261_600},
        "seven_day": {"used_percentage": 41, "resets_at": 1_785_430_800},
    },
}


class SnapshotFromPayloadTest(unittest.TestCase):
    def test_reads_both_windows(self) -> None:
        snapshot = snapshot_from_payload(LIVE_PAYLOAD, now=0.0)
        assert snapshot is not None
        self.assertEqual(
            [w.label for w in snapshot.windows],
            ["Current Session", "Week (all)"],
        )
        self.assertEqual(snapshot.windows[0].used_percentage, 72.0)
        self.assertEqual(snapshot.windows[1].resets_at, 1_785_430_800)

    def test_payload_without_rate_limits_is_none(self) -> None:
        self.assertIsNone(snapshot_from_payload({"model": {}}, now=0.0))

    def test_empty_rate_limits_is_none(self) -> None:
        self.assertIsNone(snapshot_from_payload({"rate_limits": {}}, now=0.0))

    def test_skips_window_missing_a_percentage(self) -> None:
        payload = {"rate_limits": {"five_hour": {"resets_at": 1}, "seven_day": {"used_percentage": 5}}}
        snapshot = snapshot_from_payload(payload, now=0.0)
        assert snapshot is not None
        self.assertEqual([w.label for w in snapshot.windows], ["Week (all)"])

    def test_ignores_boolean_percentage(self) -> None:
        payload = {"rate_limits": {"five_hour": {"used_percentage": True}}}
        self.assertIsNone(snapshot_from_payload(payload, now=0.0))


class MergeScopedTest(unittest.TestCase):
    def _live(self) -> UsageSnapshot:
        snapshot = snapshot_from_payload(LIVE_PAYLOAD, now=100.0)
        assert snapshot is not None
        return snapshot

    def test_appends_windows_absent_from_the_payload(self) -> None:
        cached = UsageSnapshot(
            windows=(UsageWindow("Week (Fable)", 28.0),), captured_at=0.0
        )
        merged = merge_scoped(self._live(), cached)
        self.assertEqual(
            [w.label for w in merged.windows],
            ["Current Session", "Week (all)", "Week (Fable)"],
        )

    def test_live_values_win_over_cached_duplicates(self) -> None:
        cached = UsageSnapshot(
            windows=(UsageWindow("Current Session", 5.0),), captured_at=0.0
        )
        merged = merge_scoped(self._live(), cached)
        self.assertEqual(len(merged.windows), 2)
        self.assertEqual(merged.windows[0].used_percentage, 72.0)

    def test_no_cache_returns_the_payload_unchanged(self) -> None:
        merged = merge_scoped(self._live(), None)
        self.assertEqual(len(merged.windows), 2)

    def test_keeps_the_live_capture_time(self) -> None:
        cached = UsageSnapshot(
            windows=(UsageWindow("Week (Fable)", 28.0),), captured_at=0.0
        )
        self.assertEqual(merge_scoped(self._live(), cached).captured_at, 100.0)



class InfoSegmentsTest(unittest.TestCase):
    def test_reads_model_effort_and_line_counts(self) -> None:
        payload = {
            "model": {"display_name": "Opus 5 (1M context)"},
            "effort": {"level": "medium"},
            "cost": {"total_lines_added": 3577, "total_lines_removed": 284},
        }
        self.assertEqual(
            info_segments(payload),
            [
                ("Opus 5 (1M context)", "dim"),
                ("effort medium", "dim"),
                ("+3577", "added"),
                ("-284", "removed"),
            ],
        )

    def test_skips_missing_sections(self) -> None:
        self.assertEqual(info_segments({}), [])

    def test_skips_line_counts_that_are_not_integers(self) -> None:
        payload = {"cost": {"total_lines_added": "many", "total_lines_removed": 1}}
        self.assertEqual(info_segments(payload), [])

    def test_ignores_non_dict_sections(self) -> None:
        self.assertEqual(info_segments({"model": "opus", "effort": 3}), [])


class ShortenLabelsTest(unittest.TestCase):
    def test_abbreviates_known_labels(self) -> None:
        snapshot = UsageSnapshot(
            windows=(
                UsageWindow("Context", 42.0),
                UsageWindow("Current Session", 72.0),
                UsageWindow("Week (all)", 41.0),
                UsageWindow("Week (Fable)", 28.0),
            ),
            captured_at=0.0,
        )
        self.assertEqual(
            [w.label for w in shorten_labels(snapshot).windows],
            ["Ctx", "Session", "Week", "Fable"],
        )

    def test_preserves_percentages_and_resets(self) -> None:
        snapshot = UsageSnapshot(
            windows=(UsageWindow("Week (Fable)", 28.0, resets_at=99),),
            captured_at=0.0,
        )
        window = shorten_labels(snapshot).windows[0]
        self.assertEqual((window.used_percentage, window.resets_at), (28.0, 99))

    def test_unknown_label_is_left_alone(self) -> None:
        snapshot = UsageSnapshot(
            windows=(UsageWindow("Something Else", 1.0),), captured_at=0.0
        )
        self.assertEqual(shorten_labels(snapshot).windows[0].label, "Something Else")


class GitLabelTest(unittest.TestCase):
    """Worktree and branch resolution, read from .git without a subprocess."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)

    def tearDown(self) -> None:
        self._directory.cleanup()

    def _main_repo(self, branch: str = "refs/heads/staging") -> Path:
        repo = self.root / "project"
        (repo / ".git").mkdir(parents=True)
        (repo / ".git" / "HEAD").write_text(f"ref: {branch}\n")
        return repo

    def _worktree(self, name: str, branch: str) -> Path:
        repo = self._main_repo()
        gitdir = repo / ".git" / "worktrees" / name
        gitdir.mkdir(parents=True)
        gitdir.joinpath("HEAD").write_text(f"ref: {branch}\n")
        tree = self.root / name
        tree.mkdir()
        tree.joinpath(".git").write_text(f"gitdir: {gitdir}\n")
        return tree

    def test_main_repo_shows_the_branch(self) -> None:
        self.assertEqual(git_label(str(self._main_repo())), "staging")

    def test_branch_keeps_its_full_path(self) -> None:
        repo = self._main_repo("refs/heads/feature/ment-210-form-cancel")
        self.assertEqual(git_label(str(repo)), "feature/ment-210-form-cancel")

    def test_worktree_is_marked(self) -> None:
        tree = self._worktree("project-ment-210", "refs/heads/feature/ment-210")
        self.assertEqual(git_label(str(tree)), "wt feature/ment-210")

    def test_redundant_worktree_name_is_dropped(self) -> None:
        tree = self._worktree(
            "project-ment-402-ppt-attachment-extraction",
            "refs/heads/fix/ment-402-ppt-attachment-extraction",
        )
        self.assertEqual(
            git_label(str(tree)), "wt fix/ment-402-ppt-attachment-extraction"
        )

    def test_distinct_worktree_name_is_kept(self) -> None:
        tree = self._worktree("scratchpad", "refs/heads/main")
        self.assertEqual(git_label(str(tree)), "wt scratchpad:main")

    def test_detached_head_shows_a_short_sha(self) -> None:
        repo = self._main_repo()
        (repo / ".git" / "HEAD").write_text("a08b1ab3c4d5e6f7\n")
        self.assertEqual(git_label(str(repo)), "a08b1ab")

    def test_walks_up_to_the_repo_root(self) -> None:
        repo = self._main_repo()
        nested = repo / "src" / "deep"
        nested.mkdir(parents=True)
        self.assertEqual(git_label(str(nested)), "staging")

    def test_outside_a_repo_is_none(self) -> None:
        self.assertIsNone(git_label(str(self.root)))

    def test_no_cwd_is_none(self) -> None:
        self.assertIsNone(git_label(None))


class ContextSegmentTest(unittest.TestCase):
    def test_formats_tokens_against_the_window(self) -> None:
        payload = {
            "context_window": {
                "used_percentage": 42,
                "total_input_tokens": 422810,
                "context_window_size": 1000000,
            }
        }
        self.assertEqual(context_segment(payload), ("ctx 423k/1M 42%", "dim"))

    def test_derives_percentage_when_absent(self) -> None:
        payload = {
            "context_window": {
                "total_input_tokens": 100000,
                "context_window_size": 200000,
            }
        }
        self.assertEqual(context_segment(payload), ("ctx 100k/200k 50%", "dim"))

    def test_missing_section_is_none(self) -> None:
        self.assertIsNone(context_segment({}))

    def test_zero_window_size_is_none(self) -> None:
        payload = {
            "context_window": {"total_input_tokens": 1, "context_window_size": 0}
        }
        self.assertIsNone(context_segment(payload))

    def test_non_integer_tokens_is_none(self) -> None:
        payload = {
            "context_window": {
                "total_input_tokens": "lots",
                "context_window_size": 1000,
            }
        }
        self.assertIsNone(context_segment(payload))

    def test_small_counts_are_not_abbreviated(self) -> None:
        payload = {
            "context_window": {
                "total_input_tokens": 850,
                "context_window_size": 200000,
            }
        }
        self.assertEqual(context_segment(payload)[0], "ctx 850/200k 0%")


class ActivityDirTest(unittest.TestCase):
    """The branch should follow what the session edits, not where it sits."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.repo = self.root / "project"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / ".git" / "HEAD").write_text("ref: refs/heads/staging\n")

    def tearDown(self) -> None:
        self._directory.cleanup()

    def _transcript(self, *lines: str) -> str:
        path = self.root / "transcript.jsonl"
        path.write_text("\n".join(lines) + "\n")
        return str(path)

    def test_uses_the_last_edited_file(self) -> None:
        transcript = self._transcript(
            json.dumps({"input": {"file_path": str(self.repo / "a.py")}}),
            json.dumps({"input": {"file_path": str(self.repo / "src" / "b.py")}}),
        )
        self.assertEqual(
            activity_dir({"transcript_path": transcript}),
            str(self.repo / "src"),
        )

    def test_ignores_paths_mentioned_only_in_prose(self) -> None:
        transcript = self._transcript(
            json.dumps({"input": {"file_path": str(self.repo / "a.py")}}),
            json.dumps({"text": f"you should look at {self.root / 'elsewhere.py'}"}),
        )
        self.assertEqual(
            activity_dir({"transcript_path": transcript}), str(self.repo)
        )

    def test_skips_paths_outside_a_repository(self) -> None:
        transcript = self._transcript(
            json.dumps({"input": {"file_path": str(self.repo / "a.py")}}),
            json.dumps({"input": {"file_path": str(self.root / "loose.txt")}}),
        )
        self.assertEqual(
            activity_dir({"transcript_path": transcript}), str(self.repo)
        )

    def test_missing_transcript_is_none(self) -> None:
        self.assertIsNone(
            activity_dir({"transcript_path": str(self.root / "absent.jsonl")})
        )

    def test_no_transcript_path_is_none(self) -> None:
        self.assertIsNone(activity_dir({}))

    def test_transcript_without_edits_is_none(self) -> None:
        transcript = self._transcript(json.dumps({"text": "no tools used"}))
        self.assertIsNone(activity_dir({"transcript_path": transcript}))


class BranchSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.main = self.root / "project"
        (self.main / ".git").mkdir(parents=True)
        (self.main / ".git" / "HEAD").write_text("ref: refs/heads/staging\n")
        gitdir = self.main / ".git" / "worktrees" / "project-ment-210-form-cancel"
        gitdir.mkdir(parents=True)
        gitdir.joinpath("HEAD").write_text("ref: refs/heads/feature/ment-210-form-cancel\n")
        self.tree = self.root / "project-ment-210-form-cancel"
        self.tree.mkdir()
        self.tree.joinpath(".git").write_text(f"gitdir: {gitdir}\n")
        transcript = self.root / "t.jsonl"
        transcript.write_text(
            json.dumps({"input": {"file_path": str(self.tree / "x.py")}}) + "\n"
        )
        self.payload = {
            "cwd": str(self.main),
            "transcript_path": str(transcript),
        }

    def tearDown(self) -> None:
        self._directory.cleanup()

    def test_activity_prefers_the_edited_worktree(self) -> None:
        segments = info_segments(self.payload, branch_source="activity")
        self.assertEqual(segments[0], ("wt feature/ment-210-form-cancel", "branch"))

    def test_cwd_reports_the_shell_directory(self) -> None:
        segments = info_segments(self.payload, branch_source="cwd")
        self.assertEqual(segments[0], ("staging", "branch"))

    def test_activity_falls_back_to_cwd(self) -> None:
        payload = {"cwd": str(self.main)}
        segments = info_segments(payload, branch_source="activity")
        self.assertEqual(segments[0], ("staging", "branch"))

class NamesOverlapTest(unittest.TestCase):
    """Real worktree/branch pairs, and pairs that must stay distinct."""

    def test_directory_named_after_only_the_ticket(self) -> None:
        self.assertTrue(
            _names_overlap("mentality-ment-458", "fix/ment-458-narrow-exception-handling")
        )

    def test_directory_mirroring_the_whole_slug(self) -> None:
        self.assertTrue(
            _names_overlap(
                "mentality-ment-210-form-cancel-decline",
                "feature/ment-210-form-cancel-decline",
            )
        )

    def test_differing_ref_type(self) -> None:
        self.assertTrue(
            _names_overlap(
                "mentality-ment-402-ppt-attachment-extraction",
                "fix/ment-402-ppt-attachment-extraction",
            )
        )

    def test_unrelated_names_stay_distinct(self) -> None:
        self.assertFalse(_names_overlap("scratchpad", "main"))
        self.assertFalse(_names_overlap("experiment", "staging"))

    def test_short_incidental_overlap_is_not_enough(self) -> None:
        self.assertFalse(_names_overlap("hotfix-login", "feature/logging"))



class WorktreeNameOverlapTest(unittest.TestCase):
    """Real directory/branch pairs, which follow no single naming rule."""

    def test_shared_ticket_mid_string_counts_as_redundant(self) -> None:
        # Directory names only the ticket; branch carries the full slug.
        self.assertTrue(
            _names_overlap("mentality-ment-458", "fix/ment-458-narrow-exception-handling")
        )

    def test_shared_full_slug_counts_as_redundant(self) -> None:
        self.assertTrue(
            _names_overlap(
                "mentality-ment-210-form-cancel-decline",
                "feature/ment-210-form-cancel-decline",
            )
        )

    def test_unrelated_names_are_kept(self) -> None:
        self.assertFalse(_names_overlap("scratchpad", "main"))
        self.assertFalse(_names_overlap("experiment", "staging"))
        self.assertFalse(_names_overlap("hotfix-login", "feature/logging"))

if __name__ == "__main__":
    unittest.main()
