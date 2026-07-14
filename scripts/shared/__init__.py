"""Shared utilities for scripts.

Only lightweight, non-ML imports are re-exported here.  Heavy dependencies
(CLIP, OCR, KIE) are intentionally *not* eagerly imported so that scripts
which only need constants or file-ops do not pay the torch/open_clip load
cost (~1.8 s, several hundred MB RSS).  Import those directly from their
submodules when needed:

    from shared.clip_utils import CLIPClassifier, CLIP_AVAILABLE
    from shared.ocr_classifier import extract_ocr_text, is_ocr_available
    from shared.kie_utils import extract_kie_fields, KIE_AVAILABLE
    from shared.clip_cache import get_cached_embedding, CLIP_CACHE_AVAILABLE
"""

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

__all__ = [
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
]
