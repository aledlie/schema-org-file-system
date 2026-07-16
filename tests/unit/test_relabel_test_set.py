"""Unit tests for scripts/relabel_test_set.py.

Covers the pass-5 ``is_document`` prefilter (skip the document regex when the
feature extractor already decided the file is not a document) and the
import-time guard that keeps ``_DOCUMENT_LABEL_MAP`` in sync with
``DOCUMENT_PATTERNS``.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is on sys.path so `import relabel_test_set` (and its own
# `from shared.x import y`) resolve.
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import relabel_test_set  # noqa: E402


def _triage_doc_sample(**overrides) -> dict:
    """A sample that reaches pass 5 (triage location, uncategorized, non-image)."""
    sample = {
        "parent_folder": "Downloads",
        "category": "uncategorized",
        "filename": "invoice.pdf",
        "extension_category": "document",
        "extension": ".pdf",
    }
    sample.update(overrides)
    return sample


class TestIsDocumentPrefilter:
    def test_is_document_true_relabels_matching_filename(self) -> None:
        out, counters = relabel_test_set.relabel([_triage_doc_sample(is_document=True)])
        assert (out[0]["category"], out[0]["subcategory"]) == ("financial", "invoice")
        assert counters["pass5"]["uncategorized"] == 1

    def test_is_document_false_skips_document_relabel(self) -> None:
        # Even though the filename matches DOCUMENT_PATTERNS, is_document=False
        # short-circuits pass 5 and the label is left untouched.
        out, counters = relabel_test_set.relabel([_triage_doc_sample(is_document=False)])
        assert out[0]["category"] == "uncategorized"
        assert "subcategory" not in out[0]
        assert sum(counters["pass5"].values()) == 0

    def test_missing_is_document_defaults_to_running_relabel(self) -> None:
        # Backward compat: samples without the key (not from the feature
        # extractor) still run the regex.
        out, counters = relabel_test_set.relabel([_triage_doc_sample()])
        assert (out[0]["category"], out[0]["subcategory"]) == ("financial", "invoice")
        assert counters["pass5"]["uncategorized"] == 1

    def test_is_document_true_but_nonmatching_filename_unchanged(self) -> None:
        # Prefilter lets it through, but the word-boundary regex finds no
        # document keyword, so the label stays uncategorized.
        out, counters = relabel_test_set.relabel(
            [_triage_doc_sample(filename="notes.pdf", is_document=True)]
        )
        assert out[0]["category"] == "uncategorized"
        assert sum(counters["pass5"].values()) == 0


class TestDocumentLabelMapValidation:
    def test_shipped_label_map_is_consistent(self) -> None:
        # Every _DOCUMENT_LABEL_MAP key is a substring of some DOCUMENT_PATTERNS
        # entry, so the import-time guard passes as shipped.
        from shared.constants import DOCUMENT_PATTERNS

        for key in relabel_test_set._DOCUMENT_LABEL_MAP:
            assert any(key in p for p in DOCUMENT_PATTERNS), key

    def test_key_drift_raises_value_error(self, monkeypatch) -> None:
        import shared.constants as sc

        # Swap in patterns that contain none of the label-map keys, then force a
        # fresh import so the module-level guard re-runs against the bad config.
        monkeypatch.setattr(sc, "DOCUMENT_PATTERNS", ["unrelated"])
        monkeypatch.delitem(sys.modules, "relabel_test_set", raising=False)
        with pytest.raises(ValueError, match="absent from DOCUMENT_PATTERNS"):
            importlib.import_module("relabel_test_set")
