"""Tests for the OCR document-content override that rescues document images
misrouted to game_assets/media by a filename-keyword collision.

The override is a pure method over cached OCR state, so it is exercised against a
lightweight stub `self` — no CLIP/OCR model load required.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from file_organizer_content_based import (  # noqa: E402
    ContentBasedFileOrganizer,
    _OCR_CONFIDENCE_THRESHOLD,
)

_LAB_TEXT = "RESULTADOS DE EXAMENES SYNLAB HEMOGRAMA RESULTADO REFERENCIA " * 3


def _stub(*, ocr_available=True, text=_LAB_TEXT, conf=0.9, content=("medical", "other")):
    """Minimal stand-in exposing only the attributes the override reads."""
    classifier = MagicMock()
    classifier.classify_content.return_value = (content[0], content[1], None, [])
    return SimpleNamespace(
        ocr_available=ocr_available,
        _last_file_ocr_text=text,
        _last_file_ocr_confidence=conf,
        classifier=classifier,
    )


def _run(stub):
    return ContentBasedFileOrganizer._ocr_document_override(stub, Path("bloodwork.png"))


class TestOcrDocumentOverride:
    def test_document_category_overrides(self):
        assert _run(_stub(content=("medical", "other"))) == ("medical", "other")

    @pytest.mark.parametrize("cat", ["financial", "legal", "personal", "technical"])
    def test_all_document_categories_pass(self, cat):
        assert _run(_stub(content=(cat, "other"))) == (cat, "other")

    @pytest.mark.parametrize("cat", ["media", "game_assets", "uncategorized"])
    def test_non_document_categories_do_not_override(self, cat):
        assert _run(_stub(content=(cat, "photos"))) is None

    def test_low_confidence_ocr_rejected(self):
        assert _run(_stub(conf=_OCR_CONFIDENCE_THRESHOLD - 0.01)) is None

    def test_high_confidence_ocr_accepted(self):
        assert _run(_stub(conf=_OCR_CONFIDENCE_THRESHOLD)) == ("medical", "other")

    def test_sparse_text_rejected(self):
        assert _run(_stub(text="short")) is None

    def test_no_ocr_available_returns_none(self):
        assert _run(_stub(ocr_available=False)) is None

    def test_none_confidence_is_treated_as_reliable(self):
        # extract paths can return None confidence; do not reject on that alone.
        assert _run(_stub(conf=None)) == ("medical", "other")
