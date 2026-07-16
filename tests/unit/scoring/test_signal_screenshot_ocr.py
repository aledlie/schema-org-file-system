"""ScreenshotOcrSignal tests (UNIFIED_SCORING_PLAN §4 row 10)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.scoring.context import FileContext
from src.scoring.signals.screenshot_ocr import (
    SCREENSHOT_OCR_KEYWORD_THRESHOLD,
    UI_FALLBACK_CONFIDENCE,
    UI_KEYWORD_CONFIDENCE,
    ScreenshotOcrSignal,
    is_screenshot_named,
    route_screenshot_ocr,
)
from src.scoring.weights import W_UI

SCREENSHOTS_DICT = {
    "dashboard": "Media/Photos/Screenshots/Dashboard",
    "terminal_session": "Media/Photos/Screenshots/TerminalSession",
}
SCREENSHOT_PATH = Path("/pics/Screenshot 2026-01-01 at 09.00.png")


class FakeOcrClassify:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def __call__(self, path, content_classifier=None):
        self.calls.append((path, content_classifier))
        return self.result


def make_ctx(path=SCREENSHOT_PATH, schema_type="ImageObject"):
    return FileContext(path=Path(path), schema_type=schema_type)


def make_signal(result=None, screenshot_classifier=None):
    ocr = FakeOcrClassify(result)
    signal = ScreenshotOcrSignal(
        screenshot_classifier=screenshot_classifier,
        screenshots_dict=SCREENSHOTS_DICT,
        ocr_classify=ocr,
    )
    return signal, ocr


class TestSignalContract:
    def test_identity(self):
        signal, _ = make_signal()
        assert signal.name == "screenshot_ocr"
        assert signal.weight == W_UI
        assert signal.cost_tier == "mid"

    def test_scores_tagged_with_signal_name(self):
        signal, _ = make_signal(("dashboard", 0.25, {}, "cpu usage"))
        for score in signal.run(make_ctx()):
            assert score.signal_name == signal.name


class TestAppliesTo:
    def test_screenshot_named_image(self):
        signal, _ = make_signal()
        assert signal.applies_to(make_ctx())

    def test_non_image_rejected(self):
        signal, _ = make_signal()
        assert not signal.applies_to(make_ctx(schema_type="DigitalDocument"))

    def test_non_screenshot_name_rejected(self):
        signal, _ = make_signal()
        assert not signal.applies_to(make_ctx(path="/pics/vacation.png"))

    def test_structured_renamed_screenshot_rejected(self):
        # Already-classified names ("browser_*") bypass screenshot routing.
        signal, _ = make_signal()
        assert not signal.applies_to(make_ctx(path="/pics/browser_screenshot_1.png"))


class TestIsScreenshotNamed:
    def test_prefix_and_variants(self):
        assert is_screenshot_named("screenshot 2026-01-01 at 09.00")
        assert is_screenshot_named("screen shot 2020-05-01")
        assert is_screenshot_named("my_screenshot_edit")

    def test_renamed_prefixes_excluded(self):
        assert not is_screenshot_named("browser_screenshot_1")
        assert not is_screenshot_named("terminal_screenshot_2")
        assert not is_screenshot_named("vacation")


class TestRouteScreenshotOcr:
    def test_below_threshold_returns_none(self):
        assert route_screenshot_ocr("dashboard", 0.05, SCREENSHOTS_DICT) is None

    def test_threshold_boundary_routes(self):
        routed = route_screenshot_ocr(
            "dashboard", SCREENSHOT_OCR_KEYWORD_THRESHOLD, SCREENSHOTS_DICT
        )
        assert routed == ("media", "photos_screenshots_dashboard")

    def test_screenshot_key_routes_to_media(self):
        routed = route_screenshot_ocr("terminal_session", 0.25, SCREENSHOTS_DICT)
        assert routed == ("media", "photos_screenshots_terminal_session")

    def test_schema_category_reclassifies(self):
        routed = route_screenshot_ocr("financial_invoices", 0.5, SCREENSHOTS_DICT)
        assert routed == ("financial", "financial_invoices")

    def test_unroutable_category_returns_none(self):
        assert route_screenshot_ocr("weird", 0.5, SCREENSHOTS_DICT) is None


class TestRun:
    def test_keyword_routed_emission_plus_fallback(self):
        signal, _ = make_signal(("dashboard", 0.25, {}, "cpu usage graphs"))
        routed, fallback = signal.run(make_ctx())
        assert (routed.category, routed.subcategory) == ("media", "photos_screenshots_dashboard")
        assert routed.confidence == pytest.approx(UI_KEYWORD_CONFIDENCE)
        assert routed.evidence == {"keyword_ratio": 0.25, "ocr_category": "dashboard"}
        assert (fallback.category, fallback.subcategory) == ("media", "photos_screenshots_other")
        assert fallback.confidence == pytest.approx(UI_FALLBACK_CONFIDENCE)
        assert fallback.evidence == {"fallback": True}

    def test_cross_category_reclassification(self):
        signal, _ = make_signal(("financial_invoices", 0.5, {}, "invoice total due"))
        routed, _fallback = signal.run(make_ctx())
        assert (routed.category, routed.subcategory) == ("financial", "financial_invoices")

    def test_low_ratio_emits_only_fallback(self):
        signal, _ = make_signal(("dashboard", 0.05, {}, "noise"))
        (fallback,) = signal.run(make_ctx())
        assert (fallback.category, fallback.subcategory) == ("media", "photos_screenshots_other")
        assert fallback.confidence == pytest.approx(UI_FALLBACK_CONFIDENCE)

    def test_ocr_failure_emits_only_fallback(self):
        signal, _ = make_signal(None)
        (fallback,) = signal.run(make_ctx())
        assert (fallback.category, fallback.subcategory) == ("media", "photos_screenshots_other")

    def test_ocr_called_with_path_and_classifier(self):
        sentinel_classifier = object()
        signal, ocr = make_signal(None, screenshot_classifier=sentinel_classifier)
        ctx = make_ctx()
        signal.run(ctx)
        assert ocr.calls == [(ctx.path, sentinel_classifier)]

    def test_missing_ocr_backend_emits_only_fallback(self):
        with patch("src.scoring.signals.screenshot_ocr._default_ocr_classify", None):
            signal = ScreenshotOcrSignal(screenshots_dict=SCREENSHOTS_DICT)
            (fallback,) = signal.run(make_ctx())
        assert (fallback.category, fallback.subcategory) == ("media", "photos_screenshots_other")
