"""Golden-snapshot regression tests for FileProcessor.generate_schema().

Captures generate_schema() output for one file per schema-type branch so any
refactor of the live pipeline's schema generation can be proven
output-preserving. Originally these goldens pinned the legacy
``scripts/file_organizer.py`` implementation; they were re-pointed at
``src/pipeline/file_processor.py`` (the implementation the ``organize-files
content`` pipeline actually runs) when the legacy script was retired.

Workflow:
    # Re-record after an intentional output change:
    UPDATE_GOLDEN=1 pytest tests/unit/test_generate_schema_golden.py
    # Assert output is unchanged:
    pytest tests/unit/test_generate_schema_golden.py

Branch map of FileProcessor.generate_schema:
  1. ImageObject                      -> ImageGenerator
  2. DigitalDocument/Article/Report   -> DocumentGenerator (+contentSize, url)
     ScholarlyArticle                 -> same, + identifier/sameAs/publisher
                                         from organizer._last_file_state
  3. anything else                    -> generic DocumentGenerator fallback
     (media/code/dataset/person/org types intentionally collapsed here when
     the pipeline layer moved into src/ — the graph store re-derives display
     types from MIME)
Plus cross-cutting: set_dates, extracted_text -> abstract/text, filePath.
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.pipeline.file_processor import FileProcessor

GOLDEN_DIR = Path(__file__).parent / "golden" / "generate_schema"

# Output fields that are time-, path-, or environment-dependent and therefore
# not meaningful for regression comparison. They are normalized to a constant
# before diffing.
_VOLATILE_KEYS = ("@id", "filePath", "dateCreated", "dateModified", "uploadDate")
_PLACEHOLDER = "<normalized>"


def _normalize(value):
    """Recursively replace volatile field values with a stable placeholder."""
    if isinstance(value, dict):
        return {
            key: (_PLACEHOLDER if key in _VOLATILE_KEYS else _normalize(val))
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _assert_golden(name: str, actual: dict) -> None:
    """Compare normalized output against the recorded golden, or record it."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    path = GOLDEN_DIR / f"{name}.json"
    payload = json.dumps(_normalize(actual), indent=2, sort_keys=True) + "\n"

    if os.environ.get("UPDATE_GOLDEN"):
        path.write_text(payload)
        pytest.skip(f"Recorded golden snapshot: {path.name}")

    assert path.exists(), (
        f"Missing golden {path}. Record it with:\n"
        f"  UPDATE_GOLDEN=1 pytest {Path(__file__).name}"
    )
    assert payload == path.read_text(), (
        f"generate_schema() output for '{name}' diverged from its golden "
        f"snapshot. If the change is intentional, re-record with UPDATE_GOLDEN=1."
    )


@pytest.fixture
def processor(temp_dir):
    """FileProcessor rooted at the per-test temp directory (from conftest)."""
    return FileProcessor(base_path=temp_dir)


def _write(temp_dir: Path, name: str, content: str) -> Path:
    path = temp_dir / name
    path.write_text(content)
    return path


def test_golden_image_object(processor, temp_dir):
    """ImageObject branch -> ImageGenerator (name/contentUrl/encodingFormat)."""
    image = pytest.importorskip("PIL.Image", reason="PIL needed for a real PNG")
    path = temp_dir / "sample_photo.png"
    image.new("RGB", (4, 2), "white").save(path)
    _assert_golden("image_object", processor.generate_schema(path, "ImageObject"))


def test_golden_digital_document(processor, temp_dir):
    """Document branch -> DocumentGenerator (+url, contentSize)."""
    path = _write(temp_dir, "sample_doc.txt", "document body\n")
    _assert_golden("digital_document",
                   processor.generate_schema(path, "DigitalDocument"))


def test_golden_scholarly_article(processor, temp_dir):
    """ScholarlyArticle branch -> document + identifier/sameAs/publisher from
    the organizer's per-file research state."""
    processor._organizer = SimpleNamespace(
        _last_file_state={
            "research": (
                "arxiv",
                "arXiv:2401.12345",
                "arXiv",
                "https://arxiv.org/abs/2401.12345",
            )
        }
    )
    path = _write(temp_dir, "2401.12345v1.pdf", "fake-paper-bytes")
    _assert_golden("scholarly_article",
                   processor.generate_schema(path, "ScholarlyArticle"))


def test_golden_fallback_video_object(processor, temp_dir):
    """Non-image, non-document types (VideoObject here) collapse to the
    generic DocumentGenerator fallback — pins that intentional divergence
    from the legacy per-type generators."""
    path = _write(temp_dir, "sample_clip.mp4", "fake-video-bytes")
    _assert_golden("fallback_video_object",
                   processor.generate_schema(path, "VideoObject"))


def test_golden_fallback_document(processor, temp_dir):
    """Unknown schema_type -> same generic fallback branch."""
    path = _write(temp_dir, "sample_other.bin", "opaque-bytes")
    _assert_golden("fallback_document",
                   processor.generate_schema(path, "CreativeWork"))


def test_golden_document_with_extracted_text(processor, temp_dir):
    """extracted_text -> abstract (1000-char preview) + text (5000-char cap)."""
    path = _write(temp_dir, "sample_scan.txt", "scanned body\n")
    long_text = "lorem ipsum " * 100  # 1200 chars: exercises the "..." preview
    _assert_golden(
        "document_with_extracted_text",
        processor.generate_schema(path, "DigitalDocument", extracted_text=long_text),
    )
