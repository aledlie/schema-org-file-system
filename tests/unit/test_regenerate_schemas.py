"""Tests for scripts/regenerate_schemas.py::regenerate_schema().

Covers the schema-type dispatch after the Group A migration that replaced the
deprecated generator builder methods (set_basic_info/set_file_info) with direct
set_property() calls.

Regression guard for the fixed latent bug: the previous code called
set_basic_info(name=, description=) generically in the else branch, which
raised TypeError for generators whose set_basic_info requires other positional
arguments (Video/Audio/Code/Archive, and Photograph via ImageGenerator). That
TypeError was swallowed, so those types produced no regenerated fields. They
must now serialize name + description.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from regenerate_schemas import regenerate_schema  # noqa: E402
from enrichment import MetadataEnricher  # noqa: E402

_CANONICAL_ID = "urn:sha256:deadbeef"


@pytest.fixture
def enricher():
    return MetadataEnricher()


def _regen(path: Path, schema_type: str, enricher, existing=None):
    return regenerate_schema(
        file_id="abc123",
        canonical_id=_CANONICAL_ID,
        current_path=str(path),
        schema_type=schema_type,
        existing_schema=existing or {},
        enricher=enricher,
    )


def test_carries_canonical_id_as_at_id(temp_dir, enricher):
    path = temp_dir / "doc.txt"
    path.write_text("body")
    schema = _regen(path, "DigitalDocument", enricher)
    assert schema["@id"] == _CANONICAL_ID


def test_document_gets_basic_and_file_info(temp_dir, enricher):
    path = temp_dir / "report.txt"
    path.write_text("hello world")
    schema = _regen(path, "DigitalDocument", enricher)
    assert schema["name"] == "report.txt"
    assert schema["description"] == "report.txt"
    assert "encodingFormat" in schema
    assert schema["url"] == "https://localhost/files/report.txt"
    assert schema["contentSize"] == f"{path.stat().st_size}B"


def test_image_gets_content_url_not_file_info(temp_dir, enricher):
    path = temp_dir / "pic.png"
    path.write_text("not-a-real-png")
    schema = _regen(path, "ImageObject", enricher)
    assert schema["name"] == "pic.png"
    assert schema["contentUrl"] == "https://localhost/files/pic.png"
    assert "encodingFormat" in schema
    # Images use contentUrl, not the document file-info url/contentSize.
    assert "contentSize" not in schema


def test_existing_description_preserved_over_filename(temp_dir, enricher):
    path = temp_dir / "doc.txt"
    path.write_text("body")
    schema = _regen(path, "Article", enricher, existing={"description": "Custom desc"})
    assert schema["description"] == "Custom desc"


@pytest.mark.parametrize(
    "schema_type",
    ["VideoObject", "AudioObject", "SoftwareSourceCode", "Archive", "Photograph"],
)
def test_previously_crashing_types_now_emit_basic_info(temp_dir, enricher, schema_type):
    """Regression: these all raised a swallowed TypeError before the migration."""
    path = temp_dir / "asset.bin"
    path.write_text("data")
    schema = _regen(path, schema_type, enricher)
    assert schema["name"] == "asset.bin"
    assert schema["description"] == "asset.bin"
    # Non-document types do not receive document file-info fields.
    assert "contentSize" not in schema


def test_dataset_gets_basic_info_without_file_info(temp_dir, enricher):
    path = temp_dir / "data.csv"
    path.write_text("a,b\n1,2\n")
    schema = _regen(path, "Dataset", enricher)
    assert schema["name"] == "data.csv"
    assert schema["description"] == "data.csv"
    assert "contentSize" not in schema
    assert "url" not in schema
