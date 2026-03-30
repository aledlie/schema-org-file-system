"""KIE (Key Information Extraction) using docTR's kie_predictor.

Provides structured field extraction for invoices, receipts, and contracts.
Falls back gracefully when fine-tuned weights are not available — in that case
``KIE_AVAILABLE`` is ``False`` and all public functions return ``None``.

Architecture mirrors ``ocr_utils.py``: lazy singleton predictor, rich result
dataclass, image and PDF entry points.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from shared.ocr_utils import _DET_ARCH, _RECO_ARCH

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Availability flags — set at import time
# ---------------------------------------------------------------------------

KIE_AVAILABLE = False
_kie_predictor = None

try:
    from doctr.io import DocumentFile
    from doctr.models import kie_predictor as _make_kie_predictor
    _DOCTR_KIE_IMPORTABLE = True
except ImportError:
    _DOCTR_KIE_IMPORTABLE = False

# Default path for fine-tuned weights (relative to project root).
_DEFAULT_WEIGHTS_PATH = Path(__file__).resolve().parent.parent.parent / "models" / "kie_invoice_v1.pt"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class KIEField:
    """A single extracted field from KIE."""
    class_name: str          # e.g. "vendor_name", "total_amount"
    value: str               # extracted text content
    confidence: float        # word-level confidence (0.0-1.0)
    geometry: tuple = ()     # bounding box coordinates ((x1,y1),(x2,y2))


@dataclass
class KIEResult:
    """Structured extraction result from KIE predictor."""
    fields: dict[str, list[KIEField]] = field(default_factory=dict)
    page_count: int = 0
    overall_confidence: float = 0.0


# ---------------------------------------------------------------------------
# Predictor lifecycle
# ---------------------------------------------------------------------------

def _get_kie_predictor(weights_path: Path | None = None):
    """Lazy-load the KIE predictor singleton.

    Returns ``None`` if docTR is not importable or the weights file does not
    exist.  The first successful call caches the predictor globally.
    """
    global _kie_predictor, KIE_AVAILABLE

    if _kie_predictor is not None:
        return _kie_predictor

    if not _DOCTR_KIE_IMPORTABLE:
        return None

    wp = weights_path or _DEFAULT_WEIGHTS_PATH
    if not wp.exists():
        logger.debug("KIE weights not found at %s — KIE disabled", wp)
        return None

    try:
        import torch
        from shared.kie_schema_mapping import KIE_FIELD_CLASSES

        predictor = _make_kie_predictor(
            det_arch=_DET_ARCH,
            reco_arch=_RECO_ARCH,
            pretrained=False,
            assume_straight_pages=False,
            straighten_pages=True,
        )
        state = torch.load(str(wp), map_location="cpu", weights_only=True)
        predictor.load_state_dict(state)
        _kie_predictor = predictor
        KIE_AVAILABLE = True
        logger.info("KIE predictor loaded from %s (%d classes)", wp, len(KIE_FIELD_CLASSES))
        return _kie_predictor
    except Exception:
        logger.warning("Failed to load KIE predictor from %s", wp, exc_info=True)
        return None


def is_kie_available(weights_path: Path | None = None) -> bool:
    """Check whether the KIE predictor can be loaded."""
    return _get_kie_predictor(weights_path) is not None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_kie_result(result, min_confidence: float) -> KIEResult | None:
    """Convert raw docTR KIE output to a ``KIEResult``.

    The docTR KIE predictor returns ``KIEDocument`` whose pages contain a
    ``predictions`` dict mapping class names to lists of ``Prediction``
    objects (each with ``.value``, ``.confidence``, ``.geometry``).
    """
    all_fields: dict[str, list[KIEField]] = {}
    confidences: list[float] = []

    for page in result.pages:
        for class_name, predictions in page.predictions.items():
            for pred in predictions:
                if pred.confidence < min_confidence:
                    continue
                kie_field = KIEField(
                    class_name=class_name,
                    value=pred.value,
                    confidence=pred.confidence,
                    geometry=tuple(pred.geometry) if hasattr(pred, "geometry") else (),
                )
                all_fields.setdefault(class_name, []).append(kie_field)
                confidences.append(pred.confidence)

    if not confidences:
        return None

    return KIEResult(
        fields=all_fields,
        page_count=len(result.pages),
        overall_confidence=sum(confidences) / len(confidences),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_kie_fields(
    image_path: Path,
    min_confidence: float = 0.3,
    weights_path: Path | None = None,
) -> KIEResult | None:
    """Extract structured fields from an image using KIE.

    Returns ``None`` if KIE is unavailable, the weights file is missing,
    or no fields pass the confidence threshold.
    """
    predictor = _get_kie_predictor(weights_path)
    if predictor is None:
        return None
    try:
        doc = DocumentFile.from_images([str(image_path)])
        result = predictor(doc)
        return _build_kie_result(result, min_confidence)
    except Exception:
        logger.warning("KIE extraction failed for %s", image_path, exc_info=True)
        return None


def extract_kie_fields_pdf(
    pdf_path: Path,
    max_pages: int = 5,
    min_confidence: float = 0.3,
    weights_path: Path | None = None,
) -> KIEResult | None:
    """Extract structured fields from a PDF using KIE.

    Returns ``None`` if KIE is unavailable, the weights file is missing,
    or no fields pass the confidence threshold.
    """
    predictor = _get_kie_predictor(weights_path)
    if predictor is None:
        return None
    try:
        doc = DocumentFile.from_pdf(str(pdf_path))
        if len(doc) > max_pages:
            doc = doc[:max_pages]
        result = predictor(doc)
        return _build_kie_result(result, min_confidence)
    except Exception:
        logger.warning("KIE extraction failed for %s", pdf_path, exc_info=True)
        return None
