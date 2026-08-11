"""Unit tests for the screenshot title-snippet naming branch in
scripts/rename_images.py (ImageAnalyzer.analyze_image).

CLIP classification and OCR are patched at module level; no models load.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
_ROOT = _SCRIPTS_DIR.parent
for p in (str(_ROOT), str(_SCRIPTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import rename_images  # noqa: E402
from rename_images import PHOTO_PROFILE, SCREENSHOT_PROFILE, ImageAnalyzer  # noqa: E402
from shared.clip_classification import CLIPResult  # noqa: E402
from shared.status import ProcessingStatus  # noqa: E402

# A real CLIPResult, not a bare tuple: analyze_image reads .margin, so a 3-tuple
# stub would pass while the production 4-field result path went unexercised.
_CLIP_RESULT = CLIPResult(
    "a web browser or website", 0.82, {"a web browser or website": 0.82}, margin=2.0
)


@pytest.fixture()
def screenshot(tmp_path: Path) -> Path:
    path = tmp_path / "Screenshot 2026-01-01 at 09.00.png"
    path.write_bytes(b"\x89PNG")
    return path


def _analyze(
    image_path: Path,
    *,
    profile=SCREENSHOT_PROFILE,
    lines,
    detected_number=None,
    clip_result=_CLIP_RESULT,
):
    analyzer = ImageAnalyzer(profile)
    with patch.object(rename_images, "classify_with_ocr_fallback", return_value=clip_result), \
         patch.object(rename_images, "extract_screenshot_lines", return_value=lines), \
         patch.object(ImageAnalyzer, "_detect_number", return_value=detected_number), \
         patch.object(
             rename_images, "generate_clip_filename",
             side_effect=lambda p, label, mp: f"20260101_{label.replace(' ', '_')}{p.suffix}",
         ):
        return analyzer.analyze_image(image_path)


class TestScreenshotTitleSnippetNaming:
    def test_title_line_names_the_file(self, screenshot: Path) -> None:
        result = _analyze(screenshot, lines=["Order Confirmation - Amazon", "Thanks!"])
        assert result["new_name"] == "Screenshot_Order_Confirmation_-_Amazon.png"
        assert result["status"] == ProcessingStatus.PENDING

    def test_falls_back_to_clip_name_when_no_line_qualifies(self, screenshot: Path) -> None:
        result = _analyze(screenshot, lines=["File Edit", "View"])
        assert result["new_name"] == "20260101_a_web_browser_or_website.png"

    def test_falls_back_when_ocr_returns_nothing(self, screenshot: Path) -> None:
        result = _analyze(screenshot, lines=None)
        assert result["new_name"] == "20260101_a_web_browser_or_website.png"

    def test_photo_profile_never_uses_snippet(self, tmp_path: Path) -> None:
        photo = tmp_path / "IMG_1234.jpg"
        photo.write_bytes(b"\xff\xd8")
        result = _analyze(photo, profile=PHOTO_PROFILE, lines=["A Perfect Title Line"])
        assert result["new_name"] == "20260101_a_web_browser_or_website.jpg"

    def test_classification_fields_preserved_with_snippet(self, screenshot: Path) -> None:
        result = _analyze(screenshot, lines=["Order Confirmation - Amazon"])
        assert result["category"] == "a web browser or website"
        assert result["confidence"] == 0.82


def _photo(tmp_path: Path) -> Path:
    path = tmp_path / "IMG_1234.jpg"
    path.write_bytes(b"\xff\xd8")
    return path


def _result_with_margin(margin) -> CLIPResult:
    return CLIPResult("desk", 0.0114, {"desk": 0.0114, "bookshelf": 0.0113}, margin)


class TestLabelMarginGate:
    """A CLIP label only names a file when it beat the runner-up by enough.

    Absolute confidence can't gate this: the unscaled softmax pins every label
    near the uniform floor, so the argmax over a 94-label vocab is close to
    arbitrary in a near-tie (a hallway named "bedroom", a kitchen named "desk").
    """

    def test_undecided_label_does_not_rename(self, tmp_path: Path) -> None:
        result = _analyze(
            _photo(tmp_path),
            profile=PHOTO_PROFILE,
            lines=None,
            clip_result=_result_with_margin(1.001),
        )
        assert result.get("new_name") is None
        assert result["status"] == ProcessingStatus.SKIPPED
        assert "undecided" in result["error"]

    def test_decided_label_renames(self, tmp_path: Path) -> None:
        result = _analyze(
            _photo(tmp_path),
            profile=PHOTO_PROFILE,
            lines=None,
            clip_result=_result_with_margin(1.05),
        )
        assert result["new_name"] == "20260101_desk.jpg"
        assert result["status"] == ProcessingStatus.PENDING

    def test_diagnostics_survive_the_gate(self, tmp_path: Path) -> None:
        """The near-tie has to stay inspectable, or the skip is unexplainable."""
        result = _analyze(
            _photo(tmp_path),
            profile=PHOTO_PROFILE,
            lines=None,
            clip_result=_result_with_margin(1.001),
        )
        assert result["category"] == "desk"
        assert result["margin"] == 1.001
        assert result["top_scores"]

    def test_absent_margin_is_not_gated(self, tmp_path: Path) -> None:
        """``None`` means an OCR fallback or refinement chose the label, so there
        is no CLIP separation to judge -- gating it would suppress a good name."""
        result = _analyze(
            _photo(tmp_path),
            profile=PHOTO_PROFILE,
            lines=None,
            clip_result=_result_with_margin(None),
        )
        assert result["new_name"] == "20260101_desk.jpg"

    def test_screenshot_profile_is_ungated(self, screenshot: Path) -> None:
        """Enabling the gate here needs its own labelled eval: 75% of a sampled
        20 screenshots fall below the photo threshold while still agreeing with
        the folder they were filed into."""
        assert SCREENSHOT_PROFILE.min_label_margin == 1.0
        result = _analyze(screenshot, lines=None, clip_result=_result_with_margin(1.001))
        assert result["new_name"] == "20260101_desk.png"
