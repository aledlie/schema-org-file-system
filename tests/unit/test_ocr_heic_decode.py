"""Tests for HEIC OCR decode hand-off (backlog P2: HEIC never reaches OCR).

Both OCR providers (easyocr, docTR) read image files themselves and cannot
handle HEIC containers.  The fix decodes once via PIL (already HEIF-capable)
and passes the pixel array to each backend instead of a file path.

easyocr path: _readtext_input must return ndarray for .heic/.heif
docTR path:   _run_image_ocr must not call DocumentFile.from_images for HEIC
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import shared.ocr_easyocr as easyocr_mod  # noqa: E402
import shared.ocr_classifier as ocr_mod  # noqa: E402

pytestmark = pytest.mark.skipif(
    not ocr_mod._PREPROCESS_AVAILABLE,
    reason="PIL/numpy not available",
)


def _fake_pil_image(width: int = 4, height: int = 4, color: tuple = (200, 200, 200)):
    """Return a minimal real PIL RGB image for use as a mock return value."""
    from PIL import Image

    return Image.new("RGB", (width, height), color=color)


# ---------------------------------------------------------------------------
# easyocr path: _readtext_input
# ---------------------------------------------------------------------------


class TestReadtextInputHeic:
    """_readtext_input must return an ndarray for HEIC/HEIF, str for other types."""

    def test_heic_returns_ndarray(self, tmp_path: Path) -> None:
        heic_path = tmp_path / "photo.heic"
        heic_path.write_bytes(b"fake-heic-data")
        fake_img = _fake_pil_image()

        with patch("PIL.Image.open", return_value=fake_img):
            result = easyocr_mod._readtext_input(heic_path)

        assert isinstance(result, np.ndarray), f"expected ndarray for .heic, got {type(result)}"
        assert result.shape == (4, 4, 3)

    def test_heif_returns_ndarray(self, tmp_path: Path) -> None:
        heif_path = tmp_path / "photo.heif"
        heif_path.write_bytes(b"fake-heif-data")
        fake_img = _fake_pil_image()

        with patch("PIL.Image.open", return_value=fake_img):
            result = easyocr_mod._readtext_input(heif_path)

        assert isinstance(result, np.ndarray), f"expected ndarray for .heif, got {type(result)}"

    def test_png_still_returns_str_path(self, tmp_path: Path) -> None:
        """Non-HEIC images without multiple frames keep the str-path fast path."""
        png_path = tmp_path / "photo.png"
        png_path.write_bytes(b"fake-png")
        fake_img = _fake_pil_image()

        with patch("PIL.Image.open", return_value=fake_img):
            result = easyocr_mod._readtext_input(png_path)

        assert result == str(png_path), "expected str path for .png, got ndarray"

    def test_animated_gif_still_returns_ndarray(self, tmp_path: Path) -> None:
        """Animated images keep their existing ndarray path (unaffected by change)."""
        gif_path = tmp_path / "anim.gif"
        gif_path.write_bytes(b"fake-gif")

        fake_img = _fake_pil_image()
        fake_img.n_frames = 3  # simulate animated

        with patch("PIL.Image.open", return_value=fake_img):
            result = easyocr_mod._readtext_input(gif_path)

        assert isinstance(result, np.ndarray)

    def test_case_insensitive_heic(self, tmp_path: Path) -> None:
        upper_path = tmp_path / "IMG_1234.HEIC"
        upper_path.write_bytes(b"fake")
        fake_img = _fake_pil_image()

        with patch("PIL.Image.open", return_value=fake_img):
            result = easyocr_mod._readtext_input(upper_path)

        assert isinstance(result, np.ndarray)


# ---------------------------------------------------------------------------
# docTR path: _run_image_ocr
# ---------------------------------------------------------------------------


class TestRunImageOcrHeic:
    """_run_image_ocr must not call DocumentFile.from_images for HEIC/HEIF."""

    def _setup_predictor(self, monkeypatch, text: str = ""):
        """Wire a fake predictor that captures the doc argument."""
        received: list[list] = []

        class _FakeResult:
            def render(self) -> str:
                return text

        def _fake_predictor(doc):
            received.append(list(doc))
            return _FakeResult()

        monkeypatch.setattr(ocr_mod, "OCR_AVAILABLE", True)
        monkeypatch.setattr(ocr_mod, "_get_predictor", lambda: _fake_predictor)
        return received

    def test_heic_uses_pixel_array_not_document_file(self, tmp_path: Path, monkeypatch) -> None:
        heic_path = tmp_path / "photo.heic"
        heic_path.write_bytes(b"fake-heic")

        # preprocess_for_ocr returns None for a light (non-dark) image
        monkeypatch.setattr(ocr_mod, "preprocess_for_ocr", lambda path, **_: None)
        monkeypatch.setattr(ocr_mod, "_PREPROCESS_AVAILABLE", True)

        fake_img = _fake_pil_image()
        monkeypatch.setattr(ocr_mod, "_load_rgb", lambda path: fake_img)

        received = self._setup_predictor(monkeypatch)

        # DocumentFile.from_images must NOT be reached for HEIC
        class _GuardedDocumentFile:
            @staticmethod
            def from_images(paths):
                raise AssertionError(
                    f"DocumentFile.from_images must not be called for HEIC; got {paths}"
                )

        monkeypatch.setattr(ocr_mod, "DocumentFile", _GuardedDocumentFile)

        ocr_mod._run_image_ocr(heic_path)

        assert len(received) == 1, "predictor should have been called once"
        assert isinstance(
            received[0][0], np.ndarray
        ), "predictor should receive ndarray for HEIC, not a str"

    def test_heif_uses_pixel_array(self, tmp_path: Path, monkeypatch) -> None:
        heif_path = tmp_path / "photo.heif"
        heif_path.write_bytes(b"fake-heif")

        monkeypatch.setattr(ocr_mod, "preprocess_for_ocr", lambda path, **_: None)
        monkeypatch.setattr(ocr_mod, "_PREPROCESS_AVAILABLE", True)

        fake_img = _fake_pil_image()
        monkeypatch.setattr(ocr_mod, "_load_rgb", lambda path: fake_img)

        received = self._setup_predictor(monkeypatch)

        class _GuardedDocumentFile:
            @staticmethod
            def from_images(paths):
                raise AssertionError("DocumentFile.from_images must not be called for HEIF")

        monkeypatch.setattr(ocr_mod, "DocumentFile", _GuardedDocumentFile)
        ocr_mod._run_image_ocr(heif_path)

        assert isinstance(received[0][0], np.ndarray)

    def test_png_still_uses_document_file_when_no_preprocessing(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Non-HEIC images with no preprocessing still go through DocumentFile."""
        png_path = tmp_path / "photo.png"
        png_path.write_bytes(b"fake-png")

        monkeypatch.setattr(ocr_mod, "preprocess_for_ocr", lambda path, **_: None)
        monkeypatch.setattr(ocr_mod, "_PREPROCESS_AVAILABLE", True)

        document_file_called: list[bool] = []

        class _FakeResult:
            def render(self) -> str:
                return ""

        def _fake_predictor(doc):
            return _FakeResult()

        monkeypatch.setattr(ocr_mod, "OCR_AVAILABLE", True)
        monkeypatch.setattr(ocr_mod, "_get_predictor", lambda: _fake_predictor)

        class _TrackingDocumentFile:
            @staticmethod
            def from_images(paths):
                document_file_called.append(True)
                return ["fake_page"]

        monkeypatch.setattr(ocr_mod, "DocumentFile", _TrackingDocumentFile)
        ocr_mod._run_image_ocr(png_path)

        assert document_file_called, "DocumentFile.from_images must be called for PNG"

    def test_heic_decode_failure_returns_none_without_calling_document_file(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Corrupted HEIC where _load_rgb returns None must not reach DocumentFile."""
        heic_path = tmp_path / "corrupt.heic"
        heic_path.write_bytes(b"not-valid-heic")

        monkeypatch.setattr(ocr_mod, "preprocess_for_ocr", lambda path, **_: None)
        monkeypatch.setattr(ocr_mod, "_PREPROCESS_AVAILABLE", True)
        # Simulate decode failure
        monkeypatch.setattr(ocr_mod, "_load_rgb", lambda path: None)

        self._setup_predictor(monkeypatch)

        class _GuardedDocumentFile:
            @staticmethod
            def from_images(paths):
                raise AssertionError(
                    "DocumentFile.from_images must not be called when HEIC decode fails"
                )

        monkeypatch.setattr(ocr_mod, "DocumentFile", _GuardedDocumentFile)

        result = ocr_mod._run_image_ocr(heic_path)
        assert result is None  # fails gracefully, no exception propagated

    def test_dark_heic_uses_preprocess_result(self, tmp_path: Path, monkeypatch) -> None:
        """A dark HEIC image is handled by preprocess_for_ocr (unchanged path)."""
        heic_path = tmp_path / "dark.heic"
        heic_path.write_bytes(b"fake-dark-heic")

        # preprocess_for_ocr returns an array for dark images; CLAHE retry
        # (enhance=True) returns None so the retry is skipped and the predictor
        # is called exactly once.
        dark_array = np.zeros((4, 4, 3), dtype=np.uint8)

        def _fake_preprocess(path, enhance=False, **_):
            return dark_array if not enhance else None

        monkeypatch.setattr(ocr_mod, "preprocess_for_ocr", _fake_preprocess)

        received = self._setup_predictor(monkeypatch)

        class _GuardedDocumentFile:
            @staticmethod
            def from_images(paths):
                raise AssertionError("DocumentFile.from_images must not be called")

        monkeypatch.setattr(ocr_mod, "DocumentFile", _GuardedDocumentFile)

        ocr_mod._run_image_ocr(heic_path)

        assert len(received) == 1
        assert np.array_equal(received[0][0], dark_array)

    def test_heic_does_not_fall_through_to_document_file_when_preprocess_unavailable(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """HEIC must not reach DocumentFile.from_images even when _PREPROCESS_AVAILABLE
        is False (e.g. PIL/numpy not installed).  Formerly the _PREPROCESS_AVAILABLE
        gate short-circuited the PIL decode path and the file fell through to
        DocumentFile.from_images, which raises ValueError for HEIC containers.
        After the fix the HEIC extension check is unconditional and _load_rgb catches
        any import error, so the function returns None rather than propagating."""
        heic_path = tmp_path / "photo.heic"
        heic_path.write_bytes(b"fake-heic")

        # Simulate preprocessing deps absent
        monkeypatch.setattr(ocr_mod, "_PREPROCESS_AVAILABLE", False)
        monkeypatch.setattr(ocr_mod, "preprocess_for_ocr", lambda path, **_: None)
        # Simulate _load_rgb returning None as it would when PIL is absent
        monkeypatch.setattr(ocr_mod, "_load_rgb", lambda path: None)

        self._setup_predictor(monkeypatch)

        class _GuardedDocumentFile:
            @staticmethod
            def from_images(paths):
                raise AssertionError(
                    "DocumentFile.from_images must not be called for HEIC when "
                    "_PREPROCESS_AVAILABLE is False — spurious gate was not removed"
                )

        monkeypatch.setattr(ocr_mod, "DocumentFile", _GuardedDocumentFile)

        result = ocr_mod._run_image_ocr(heic_path)
        # _load_rgb returned None → early return, no DocumentFile call, no exception
        assert result is None

    def test_heic_array_conversion_failure_returns_none(self, tmp_path: Path, monkeypatch) -> None:
        """np.asarray guard returns None instead of propagating or falling through.

        The scenario "PIL present, numpy raises" cannot occur in production today
        because numpy is imported before PIL in the same try block — a missing
        numpy leaves PIL unbound too and _load_rgb returns None first.  The guard
        is defense-in-depth against future import reordering; this test verifies
        its behaviour by monkeypatching np directly.
        """
        heic_path = tmp_path / "photo.heic"
        heic_path.write_bytes(b"fake-heic")

        monkeypatch.setattr(ocr_mod, "preprocess_for_ocr", lambda path, **_: None)
        monkeypatch.setattr(ocr_mod, "_PREPROCESS_AVAILABLE", True)

        fake_img = _fake_pil_image()
        monkeypatch.setattr(ocr_mod, "_load_rgb", lambda path: fake_img)

        # Simulate np.asarray raising (e.g. numpy not installed → NameError)
        class _BrokenNp:
            @staticmethod
            def asarray(*args, **kwargs):
                raise NameError("name 'np' is not defined")

        monkeypatch.setattr(ocr_mod, "np", _BrokenNp())

        self._setup_predictor(monkeypatch)

        class _GuardedDocumentFile:
            @staticmethod
            def from_images(paths):
                raise AssertionError(
                    "DocumentFile.from_images must not be called when np.asarray fails"
                )

        monkeypatch.setattr(ocr_mod, "DocumentFile", _GuardedDocumentFile)

        result = ocr_mod._run_image_ocr(heic_path)
        assert result is None
