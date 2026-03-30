"""
Unit tests for KIE utilities and Schema.org mapping.

All heavy dependencies (doctr, torch) are mocked so the tests run without
those libraries installed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts/ is importable.
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))


# ---------------------------------------------------------------------------
# KIEField / KIEResult dataclass tests
# ---------------------------------------------------------------------------

class TestKIEDataclasses:
    def test_kie_field_construction(self):
        from shared.kie_utils import KIEField

        field = KIEField(
            class_name="vendor_name",
            value="Acme Corp",
            confidence=0.92,
            geometry=((0.1, 0.2), (0.5, 0.4)),
        )
        assert field.class_name == "vendor_name"
        assert field.value == "Acme Corp"
        assert field.confidence == 0.92
        assert len(field.geometry) == 2

    def test_kie_field_default_geometry(self):
        from shared.kie_utils import KIEField

        field = KIEField(class_name="total_amount", value="$150.00", confidence=0.8)
        assert field.geometry == ()

    def test_kie_result_construction(self):
        from shared.kie_utils import KIEField, KIEResult

        vendor = KIEField(class_name="vendor_name", value="Acme", confidence=0.9)
        amount = KIEField(class_name="total_amount", value="100.00", confidence=0.85)
        result = KIEResult(
            fields={"vendor_name": [vendor], "total_amount": [amount]},
            page_count=1,
            overall_confidence=0.875,
        )
        assert result.page_count == 1
        assert len(result.fields) == 2
        assert result.overall_confidence == 0.875

    def test_kie_result_defaults(self):
        from shared.kie_utils import KIEResult

        result = KIEResult()
        assert result.fields == {}
        assert result.page_count == 0
        assert result.overall_confidence == 0.0


# ---------------------------------------------------------------------------
# Schema.org mapping tests
# ---------------------------------------------------------------------------

class TestKIESchemaMapping:
    def _make_result(self, fields_dict):
        from shared.kie_utils import KIEField, KIEResult

        fields = {}
        confs = []
        for cls, entries in fields_dict.items():
            kie_fields = []
            for value, confidence in entries:
                kie_fields.append(KIEField(class_name=cls, value=value, confidence=confidence))
                confs.append(confidence)
            fields[cls] = kie_fields
        return KIEResult(
            fields=fields,
            page_count=1,
            overall_confidence=sum(confs) / len(confs) if confs else 0.0,
        )

    def test_basic_invoice_mapping(self):
        from shared.kie_schema_mapping import kie_result_to_schema_org

        result = self._make_result({
            "vendor_name": [("Acme Corp", 0.9)],
            "total_amount": [("1500.00", 0.85)],
            "currency": [("USD", 0.8)],
            "invoice_date": [("2024-03-15", 0.75)],
            "invoice_number": [("INV-2024-001", 0.88)],
        })

        schema = kie_result_to_schema_org(result)

        assert schema["@type"] == "Invoice"
        assert schema["provider"] == {"@type": "Organization", "name": "Acme Corp"}
        assert schema["totalPaymentDue"]["@type"] == "MonetaryAmount"
        assert schema["totalPaymentDue"]["value"] == "1500.00"
        assert schema["totalPaymentDue"]["currency"] == "USD"
        assert schema["confirmationNumber"] == "INV-2024-001"
        assert schema["paymentDueDate"] == "2024-03-15"

    def test_low_confidence_fields_excluded(self):
        from shared.kie_schema_mapping import kie_result_to_schema_org

        result = self._make_result({
            "vendor_name": [("Acme Corp", 0.9)],
            "total_amount": [("???", 0.2)],  # below threshold
        })

        schema = kie_result_to_schema_org(result)
        assert "provider" in schema
        assert "totalPaymentDue" not in schema

    def test_picks_highest_confidence_field(self):
        from shared.kie_schema_mapping import kie_result_to_schema_org

        result = self._make_result({
            "vendor_name": [("Wrong Corp", 0.4), ("Acme Corp", 0.9)],
        })

        schema = kie_result_to_schema_org(result)
        assert schema["provider"]["name"] == "Acme Corp"

    def test_receipt_fields_map_to_invoice(self):
        from shared.kie_schema_mapping import kie_result_to_schema_org

        result = self._make_result({
            "store_name": [("Target", 0.85)],
            "receipt_total": [("42.99", 0.9)],
            "receipt_date": [("2024-01-20", 0.7)],
        })

        schema = kie_result_to_schema_org(result)
        assert schema["@type"] == "Invoice"
        assert schema["provider"]["name"] == "Target"
        assert schema["totalPaymentDue"]["value"] == "42.99"
        assert schema["paymentDueDate"] == "2024-01-20"

    def test_empty_result(self):
        from shared.kie_schema_mapping import kie_result_to_schema_org
        from shared.kie_utils import KIEResult

        result = KIEResult()
        schema = kie_result_to_schema_org(result)
        assert schema == {"@type": "Invoice"}


# ---------------------------------------------------------------------------
# KIE availability / graceful fallback tests
# ---------------------------------------------------------------------------

class TestKIEAvailability:
    def test_kie_unavailable_when_no_weights(self, tmp_path):
        from shared.kie_utils import _get_kie_predictor

        # Point at a non-existent weights file.
        result = _get_kie_predictor(weights_path=tmp_path / "nonexistent.pt")
        assert result is None

    def test_extract_kie_fields_returns_none_without_predictor(self, tmp_path):
        from shared.kie_utils import extract_kie_fields

        fake_image = tmp_path / "test.png"
        fake_image.write_bytes(b"fake")

        # Should return None gracefully (no weights).
        result = extract_kie_fields(fake_image, weights_path=tmp_path / "no.pt")
        assert result is None

    def test_extract_kie_fields_pdf_returns_none_without_predictor(self, tmp_path):
        from shared.kie_utils import extract_kie_fields_pdf

        fake_pdf = tmp_path / "test.pdf"
        fake_pdf.write_bytes(b"fake")

        result = extract_kie_fields_pdf(fake_pdf, weights_path=tmp_path / "no.pt")
        assert result is None


# ---------------------------------------------------------------------------
# classify_with_kie tests
# ---------------------------------------------------------------------------

class TestClassifyWithKIE:
    def _make_result(self, fields_dict):
        from shared.kie_utils import KIEField, KIEResult

        fields = {}
        confs = []
        for cls, entries in fields_dict.items():
            kie_fields = []
            for value, confidence in entries:
                kie_fields.append(KIEField(class_name=cls, value=value, confidence=confidence))
                confs.append(confidence)
            fields[cls] = kie_fields
        return KIEResult(
            fields=fields,
            page_count=1,
            overall_confidence=sum(confs) / len(confs) if confs else 0.0,
        )

    def test_classifies_invoice_with_vendor_and_amount(self):
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
        from classifiers.content_classifier import ContentClassifier

        classifier = ContentClassifier()
        kie_result = self._make_result({
            "vendor_name": [("Acme Corp", 0.9)],
            "total_amount": [("500.00", 0.85)],
        })

        result = classifier.classify_with_kie(kie_result)
        assert result is not None
        category, subcategory, company_name, people = result
        assert category == "financial"
        assert subcategory == "invoices"
        assert company_name == "Acme Corp"

    def test_classifies_invoice_with_vendor_and_date(self):
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
        from classifiers.content_classifier import ContentClassifier

        classifier = ContentClassifier()
        kie_result = self._make_result({
            "store_name": [("Target", 0.8)],
            "receipt_date": [("2024-01-15", 0.75)],
        })

        result = classifier.classify_with_kie(kie_result)
        assert result is not None
        assert result[0] == "financial"
        assert result[2] == "Target"

    def test_returns_none_without_vendor(self):
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
        from classifiers.content_classifier import ContentClassifier

        classifier = ContentClassifier()
        kie_result = self._make_result({
            "total_amount": [("500.00", 0.85)],
        })

        result = classifier.classify_with_kie(kie_result)
        assert result is None

    def test_returns_none_with_low_confidence(self):
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
        from classifiers.content_classifier import ContentClassifier

        classifier = ContentClassifier()
        kie_result = self._make_result({
            "vendor_name": [("Maybe Corp", 0.3)],  # below 0.5 threshold
            "total_amount": [("100.00", 0.3)],
        })

        result = classifier.classify_with_kie(kie_result)
        assert result is None

    def test_returns_none_with_vendor_only(self):
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
        from classifiers.content_classifier import ContentClassifier

        classifier = ContentClassifier()
        kie_result = self._make_result({
            "vendor_name": [("Acme Corp", 0.9)],
        })

        # Vendor alone is not enough — need amount OR date.
        result = classifier.classify_with_kie(kie_result)
        assert result is None


# ---------------------------------------------------------------------------
# KIE field class list
# ---------------------------------------------------------------------------

class TestKIEFieldClasses:
    def test_all_classes_have_schema_mapping(self):
        from shared.kie_schema_mapping import KIE_FIELD_CLASSES, KIE_FIELD_TO_SCHEMA

        for cls in KIE_FIELD_CLASSES:
            assert cls in KIE_FIELD_TO_SCHEMA, f"Class {cls!r} missing from KIE_FIELD_TO_SCHEMA"

    def test_no_extra_mappings(self):
        from shared.kie_schema_mapping import KIE_FIELD_CLASSES, KIE_FIELD_TO_SCHEMA

        for cls in KIE_FIELD_TO_SCHEMA:
            assert cls in KIE_FIELD_CLASSES, f"Mapping {cls!r} not in KIE_FIELD_CLASSES"
