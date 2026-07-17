"""Unit tests for `organize-files evaluate --classifier unified`.

Covers the CLI contract (the "unified" choice on src.cli.add_evaluate_arguments
and the EvaluateInputs dataclass) and the UnifiedScorerModel path in
scripts/evaluate_model.py: synthetic test-set records (the ml_data test.json
shape) classified through the REAL signal registry, with predictions landing
in the harness's (category, subcategory) label space and low-confidence
decisions routing to 'uncategorized'. Text fixtures mirror the golden
integration suite so expected decisions are already pinned there.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is on sys.path so `import evaluate_model` (and its own
# `from shared.x import y`) resolve (mirrors tests/unit/test_relabel_test_set.py).
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import evaluate_model  # noqa: E402

from src.cli import add_evaluate_arguments  # noqa: E402
from src.cli_inputs import EvaluateInputs  # noqa: E402

# --------------------------------------------------------------------------- #
# Fixtures (texts mirror tests/integration/test_unified_scoring_golden.py)     #
# --------------------------------------------------------------------------- #

VENDOR_INVOICE_TEXT = (
    "INVOICE #2041 from Morning Train LLC. Purchase order PO-118 attached. "
    "Bill to: Integrity Studio. Payment terms net 30; supplier vendor id 88. "
    "Remit payment upon receipt of this invoice."
)

BLOODWORK_OCR_TEXT = (
    "Laboratory lab results for patient. Blood panel diagnosis reviewed by "
    "doctor at the hospital clinic. Prescription and treatment plan enclosed. "
    "Medical record number 4417."
)

COURT_NOTICE_TEXT = (
    "NOTICE OF COURT SETTING. Cause No 2026-441 on the docket. "
    "Plaintiff: Mr. John Doe vs defendant. A hearing is set before the "
    "judicial officer. District Clerk contact info - phone: 512-555-0100, "
    "email: clerk@court.gov, address: 100 Main St. Contact the clerk."
)

# The harness's fallback labels (scorer LOW_CONFIDENCE_FALLBACK).
UNCATEGORIZED = "uncategorized"
UNCATEGORIZED_SUBCATEGORY = "other"


def _record(filename: str, filepath: str, **extra) -> dict:
    """A minimal ml_data test.json-shaped record."""
    record = {"filename": filename, "filepath": filepath}
    record.update(extra)
    return record


SPRITE_RECORD = _record("frame_12.png", "/tmp/assets/frame_12.png")
VENDOR_RECORD = _record(
    "morning-train-2041.pdf",
    "/tmp/docs/morning-train-2041.pdf",
    extracted_text=VENDOR_INVOICE_TEXT,
)
BLOODWORK_RECORD = _record(
    "medellin_bloodwork.png",
    "/tmp/scans/medellin_bloodwork.png",
    extracted_text=BLOODWORK_OCR_TEXT,
)
COURT_RECORD = _record(
    "notice-of-ct-setting.pdf",
    "/tmp/docs/notice-of-ct-setting.pdf",
    extracted_text=COURT_NOTICE_TEXT,
)
NO_SIGNAL_RECORD = _record("mystery.bin", "/tmp/docs/mystery.bin")


@pytest.fixture(scope="module")
def unified_model() -> "evaluate_model.UnifiedScorerModel":
    return evaluate_model.UnifiedScorerModel()


# --------------------------------------------------------------------------- #
# CLI contract                                                                  #
# --------------------------------------------------------------------------- #


def parse(argv):
    parser = argparse.ArgumentParser()
    add_evaluate_arguments(parser)
    return parser.parse_args(argv)


class TestCliContract:
    def test_unified_is_an_accepted_choice(self):
        assert parse(["--classifier", "unified"]).classifier == "unified"

    def test_short_flag_accepts_unified(self):
        assert parse(["-c", "unified"]).classifier == "unified"

    def test_existing_choices_still_accepted(self):
        assert parse(["--classifier", "baseline"]).classifier == "baseline"
        assert parse(["--classifier", "content"]).classifier == "content"

    def test_unknown_choice_rejected(self):
        with pytest.raises(SystemExit):
            parse(["--classifier", "bogus"])

    def test_evaluate_inputs_dataclass_carries_unified(self):
        inputs = EvaluateInputs.from_namespace(parse(["--classifier", "unified"]))
        assert inputs.classifier == "unified"


# --------------------------------------------------------------------------- #
# UnifiedScorerModel predictions                                                #
# --------------------------------------------------------------------------- #


class TestUnifiedPredictions:
    def test_filename_only_record_classifies_from_filename_signals(self, unified_model):
        category, subcategory, confidence = unified_model.predict_category(SPRITE_RECORD)
        assert (category, subcategory) == ("game_assets", "sprites")
        assert 0.0 <= confidence <= 1.0

    def test_record_text_reaches_document_signals(self, unified_model):
        category, subcategory, _ = unified_model.predict_category(VENDOR_RECORD)
        assert (category, subcategory) == ("organization", "vendors")

    def test_image_record_text_reaches_signals_via_ocr_channel(self, unified_model):
        """Image records carrying text classify from it (synthesized OCR shape)."""
        category, subcategory, _ = unified_model.predict_category(BLOODWORK_RECORD)
        assert (category, subcategory) == ("medical", "records")

    def test_court_text_routes_legal(self, unified_model):
        category, subcategory, _ = unified_model.predict_category(COURT_RECORD)
        assert (category, subcategory) == ("legal", "litigation")

    def test_low_confidence_routes_to_uncategorized(self, unified_model):
        category, subcategory, confidence = unified_model.predict_category(NO_SIGNAL_RECORD)
        assert (category, subcategory) == (UNCATEGORIZED, UNCATEGORIZED_SUBCATEGORY)
        assert confidence == 0.0

    def test_predictions_stay_in_harness_label_space(self, unified_model):
        """Every prediction is a (str, str, float-in-[0,1]) triple."""
        for record in (
            SPRITE_RECORD,
            VENDOR_RECORD,
            BLOODWORK_RECORD,
            COURT_RECORD,
            NO_SIGNAL_RECORD,
        ):
            category, subcategory, confidence = unified_model.predict_category(record)
            assert isinstance(category, str) and category
            assert isinstance(subcategory, str) and subcategory
            assert 0.0 <= confidence <= 1.0

    def test_model_never_skips_records(self, unified_model):
        """No disk reads -> no SKIP sentinel (unlike the content classifier)."""
        assert not hasattr(unified_model, "SKIP")


# --------------------------------------------------------------------------- #
# Harness dispatch                                                              #
# --------------------------------------------------------------------------- #


class TestEvaluateDispatch:
    def test_evaluate_model_end_to_end_with_unified(self, tmp_path):
        test_data = [
            dict(SPRITE_RECORD, category="game_assets", subcategory="sprites"),
            dict(COURT_RECORD, category="legal", subcategory="litigation"),
            dict(NO_SIGNAL_RECORD, category=UNCATEGORIZED, subcategory=UNCATEGORIZED_SUBCATEGORY),
        ]
        test_path = tmp_path / "test.json"
        test_path.write_text(json.dumps(test_data), encoding="utf-8")
        output_path = tmp_path / "evaluation.json"

        evaluation = evaluate_model.evaluate_model(
            str(test_path),
            str(output_path),
            classifier=evaluate_model.CLASSIFIER_UNIFIED,
            min_support=1,
        )

        assert (
            evaluation["metadata"]["model"]
            == evaluate_model.MODEL_LABELS[evaluate_model.CLASSIFIER_UNIFIED]
        )
        assert evaluation["metadata"]["evaluated"] == len(test_data)
        assert evaluation["metadata"]["skipped_missing"] == 0
        assert evaluation["overall_metrics"]["accuracy"] == 1.0
        assert evaluation["overall_metrics"]["subcategory_accuracy"] == 1.0
        assert output_path.exists()
        assert json.loads(output_path.read_text(encoding="utf-8"))

    def test_baseline_label_unchanged(self, tmp_path):
        """The existing baseline path still reports its original model label."""
        test_path = tmp_path / "test.json"
        test_path.write_text(
            json.dumps([dict(SPRITE_RECORD, category="game_assets", subcategory="sprites")]),
            encoding="utf-8",
        )
        evaluation = evaluate_model.evaluate_model(
            str(test_path), None, classifier=evaluate_model.CLASSIFIER_BASELINE, min_support=1
        )
        assert evaluation["metadata"]["model"] == evaluate_model.DEFAULT_MODEL_LABEL
