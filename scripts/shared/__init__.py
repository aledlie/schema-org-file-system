"""Shared utilities for scripts."""

from shared.clip_utils import CLIPClassifier, CLIP_AVAILABLE
from shared.constants import (
  IMAGE_EXTENSIONS,
  IMAGE_EXTENSIONS_WIDE,
  CLIP_CONTENT_LABELS,
  CLIP_CATEGORY_PROMPTS,
  CONTENT_TO_SCHEMA,
  CONTENT_TO_EXISTING_FOLDER,
  CONTENT_ABBREVIATIONS,
  GAME_SPRITE_KEYWORDS,
  GAME_AUDIO_KEYWORDS,
  GAME_MUSIC_KEYWORDS,
  GAME_FONT_KEYWORDS,
  SCREENSHOT_PATTERNS,
  DOCUMENT_PATTERNS,
)
from shared.db_utils import get_db_connection, db_connection, DEFAULT_DB_PATH
from shared.file_ops import resolve_collision
from shared.ocr_utils import (
    extract_ocr_text,
    extract_ocr_text_pdf,
    extract_ocr_with_confidence,
    extract_ocr_pdf_with_confidence,
    is_ocr_available,
    OCRResult,
)
from shared.kie_utils import (
    extract_kie_fields,
    extract_kie_fields_pdf,
    is_kie_available,
    KIE_AVAILABLE,
    KIEResult,
    KIEField,
)
from shared.clip_cache import get_cached_embedding, get_cached_embeddings_batch, CLIP_CACHE_AVAILABLE
