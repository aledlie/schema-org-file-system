"""RenamedScreenshotSignal tests (UNIFIED_SCORING_PLAN §4 row 1)."""

from pathlib import Path

from src.scoring.signals.renamed_screenshot import (
    RENAMED_MATCH_CONFIDENCE,
    RenamedScreenshotSignal,
    match_renamed_screenshot,
)
from src.scoring.context import FileContext
from src.scoring.weights import W_RENAMED

SCREENSHOTS_DICT = {
    "browser": "Media/Photos/Screenshots/Browser",
    "terminal": "Media/Photos/Screenshots/Terminal",
    "terminal_session": "Media/Photos/Screenshots/TerminalSession",
    "docs": "Media/Photos/Screenshots/Docs",
    "other": "Media/Photos/Screenshots",
}


def make_ctx(path="/tmp/Screenshot 2026-03-20.png", display_path=None):
    return FileContext(
        path=Path(path),
        schema_type="ImageObject",
        display_path=Path(display_path) if display_path else None,
    )


class TestMatchRenamedScreenshot:
    def test_matches_key_in_stem(self):
        assert match_renamed_screenshot("20260320_browser_tabs", SCREENSHOTS_DICT) == "browser"

    def test_longer_keys_checked_first(self):
        stem = "20260320_terminal_session"
        assert match_renamed_screenshot(stem, SCREENSHOTS_DICT) == "terminal_session"

    def test_other_key_is_skipped(self):
        assert match_renamed_screenshot("another_thing", {"other": "Media"}) is None

    def test_no_match_returns_none(self):
        assert match_renamed_screenshot("20260320_vacation", SCREENSHOTS_DICT) is None


class TestAppliesTo:
    def test_applies_when_renamed_screenshot(self):
        ctx = make_ctx(display_path="/tmp/20260320_terminal_session.png")
        assert RenamedScreenshotSignal(SCREENSHOTS_DICT).applies_to(ctx) is True

    def test_skips_without_display_path(self):
        ctx = make_ctx()
        assert RenamedScreenshotSignal(SCREENSHOTS_DICT).applies_to(ctx) is False

    def test_skips_when_display_equals_path(self):
        ctx = make_ctx(display_path="/tmp/Screenshot 2026-03-20.png")
        assert RenamedScreenshotSignal(SCREENSHOTS_DICT).applies_to(ctx) is False

    def test_skips_non_screenshot_originals(self):
        ctx = FileContext(
            path=Path("/tmp/IMG_1234.png"),
            schema_type="ImageObject",
            display_path=Path("/tmp/20260320_terminal_session.png"),
        )
        assert RenamedScreenshotSignal(SCREENSHOTS_DICT).applies_to(ctx) is False


class TestRun:
    def test_emits_screenshot_subcategory(self):
        ctx = make_ctx(display_path="/tmp/20260320_terminal_session.png")
        scores = RenamedScreenshotSignal(SCREENSHOTS_DICT).run(ctx)
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == (
            "media",
            "photos_screenshots_terminal_session",
        )
        assert score.confidence == RENAMED_MATCH_CONFIDENCE
        assert score.signal_name == "renamed_screenshot"
        assert score.evidence == {
            "matched_key": "terminal_session",
            "renamed_stem": "20260320_terminal_session",
        }

    def test_no_key_match_emits_nothing(self):
        ctx = make_ctx(display_path="/tmp/20260320_vacation.png")
        assert RenamedScreenshotSignal(SCREENSHOTS_DICT).run(ctx) == []

    def test_signal_metadata(self):
        signal = RenamedScreenshotSignal(SCREENSHOTS_DICT)
        assert signal.name == "renamed_screenshot"
        assert signal.weight == W_RENAMED
        assert signal.cost_tier == "cheap"
