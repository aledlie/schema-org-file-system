"""Naming strategy for CLIP-classified images."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


def generate_filename(
    image_path: Path,
    content: str,
    metadata_parser=None,
) -> str:
  """Generate descriptive filename from content classification.

  Creates names like: YYYYMMDD_descriptive_content.ext or descriptive_content.ext

  Args:
    image_path: Path to image file
    content: CLIP classification result (category/description)
    metadata_parser: Optional ImageMetadataParser for datetime extraction

  Returns:
    New filename with extension
  """
  clean_content = re.sub(r'[^a-z0-9_]', '', content.lower().replace(" ", "_"))

  # Try to extract datetime from metadata or file mtime
  dt = None
  if metadata_parser:
    dt = metadata_parser.extract_datetime(image_path)

  if dt is None:
    try:
      dt = datetime.fromtimestamp(image_path.stat().st_mtime)
    except Exception:
      dt = None

  date_str = dt.strftime("%Y%m%d") if dt else None
  ext = image_path.suffix.lower()

  if date_str:
    return f"{date_str}_{clean_content}{ext}"
  return f"{clean_content}{ext}"
