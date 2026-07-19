"""FileContext: per-file inputs with lazy, memoized extraction.

Replaces the ``ContentOrganizer`` per-file instance state
(``_last_file_ocr_text``/``_confidence``/``_detected_language``,
``_last_file_state["kie_result"]``, ``_clip_enhance_cache``) with an explicit
value object (UNIFIED_SCORING_PLAN §5.1). Signals declare what they need by
calling ``ensure_*()``; every extraction runs at most once and nothing
observes mutation order, which removes the ordering coupling between legacy
tiers and makes per-file scoring parallel-safe.

Providers are plain callables injected by the organizer (or tests); ``None``
means the capability is unavailable and the corresponding ``ensure_*``
returns its empty value. The context never imports OCR/CLIP/KIE modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, Optional, cast

from .weights import OCR_CONFIDENCE_GATE

# Sentinel distinguishing "never computed" from a computed None/empty result.
_UNSET = object()

# Schema type whose text extraction routes through OCR (mirrors the legacy
# coupling where tier 3.5 cached OCR text for tier 6's extract_text).
_IMAGE_SCHEMA_TYPE = "ImageObject"


class FileContext:
    """Lazily populated per-file inputs shared by all signals (§5.1)."""

    def __init__(
        self,
        path: Path,
        schema_type: str,
        mime_type: Optional[str] = None,
        display_path: Optional[Path] = None,
        *,
        text_provider: Optional[Callable[[Path], str]] = None,
        ocr_provider: Optional[Callable[[Path], Any]] = None,
        clip_provider: Optional[Callable[[Path], Optional[Dict[str, float]]]] = None,
        image_metadata_provider: Optional[Callable[[Path], Dict[str, Any]]] = None,
        kie_provider: Optional[Callable[[Path], Any]] = None,
        ocr_confidence_gate: float = OCR_CONFIDENCE_GATE,
        ocr_clip_topk: Optional[int] = None,
        clip_text_labels: FrozenSet[str] = frozenset(),
    ) -> None:
        self.path = Path(path)
        self.schema_type = schema_type
        self.mime_type = mime_type
        self.display_path = Path(display_path) if display_path is not None else None

        self._text_provider = text_provider
        self._ocr_provider = ocr_provider
        self._clip_provider = clip_provider
        self._image_metadata_provider = image_metadata_provider
        self._kie_provider = kie_provider
        self._ocr_confidence_gate = ocr_confidence_gate
        # CLIP-based OCR gate (opt-in). None disables it (OCR always runs on
        # images, the historical behavior). When set to an integer K, an image
        # skips OCR unless a text-bearing label (``clip_text_labels``) ranks in
        # its top-K CLIP labels. Ranking, not magnitude: cached CLIP scores are
        # a near-uniform softmax (~0.05/label over 20 labels), so absolute
        # summed probability can't separate text images from photos — the
        # signal is in which labels rank highest (eval: K=3 → 100% text recall,
        # 35% of photos skip OCR). OCR is the dominant per-file cost.
        self._ocr_clip_topk = ocr_clip_topk
        self._clip_text_labels = clip_text_labels

        self._text: Any = _UNSET
        self._ocr: Any = _UNSET
        self._clip: Any = _UNSET
        self._image_metadata: Any = _UNSET
        self._kie: Any = _UNSET
        # Telemetry: set when ensure_ocr suppressed OCR via the CLIP gate.
        self._ocr_gated: bool = False

    # ------------------------------------------------------------------ #
    # Derived path conveniences                                            #
    # ------------------------------------------------------------------ #

    @property
    def pattern_path(self) -> Path:
        """Path whose *name* drives filename classification (display first)."""
        return self.display_path or self.path

    @property
    def is_image(self) -> bool:
        return self.schema_type == _IMAGE_SCHEMA_TYPE

    # ------------------------------------------------------------------ #
    # Lazy extractions (each provider runs at most once)                   #
    # ------------------------------------------------------------------ #

    def ensure_text(self) -> str:
        """Extracted document text ('' when unavailable).

        For images this routes through :meth:`ensure_ocr` so text and OCR are
        the same extraction — the explicit form of the legacy tier-3.5 →
        tier-6 cached-OCR coupling.
        """
        if self._text is _UNSET:
            if self.is_image:
                ocr = self.ensure_ocr()
                self._text = (ocr.text if ocr is not None else "") or ""
            elif self._text_provider is None:
                self._text = ""
            else:
                self._text = self._text_provider(self.path) or ""
        return cast(str, self._text)

    @property
    def text_length(self) -> int:
        return len(self.ensure_text())

    def ensure_ocr(self) -> Any:
        """OCR result (``shared.ocr_classifier.OCRResult``-shaped) or None.

        The provider is *image* OCR (easyocr → docTR image readers), so
        non-images resolve to None without invoking it — their text comes
        from ``ensure_text``'s text_provider (PDF/docx/xlsx/plain-text
        extractors), and feeding them to the image backends only produces
        backend errors before returning None anyway.

        When the CLIP OCR gate is enabled, an image CLIP confidently reads as
        a text-free photo skips OCR (returns None) — the OCR CNN pass is the
        dominant per-file cost, so this is the primary throughput lever on
        photo-heavy sources. The gate never fires when no OCR provider exists,
        on non-images, or when CLIP yields no signal (fail-open: run OCR).
        """
        if self._ocr is _UNSET:
            if self._ocr_provider is None or not self.is_image:
                self._ocr = None
            elif self._skip_ocr_by_clip_gate():
                self._ocr_gated = True
                self._ocr = None
            else:
                self._ocr = self._ocr_provider(self.path)
        return self._ocr

    def _skip_ocr_by_clip_gate(self) -> bool:
        """True when the CLIP gate is enabled and votes 'text-free photo'.

        Keeps OCR when any text-bearing label ranks in the top-K CLIP labels;
        skips otherwise. Fails open (keeps OCR) when the gate is disabled (K
        is None, 0, or negative), the file is not an image, or CLIP produced
        no signal. Pass K=0 to disable (e.g. --ocr-clip-topk 0 on CLI).
        """
        if not self._ocr_clip_topk or self._ocr_clip_topk < 0 or not self.is_image:
            return False
        clip = self.ensure_clip()
        if not clip:  # no CLIP signal → fail open, keep OCR
            return False
        top_labels = sorted(clip, key=lambda label: clip[label], reverse=True)[
            : self._ocr_clip_topk
        ]
        return not any(label in self._clip_text_labels for label in top_labels)

    @property
    def ocr_gated(self) -> bool:
        """Whether the CLIP gate suppressed OCR for this file (telemetry)."""
        return self._ocr_gated

    @property
    def ocr_text(self) -> str:
        ocr = self.ensure_ocr()
        return (ocr.text if ocr is not None else "") or ""

    @property
    def ocr_confidence(self) -> Optional[float]:
        ocr = self.ensure_ocr()
        return ocr.confidence if ocr is not None else None

    @property
    def ocr_language(self) -> Optional[str]:
        ocr = self.ensure_ocr()
        return ocr.language if ocr is not None else None

    def ensure_clip(self) -> Dict[str, float]:
        """CLIP label → score mapping ({} when vision is unavailable)."""
        if self._clip is _UNSET:
            scores = self._clip_provider(self.path) if self._clip_provider else None
            self._clip = dict(scores) if scores else {}
        return cast(Dict[str, float], self._clip)

    def ensure_image_metadata(self) -> Dict[str, Any]:
        """EXIF/GPS metadata summary ({} when unavailable or not an image)."""
        if self._image_metadata is _UNSET:
            provider = self._image_metadata_provider
            metadata = provider(self.path) if (provider and self.is_image) else None
            self._image_metadata = metadata or {}
        return cast(Dict[str, Any], self._image_metadata)

    def ensure_kie(self) -> Any:
        """KIE result, gated on reliable OCR (conf ≥ gate), or None.

        Encodes the legacy tier-3.5 dependency explicitly: KIE extraction only
        runs when OCR produced a confidence at or above
        ``ocr_confidence_gate`` (low-confidence OCR on a blurry photo must not
        feed structured extraction).
        """
        if self._kie is _UNSET:
            self._kie = None
            if self._kie_provider is not None:
                ocr = self.ensure_ocr()
                confidence = ocr.confidence if ocr is not None else None
                if confidence is not None and confidence >= self._ocr_confidence_gate:
                    self._kie = self._kie_provider(self.path)
        return self._kie

    # ------------------------------------------------------------------ #
    # Non-forcing accessors (telemetry/persistence must not trigger        #
    # extraction that no signal asked for)                                 #
    # ------------------------------------------------------------------ #

    @property
    def text_if_loaded(self) -> Optional[str]:
        return None if self._text is _UNSET else self._text

    @property
    def ocr_if_loaded(self) -> Any:
        return None if self._ocr is _UNSET else self._ocr

    @property
    def clip_if_loaded(self) -> Optional[Dict[str, float]]:
        return None if self._clip is _UNSET else self._clip

    @property
    def image_metadata_if_loaded(self) -> Optional[Dict[str, Any]]:
        return None if self._image_metadata is _UNSET else self._image_metadata

    @property
    def kie_if_loaded(self) -> Any:
        return None if self._kie is _UNSET else self._kie
