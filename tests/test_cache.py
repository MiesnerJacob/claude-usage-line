"""Tests for the on-disk snapshot cache."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from claude_usage_line import cache
from claude_usage_line.model import Severity, UsageSnapshot, UsageWindow


def _snapshot(captured_at: float = 1_000.0) -> UsageSnapshot:
    return UsageSnapshot(
        windows=(
            UsageWindow("Current Session", 71.0, resets_at=8_040),
            UsageWindow(
                "Week (Fable)", 28.0, resets_at=None,
                reported_severity=Severity.ELEVATED,
            ),
        ),
        captured_at=captured_at,
    )


class CacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self._previous = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = self._directory.name

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = self._previous
        self._directory.cleanup()

    def test_round_trips_a_snapshot(self) -> None:
        cache.write_snapshot(_snapshot())
        restored = cache.read_snapshot(now=1_010.0, max_age=60.0)
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(
            [w.label for w in restored.windows],
            ["Current Session", "Week (Fable)"],
        )
        self.assertEqual(restored.windows[0].resets_at, 8_040)
        self.assertEqual(restored.captured_at, 1_000.0)

    def test_preserves_reported_severity(self) -> None:
        cache.write_snapshot(_snapshot())
        restored = cache.read_snapshot(now=1_010.0, max_age=60.0)
        assert restored is not None
        self.assertEqual(restored.windows[1].reported_severity, Severity.ELEVATED)

    def test_expired_cache_is_a_miss(self) -> None:
        cache.write_snapshot(_snapshot())
        self.assertIsNone(cache.read_snapshot(now=1_100.0, max_age=60.0))

    def test_missing_file_is_a_miss(self) -> None:
        self.assertIsNone(cache.read_snapshot(now=0.0))

    def test_corrupt_file_is_a_miss(self) -> None:
        path = cache.cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json")
        self.assertIsNone(cache.read_snapshot(now=0.0))

    def test_wrong_version_is_a_miss(self) -> None:
        cache.write_snapshot(_snapshot())
        path = cache.cache_path()
        path.write_text(path.read_text().replace('"version": 1', '"version": 99'))
        self.assertIsNone(cache.read_snapshot(now=1_010.0, max_age=60.0))

    def test_write_leaves_no_temporary_files(self) -> None:
        cache.write_snapshot(_snapshot())
        leftovers = list(cache.cache_path().parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_honours_xdg_cache_home(self) -> None:
        self.assertTrue(
            str(cache.cache_path()).startswith(self._directory.name),
            cache.cache_path(),
        )


if __name__ == "__main__":
    unittest.main()
