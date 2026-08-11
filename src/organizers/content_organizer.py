"""Content-based file organizer with classification/routing methods.

Owns the full classification layer of the production organizer
(``scripts/file_organizer_content_based.py``): filename/filepath patterns,
game-asset detection, entity (organization/person) detection, media routing,
identification-document OCR, screenshot OCR+CLIP sub-classification, and the
unified CLIP+text scoring used for weak-image enhancement.

``ContentBasedFileOrganizer`` in the script subclasses this and adds only
pipeline concerns (schema generation, graph persistence, renaming, moves).
"""

import json
import re
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Tuple, cast

if TYPE_CHECKING:
    from src.analyzers.image_analyzer import ImageContentAnalyzer
    from src.analyzers.image_metadata import ImageMetadataParser
    from src.analyzers.text_extractor import TextExtractor

from src.classifiers.entity_detector import _has_human_name_signal
from src.enrichment import MetadataEnricher
from src.organizers.base_organizer import BaseOrganizer
from src.organizers.category_config import CONTENT_CATEGORY_PATHS
from src.organizers.mime_classifier import classify_by_mime
from src.scoring.context import FileContext
from src.scoring.registry import build_default_signals
from src.scoring.scorer import Scorer
from src.scoring.types import (
    EVIDENCE_EVENT_NAME,
    ClassificationDecision,
    DecisionSnapshot,
)
from src.scoring.signals.clip_vision import GEOGRAPHIC_LABELS, map_clip_label
from src.scoring.signals.event_content import EVENT_SIGNAL_NAME, EVENTS_CATEGORY
from src.scoring.signals.photo_composition import (
    PEOPLE_PHOTO_CATEGORY,
    PHOTO_COMPOSITION_SIGNAL_NAME,
)
from src.scoring.signals.scene import (
    EVIDENCE_SCENE_CLASS,
    EVIDENCE_SCENE_PROB,
    SCENE_DESCRIPTION_LABELS,
    SCENE_SIGNAL_NAME,
)

# Logic extracted into the unified-scoring signal modules (Phase 1); the
# legacy chain delegates to these and keeps the historical names importable.
from src.scoring.signals.filepath import (
    FILEPATH_PATTERNS,
    classify_filepath,
)
from src.scoring.signals.filepath import extract_project_name as _extract_project_name
from src.scoring.signals.game_asset import (
    GAME_SPRITE_PATTERNS,
    SPRITE_DISCRIMINATOR_KEYWORDS,
    detect_game_asset,
)
from src.scoring.signals.media_heuristic import detect_media_category
from src.scoring.signals.mime_fallback import MIME_TO_CONTENT as _MIME_TO_CONTENT  # noqa: F401
from src.scoring.signals.mime_fallback import (
    mime_result_to_content_category as _mime_result_to_content_category,
)
from src.scoring.types import (
    SCORER_DEFAULT,
    SCORER_MODES,
    SCORER_UNIFIED,
)
from src.scoring.weights import OCR_CLIP_GATE_TOPK, OCR_FORCE_DOCTR_FALLBACK

# Extracted mid-tier signal cores (UNIFIED_SCORING_PLAN Phase 1, batch B).
# The classify_* methods below delegate to these pure functions so the legacy
# chain and the unified signals share one implementation; the moved module
# constants are aliased further down under their historical underscore names.
from src.scoring.signals.legal_content import (
    LEGAL_DOCUMENT_SIGNALS,
    LEGAL_SIGNAL_MIN_HITS,
)
from src.scoring.signals.organization import ORG_MIN_TEXT_CHARS, detect_organization
from src.scoring.signals.personal_doc import (
    CONTACTS_MIN_KEYWORD_HITS,
    PERSON_MIN_KEYWORD_HITS,
    PERSON_MIN_TEXT_CHARS,
    PERSON_SUBCAT_TO_PERSONAL_SUBCAT,
    detect_person_indicators,
    is_resume_filename,
)
from src.scoring.signals.screenshot_ocr import (
    MEDIA_CATEGORY,
    SCREENSHOT_FALLBACK_SUBCATEGORY,
    SCREENSHOT_OCR_KEYWORD_THRESHOLD,
    is_screenshot_named,
    route_screenshot_ocr,
)
from shared.constants import (
    GAME_AUDIO_KEYWORDS,
    GAME_FONT_KEYWORDS,
    GAME_MUSIC_KEYWORDS,
    GAME_SPRITE_KEYWORDS,
)
from shared.file_ops import resolve_collision, should_skip_file as _shared_should_skip_file
from shared.filename_classifier import (  # noqa: F401 — re-exported for tests/script
    RESEARCH_CATEGORY,
    SCHOLARLY_ARTICLE_SCHEMA_TYPE,
)
from shared.filename_classifier import (
    FilenameClassification,
    classify_by_filename_patterns as _classify_by_filename_patterns,
)

# OCR (docTR via shared.ocr_classifier) and PDF availability probe.
# pypdf and PIL are imported here (even though extraction lives in
# src.analyzers.text_extractor) so that OCR_AVAILABLE keeps gating the
# pipeline on the full dependency set, matching historical behavior.
try:
    import pypdf  # noqa: F401 — availability probe
    from PIL import Image  # noqa: F401 — availability probe
    from shared.ocr_classifier import (
        OCR_AVAILABLE,
    )  # shared module-level flag; avoids duplicate probe
    from shared.ocr_classifier import SCREENSHOT_KEYWORDS
    from shared.ocr_classifier import classify_by_ocr as _shared_classify_by_ocr
    from shared.ocr_classifier import extract_ocr_with_confidence

    # HEIC support
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:
        pass
except ImportError:
    OCR_AVAILABLE = False
    SCREENSHOT_KEYWORDS: Dict[str, List[str]] = {}  # type: ignore[no-redef]
    _shared_classify_by_ocr = None  # type: ignore[assignment]
    extract_ocr_with_confidence = None  # type: ignore[assignment]

# KIE (Key Information Extraction) imports
try:
    from shared.kie_utils import extract_kie_fields, is_kie_available

    KIE_AVAILABLE = is_kie_available()
except ImportError:
    KIE_AVAILABLE = False

# CLIP enhancement constants for weak image classification
try:
    from shared.constants import (
        CLIP_CATEGORY_PROMPTS,
        CLIP_CONTENT_LABELS,
        CLIP_ENHANCE_THRESHOLD,
        CLIP_LABEL_TO_ORGANIZER,
        CLIP_TEXT_BEARING_LABELS,
    )

    ENHANCED_CLIP_AVAILABLE = True
except ImportError:
    ENHANCED_CLIP_AVAILABLE = False
    CLIP_CATEGORY_PROMPTS: List[str] = []  # type: ignore[no-redef]
    CLIP_CONTENT_LABELS: List[str] = []  # type: ignore[no-redef]
    CLIP_LABEL_TO_ORGANIZER: Dict[str, Tuple[str, str]] = {}  # type: ignore[no-redef]
    CLIP_ENHANCE_THRESHOLD: float = 0.3  # type: ignore[no-redef]
    CLIP_TEXT_BEARING_LABELS: frozenset = frozenset()  # type: ignore[no-redef]

# CLIP classifier — used by the weak-image enhancement signal (_run_clip_signal).
# Image composition/face detection lives in the injected image_analyzer.
try:
    from shared.clip_utils import get_clip_classifier
except ImportError:
    get_clip_classifier = None  # type: ignore[assignment]
    print("Warning: Vision libraries not available. Install open-clip-torch, torch, opencv-python")

# CLIP cache support
try:
    from shared.clip_cache import CLIP_CACHE_AVAILABLE, get_cached_embedding
except ImportError:
    CLIP_CACHE_AVAILABLE = False

# Reverse map: full CLIP prompt → short CLIP_CONTENT_LABELS key.
# Built once at import time; used by _run_clip_signal.
_CLIP_PROMPT_TO_LABEL: dict = (
    dict(zip(CLIP_CATEGORY_PROMPTS, CLIP_CONTENT_LABELS)) if ENHANCED_CLIP_AVAILABLE else {}
)

# Minimum OCR confidence required to treat text as reliable for ID doc detection.
# Low-confidence OCR on a photo (e.g. a blurry selfie) must not trigger passport detection.
# Uses docTR word-level confidence (true 0–1 scale).
_OCR_CONFIDENCE_THRESHOLD = 0.3

# Screenshot OCR keyword-ratio threshold — moved (with its calibration
# comment) to src/scoring/signals/screenshot_ocr.py; aliased for existing
# importers (scripts/file_organizer_content_based.py re-exports it).
_SCREENSHOT_OCR_KEYWORD_THRESHOLD = SCREENSHOT_OCR_KEYWORD_THRESHOLD

# The extension-only voters' generic photo bucket (MediaHeuristicSignal +
# MimeFallbackSignal both emit it); the people-photo refinement only ever
# rewrites THIS subcategory (see _refine_people_photo_subcategory).
_GENERIC_PHOTO_SUBCATEGORY = "photos_other"

# Provenance reroute for scene-classified screenshots: when a scene-class
# media subcategory wins on a screenshot-named file, refile it under
# Media/Photos/Screenshots/* — a screenshot OF a listing photo is reference
# material and belongs with the other screenshots, while Media/{Interiors,
# Exteriors,Place} hold first-party photos and renders. The scene schema
# @type (Room/House/Place) is kept: the @type answers "what does it depict",
# the folder answers "how was it captured". graphics_other is deliberately
# absent — the graphic-vs-screenshot boundary is the probe corpus's job and
# graphic already maps to ImageObject.
SCREENSHOT_SCENE_SUBCATEGORY: Dict[str, str] = {
    "interiors_other": "photos_screenshots_interiors",
    "exteriors_other": "photos_screenshots_exteriors",
    "place_other": "photos_screenshots_places",
}

# Unified-scoring weights for the image classification path.
# CLIP score (already 0-1) is used as-is; OCR-text contributes a prior scaled by
# extraction length, plus an agreement boost when both signals point at the same
# (category, subcategory). Values are tuned so that text — which is typically
# more semantically specific than CLIP — wins ties on longer OCR extractions,
# while CLIP retains primacy when text extraction is sparse or unparseable.
_TEXT_SIGNAL_PRIOR = 0.80
_TEXT_LENGTH_FULL_CHARS = 200
_TEXT_MIN_CHARS = 30
_SIGNAL_AGREEMENT_BOOST = 0.15

# Option C person→personal subcategory map and person keyword thresholds —
# moved (with their rationale comments) to src/scoring/signals/personal_doc.py;
# aliased for existing importers.
_PERSON_SUBCAT_TO_PERSONAL_SUBCAT = PERSON_SUBCAT_TO_PERSONAL_SUBCAT
_PERSON_MIN_KEYWORD_HITS = PERSON_MIN_KEYWORD_HITS
_CONTACTS_MIN_KEYWORD_HITS = CONTACTS_MIN_KEYWORD_HITS

# Legal-document veto vocabulary for the person keyword tier — moved (with its
# rationale comment) to src/scoring/signals/legal_content.py; aliased for the
# veto in classify_by_person and existing importers.
_LEGAL_DOCUMENT_SIGNALS = LEGAL_DOCUMENT_SIGNALS
_LEGAL_SIGNAL_MIN_HITS = LEGAL_SIGNAL_MIN_HITS

# Content categories that indicate a *document* (as opposed to a photo, game
# asset, or generic media). Used to let clean, high-confidence OCR text override
# a filename-driven game-asset/media guess — e.g. "medellin_bloodwork" matches
# the game sprite keyword "blood" but OCRs as Spanish lab results → medical.
# Excludes 'media', 'game_assets', and 'uncategorized' on purpose.
_DOCUMENT_CONTENT_CATEGORIES = frozenset(
    {"financial", "medical", "legal", "business", "personal", "technical", "research", "education"}
)


def _derive_schema_type(mime_type: Optional[str]) -> str:
    """Map a MIME type onto the coarse Schema.org type the pipeline uses."""
    if mime_type:
        if mime_type.startswith("image/"):
            return "ImageObject"
        if mime_type == "application/pdf":
            return "DigitalDocument"
        if mime_type.startswith("video/"):
            return "VideoObject"
        if mime_type.startswith("audio/"):
            return "AudioObject"
    return "DigitalDocument"


# The MIME→content translation (formerly ``_MIME_TO_CONTENT`` /
# ``_mime_result_to_content_category`` here) moved to
# ``src.scoring.signals.mime_fallback`` (MimeFallbackSignal extraction) and is
# re-imported above under the historical underscore names.


class ContentOrganizer(BaseOrganizer):
    """
    Organizer that classifies files by content, filename patterns, and entities.

    Heavy dependencies (content classifier, image analyzer, metadata parser,
    text extractor, MIME enricher) are injected; all default to ``None`` so the
    organizer stays constructible in lightweight/test contexts.
    """

    # Canonical set lives in src.scoring.signals.clip_vision; kept as a class
    # attribute alias for backward compatibility with existing consumers.
    _GEOGRAPHIC_LABELS = GEOGRAPHIC_LABELS

    # Subset of game_sprite_keywords that implies sprite (vs texture)
    # classification. Single-homed in src.scoring.signals.game_asset
    # (GameAssetSignal extraction); kept as a class attribute so subclass
    # overrides keep working.
    _SPRITE_DISCRIMINATOR_KEYWORDS = SPRITE_DISCRIMINATOR_KEYWORDS

    def __init__(
        self,
        base_path: Path,
        content_classifier: Any,
        organize_by_date: bool = False,
        organize_by_location: bool = False,
        enable_cost_tracking: bool = False,
        db_path: str | None = None,
        *,
        image_analyzer: Optional["ImageContentAnalyzer"] = None,
        metadata_parser: Optional["ImageMetadataParser"] = None,
        text_extractor: Optional["TextExtractor"] = None,
        enricher: Optional[MetadataEnricher] = None,
        screenshot_content_classifier: Any = None,
        ocr_available: Optional[bool] = None,
        scorer: str = SCORER_DEFAULT,
        ocr_clip_topk: Optional[int] = OCR_CLIP_GATE_TOPK,
        force_doctr_fallback: bool = OCR_FORCE_DOCTR_FALLBACK,
    ) -> None:
        super().__init__(
            base_path=base_path,
            organize_by_date=organize_by_date,
            organize_by_location=organize_by_location,
            enable_cost_tracking=enable_cost_tracking,
            db_path=db_path,
        )
        if scorer not in SCORER_MODES:
            raise ValueError(f"scorer must be one of {SCORER_MODES}, got {scorer!r}")
        self.scorer_mode = scorer
        # CLIP-based OCR gate top-K. Defaults to OCR_CLIP_GATE_TOPK (3) so OCR
        # is skipped on text-free photos without any flag: a text-bearing CLIP
        # label must rank in the top-K for OCR to run. Fails open when CLIP is
        # unavailable (no signal = run OCR). Pass 0 or None to disable.
        # (UNIFIED_SCORING_PLAN P1)
        self.ocr_clip_topk = ocr_clip_topk
        # docTR-fallback gate (P2): False (default) skips the docTR pass when
        # easyocr cleanly finds no text; True always runs it (faint-text
        # recall over cost). CLI: --ocr-doctr-fallback.
        self.force_doctr_fallback = force_doctr_fallback
        # Built lazily on first classification (registry deps need the fully
        # constructed organizer).
        self._unified_scorer: Optional[Scorer] = None
        self.classifier = content_classifier
        self.image_analyzer = image_analyzer
        self.metadata_parser = metadata_parser
        self.text_extractor = text_extractor
        self.enricher = enricher
        # ContentClassifier used for screenshot OCR sub-classification (the
        # production script passes its image renamer's classifier here).
        self.screenshot_content_classifier = screenshot_content_classifier
        self.ocr_available = OCR_AVAILABLE if ocr_available is None else ocr_available

        # Temporary OCR metadata for the current file being processed.
        # Set inside detect_file_category; consumed by downstream persistence.
        self._last_file_ocr_confidence: Optional[float] = None
        self._last_file_detected_language: Optional[str] = None
        self._last_file_ocr_text: Optional[str] = None  # cached OCR text to avoid re-running
        # Structured per-file outputs (KIE result, research-paper metadata).
        # Keyed dict so new metadata types can land here without growing the
        # attribute surface.
        self._last_file_state: Dict[str, Any] = {}
        # Per-file CLIP enhance cache: (file_path, tuple(labels)) -> List of results
        self._clip_enhance_cache: Dict[tuple, list] = {}

        # Filepath-based classification (checked FIRST before content analysis).
        # Rule table single-homed in src.scoring.signals.filepath
        # (FilepathSignal extraction); per-instance copy so instance-level
        # mutation cannot leak across organizers.
        self.filepath_patterns: Dict[str, str] = dict(FILEPATH_PATTERNS)

        # Content-based organization structure: shared taxonomy, deepcopied
        # because __init__ extends the screenshots sub-dict per instance.
        self.category_paths: Dict[str, Any] = deepcopy(CONTENT_CATEGORY_PATHS)

        # Extend screenshot sub-folders from classifier taxonomies so that
        # content labels map directly to folder paths without a separate lookup.
        _screenshots = self.category_paths["media"]["photos"]["screenshots"]
        for key in SCREENSHOT_KEYWORDS:
            if key not in _screenshots:
                folder = key.replace("_", " ").title().replace(" ", "")
                _screenshots[key] = f"Media/Photos/Screenshots/{folder}"
        for key in getattr(self.classifier, "patterns", None) or []:
            if key not in _screenshots:
                _screenshots[key] = f"Media/Photos/Screenshots/{key.title()}"

        # Game asset detection patterns — single-homed in shared.constants
        # (same lists the eval baseline uses).
        self.game_audio_keywords: List[str] = GAME_AUDIO_KEYWORDS
        self.game_music_keywords: List[str] = GAME_MUSIC_KEYWORDS

        # Single-homed in shared.constants (same list the production script used).
        self.game_sprite_keywords: List[str] = GAME_SPRITE_KEYWORDS

        # Regex patterns for game asset detection (numbered sprites, variants).
        # Single-homed in src.scoring.signals.game_asset (GameAssetSignal
        # extraction); per-instance list so subclasses may extend it without
        # mutating the shared constant.
        self.game_sprite_patterns: List[re.Pattern[str]] = list(GAME_SPRITE_PATTERNS)

        # Game font sprite sheet patterns — single-homed in shared.constants
        self.game_font_keywords: List[str] = GAME_FONT_KEYWORDS

    # ------------------------------------------------------------------ #
    # Classification methods                                               #
    # ------------------------------------------------------------------ #

    def classify_by_filepath(self, file_path: Path) -> Optional[str]:
        """
        Classify file based on filepath patterns (extension, filename).

        Delegates to the pure ``classify_filepath`` in
        ``src.scoring.signals.filepath``, passing the per-instance pattern
        table so instance/subclass overrides of ``filepath_patterns`` keep
        working.

        Returns:
            Category path string if matched, None otherwise
        """
        return classify_filepath(file_path, self.filepath_patterns)

    def extract_project_name(self, file_path: Path) -> Optional[str]:
        """
        Extract project name from file path.

        Looks for common project indicators in path:
        - Directory names like 'myproject', 'my-app', etc.
        - Skips common non-project directories

        Delegates to the pure ``extract_project_name`` in
        ``src.scoring.signals.filepath`` (FilepathSignal extraction).

        Returns:
            Project name if found, None otherwise
        """
        return _extract_project_name(file_path)

    def classify_game_asset(self, file_path: Path) -> Optional[Tuple[str, str]]:
        """
        Classify file as a game asset based on filename patterns.

        Delegates to the pure ``detect_game_asset`` in
        ``src.scoring.signals.game_asset``, passing instance keyword/pattern
        state explicitly so subclass overrides keep working.

        Returns:
            Tuple of (category, subcategory) or None if not a game asset
        """
        return detect_game_asset(
            file_path,
            music_keywords=self.game_music_keywords,
            audio_keywords=self.game_audio_keywords,
            font_keywords=self.game_font_keywords,
            sprite_patterns=self.game_sprite_patterns,
            sprite_keywords=self.game_sprite_keywords,
            sprite_discriminators=self._SPRITE_DISCRIMINATOR_KEYWORDS,
        )

    def classify_by_organization(self, text: str, filename: str) -> Optional[Tuple[str, str, str]]:
        """
        Classify file primarily by Organization entity detection.

        Looks for strong organization indicators like:
        - Company names in headers/footers
        - Official letterheads
        - Business correspondence
        - Invoices, contracts with company names

        Returns:
            Tuple of (category, subcategory, org_name) or None if no strong organization match

        The indicator vocabulary and matching rules moved to
        ``src/scoring/signals/organization.py`` (``ORG_INDICATORS`` /
        ``detect_organization``); this method delegates so the legacy chain
        and ``OrganizationKeywordSignal`` share one implementation.
        """
        if not text or len(text) < ORG_MIN_TEXT_CHARS:
            return None

        detected = detect_organization(
            text, extract_company_names=self.classifier.extract_company_names
        )
        if detected is None:
            return None
        org_type, org_name, _hits = detected
        return ("organization", org_type, org_name)

    def classify_by_person(self, text: str, filename: str) -> Optional[Tuple[str, str, List[str]]]:
        """
        Classify file primarily by Person entity detection.

        Looks for strong person indicators like:
        - Resumes/CVs
        - Contact information (vCards)
        - Personal identification documents
        - Reference letters

        Returns:
            Tuple of (category, subcategory, person_names) or None if no strong person match

        The indicator vocabulary and matching core moved to
        ``src/scoring/signals/personal_doc.py`` (``PERSON_INDICATORS`` /
        ``detect_person_indicators``); this method delegates but KEEPS the
        legal-document veto and the binary name gate — ``PersonalDocSignal``
        replaces both with competition/graduated confidence in the unified
        scorer.
        """
        if not text or len(text) < PERSON_MIN_TEXT_CHARS:
            return None

        # Check filename patterns for resumes/CVs
        if is_resume_filename(filename):
            people = self.classifier.extract_people_names(text)
            return ("personal", "contacts", people if people else [])

        # Legal-document veto: court filings carry clerk contact info that
        # satisfies the generic person indicators; defer to content analysis.
        text_lower = text.lower()
        legal_hits = sum(1 for kw in _LEGAL_DOCUMENT_SIGNALS if kw in text_lower)
        if legal_hits >= _LEGAL_SIGNAL_MIN_HITS:
            return None

        match = detect_person_indicators(
            text,
            extract_people_names=self.classifier.extract_people_names,
            has_human_name_signal=_has_human_name_signal,
        )
        if match is None or not match.people or not match.name_gate:
            return None
        return ("personal", match.subcategory, match.people)

    def classify_media_file(
        self, file_path: Path, image_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Tuple[str, str, str]]:
        """
        Classify media files (photos, videos, audio) into subcategories.

        Delegates to the pure ``detect_media_category`` in
        ``src.scoring.signals.media_heuristic`` (MediaHeuristicSignal
        extraction).

        Returns:
            Tuple of (category, media_type, subcategory) or None if not a media file
            Example: ('media', 'photos', 'documents') or ('media', 'videos', 'recordings')
        """
        return detect_media_category(file_path, image_metadata)

    def classify_by_filename_patterns(self, file_path: Path) -> Optional[FilenameClassification]:
        """
        Classify file based on filename patterns before content extraction.

        Delegates to the shared ``filename_classifier`` so the rule set is
        single-homed with ``scripts/file_organizer_content_based.py``. Returns
        ``(category, subcategory, company_name, people_names)`` or ``None``.
        """
        return _classify_by_filename_patterns(
            file_path,
            game_sprite_keywords=self.game_sprite_keywords,
            last_file_state=self._last_file_state,
        )

    # ------------------------------------------------------------------ #
    # Text extraction (cache-aware wrappers over the injected extractor)   #
    # ------------------------------------------------------------------ #

    def extract_text_from_image(self, image_path: Path) -> str:
        """Extract text from image using docTR OCR.

        Reuses cached OCR text from ID detection or the image renamer
        when available, avoiding a redundant OCR pass. The cache is
        organizer state; the pure extraction lives in TextExtractor.
        """
        if not self.ocr_available:
            return ""

        # Return cached OCR text from an earlier pipeline stage if available.
        if self._last_file_ocr_text:
            return self._last_file_ocr_text

        if self.text_extractor is None:
            return ""
        return self.text_extractor.extract_text_from_image(image_path)

    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract text from PDF (searchable or scanned)."""
        if not self.ocr_available or self.text_extractor is None:
            return ""
        return self.text_extractor.extract_text_from_pdf(pdf_path)

    def extract_text_from_docx(self, docx_path: Path) -> str:
        """Extract text from Word document."""
        if self.text_extractor is None:
            return ""
        return self.text_extractor.extract_text_from_docx(docx_path)

    def extract_text_from_xlsx(self, xlsx_path: Path) -> str:
        """Extract text from Excel spreadsheet."""
        if self.text_extractor is None:
            return ""
        return self.text_extractor.extract_text_from_xlsx(xlsx_path)

    def extract_text(self, file_path: Path) -> str:
        """Extract text from various file types.

        MIME detection stays here (organizer owns the enricher); the image
        branch routes through the cache-aware wrapper above, everything else
        dispatches through the organizer methods so overrides keep working.
        """
        mime_type = (
            self.enricher.detect_mime_type(str(file_path)) if self.enricher is not None else None
        )
        file_ext = file_path.suffix.lower()

        if mime_type and mime_type.startswith("image/"):
            return self.extract_text_from_image(file_path)
        elif mime_type == "application/pdf" or file_ext == ".pdf":
            return self.extract_text_from_pdf(file_path)
        elif file_ext in [".docx", ".doc"]:
            return self.extract_text_from_docx(file_path)
        elif file_ext in [".xlsx", ".xls"]:
            return self.extract_text_from_xlsx(file_path)

        # Text files and unknown types: pure extraction, no organizer state.
        if self.text_extractor is None:
            return ""
        return self.text_extractor.extract_text(file_path, mime_type)

    # ------------------------------------------------------------------ #
    # CLIP / unified-scoring signals                                       #
    # ------------------------------------------------------------------ #

    def _map_clip_label(
        self, label: str, image_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Tuple[str, str]]:
        """Map a CLIP label to (category, subcategory), upgrading to travel if GPS present.

        Delegates to the pure ``map_clip_label`` in
        ``src.scoring.signals.clip_vision`` (passing this module's
        import-guarded ``CLIP_LABEL_TO_ORGANIZER``).
        """
        return map_clip_label(
            label, image_metadata, CLIP_LABEL_TO_ORGANIZER, self._GEOGRAPHIC_LABELS
        )

    def _merge_clip_text_scores(
        self,
        clip_candidate: Optional[Tuple[str, str]],
        clip_score: float,
        text_candidate: Optional[Tuple[str, str]],
        text_chars: int,
    ) -> Optional[Tuple[Tuple[str, str], float, str]]:
        """Combine CLIP and OCR-text signals into a per-(category, subcategory)
        weighted score. Returns (winner, total_score, sources_str) or None.

        Used by both the main image path and enhance_weak_image_classification
        so that PDF/PNG sibling files of the same content converge on the same
        category regardless of which extraction modality dominates.
        """
        scores: Dict[Tuple[str, str], float] = {}
        sources: Dict[Tuple[str, str], List[str]] = {}
        if clip_candidate and clip_score > 0:
            scores[clip_candidate] = scores.get(clip_candidate, 0.0) + clip_score
            sources.setdefault(clip_candidate, []).append(f"CLIP {clip_score:.2f}")
        if text_candidate and text_chars >= _TEXT_MIN_CHARS:
            text_score = _TEXT_SIGNAL_PRIOR * min(1.0, text_chars / _TEXT_LENGTH_FULL_CHARS)
            scores[text_candidate] = scores.get(text_candidate, 0.0) + text_score
            sources.setdefault(text_candidate, []).append(f"text {text_score:.2f}")
        if clip_candidate and text_candidate and clip_candidate == text_candidate:
            scores[clip_candidate] += _SIGNAL_AGREEMENT_BOOST
            sources[clip_candidate].append("agree")
        if not scores:
            return None
        winner, top = max(scores.items(), key=lambda kv: kv[1])
        return winner, top, ", ".join(sources[winner])

    def _cross_check_with_clip(
        self,
        file_path: Path,
        image_metadata: Optional[Dict],
        category: str,
        subcategory: str,
        text_chars: int,
    ) -> Tuple[str, str]:
        """Cross-check a text-derived image classification against CLIP and
        return the merged winner, swapping (cat, sub) only when CLIP outscores
        the text candidate.
        """
        clip_candidate, clip_score = self._run_clip_signal(file_path, image_metadata)
        if not clip_candidate:
            return (category, subcategory)
        merged = self._merge_clip_text_scores(
            clip_candidate,
            clip_score,
            (category, subcategory),
            text_chars,
        )
        if not merged:
            return (category, subcategory)
        (m_cat, m_sub), m_score, m_src = merged
        if (m_cat, m_sub) == (category, subcategory):
            return (category, subcategory)
        print(f"  Unified → {m_cat}/{m_sub} ({m_src}; total {m_score:.2f})")
        return (m_cat, m_sub)

    def _run_clip_signal(
        self,
        file_path: Path,
        image_metadata: Optional[Dict] = None,
    ) -> Tuple[Optional[Tuple[str, str]], float]:
        """Run the 20-category CLIP classifier and map its top label.

        Returns (candidate, score) or (None, 0.0) if CLIP is unavailable or
        below the enhancement threshold.
        """
        if (
            not ENHANCED_CLIP_AVAILABLE
            or self.image_analyzer is None
            or not self.image_analyzer.vision_available
        ):
            return (None, 0.0)
        enhance_cache_key = (str(file_path), tuple(CLIP_CATEGORY_PROMPTS))
        try:
            if enhance_cache_key in self._clip_enhance_cache:
                results = self._clip_enhance_cache[enhance_cache_key]
            elif CLIP_CACHE_AVAILABLE:
                results = get_cached_embedding(file_path, CLIP_CATEGORY_PROMPTS, prompt_prefix="")
                self._clip_enhance_cache[enhance_cache_key] = results
            else:
                results = get_clip_classifier().classify_raw(file_path, CLIP_CATEGORY_PROMPTS)
                self._clip_enhance_cache[enhance_cache_key] = results
            best_prompt, best_score = results[0]
            best_label = _CLIP_PROMPT_TO_LABEL.get(best_prompt, best_prompt)
        except Exception as e:
            print(f"  CLIP signal error: {e}")
            return (None, 0.0)
        # Stash the raw label for schema.org description composition even when
        # the score is below the classification-enhancement threshold — the
        # description states its confidence, so a weak signal is still useful.
        self._last_file_state["clip_description"] = (best_label, best_score)
        if best_score < CLIP_ENHANCE_THRESHOLD:
            return (None, 0.0)
        return (self._map_clip_label(best_label, image_metadata), best_score)

    def enhance_weak_image_classification(
        self, file_path: Path, image_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Tuple[str, str]]:
        """Run full 20-category CLIP + OCR fallback for weakly classified images.

        Only called for images that would otherwise land in photos_other or uncategorized.
        Returns (category, subcategory) or None to keep original classification.
        """
        clip_candidate, clip_score = self._run_clip_signal(file_path, image_metadata)
        # Do NOT bail when CLIP is weak — that is exactly when OCR text should
        # decide. _merge_clip_text_scores tolerates a missing CLIP signal and
        # returns None only when neither CLIP nor text yields a candidate.

        text_candidate: Optional[Tuple[str, str]] = None
        text_chars = 0
        if self.ocr_available:
            try:
                ocr_text = self.extract_text_from_image(file_path)
                if ocr_text and len(ocr_text) >= _TEXT_MIN_CHARS:
                    text_chars = len(ocr_text)
                    text_cat, text_subcat, _, _ = self.classifier.classify_content(
                        ocr_text, file_path.name
                    )
                    if text_cat != "uncategorized":
                        text_candidate = (text_cat, text_subcat)
            except Exception as e:
                print(f"  CLIP enhance OCR error: {e}")

        merged = self._merge_clip_text_scores(
            clip_candidate,
            clip_score,
            text_candidate,
            text_chars,
        )
        if not merged:
            return None
        winner, top_score, src = merged
        print(f"  Unified → {winner[0]}/{winner[1]} ({src}; total {top_score:.2f})")
        return winner

    def _ocr_document_override(self, file_path: Path) -> Optional[Tuple[str, str]]:
        """Return a (category, subcategory) from OCR content when a document image
        was misrouted by a filename heuristic (e.g. "bloodwork" → game "blood").

        Runs OCR (reusing cached text when present), classifies it, and returns the
        content category only when OCR is reliable and maps to a genuine document
        category (_DOCUMENT_CONTENT_CATEGORIES). Returns None otherwise so the
        caller keeps its original classification.
        """
        if not getattr(self, "ocr_available", False):
            return None
        ocr_text = self._last_file_ocr_text
        if not ocr_text:
            _res = extract_ocr_with_confidence(
                file_path, max_chars=0, force_doctr_fallback=self.force_doctr_fallback
            )
            if _res:
                ocr_text = _res.text
                self._last_file_ocr_confidence = _res.confidence
                self._last_file_detected_language = _res.language
                if ocr_text:
                    self._last_file_ocr_text = ocr_text
        conf = self._last_file_ocr_confidence
        if not ocr_text or len(ocr_text) < _TEXT_MIN_CHARS:
            return None
        if conf is not None and conf < _OCR_CONFIDENCE_THRESHOLD:
            return None
        cat, subcat, _, _ = self.classifier.classify_content(ocr_text, file_path.name)
        if cat in _DOCUMENT_CONTENT_CATEGORIES:
            return (cat, subcat)
        return None

    # ------------------------------------------------------------------ #
    # Category detection pipeline                                          #
    # ------------------------------------------------------------------ #

    def detect_file_category(
        self,
        file_path: Path,
        display_path: Path | None = None,
    ) -> Tuple[str, str, str, str, Optional[str], List[str], Dict[str, Any]]:
        """
        Detect file category based on content.

        Runs the unified weighted signal scorer (UNIFIED_SCORING_PLAN §3).
        The legacy 10-tier chain and shadow mode were removed in Phase 5;
        the extracted per-tier ``classify_*`` helpers remain as directly
        testable shims over their signals.

        Args:
            file_path: Physical path to the file on disk (used for content reading).
            display_path: Optional override path whose *name* is used for
                filename-pattern classification.  When the image renamer proposes
                a rename in dry-run mode, display_path carries the descriptive
                name while file_path still points to the original file.

        Returns:
            Tuple of (main_category, subcategory, schema_type, extracted_text,
            company_name, people_names, image_metadata)
        """
        result = self._detect_file_category_unified(file_path, display_path)
        # Category-independent enrichment (runs for both engines): derive a
        # file→location edge from a postal address in the extracted text when
        # the file has no image-GPS location. Never changes category/folder.
        return self._enrich_location_from_text(result)

    def _enrich_location_from_text(
        self,
        result: Tuple[str, str, str, str, Optional[str], List[str], Dict[str, Any]],
    ) -> Tuple[str, str, str, str, Optional[str], List[str], Dict[str, Any]]:
        """Add a text-derived location to image_metadata['location'].

        A no-op when the file already has a location (image EXIF GPS), has no
        extracted text, or no address is found. Forward-geocodes the address
        (rate-limited + cached) for coordinates; falls back to the parsed
        city/state with null coordinates when geocoding is unavailable, so an
        edge is still created. Tuple arity is unchanged.
        """
        category, subcategory, schema_type, text, company, people, image_metadata = result
        image_metadata = image_metadata or {}
        if image_metadata.get("location") or image_metadata.get("location_name") or not text:
            return result

        try:
            from ..analyzers.address_extractor import extract_primary_address
        except ImportError:
            try:
                from analyzers.address_extractor import (  # type: ignore[no-redef]
                    extract_primary_address,
                )
            except ImportError:
                return result

        address = extract_primary_address(text)
        if not address:
            return result

        geo: Mapping[str, object] = {}
        raw_address = address.get("raw")
        if self.metadata_parser is not None and raw_address:
            try:
                geo = self.metadata_parser.geocode_address(raw_address) or {}
            except Exception:
                geo = {}

        location = {
            "display_name": geo.get("display_name") or address.get("display_name"),
            "latitude": geo.get("latitude"),
            "longitude": geo.get("longitude"),
            "city": geo.get("city") or address.get("city"),
            "state": geo.get("state") or address.get("state"),
            "country": geo.get("country"),
        }
        image_metadata = dict(image_metadata)
        image_metadata["location"] = location
        return (category, subcategory, schema_type, text, company, people, image_metadata)

    # ------------------------------------------------------------------ #
    # Unified scoring path (UNIFIED_SCORING_PLAN §3)                       #
    # ------------------------------------------------------------------ #

    def _get_unified_scorer(self) -> Scorer:
        """Build the Scorer over the registered signals on first use."""
        if self._unified_scorer is None:
            signals = build_default_signals(
                classifier=self.classifier,
                screenshot_classifier=self.screenshot_content_classifier,
                image_analyzer=self.image_analyzer,
                category_paths=self.category_paths,
                game_sprite_keywords=self.game_sprite_keywords,
            )
            self._unified_scorer = Scorer(signals)
        return self._unified_scorer

    def _extract_text_pure(self, file_path: Path, mime_type: Optional[str]) -> str:
        """Text extraction without organizer per-file cache state.

        Mirrors :meth:`extract_text` dispatch but never consults
        ``_last_file_ocr_text`` — FileContext owns memoization on the unified
        path (image OCR routes through ``FileContext.ensure_ocr``, so this
        provider only serves non-image types).
        """
        if self.text_extractor is None:
            return ""
        file_ext = file_path.suffix.lower()
        if mime_type == "application/pdf" or file_ext == ".pdf":
            if not self.ocr_available:
                return ""
            return self.text_extractor.extract_text_from_pdf(file_path)
        if file_ext in [".docx", ".doc"]:
            return self.text_extractor.extract_text_from_docx(file_path)
        if file_ext in [".xlsx", ".xls"]:
            return self.text_extractor.extract_text_from_xlsx(file_path)
        return self.text_extractor.extract_text(file_path, mime_type)

    def _clip_scores_for_context(self, file_path: Path) -> Optional[Dict[str, float]]:
        """Full CLIP label→score mapping for the unified path (cache-backed).

        Same fetch as :meth:`_run_clip_signal` but returns every label score
        (signals apply their own thresholds) and keeps no organizer state.
        """
        try:
            if CLIP_CACHE_AVAILABLE:
                results = get_cached_embedding(file_path, CLIP_CATEGORY_PROMPTS, prompt_prefix="")
            else:
                results = get_clip_classifier().classify_raw(file_path, CLIP_CATEGORY_PROMPTS)
        except Exception as e:
            print(f"  CLIP signal error: {e}")
            return None
        return {_CLIP_PROMPT_TO_LABEL.get(prompt, prompt): score for prompt, score in results}

    def _build_file_context(
        self, file_path: Path, display_path: Optional[Path] = None
    ) -> FileContext:
        """Assemble the lazily-populated per-file inputs for the scorer."""
        mime_type = (
            self.enricher.detect_mime_type(str(file_path)) if self.enricher is not None else None
        )
        schema_type = _derive_schema_type(mime_type)

        ocr_provider = None
        if self.ocr_available and extract_ocr_with_confidence is not None:

            def ocr_provider(path: Path):  # noqa: F811 — conditional binding
                return extract_ocr_with_confidence(
                    path, max_chars=0, force_doctr_fallback=self.force_doctr_fallback
                )

        clip_provider = None
        if (
            ENHANCED_CLIP_AVAILABLE
            and self.image_analyzer is not None
            and self.image_analyzer.vision_available
        ):
            clip_provider = self._clip_scores_for_context

        metadata_provider = None
        if self.metadata_parser is not None and self.metadata_parser.metadata_available:
            metadata_provider = self.metadata_parser.get_metadata_summary

        kie_provider = extract_kie_fields if KIE_AVAILABLE else None

        def text_provider(path: Path) -> str:
            return self._extract_text_pure(path, mime_type)

        return FileContext(
            path=file_path,
            schema_type=schema_type,
            mime_type=mime_type,
            display_path=display_path,
            text_provider=text_provider,
            ocr_provider=ocr_provider,
            clip_provider=clip_provider,
            image_metadata_provider=metadata_provider,
            kie_provider=kie_provider,
            ocr_confidence_gate=_OCR_CONFIDENCE_THRESHOLD,
            ocr_clip_topk=self.ocr_clip_topk,
            clip_text_labels=CLIP_TEXT_BEARING_LABELS,
        )

    def _detect_file_category_unified(
        self,
        file_path: Path,
        display_path: Path | None = None,
        *,
        update_state: bool = True,
    ) -> Tuple[str, str, str, str, Optional[str], List[str], Dict[str, Any]]:
        """Classify via the unified scorer, adapting to the legacy 7-tuple.

        ``update_state=False`` (shadow mode) leaves the legacy per-file
        instance state untouched so persistence keeps reading the legacy
        chain's OCR/KIE metadata.
        """
        if update_state:
            self._last_file_ocr_confidence = None
            self._last_file_detected_language = None
            self._last_file_ocr_text = None
            self._last_file_state.clear()
            self._clip_enhance_cache.clear()

        ctx = self._build_file_context(file_path, display_path)
        decision = self._get_unified_scorer().classify(ctx)
        decision = self._reroute_screenshot_scene(ctx, decision)
        decision = self._refine_people_photo_subcategory(decision)

        if update_state:
            ocr = ctx.ocr_if_loaded
            if ocr is not None:
                self._last_file_ocr_confidence = ocr.confidence
                self._last_file_detected_language = ocr.language
                if ocr.text:
                    self._last_file_ocr_text = ocr.text
            kie = ctx.kie_if_loaded
            if kie is not None:
                self._last_file_state["kie_result"] = kie
            self._stash_decision_state(decision, scorer_label=SCORER_UNIFIED)

        return (
            decision.category,
            decision.subcategory,
            decision.schema_type,
            ctx.text_if_loaded or "",
            decision.company_name,
            decision.people_names,
            ctx.image_metadata_if_loaded or {},
        )

    @staticmethod
    def _reroute_screenshot_scene(
        ctx: FileContext, decision: ClassificationDecision
    ) -> ClassificationDecision:
        """Refile a scene-class win on a screenshot-named file under Screenshots/*.

        Applied after scoring, before state stash/persistence, so the stored
        subcategory matches the folder. Only the subcategory changes — the
        schema @type and the raw votes in ``all_scores`` are untouched (the
        original scene subcategory stays visible there for audit). Renamed or
        cropped screenshots miss the filename gate and keep today's
        ``Media/{Interiors,Exteriors,Place}`` placement by design.

        Corroboration guard: when ``SceneSignal`` is the *sole* winner
        (``winning_signals == ["scene"]``), the probe's calibrated high
        confidence (~0.99) inflates the decision margin to ~0.81, bypassing
        the ``low_margin`` gate even when all other signals score 1–12%.  A
        screenshot labelled as an interior by the probe alone is ambiguous
        (real-estate listing screenshot vs. an actual room photo) — route to
        the generic screenshots bucket instead of committing the scene class.
        When another signal also voted for the winning (category, subcategory)
        the decision is corroborated and the specific reroute applies normally.
        """
        if decision.category != MEDIA_CATEGORY:
            return decision
        rerouted = SCREENSHOT_SCENE_SUBCATEGORY.get(decision.subcategory)
        if rerouted is None or not is_screenshot_named(ctx.path.stem.lower()):
            return decision
        # Solo scene win → conservative fallback; corroborated → specific bucket.
        if len(decision.winning_signals) == 1 and SCENE_SIGNAL_NAME in decision.winning_signals:
            return replace(decision, subcategory=SCREENSHOT_FALLBACK_SUBCATEGORY)
        return replace(decision, subcategory=rerouted)

    @staticmethod
    def _refine_people_photo_subcategory(
        decision: ClassificationDecision,
    ) -> ClassificationDecision:
        """Prefer ``photos_social`` over the generic ``photos_other`` for
        photos with people.

        ``media/photos_other`` from the extension-only voters
        (MediaHeuristicSignal + MimeFallbackSignal, ~0.92 aggregate)
        structurally outscores ``photos_social`` from the people detector
        (PhotoCompositionSignal, W_PEOPLE_PHOTO × 0.8 ≈ 0.52), so a people
        photo lands in Photos/Other whenever no stronger evidence fires.
        When the winner is exactly the generic bucket and the composition
        pass detected people (its ``photos_social`` vote is in
        ``all_scores``), refine the subcategory to ``photos_social``.
        Specific winners (screenshots, scene classes, events) are never
        overridden — people in a screenshot don't make it a social photo.
        Like the scene reroute, only the subcategory changes; the raw votes
        stay visible in ``all_scores`` for audit.
        """
        people_category, people_subcategory = PEOPLE_PHOTO_CATEGORY
        if (decision.category, decision.subcategory) != (
            people_category,
            _GENERIC_PHOTO_SUBCATEGORY,
        ):
            return decision
        people_vote = any(
            score.signal_name == PHOTO_COMPOSITION_SIGNAL_NAME
            and (score.category, score.subcategory) == PEOPLE_PHOTO_CATEGORY
            for score in decision.all_scores
        )
        if not people_vote:
            return decision
        return replace(decision, subcategory=people_subcategory)

    def _stash_decision_state(self, decision: ClassificationDecision, *, scorer_label: str) -> None:
        """Populate ``_last_file_state`` from decision evidence.

        Mirrors the legacy side-channels downstream consumers read:
        ``research`` (ScholarlyArticle provenance for schema generation),
        ``clip_description`` ((label, score) for description composition),
        plus the JSON-safe ``scoring_decision`` snapshot persisted into
        ``file_categories.signal_evidence``.
        """
        # A probe-detected scene describes itself from its calibrated
        # P(class), not the zero-shot CLIP label whose softmax floor (~5%)
        # understated these images. Set first so the first-write-wins clip_label
        # loop below cannot overwrite it.
        if SCENE_SIGNAL_NAME in decision.winning_signals:
            for score in decision.all_scores:
                if score.signal_name != SCENE_SIGNAL_NAME:
                    continue
                scene_class = score.evidence.get(EVIDENCE_SCENE_CLASS)
                label = (
                    SCENE_DESCRIPTION_LABELS.get(scene_class) if scene_class is not None else None
                )
                if label is not None:
                    self._last_file_state["clip_description"] = (
                        label,
                        score.evidence.get(EVIDENCE_SCENE_PROB, score.confidence),
                    )
                break
        # Event name for Events/{EventName}/ routing: only meaningful when
        # the events category actually won (get_destination_path reads it).
        if decision.category == EVENTS_CATEGORY and EVENT_SIGNAL_NAME in decision.winning_signals:
            for score in decision.all_scores:
                if score.signal_name != EVENT_SIGNAL_NAME:
                    continue
                event_name = score.evidence.get(EVIDENCE_EVENT_NAME)
                if event_name:
                    self._last_file_state[EVIDENCE_EVENT_NAME] = event_name
                break
        for score in decision.all_scores:
            research = score.evidence.get("research")
            if research and "research" not in self._last_file_state:
                self._last_file_state["research"] = research
            clip_label = score.evidence.get("clip_label")
            if clip_label is not None and "clip_description" not in self._last_file_state:
                self._last_file_state["clip_description"] = (
                    clip_label,
                    score.evidence.get("clip_score", score.confidence),
                )
        self._last_file_state["scoring_decision"] = self._decision_snapshot(
            decision, scorer_label=scorer_label
        )

    @staticmethod
    def _decision_snapshot(
        decision: ClassificationDecision, *, scorer_label: str
    ) -> DecisionSnapshot:
        """JSON-safe snapshot of a ClassificationDecision (§7.1 record core)."""
        snapshot = {
            "scorer": scorer_label,
            "decision": {
                "category": decision.category,
                "subcategory": decision.subcategory,
                "schema_type": decision.schema_type,
                "confidence": round(decision.confidence, 4),
                "margin": round(decision.margin, 4),
                "decision_state": decision.decision_state,
            },
            "winning_signals": list(decision.winning_signals),
            "all_scores": [
                {
                    "signal": score.signal_name,
                    "cat": score.category,
                    "sub": score.subcategory,
                    "conf": round(score.confidence, 4),
                    "evidence": score.evidence,
                }
                for score in decision.all_scores
            ],
        }
        # Round-trip through json to guarantee persistability (EXIF datetimes
        # and other rich objects inside evidence degrade to strings).
        return cast(DecisionSnapshot, json.loads(json.dumps(snapshot, default=str)))

    def _classify_screenshot_ocr(
        self,
        file_path: Path,
        schema_type: str,
        image_metadata: Dict[str, Any],
    ) -> Optional[Tuple[str, str, str, str, Optional[str], List[str], Dict[str, Any]]]:
        """PRIORITY 4.5: Screenshot sub-classification via OCR + CLIP.

        Raw screenshots (e.g. "Screenshot 2025-*") that bypassed Priority 4 because
        classify_media_file returned None.  Try OCR first (reliable for screenshots
        with text), then CLIP for non-text images.  Returns a classification tuple
        for any screenshot-named image, or None for non-screenshots.
        """
        _stem_lower = file_path.stem.lower()
        if not (schema_type == "ImageObject" and is_screenshot_named(_stem_lower)):
            return None

        screenshots_dict = self.category_paths["media"]["photos"]["screenshots"]

        # Step 1: OCR-based sub-classification (dashboard, terminal, etc.).
        # Branch decisions are shared with ScreenshotOcrSignal via
        # route_screenshot_ocr; the prints and step-2/fallback flow stay here.
        ocr_result = None
        if _shared_classify_by_ocr is not None:
            ocr_result = _shared_classify_by_ocr(
                file_path,
                content_classifier=self.screenshot_content_classifier,
            )
        if ocr_result:
            ocr_category, ocr_confidence, _ocr_scores, ocr_text = ocr_result
            if ocr_text:
                self._last_file_ocr_text = ocr_text
            routed = route_screenshot_ocr(ocr_category, ocr_confidence, screenshots_dict)
            if ocr_confidence < _SCREENSHOT_OCR_KEYWORD_THRESHOLD:
                print(
                    f"  ↪ Screenshot OCR low confidence ({ocr_confidence:.0%} < "
                    f"{_SCREENSHOT_OCR_KEYWORD_THRESHOLD:.0%}) — falling back to CLIP"
                )
            elif routed is not None:
                routed_category, routed_subcategory = routed
                if ocr_category in screenshots_dict:
                    print(f"  ✓ Screenshot OCR sub-class: {ocr_category} ({ocr_confidence:.0%})")
                else:
                    # OCR matched a non-screenshot Schema.org category — use it
                    print(f"  ✓ Screenshot OCR reclassified: {ocr_category} ({ocr_confidence:.0%})")
                return (
                    routed_category,
                    routed_subcategory,
                    schema_type,
                    "",
                    None,
                    [],
                    image_metadata,
                )

        # Step 2: CLIP enhancement for images OCR couldn't classify
        enhanced = self.enhance_weak_image_classification(file_path, image_metadata)
        if enhanced:
            ecat, esubcat = enhanced
            # CLIP identified non-media content (e.g. game_assets) — use that
            if ecat not in ("media",):
                print(f"  ✓ Screenshot reclassified: {ecat}/{esubcat}")
                return (ecat, esubcat, schema_type, "", None, [], image_metadata)
            # CLIP identified a specific screenshot subcategory
            if "screenshots" in esubcat and esubcat != "photos_screenshots_other":
                print(f"  ✓ Screenshot CLIP sub-class: {esubcat}")
                return ("media", esubcat, schema_type, "", None, [], image_metadata)

        # Fallback: generic screenshot folder
        print("  ✓ Screenshot (unclassified)")
        return ("media", "photos_screenshots_other", schema_type, "", None, [], image_metadata)

    def _classify_photo_composition(
        self,
        file_path: Path,
        schema_type: str,
        image_metadata: Dict[str, Any],
    ) -> Optional[Tuple[str, str, str, str, Optional[str], List[str], Dict[str, Any]]]:
        """PRIORITY 5: Photo composition analysis (people / home interior).

        Returns a media/property_management tuple on a vision match, or None when
        vision is unavailable or no composition matched.
        """
        if not (
            schema_type == "ImageObject"
            and self.image_analyzer is not None
            and self.image_analyzer.vision_available
        ):
            return None
        print("  Analyzing image content...")

        # Single CLIP pass yields both composition flags (people / home interior).
        has_people, is_property_mgmt, scores = self.image_analyzer.analyze_for_organization(
            file_path
        )

        if has_people:
            print("  ✓ Detected: Photo with people")
            if scores:
                top_categories = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
                print(
                    f"  Top matches: {', '.join([f'{cat}: {score:.2%}' for cat, score in top_categories])}"  # noqa: E501
                )
            return ("media", "photos_social", schema_type, "", None, [], image_metadata)

        if is_property_mgmt:
            print("  ✓ Detected: Home interior without people")
            if scores:
                top_categories = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
                print(
                    f"  Top matches: {', '.join([f'{cat}: {score:.2%}' for cat, score in top_categories])}"  # noqa: E501
                )
            return ("property_management", "other", schema_type, "", None, [], image_metadata)

        return None

    def _classify_by_content_and_kie(
        self,
        file_path: Path,
        schema_type: str,
        image_metadata: Dict[str, Any],
    ) -> Tuple[str, str, str, str, Optional[str], List[str], Dict[str, Any]]:
        """PRIORITY 6: Regular text extraction and content/KIE classification.

        Terminal tier — always returns a result tuple (the fall-through default for
        detect_file_category).
        """
        print("  Extracting content...")
        extracted_text = self.extract_text(file_path)

        if extracted_text:
            print(f"  Extracted {len(extracted_text)} characters")

            kie_result = self._last_file_state.get("kie_result")
            kie_classification = None
            if kie_result is not None:
                kie_classification = self.classifier.classify_with_kie(
                    kie_result,
                    extracted_text,
                    file_path.name,
                )
            if kie_classification is not None:
                category, subcategory, company_name, people_names = kie_classification
                print(f"  ✓ KIE classification: {category}/{subcategory}")
            else:
                category, subcategory, company_name, people_names = (
                    self.classifier.classify_content(extracted_text, file_path.name)
                )

            if company_name:
                print(f"  Detected company: {company_name}")
            if people_names:
                print(
                    f"  Detected people: {', '.join(people_names[:3])}{' ...' if len(people_names) > 3 else ''}"  # noqa: E501
                )
            print(f"  Classified as: {category}/{subcategory}")

            if schema_type == "ImageObject" and category != "uncategorized":
                category, subcategory = self._cross_check_with_clip(
                    file_path,
                    image_metadata,
                    category,
                    subcategory,
                    len(extracted_text),
                )
        else:
            print("  No text extracted, using filename")
            category, subcategory, company_name, people_names = self.classifier.classify_content(
                "", file_path.name
            )

        # Point C: last-resort enhancement for uncategorized images
        if category == "uncategorized" and schema_type == "ImageObject":
            enhanced = self.enhance_weak_image_classification(file_path, image_metadata)
            if enhanced:
                print(f"  ✓ Enhanced uncategorized: {enhanced[0]}/{enhanced[1]}")
                return (
                    enhanced[0],
                    enhanced[1],
                    schema_type,
                    extracted_text,
                    None,
                    [],
                    image_metadata,
                )

        # Final fallback: route by MIME/extension when no content signal produced
        # a category. Rescues binary media (gif/webp/video/audio/fonts) that carry
        # no extractable text and would otherwise land in Uncategorized.
        if category == "uncategorized":
            mime_category, mime_subcategory, _ = classify_by_mime(file_path, None)
            fallback = _mime_result_to_content_category(mime_category, mime_subcategory)
            if fallback is not None:
                category, subcategory = fallback
                print(f"  ✓ MIME fallback: {category}/{subcategory}")

        return (
            category,
            subcategory,
            schema_type,
            extracted_text,
            company_name,
            people_names,
            image_metadata,
        )

    def get_destination_path(
        self,
        file_path: Path,
        category: str,
        subcategory: str,
        company_name: Optional[str] = None,
        image_metadata: Optional[Dict[str, Any]] = None,
        people_names: Optional[List[str]] = None,
    ) -> Path:
        """
        Get the destination path for a file based on content category.

        Args:
            file_path: Path to the file
            category: Main category
            subcategory: Subcategory
            company_name: Optional company name for business/organization files
            image_metadata: Optional metadata for images (datetime, location)
            people_names: Optional list of people names for person-classified files

        Returns:
            Destination path for the file
        """
        # Special handling for filepath-based classification
        # Values come from the untyped category_paths taxonomy; a missed
        # lookup can yield None (the terminal str() guards the path join).
        relative_path: Optional[str]
        if category == "filepath":
            # subcategory contains the full path (e.g., "Technical/Python/MyProject")
            relative_path = subcategory
        # Special handling for media files with nested structure
        elif category == "media" and "_" in subcategory:
            # subcategory format: "photos_screenshots" or "photos_screenshots_browser"
            parts = subcategory.split("_", 1)  # Split into at most 2 parts
            if len(parts) == 2:
                media_type, media_subcat = parts
                if media_type in self.category_paths["media"]:
                    media_dict = self.category_paths["media"][media_type]
                    if isinstance(media_dict, dict):
                        # Check for 3-level nesting (e.g., screenshots_browser)
                        if "_" in media_subcat:
                            parent_key, child_key = media_subcat.split("_", 1)
                            parent_val = media_dict.get(parent_key)
                            if isinstance(parent_val, dict):
                                relative_path = parent_val.get(
                                    child_key,
                                    parent_val.get(
                                        "other",
                                        f"Media/{media_type.capitalize()}/"
                                        f"{parent_key.capitalize()}",
                                    ),
                                )
                            else:
                                relative_path = media_dict.get(
                                    media_subcat,
                                    media_dict.get(
                                        "other", f"Media/{media_type.capitalize()}/Other"
                                    ),
                                )
                        else:
                            val = media_dict.get(media_subcat)
                            if isinstance(val, dict):
                                relative_path = val.get(
                                    "other",
                                    f"Media/{media_type.capitalize()}/{media_subcat.capitalize()}",
                                )
                            elif val:
                                relative_path = val
                            else:
                                relative_path = media_dict.get(
                                    "other", f"Media/{media_type.capitalize()}/Other"
                                )
                    else:
                        relative_path = media_dict
                else:
                    relative_path = "Media/Other"
            else:
                relative_path = "Media/Other"
        elif category in self.category_paths:
            if isinstance(self.category_paths[category], dict):
                if subcategory in self.category_paths[category]:
                    relative_path = self.category_paths[category][subcategory]
                else:
                    relative_path = self.category_paths[category].get(
                        "other", f"{category.capitalize()}/Other"
                    )
            else:
                relative_path = self.category_paths[category]
        else:
            relative_path = "Uncategorized"

        # Organization: Create entity-named subfolders under Organization/
        # Structure: Organization/{OrgName}/ for most types
        # Exception: Organization/Clients/{OrgName}/ for clients (nested subfolders)
        if category == "organization" and company_name:
            sanitized_company = self.classifier.sanitize_company_name(company_name)
            # Only create company subfolder if name is valid (not a sentence fragment)
            if sanitized_company:
                if subcategory == "clients":
                    # Clients get nested: Organization/Clients/{OrgName}/
                    relative_path = f"{relative_path}/{sanitized_company}"
                elif subcategory == "meeting_notes":
                    # Meeting notes get nested: Organization/{OrgName}/Meeting Notes/
                    relative_path = f"{relative_path}/{sanitized_company}/Meeting Notes"
                else:
                    # All other org types: Organization/{OrgName}/
                    relative_path = f"{relative_path}/{sanitized_company}"

        # Events: entity-named subfolders under Events/, mirroring the
        # Organization/{OrgName}/ structure. The event name arrives via the
        # unified decision's evidence stash (_last_file_state); the title was
        # already shape-validated by EventContentSignal, so only folder-unsafe
        # characters are stripped here. Without a name, files stay in Events/.
        if category == EVENTS_CATEGORY:
            event_name = self._last_file_state.get(EVIDENCE_EVENT_NAME)
            if event_name:
                safe_event = re.sub(r'[<>:"/\\|?*]', "", event_name).strip()
                if safe_event:
                    relative_path = f"{relative_path}/{safe_event}"

        # Legacy: client files from business category with company name
        if category == "business" and subcategory == "clients" and company_name:
            sanitized_company = self.classifier.sanitize_company_name(company_name)
            # Only create company subfolder if name is valid
            if sanitized_company:
                relative_path = f"{relative_path}/{sanitized_company}"

        # Date-based organization for images (if enabled and metadata available)
        if self.organize_by_date and image_metadata and image_metadata.get("year"):
            year = image_metadata["year"]
            month = image_metadata["month"]
            relative_path = f"Photos/{year}/{month:02d}"

        # Location-based organization for images (if enabled and location available)
        elif self.organize_by_location and image_metadata and image_metadata.get("location_name"):
            # Clean location name for folder
            location = image_metadata["location_name"]
            # Take first part (usually city)
            city = location.split(",")[0].strip()
            # Sanitize for folder name
            safe_city = re.sub(r'[<>:"/\\|?*]', "", city)
            relative_path = f"Photos/Locations/{safe_city}"

        dest_dir = self.base_path / str(relative_path)
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Handle duplicate filenames — delegate to the shared incrementing counter
        dest_path = dest_dir / file_path.name
        if dest_path.exists() and dest_path != file_path:
            dest_path = resolve_collision(dest_path)

        return dest_path

    def should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped (delegates to shared.file_ops.should_skip_file)."""
        return bool(_shared_should_skip_file(file_path))
