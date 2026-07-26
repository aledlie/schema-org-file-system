"""PII redaction for persisted medical extracted text.

Covers the pure redactor (``src.analyzers.text_redaction``) and the
``FileProcessor._persist_to_graph_store`` wiring: medical-category files
store redacted ``extracted_text`` / ``schema_data["text"]``; other
categories persist verbatim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

from src.analyzers.text_redaction import (
    MEDICAL_TEXT_REDACTION_CATEGORIES,
    REDACTION_CHAR,
    redact_pii_text,
)
from src.pipeline import FileProcessor

BLOODWORK_TEXT = (
    "Patient: Jane Doe  DOB: 1993-11-26  MRN: 55501234\n"
    "Contact jane.doe@example.com or 512-555-0100\n"
    "Hemoglobin 12.5 g/dL (normal range 12.0-15.5)\n"
    "Vitamin D3 sufficient. Type 2 screening negative."
)


class TestRedactPiiText:
    def test_emails_masked(self):
        out = redact_pii_text("reach me at jane.doe@example.com now")
        assert "jane.doe@example.com" not in out
        assert REDACTION_CHAR * len("jane.doe@example.com") in out

    def test_digit_runs_masked_length_preserved(self):
        out = redact_pii_text("MRN: 55501234 on 1993-11-26, value 12.5")
        assert "55501234" not in out and "1993" not in out and "12.5" not in out
        assert (
            out == f"MRN: {REDACTION_CHAR * 8} on {REDACTION_CHAR * 10}, value {REDACTION_CHAR * 4}"
        )

    def test_single_digits_preserved(self):
        out = redact_pii_text("Vitamin D3 and Type 2 screening")
        assert out == "Vitamin D3 and Type 2 screening"

    def test_people_names_and_parts_masked_case_insensitive(self):
        out = redact_pii_text("Patient JANE DOE; contact Doe family", people_names=["Jane Doe"])
        assert "JANE" not in out and "DOE" not in out and "Doe" not in out
        assert "Patient" in out and "contact" in out and "family" in out

    def test_empty_text_passthrough(self):
        assert redact_pii_text("") == ""

    def test_bloodwork_document_end_to_end(self):
        out = redact_pii_text(BLOODWORK_TEXT, people_names=["Jane Doe"])
        for pii in ("Jane", "Doe", "1993", "55501234", "example.com", "555-0100", "12.5"):
            assert pii not in out
        for kept in ("Patient", "Hemoglobin", "g/dL", "normal range", "screening negative"):
            assert kept in out


def _make_file_processor(base_path: Path, graph_store: Any) -> FileProcessor:
    fp = FileProcessor(
        base_path=base_path,
        dry_run=True,
        db_path=None,
        cost_calculator=None,
        graph_store=graph_store,
    )
    fp.validator = MagicMock()
    fp.validator.validate.return_value.is_valid.return_value = True
    fp.registry = MagicMock()
    return fp


class TestMedicalPersistenceRedaction:
    def _persist(self, tmp_path: Path, category: str) -> MagicMock:
        graph_store = MagicMock()
        graph_store.add_file.return_value = MagicMock(id="file-1")
        fp = _make_file_processor(tmp_path, graph_store)
        src = tmp_path / "labs.pdf"
        src.write_text("content")
        people: List[str] = ["Jane Doe"]
        schema: Dict[str, Any] = {"@type": "DigitalDocument", "text": BLOODWORK_TEXT[:50]}
        fp._persist_to_graph_store(
            file_path=src,
            dest_path=tmp_path / "dest" / "labs.pdf",
            category=category,
            subcategory="records",
            schema=schema,
            extracted_text=BLOODWORK_TEXT,
            company_name=None,
            people_names=people,
            image_metadata={},
        )
        return graph_store

    def test_medical_category_persists_redacted_text(self, tmp_path: Path) -> None:
        assert "medical" in MEDICAL_TEXT_REDACTION_CATEGORIES
        store = self._persist(tmp_path, "medical")
        kwargs = store.add_file.call_args.kwargs
        stored_text = kwargs["extracted_text"]
        assert "Jane" not in stored_text and "55501234" not in stored_text
        assert "Hemoglobin" in stored_text
        assert "Jane" not in kwargs["schema_data"]["text"]

    def test_non_medical_category_persists_verbatim(self, tmp_path: Path) -> None:
        store = self._persist(tmp_path, "technical")
        kwargs = store.add_file.call_args.kwargs
        assert kwargs["extracted_text"] == BLOODWORK_TEXT
        assert kwargs["schema_data"]["text"] == BLOODWORK_TEXT[:50]

    def test_caller_schema_dict_not_mutated(self, tmp_path: Path) -> None:
        graph_store = MagicMock()
        graph_store.add_file.return_value = MagicMock(id="file-1")
        fp = _make_file_processor(tmp_path, graph_store)
        src = tmp_path / "labs.pdf"
        src.write_text("content")
        schema: Dict[str, Any] = {"@type": "DigitalDocument", "text": "MRN 55501234"}
        fp._persist_to_graph_store(
            file_path=src,
            dest_path=tmp_path / "dest" / "labs.pdf",
            category="medical",
            subcategory="records",
            schema=schema,
            extracted_text="MRN 55501234",
            company_name=None,
            people_names=[],
            image_metadata={},
        )
        assert schema["text"] == "MRN 55501234"
