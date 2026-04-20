"""OCR-based image classification with screenshot and schema.org fallbacks."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from shared.ocr_utils import extract_ocr_text, is_ocr_available

# Minimum keyword hits for screenshot-specific matching
SCREENSHOT_MIN_HITS = 2

SCREENSHOT_KEYWORDS: dict[str, list[str]] = {
    'dashboard': [
        'daily requests', 'monthly cost', 'active alerts', 'latency',
        'trace pipeline', 'provider costs', 'dashboard', 'metrics',
        'monitoring', 'uptime', 'throughput',
    ],
    'terminal_session': [
        'completed:', 'next steps:', 'blocked by', 'npm run', 'git ',
        'curl ', 'http 2', 'signup successful', 'deploy', '$ ',
        'insert --', 'bash(', 'command:', 'exit code',
    ],
    'error_log': [
        'error:', 'traceback', 'exception', 'stack trace', 'fatal',
        'panic:', 'segfault', 'core dumped',
    ],
    'api_response': [
        '"jwt":', '"token":', '"userid":', 'http 200', 'http 201',
        'http 400', 'http 500', 'response:', 'status:',
        'content-type:', 'application/json',
    ],
}


def classify_by_ocr(
    image_path: Path,
    content_classifier=None,
    max_chars: int = 1000,
) -> tuple[str, float, dict[str, float], str] | None:
  """Classify image by OCR text extraction with fallback hierarchy.

  Tries screenshot-specific keywords first, then falls back to Schema.org
  taxonomy if available.

  Args:
    image_path: Path to the image file
    content_classifier: Optional ContentClassifier for schema.org taxonomy
    max_chars: Max characters to extract via OCR

  Returns:
    Tuple of (category, confidence, all_scores, extracted_text) or None
    if OCR unavailable or no matches found.
    all_scores maps every matched category to its confidence.
  """
  if not is_ocr_available():
    return None

  text = extract_ocr_text(image_path, max_chars=max_chars)
  if not text:
    return None

  text_lower = text.lower()

  # Screenshot-specific scores
  screenshot_scores: dict[str, float] = {}
  screenshot_hits: dict[str, int] = {}
  for category, keywords in SCREENSHOT_KEYWORDS.items():
    hits = sum(1 for kw in keywords if kw in text_lower)
    if hits:
      screenshot_hits[category] = hits
      screenshot_scores[category] = hits / len(keywords)

  # Schema.org taxonomy scores (if classifier provided)
  schema_scores: dict[str, float] = {}
  if content_classifier:
    schema_scores = content_classifier.score_all_categories(
        text, image_path.name
    )

  # Merge: screenshot-specific keys take precedence
  all_scores = {**schema_scores, **screenshot_scores}

  if not all_scores:
    return None

  # Pass 1: screenshot-specific winner
  if screenshot_scores:
    best_ss = max(screenshot_scores, key=screenshot_scores.get)
    if screenshot_hits[best_ss] >= SCREENSHOT_MIN_HITS:
      return (best_ss, screenshot_scores[best_ss], all_scores, text)

  # Pass 2: Schema.org taxonomy winner
  if schema_scores and content_classifier:
    best_cat = max(schema_scores, key=schema_scores.get)
    category, subcategory, _company, _people = (
        content_classifier.classify_content(text, image_path.name)
    )
    if category != 'uncategorized':
      label = f"{category}_{subcategory}" if subcategory != 'other' else category
      return (label, schema_scores.get(category, 0.0), all_scores, text)

  return None
