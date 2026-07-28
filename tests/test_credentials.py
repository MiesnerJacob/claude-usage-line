from __future__ import annotations

import unittest

from claude_usage_line.credentials import _find_access_token


class FindAccessTokenTest(unittest.TestCase):
    def test_finds_token_at_top_level(self) -> None:
        self.assertEqual(_find_access_token({"accessToken": "abc"}), "abc")

    def test_finds_token_under_wrapper_key(self) -> None:
        blob = {"claudeAiOauth": {"accessToken": "xyz", "refreshToken": "r"}}
        self.assertEqual(_find_access_token(blob), "xyz")

    def test_finds_snake_case_spelling(self) -> None:
        self.assertEqual(_find_access_token({"access_token": "snake"}), "snake")

    def test_ignores_empty_token(self) -> None:
        self.assertIsNone(_find_access_token({"accessToken": ""}))

    def test_ignores_non_string_token(self) -> None:
        self.assertIsNone(_find_access_token({"accessToken": 12345}))

    def test_returns_none_when_absent(self) -> None:
        self.assertIsNone(_find_access_token({"refreshToken": "r"}))


if __name__ == "__main__":
    unittest.main()
