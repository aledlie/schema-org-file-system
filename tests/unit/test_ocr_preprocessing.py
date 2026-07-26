"""Unit tests for dark-background OCR preprocessing in shared/ocr_classifier.

These cover the pure preprocessing helpers (luminance/inversion/CLAHE) and the
new IDE/browser screenshot keyword routing. The docTR model itself is not
exercised (and may be unavailable); OCR text is stubbed where needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import shared.ocr_classifier as oc  # noqa: E402

pytestmark = pytest.mark.skipif(not oc._PREPROCESS_AVAILABLE, reason="PIL/numpy not available")


def _make_image(path: Path, color: tuple[int, int, int], size=(120, 60)) -> Path:
    from PIL import Image

    Image.new("RGB", size, color).save(path)
    return path


# ---------------------------------------------------------------------------
# Dark-background detection + inversion
# ---------------------------------------------------------------------------


class TestDarkBackgroundDetection:
    def test_dark_image_detected(self, temp_dir: Path) -> None:
        p = _make_image(temp_dir / "dark.png", (15, 15, 20))
        assert oc.is_dark_background(p) is True

    def test_bright_image_not_dark(self, temp_dir: Path) -> None:
        p = _make_image(temp_dir / "bright.png", (240, 240, 240))
        assert oc.is_dark_background(p) is False

    def test_threshold_boundary(self, temp_dir: Path) -> None:
        below = int(oc._DARK_BACKGROUND_LUMINANCE_THRESHOLD) - 10
        above = int(oc._DARK_BACKGROUND_LUMINANCE_THRESHOLD) + 10
        assert oc.is_dark_background(_make_image(temp_dir / "b.png", (below,) * 3)) is True
        assert oc.is_dark_background(_make_image(temp_dir / "a.png", (above,) * 3)) is False

    def test_missing_file_is_not_dark(self, temp_dir: Path) -> None:
        assert oc.is_dark_background(temp_dir / "nope.png") is False


class TestPreprocessForOcr:
    def test_dark_image_is_inverted(self, temp_dir: Path) -> None:
        p = _make_image(temp_dir / "dark.png", (15, 15, 20))
        arr = oc.preprocess_for_ocr(p, enhance=False)
        assert arr is not None
        # Inversion turns a near-black page into a near-white one.
        assert arr.mean() > 200

    def test_bright_image_no_preprocessing(self, temp_dir: Path) -> None:
        # Bright + no enhancement → None so the caller uses the original path
        # unchanged (zero regression for the common document case).
        p = _make_image(temp_dir / "bright.png", (240, 240, 240))
        assert oc.preprocess_for_ocr(p, enhance=False) is None

    @pytest.mark.skipif(not oc._CV2_AVAILABLE, reason="cv2 not available")
    def test_enhance_returns_clahe_array(self, temp_dir: Path) -> None:
        p = _make_image(temp_dir / "bright.png", (200, 200, 200))
        arr = oc.preprocess_for_ocr(p, enhance=True)
        assert arr is not None
        assert arr.dtype.name == "uint8"
        assert arr.shape[2] == 3

    def test_missing_file_returns_none(self, temp_dir: Path) -> None:
        assert oc.preprocess_for_ocr(temp_dir / "nope.png", enhance=True) is None


# ---------------------------------------------------------------------------
# New IDE / browser screenshot keyword routing
# ---------------------------------------------------------------------------


class TestScreenshotKeywordRouting:
    def test_new_categories_present(self) -> None:
        assert "code" in oc.SCREENSHOT_KEYWORDS
        assert "browser" in oc.SCREENSHOT_KEYWORDS

    def _classify(self, monkeypatch, text: str):
        monkeypatch.setattr(oc, "OCR_AVAILABLE", True)
        monkeypatch.setattr(oc, "is_ocr_available", lambda: True)
        monkeypatch.setattr(oc, "extract_ocr_text", lambda *a, **k: text)
        return oc.classify_by_ocr(Path("/x/shot.png"))

    def test_ide_code_routes_to_code(self, monkeypatch) -> None:
        res = self._classify(
            monkeypatch,
            "import os\nclass Foo:\n    def bar(self):\n        return 1\nconst x = () => {}",
        )
        assert res is not None and res[0] == "code"

    def test_browser_routes_to_browser(self, monkeypatch) -> None:
        res = self._classify(
            monkeypatch, "https://example.com www.google.com search new tab bookmarks"
        )
        assert res is not None and res[0] == "browser"

    def test_terminal_still_routes_to_terminal_session(self, monkeypatch) -> None:
        res = self._classify(
            monkeypatch, "$ npm run build\ngit commit -m x\nexit code 0\ncommand: deploy"
        )
        assert res is not None and res[0] == "terminal_session"

    def test_single_hit_below_min_does_not_classify(self, monkeypatch) -> None:
        # One keyword hit is below SCREENSHOT_MIN_HITS; no screenshot label.
        res = self._classify(monkeypatch, "just one import here and nothing else relevant")
        assert res is None or res[0] not in {"code", "browser"}


class TestScreenshotOCRBackendSelection:
    """extract_screenshot_text prefers easyocr, falls back to docTR."""

    def test_prefers_easyocr_when_available(self, monkeypatch) -> None:
        monkeypatch.setattr(oc, "EASYOCR_AVAILABLE", True)
        monkeypatch.setattr(oc, "extract_text_easyocr", lambda *a, **k: "from easyocr")
        monkeypatch.setattr(oc, "extract_ocr_text", lambda *a, **k: "from doctr")
        assert oc.extract_screenshot_text(Path("/x/shot.png")) == "from easyocr"

    def test_falls_back_to_doctr_when_easyocr_returns_none(self, monkeypatch) -> None:
        monkeypatch.setattr(oc, "EASYOCR_AVAILABLE", True)
        monkeypatch.setattr(oc, "extract_text_easyocr", lambda *a, **k: None)
        monkeypatch.setattr(oc, "extract_ocr_text", lambda *a, **k: "from doctr")
        assert oc.extract_screenshot_text(Path("/x/shot.png")) == "from doctr"

    def test_uses_doctr_when_easyocr_unavailable(self, monkeypatch) -> None:
        monkeypatch.setattr(oc, "EASYOCR_AVAILABLE", False)
        monkeypatch.setattr(oc, "extract_ocr_text", lambda *a, **k: "from doctr")
        assert oc.extract_screenshot_text(Path("/x/shot.png")) == "from doctr"
