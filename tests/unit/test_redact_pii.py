"""Unit tests for scripts/redact_pii.py.

Covers:
- is_pii_token: digit/email/date/name/redact-terms matching
- detect_and_cover_barcodes: no-barcode path + mocked detection path
- redact (integration): manifest fields, --redact-terms wiring, barcode flags,
  non-zero exit on unlocalized barcode
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Import the module under test (scripts/ is not a package; add to sys.path)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import redact_pii  # noqa: E402


# ---------------------------------------------------------------------------
# is_pii_token
# ---------------------------------------------------------------------------

class TestIsPiiToken:
    def test_empty_string_is_not_pii(self):
        assert not redact_pii.is_pii_token("", [])

    def test_whitespace_only_is_not_pii(self):
        assert not redact_pii.is_pii_token("   ", [])

    def test_digit_run_is_pii(self):
        assert redact_pii.is_pii_token("12345", [])

    def test_short_digit_run_is_not_pii(self):
        # fewer than 3 digits — not matched
        assert not redact_pii.is_pii_token("12", [])

    def test_email_is_pii(self):
        assert redact_pii.is_pii_token("user@example.com", [])

    def test_date_slash_is_pii(self):
        assert redact_pii.is_pii_token("01/09/1954", [])

    def test_date_hyphen_is_pii(self):
        assert redact_pii.is_pii_token("12-31-2024", [])

    def test_plain_word_is_not_pii(self):
        assert not redact_pii.is_pii_token("hello", [])

    def test_name_term_substring_match(self):
        assert redact_pii.is_pii_token("Smith", ["smith"])

    def test_name_term_case_insensitive(self):
        assert redact_pii.is_pii_token("GRAVES", ["graves"])

    def test_name_term_not_in_word(self):
        assert not redact_pii.is_pii_token("healthy", ["graves"])

    def test_sensitive_term_health_condition(self):
        # OCR tokenises each word separately; pass individual word terms.
        # "Graves'" matches the term "graves'" (apostrophe included).
        assert redact_pii.is_pii_token("Graves'", ["graves'"])
        # "disease" matches the term "disease"
        assert redact_pii.is_pii_token("disease", ["disease"])

    def test_sensitive_term_partial_match(self):
        # Term "disease" → matches word "disease"
        assert redact_pii.is_pii_token("disease", ["disease"])

    def test_multiple_terms(self):
        assert redact_pii.is_pii_token("cancer", ["diabetes", "cancer", "arthritis"])
        assert not redact_pii.is_pii_token("tumor", ["diabetes", "cancer", "arthritis"])


# ---------------------------------------------------------------------------
# detect_and_cover_barcodes — no barcode on blank image
# ---------------------------------------------------------------------------

class TestDetectAndCoverBarcodesNoBarcode:
    def test_blank_image_returns_zero(self, tmp_path):
        png = tmp_path / "blank.png"
        Image.new("RGB", (100, 100), "white").save(png)
        detected, covered = redact_pii.detect_and_cover_barcodes(png)
        assert detected == 0
        assert covered == 0

    def test_blank_image_unchanged(self, tmp_path):
        png = tmp_path / "blank.png"
        original = Image.new("RGB", (200, 200), "white")
        original.save(png)
        redact_pii.detect_and_cover_barcodes(png)
        result = Image.open(png)
        assert result.size == (200, 200)

    def test_missing_cv2_returns_zero(self, tmp_path):
        png = tmp_path / "blank.png"
        Image.new("RGB", (100, 100), "white").save(png)
        with patch.dict(sys.modules, {"cv2": None}):
            detected, covered = redact_pii.detect_and_cover_barcodes(png)
        assert (detected, covered) == (0, 0)


# ---------------------------------------------------------------------------
# detect_and_cover_barcodes — mocked barcode detection
# ---------------------------------------------------------------------------

class TestDetectAndCoverBarcodesMocked:
    """Test barcode coverage logic without needing a real barcode image."""

    def _make_png(self, tmp_path: Path, size: tuple[int, int] = (400, 200)) -> Path:
        png = tmp_path / "test.png"
        Image.new("RGB", size, "white").save(png)
        return png

    def test_barcode_detected_and_covered(self, tmp_path):
        import numpy as np

        png = self._make_png(tmp_path)
        # Fake one barcode at top-left quadrant: corners (10,10) (110,10) (110,60) (10,60)
        fake_pts = np.array([[[10, 10], [110, 10], [110, 60], [10, 60]]], dtype=np.float32)

        mock_bd = MagicMock()
        mock_bd.detectMulti.return_value = (True, fake_pts)
        mock_qr = MagicMock()
        mock_qr.detectMulti.return_value = (False, None)

        # cv2 is lazily imported inside detect_and_cover_barcodes; patch via sys.modules
        mock_cv2 = MagicMock()
        mock_cv2.imread.return_value = MagicMock()  # non-None so we proceed
        mock_cv2.barcode_BarcodeDetector.return_value = mock_bd
        mock_cv2.QRCodeDetector.return_value = mock_qr

        with patch.dict(sys.modules, {"cv2": mock_cv2, "numpy": np}):
            detected, covered = redact_pii.detect_and_cover_barcodes(png)

        assert detected == 1
        assert covered == 1

    def test_degenerate_polygon_counted_as_unlocalized(self, tmp_path):
        import numpy as np

        png = self._make_png(tmp_path)
        # A degenerate polygon with only 2 points (< 3 required)
        fake_pts = np.array([[[10, 10], [20, 20]]], dtype=np.float32)

        mock_bd = MagicMock()
        mock_bd.detectMulti.return_value = (True, fake_pts)
        mock_qr = MagicMock()
        mock_qr.detectMulti.return_value = (False, None)

        mock_cv2 = MagicMock()
        mock_cv2.imread.return_value = MagicMock()
        mock_cv2.barcode_BarcodeDetector.return_value = mock_bd
        mock_cv2.QRCodeDetector.return_value = mock_qr

        with patch.dict(sys.modules, {"cv2": mock_cv2, "numpy": np}):
            detected, covered = redact_pii.detect_and_cover_barcodes(png)

        assert detected == 1
        assert covered == 0

    def test_qr_native_shape_detected_and_covered(self, tmp_path):
        import numpy as np

        png = self._make_png(tmp_path)
        # QRCodeDetector.detectMulti native (N,4,2) shape — ndim==2 per poly,
        # so the reshape branch is skipped and the polygon is used directly
        fake_pts = np.array(
            [[[10, 10], [110, 10], [110, 110], [10, 110]]], dtype=np.float32
        )

        mock_bd = MagicMock()
        mock_bd.detectMulti.return_value = (False, None)
        mock_qr = MagicMock()
        mock_qr.detectMulti.return_value = (True, fake_pts)

        mock_cv2 = MagicMock()
        mock_cv2.imread.return_value = MagicMock()
        mock_cv2.barcode_BarcodeDetector.return_value = mock_bd
        mock_cv2.QRCodeDetector.return_value = mock_qr

        with patch.dict(sys.modules, {"cv2": mock_cv2, "numpy": np}):
            detected, covered = redact_pii.detect_and_cover_barcodes(png)

        assert detected == 1
        assert covered == 1

    def test_imread_none_returns_zero(self, tmp_path):
        import numpy as np

        png = self._make_png(tmp_path)

        mock_cv2 = MagicMock()
        mock_cv2.imread.return_value = None  # unreadable image

        with patch.dict(sys.modules, {"cv2": mock_cv2, "numpy": np}):
            detected, covered = redact_pii.detect_and_cover_barcodes(png)

        assert (detected, covered) == (0, 0)
        mock_cv2.barcode_BarcodeDetector.assert_not_called()
        mock_cv2.QRCodeDetector.assert_not_called()

    def test_no_barcodes_detected(self, tmp_path):
        import numpy as np

        png = self._make_png(tmp_path)

        mock_bd = MagicMock()
        mock_bd.detectMulti.return_value = (False, None)
        mock_qr = MagicMock()
        mock_qr.detectMulti.return_value = (False, None)

        mock_cv2 = MagicMock()
        mock_cv2.imread.return_value = MagicMock()
        mock_cv2.barcode_BarcodeDetector.return_value = mock_bd
        mock_cv2.QRCodeDetector.return_value = mock_qr

        with patch.dict(sys.modules, {"cv2": mock_cv2, "numpy": np}):
            detected, covered = redact_pii.detect_and_cover_barcodes(png)

        assert detected == 0
        assert covered == 0


# ---------------------------------------------------------------------------
# redact() integration — manifest fields and --redact-terms wiring
# ---------------------------------------------------------------------------

class TestRedactIntegration:
    """Integration tests using stub docTR + blank PNG inputs."""

    def _make_doctr_stub(self):
        """Return a stub docTR model that returns an empty page (no words)."""
        word = MagicMock()
        word.value = "hello"
        word.geometry = ((0.1, 0.1), (0.3, 0.2))

        line = MagicMock()
        line.words = []

        block = MagicMock()
        block.lines = [line]

        page = MagicMock()
        page.blocks = [block]

        doc_result = MagicMock()
        doc_result.pages = [page]

        model = MagicMock(return_value=doc_result)
        return model

    def _stub_doctr(self):
        """Patch doctr imports so redact_raster doesn't need the real model."""
        doctr_io = types.ModuleType("doctr.io")
        doctr_models = types.ModuleType("doctr.models")

        fake_doc = MagicMock()
        doctr_io.DocumentFile = MagicMock()
        doctr_io.DocumentFile.from_images = MagicMock(return_value=fake_doc)

        model = self._make_doctr_stub()
        doctr_models.ocr_predictor = MagicMock(return_value=model)

        doctr_root = types.ModuleType("doctr")
        doctr_root.io = doctr_io
        doctr_root.models = doctr_models

        return {
            "doctr": doctr_root,
            "doctr.io": doctr_io,
            "doctr.models": doctr_models,
        }

    def test_image_manifest_has_barcode_fields(self, tmp_path):
        src = tmp_path / "photo.jpg"
        Image.new("RGB", (100, 100), "white").save(src, "JPEG")
        out_dir = tmp_path / "out"

        with patch.dict(sys.modules, self._stub_doctr()):
            manifest = redact_pii.redact([src], out_dir, dpi=72, name_terms=[])

        entry = manifest[0]
        assert entry["status"] == "redacted"
        assert "barcode_detected" in entry
        assert "barcode_covered" in entry
        assert "barcode_unredacted" in entry
        assert entry["barcode_detected"] == 0
        assert entry["barcode_covered"] == 0
        assert entry["barcode_unredacted"] is False

    def test_sensitive_terms_passed_to_is_pii_token(self, tmp_path):
        """--redact-terms terms reach the OCR token filter."""
        src = tmp_path / "health.jpg"
        Image.new("RGB", (100, 100), "white").save(src, "JPEG")
        out_dir = tmp_path / "out"

        # Build a stub model that returns one word "diabetes" on the page
        word = MagicMock()
        word.value = "diabetes"
        word.geometry = ((0.1, 0.1), (0.5, 0.2))
        line = MagicMock()
        line.words = [word]
        block = MagicMock()
        block.lines = [line]
        page = MagicMock()
        page.blocks = [block]
        doc_result = MagicMock()
        doc_result.pages = [page]
        model = MagicMock(return_value=doc_result)

        doctr_io = types.ModuleType("doctr.io")
        doctr_models = types.ModuleType("doctr.models")
        doctr_io.DocumentFile = MagicMock()
        doctr_io.DocumentFile.from_images = MagicMock(return_value=MagicMock())
        doctr_models.ocr_predictor = MagicMock(return_value=model)
        doctr_root = types.ModuleType("doctr")
        doctr_root.io = doctr_io
        doctr_root.models = doctr_models
        stubs = {"doctr": doctr_root, "doctr.io": doctr_io, "doctr.models": doctr_models}

        with patch.dict(sys.modules, stubs):
            manifest = redact_pii.redact(
                [src], out_dir, dpi=72,
                name_terms=[],
                sensitive_terms=["diabetes"],
            )

        entry = manifest[0]
        # boxes_blacked == 1 means the "diabetes" word was caught
        assert entry["boxes_blacked"] == 1

    def test_manifest_written_to_disk(self, tmp_path):
        src = tmp_path / "img.png"
        Image.new("RGB", (50, 50), "white").save(src)
        out_dir = tmp_path / "out"

        with patch.dict(sys.modules, self._stub_doctr()):
            redact_pii.redact([src], out_dir, dpi=72, name_terms=[])

        manifest_path = out_dir / "manifest.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["status"] == "redacted"

    def test_text_file_no_barcode_fields(self, tmp_path):
        src = tmp_path / "notes.txt"
        src.write_text("My email is user@example.com and SSN is 123-45-6789")
        out_dir = tmp_path / "out"

        manifest = redact_pii.redact([src], out_dir, dpi=72, name_terms=[])
        entry = manifest[0]
        assert entry["status"] == "redacted"
        assert "barcode_detected" not in entry

    def test_barcode_unredacted_flag_true_when_unlocalized(self, tmp_path):
        """Manifest sets barcode_unredacted=True when covered < detected."""
        src = tmp_path / "id.jpg"
        Image.new("RGB", (200, 200), "white").save(src, "JPEG")
        out_dir = tmp_path / "out"

        # Patch detect_and_cover_barcodes to simulate 1 detected, 0 covered
        with (
            patch.object(redact_pii, "detect_and_cover_barcodes", return_value=(1, 0)),
            patch.dict(sys.modules, self._stub_doctr()),
        ):
            manifest = redact_pii.redact([src], out_dir, dpi=72, name_terms=[])

        entry = manifest[0]
        assert entry["barcode_detected"] == 1
        assert entry["barcode_covered"] == 0
        assert entry["barcode_unredacted"] is True


# ---------------------------------------------------------------------------
# main() exit code
# ---------------------------------------------------------------------------

class TestMainExitCode:
    def test_main_returns_zero_on_clean_run(self, tmp_path, monkeypatch):
        src = tmp_path / "clean.txt"
        src.write_text("no pii here")
        out_dir = tmp_path / "out"
        monkeypatch.setattr(
            sys, "argv",
            ["redact_pii.py", str(src), "--output", str(out_dir)],
        )
        assert redact_pii.main() == 0

    def test_main_returns_one_on_unredacted_barcode(self, tmp_path, monkeypatch):
        src = tmp_path / "id.jpg"
        Image.new("RGB", (200, 200), "white").save(src, "JPEG")
        out_dir = tmp_path / "out"
        monkeypatch.setattr(
            sys, "argv",
            ["redact_pii.py", str(src), "--output", str(out_dir)],
        )

        import types as _types
        doctr_io = _types.ModuleType("doctr.io")
        doctr_models = _types.ModuleType("doctr.models")
        doctr_io.DocumentFile = MagicMock()
        doctr_io.DocumentFile.from_images = MagicMock(return_value=MagicMock())
        model = MagicMock(return_value=MagicMock(pages=[MagicMock(blocks=[])]))
        doctr_models.ocr_predictor = MagicMock(return_value=model)
        doctr_root = _types.ModuleType("doctr")
        doctr_root.io = doctr_io
        doctr_root.models = doctr_models
        stubs = {"doctr": doctr_root, "doctr.io": doctr_io, "doctr.models": doctr_models}

        with (
            patch.object(redact_pii, "detect_and_cover_barcodes", return_value=(1, 0)),
            patch.dict(sys.modules, stubs),
        ):
            exit_code = redact_pii.main()

        assert exit_code == 1
