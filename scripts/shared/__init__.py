"""Shared utilities for scripts."""

from shared.clip_cache import (
    CLIP_CACHE_AVAILABLE,
    get_cached_embedding,
    get_cached_embeddings_batch,
)
from shared.clip_utils import CLIP_AVAILABLE, CLIPClassifier
from shared.constants import (
    CLIP_CATEGORY_PROMPTS,
    CLIP_CONTENT_LABELS,
    CONTENT_ABBREVIATIONS,
    CONTENT_TO_EXISTING_FOLDER,
    CONTENT_TO_SCHEMA,
    DOCUMENT_PATTERNS,
    GAME_AUDIO_KEYWORDS,
    GAME_FONT_KEYWORDS,
    GAME_MUSIC_KEYWORDS,
    GAME_SPRITE_KEYWORDS,
    IMAGE_EXTENSIONS,
    IMAGE_EXTENSIONS_WIDE,
    SCREENSHOT_PATTERNS,
)
from shared.db_utils import DEFAULT_DB_PATH, db_connection, get_db_connection
from shared.file_ops import resolve_collision
from shared.kie_utils import (
    KIE_AVAILABLE,
    KIEField,
    KIEResult,
    extract_kie_fields,
    extract_kie_fields_pdf,
    is_kie_available,
)
from shared.ocr_classifier import (
    OCRResult,
    extract_ocr_pdf_with_confidence,
    extract_ocr_text,
    extract_ocr_text_pdf,
    extract_ocr_with_confidence,
    is_ocr_available,
)

__all__ = [
    "CLIP_CACHE_AVAILABLE",
    "get_cached_embedding",
    "get_cached_embeddings_batch",
    "CLIP_AVAILABLE",
    "CLIPClassifier",
    "CLIP_CATEGORY_PROMPTS",
    "CLIP_CONTENT_LABELS",
    "CONTENT_ABBREVIATIONS",
    "CONTENT_TO_EXISTING_FOLDER",
    "CONTENT_TO_SCHEMA",
    "DOCUMENT_PATTERNS",
    "GAME_AUDIO_KEYWORDS",
    "GAME_FONT_KEYWORDS",
    "GAME_MUSIC_KEYWORDS",
    "GAME_SPRITE_KEYWORDS",
    "IMAGE_EXTENSIONS",
    "IMAGE_EXTENSIONS_WIDE",
    "SCREENSHOT_PATTERNS",
    "DEFAULT_DB_PATH",
    "db_connection",
    "get_db_connection",
    "resolve_collision",
    "KIE_AVAILABLE",
    "KIEField",
    "KIEResult",
    "extract_kie_fields",
    "extract_kie_fields_pdf",
    "is_kie_available",
    "OCRResult",
    "extract_ocr_pdf_with_confidence",
    "extract_ocr_text",
    "extract_ocr_text_pdf",
    "extract_ocr_with_confidence",
    "is_ocr_available",
]
