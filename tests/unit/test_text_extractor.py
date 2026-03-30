"""
Unit tests for src/analyzers/text_extractor.py.

All heavy optional dependencies (doctr, pypdf, python-docx, openpyxl)
are mocked so the tests run without those libraries installed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure src/ is on the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))


# ---------------------------------------------------------------------------
# extract_text_from_image
# ---------------------------------------------------------------------------

class TestExtractTextFromImage:
    def test_returns_string_when_ocr_available(self, tmp_path):
        fake_image = tmp_path / "test.png"
        fake_image.write_bytes(b"fake")

        with (
            patch("src.analyzers.text_extractor.OCR_AVAILABLE", True),
            patch("src.analyzers.text_extractor.extract_ocr_text", return_value="hello world"),
        ):
            from src.analyzers.text_extractor import TextExtractor
            extractor = TextExtractor()
            extractor.ocr_available = True

            result = extractor.extract_text_from_image(fake_image)

        assert isinstance(result, str)
        assert result == "hello world"

    def test_returns_empty_when_ocr_unavailable(self, tmp_path):
        fake_image = tmp_path / "test.png"
        fake_image.write_bytes(b"fake")

        from src.analyzers.text_extractor import TextExtractor
        extractor = TextExtractor()
        extractor.ocr_available = False

        result = extractor.extract_text_from_image(fake_image)
        assert result == ""

    def test_returns_empty_on_exception(self, tmp_path):
        fake_image = tmp_path / "test.png"
        fake_image.write_bytes(b"fake")

        with patch(
            "src.analyzers.text_extractor.extract_ocr_text",
            side_effect=RuntimeError("bad image"),
        ):
            from src.analyzers.text_extractor import TextExtractor
            extractor = TextExtractor()
            extractor.ocr_available = True

            result = extractor.extract_text_from_image(fake_image)

        assert result == ""


# ---------------------------------------------------------------------------
# extract_text_from_pdf
# ---------------------------------------------------------------------------

class TestExtractTextFromPdf:
    def test_returns_string_from_searchable_pdf(self, tmp_path):
        fake_pdf = tmp_path / "test.pdf"
        fake_pdf.write_bytes(b"fake")

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "A" * 200

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        with (
            patch("src.analyzers.text_extractor.OCR_AVAILABLE", True),
            patch("src.analyzers.text_extractor.pypdf") as mock_pypdf,
        ):
            mock_pypdf.PdfReader.return_value = mock_reader

            from src.analyzers.text_extractor import TextExtractor
            extractor = TextExtractor()
            extractor.ocr_available = True

            result = extractor.extract_text_from_pdf(fake_pdf)

        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_empty_when_ocr_unavailable(self, tmp_path):
        fake_pdf = tmp_path / "test.pdf"
        fake_pdf.write_bytes(b"fake")

        from src.analyzers.text_extractor import TextExtractor
        extractor = TextExtractor()
        extractor.ocr_available = False

        result = extractor.extract_text_from_pdf(fake_pdf)
        assert result == ""

    def test_returns_empty_on_exception(self, tmp_path):
        fake_pdf = tmp_path / "test.pdf"
        fake_pdf.write_bytes(b"fake")

        with patch("src.analyzers.text_extractor.pypdf") as mock_pypdf:
            mock_pypdf.PdfReader.side_effect = Exception("corrupt pdf")

            from src.analyzers.text_extractor import TextExtractor
            extractor = TextExtractor()
            extractor.ocr_available = True

            result = extractor.extract_text_from_pdf(fake_pdf)

        assert result == ""


# ---------------------------------------------------------------------------
# extract_text_from_docx
# ---------------------------------------------------------------------------

class TestExtractTextFromDocx:
    def test_returns_string_when_docx_available(self, tmp_path):
        fake_docx = tmp_path / "test.docx"
        fake_docx.write_bytes(b"fake")

        mock_para = MagicMock()
        mock_para.text = "Hello from docx"

        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_para]
        mock_doc.tables = []

        with (
            patch("src.analyzers.text_extractor.DOCX_AVAILABLE", True),
            patch("src.analyzers.text_extractor.Document", return_value=mock_doc),
        ):
            from src.analyzers.text_extractor import TextExtractor
            extractor = TextExtractor()

            result = extractor.extract_text_from_docx(fake_docx)

        assert isinstance(result, str)
        assert "Hello from docx" in result

    def test_returns_empty_when_docx_unavailable(self, tmp_path):
        fake_docx = tmp_path / "test.docx"
        fake_docx.write_bytes(b"fake")

        with patch("src.analyzers.text_extractor.DOCX_AVAILABLE", False):
            from src.analyzers.text_extractor import TextExtractor
            extractor = TextExtractor()
            result = extractor.extract_text_from_docx(fake_docx)

        assert result == ""

    def test_returns_empty_on_exception(self, tmp_path):
        fake_docx = tmp_path / "test.docx"
        fake_docx.write_bytes(b"fake")

        with (
            patch("src.analyzers.text_extractor.DOCX_AVAILABLE", True),
            patch("src.analyzers.text_extractor.Document", side_effect=Exception("bad docx")),
        ):
            from src.analyzers.text_extractor import TextExtractor
            extractor = TextExtractor()
            result = extractor.extract_text_from_docx(fake_docx)

        assert result == ""


# ---------------------------------------------------------------------------
# extract_text_from_xlsx
# ---------------------------------------------------------------------------

class TestExtractTextFromXlsx:
    def test_returns_string_when_excel_available(self, tmp_path):
        fake_xlsx = tmp_path / "test.xlsx"
        fake_xlsx.write_bytes(b"fake")

        mock_sheet = MagicMock()
        mock_sheet.iter_rows.return_value = [("cell1", "cell2"), ("cell3", None)]

        mock_workbook = MagicMock()
        mock_workbook.sheetnames = ["Sheet1"]
        mock_workbook.__getitem__ = MagicMock(return_value=mock_sheet)

        with (
            patch("src.analyzers.text_extractor.EXCEL_AVAILABLE", True),
            patch("src.analyzers.text_extractor.load_workbook", return_value=mock_workbook),
        ):
            from src.analyzers.text_extractor import TextExtractor
            extractor = TextExtractor()
            result = extractor.extract_text_from_xlsx(fake_xlsx)

        assert isinstance(result, str)
        assert "cell1" in result

    def test_returns_empty_when_excel_unavailable(self, tmp_path):
        fake_xlsx = tmp_path / "test.xlsx"
        fake_xlsx.write_bytes(b"fake")

        with patch("src.analyzers.text_extractor.EXCEL_AVAILABLE", False):
            from src.analyzers.text_extractor import TextExtractor
            extractor = TextExtractor()
            result = extractor.extract_text_from_xlsx(fake_xlsx)

        assert result == ""

    def test_returns_empty_on_exception(self, tmp_path):
        fake_xlsx = tmp_path / "test.xlsx"
        fake_xlsx.write_bytes(b"fake")

        with (
            patch("src.analyzers.text_extractor.EXCEL_AVAILABLE", True),
            patch("src.analyzers.text_extractor.load_workbook", side_effect=Exception("bad xlsx")),
        ):
            from src.analyzers.text_extractor import TextExtractor
            extractor = TextExtractor()
            result = extractor.extract_text_from_xlsx(fake_xlsx)

        assert result == ""


# ---------------------------------------------------------------------------
# extract_text dispatch
# ---------------------------------------------------------------------------

class TestExtractTextDispatch:
    def _extractor(self):
        from src.analyzers.text_extractor import TextExtractor
        return TextExtractor()

    def test_routes_image_by_mime(self, tmp_path):
        p = tmp_path / "photo.jpg"
        p.write_bytes(b"fake")
        ext = self._extractor()
        ext.extract_text_from_image = MagicMock(return_value="img text")

        result = ext.extract_text(p, mime_type="image/jpeg")
        ext.extract_text_from_image.assert_called_once_with(p)
        assert result == "img text"

    def test_routes_pdf_by_mime(self, tmp_path):
        p = tmp_path / "doc.pdf"
        p.write_bytes(b"fake")
        ext = self._extractor()
        ext.extract_text_from_pdf = MagicMock(return_value="pdf text")

        result = ext.extract_text(p, mime_type="application/pdf")
        ext.extract_text_from_pdf.assert_called_once_with(p)
        assert result == "pdf text"

    def test_routes_pdf_by_extension(self, tmp_path):
        p = tmp_path / "doc.pdf"
        p.write_bytes(b"fake")
        ext = self._extractor()
        ext.extract_text_from_pdf = MagicMock(return_value="pdf text")

        result = ext.extract_text(p, mime_type=None)
        ext.extract_text_from_pdf.assert_called_once_with(p)
        assert result == "pdf text"

    def test_routes_docx_by_extension(self, tmp_path):
        p = tmp_path / "report.docx"
        p.write_bytes(b"fake")
        ext = self._extractor()
        ext.extract_text_from_docx = MagicMock(return_value="docx text")

        result = ext.extract_text(p, mime_type=None)
        ext.extract_text_from_docx.assert_called_once_with(p)
        assert result == "docx text"

    def test_routes_xlsx_by_extension(self, tmp_path):
        p = tmp_path / "data.xlsx"
        p.write_bytes(b"fake")
        ext = self._extractor()
        ext.extract_text_from_xlsx = MagicMock(return_value="xlsx text")

        result = ext.extract_text(p, mime_type=None)
        ext.extract_text_from_xlsx.assert_called_once_with(p)
        assert result == "xlsx text"

    def test_routes_text_file_by_extension(self, tmp_path):
        p = tmp_path / "notes.txt"
        p.write_text("hello text file")

        ext = self._extractor()
        result = ext.extract_text(p, mime_type=None)
        assert "hello text file" in result

    def test_returns_empty_for_unknown_type(self, tmp_path):
        p = tmp_path / "binary.bin"
        p.write_bytes(b"\x00\x01\x02")

        ext = self._extractor()
        result = ext.extract_text(p, mime_type=None)
        assert result == ""


# ---------------------------------------------------------------------------
# ExtractionResult and extract_from_image
# ---------------------------------------------------------------------------

class TestExtractFromImage:
    def test_returns_extraction_result_with_confidence(self, tmp_path):
        fake_image = tmp_path / "test.png"
        fake_image.write_bytes(b"fake")

        mock_ocr_result = MagicMock()
        mock_ocr_result.text = "hello world"
        mock_ocr_result.confidence = 0.95
        mock_ocr_result.language = "en"

        with (
            patch("src.analyzers.text_extractor.OCR_AVAILABLE", True),
            patch("src.analyzers.text_extractor.extract_ocr_with_confidence", return_value=mock_ocr_result),
        ):
            from src.analyzers.text_extractor import TextExtractor
            extractor = TextExtractor()
            extractor.ocr_available = True

            result = extractor.extract_from_image(fake_image)

        assert result.text == "hello world"
        assert result.confidence == 0.95
        assert result.language == "en"
        assert result.source == "ocr"

    def test_returns_empty_result_when_ocr_unavailable(self, tmp_path):
        fake_image = tmp_path / "test.png"
        fake_image.write_bytes(b"fake")

        from src.analyzers.text_extractor import TextExtractor
        extractor = TextExtractor()
        extractor.ocr_available = False

        result = extractor.extract_from_image(fake_image)
        assert result.text == ""
        assert result.source == "ocr"

    def test_returns_empty_result_on_none(self, tmp_path):
        fake_image = tmp_path / "test.png"
        fake_image.write_bytes(b"fake")

        with patch(
            "src.analyzers.text_extractor.extract_ocr_with_confidence",
            return_value=None,
        ):
            from src.analyzers.text_extractor import TextExtractor
            extractor = TextExtractor()
            extractor.ocr_available = True

            result = extractor.extract_from_image(fake_image)

        assert result.text == ""


# ---------------------------------------------------------------------------
# extract (rich dispatch)
# ---------------------------------------------------------------------------

class TestExtractDispatch:
    def _extractor(self):
        from src.analyzers.text_extractor import TextExtractor
        return TextExtractor()

    def test_routes_image_returns_extraction_result(self, tmp_path):
        from src.analyzers.text_extractor import ExtractionResult
        p = tmp_path / "photo.jpg"
        p.write_bytes(b"fake")
        ext = self._extractor()
        ext.extract_from_image = MagicMock(
            return_value=ExtractionResult(text="img", confidence=0.9, source="ocr")
        )

        result = ext.extract(p, mime_type="image/jpeg")
        ext.extract_from_image.assert_called_once_with(p)
        assert result.text == "img"
        assert result.confidence == 0.9

    def test_text_file_has_full_confidence(self, tmp_path):
        p = tmp_path / "notes.txt"
        p.write_text("hello text")

        ext = self._extractor()
        result = ext.extract(p, mime_type=None)
        assert "hello text" in result.text
        assert result.confidence == 1.0
        assert result.source == "text"

    def test_unknown_type_returns_empty(self, tmp_path):
        p = tmp_path / "binary.bin"
        p.write_bytes(b"\x00\x01\x02")

        ext = self._extractor()
        result = ext.extract(p, mime_type=None)
        assert result.text == ""
        assert result.source == "unknown"
