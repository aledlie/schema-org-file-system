"""Golden-snapshot regression tests for FileOrganizer.generate_schema().

Captures generate_schema() output for one file per schema-type branch so the
Group A migration (replacing the deprecated generator builder methods such as
set_basic_info/set_file_info/set_name/set_address with direct set_property
calls) can be proven output-preserving.

Workflow:
    # 1. Record goldens BEFORE the migration (current builder-based output):
    UPDATE_GOLDEN=1 pytest tests/unit/test_generate_schema_golden.py
    # 2. Perform the migration, then assert output is unchanged:
    pytest tests/unit/test_generate_schema_golden.py

The Person and Organization cases use .vcf fixtures because those exercise the
highest-risk nested builders (set_name multi-field, set_contact_info,
set_job_info -> worksFor, set_address -> PostalAddress).
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from file_organizer import FileOrganizer  # noqa: E402

GOLDEN_DIR = Path(__file__).parent / "golden" / "generate_schema"

# Output fields that are time-, path-, or environment-dependent and therefore
# not meaningful for regression comparison. They are normalized to a constant
# before diffing. None of these are produced by the deprecated builder methods
# under migration (@id comes from the constructor entity_id; the dates/uploadDate
# come from file stat()), so scrubbing them hides no migration regression.
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
        f"Missing golden {path}. Record it (pre-migration) with:\n"
        f"  UPDATE_GOLDEN=1 pytest {Path(__file__).name}"
    )
    assert payload == path.read_text(), (
        f"generate_schema() output for '{name}' diverged from its golden "
        f"snapshot. If the change is intentional, re-record with UPDATE_GOLDEN=1."
    )


@pytest.fixture
def organizer(temp_dir):
    """FileOrganizer rooted at the per-test temp directory (from conftest)."""
    return FileOrganizer(base_path=str(temp_dir))


def _write(temp_dir: Path, name: str, content: str) -> Path:
    path = temp_dir / name
    path.write_text(content)
    return path


_PERSON_VCARD = """BEGIN:VCARD
VERSION:3.0
FN:John Doe
N:Doe;John;Michael;Dr.;PhD
EMAIL:john.doe@example.com
TEL:+1-555-123-4567
ORG:Acme Corp
TITLE:Software Engineer
URL:https://johndoe.com
BDAY:1990-01-15
ADR:;;123 Main St;San Francisco;CA;94102;USA
END:VCARD"""

_ORG_VCARD = """BEGIN:VCARD
VERSION:3.0
FN:Acme Corp
ORG:Acme Corporation
TEL:+1-555-999-0000
EMAIL:info@acme.com
URL:https://acme.com
ADR:;;456 Business Ave;New York;NY;10001;USA
END:VCARD"""


def test_golden_image_object(organizer, temp_dir):
    """ImageObject -> ImageGenerator.set_basic_info + set_dimensions."""
    image = pytest.importorskip("PIL.Image", reason="PIL needed for dimensions")
    path = temp_dir / "sample_photo.png"
    image.new("RGB", (4, 2), "white").save(path)
    _assert_golden("image_object", organizer.generate_schema(path, "ImageObject"))


def test_golden_video_object(organizer, temp_dir):
    """VideoObject -> VideoGenerator.set_basic_info (uploadDate scrubbed)."""
    path = _write(temp_dir, "sample_clip.mp4", "fake-video-bytes")
    _assert_golden("video_object", organizer.generate_schema(path, "VideoObject"))


def test_golden_audio_object(organizer, temp_dir):
    """AudioObject -> AudioGenerator.set_basic_info."""
    path = _write(temp_dir, "sample_track.mp3", "fake-audio-bytes")
    _assert_golden("audio_object", organizer.generate_schema(path, "AudioObject"))


def test_golden_software_source_code(organizer, temp_dir):
    """SoftwareSourceCode -> CodeGenerator.set_basic_info + set_property(url)."""
    path = _write(temp_dir, "sample_module.py", "print('hello')\n")
    _assert_golden("software_source_code",
                   organizer.generate_schema(path, "SoftwareSourceCode"))


def test_golden_dataset(organizer, temp_dir):
    """Dataset -> DatasetGenerator.set_basic_info."""
    path = _write(temp_dir, "sample_data.csv", "a,b\n1,2\n")
    _assert_golden("dataset", organizer.generate_schema(path, "Dataset"))


def test_golden_digital_document(organizer, temp_dir):
    """DigitalDocument -> DocumentGenerator.set_basic_info + set_file_info."""
    path = _write(temp_dir, "sample_doc.txt", "document body\n")
    _assert_golden("digital_document",
                   organizer.generate_schema(path, "DigitalDocument"))


def test_golden_organization(organizer, temp_dir):
    """Organization -> set_basic_info + vCard set_contact_info/set_address."""
    path = _write(temp_dir, "acme_corp.vcf", _ORG_VCARD)
    _assert_golden("organization", organizer.generate_schema(path, "Organization"))


def test_golden_person(organizer, temp_dir):
    """Person -> set_name (multi) + set_contact_info + set_job_info + set_address."""
    path = _write(temp_dir, "john_doe.vcf", _PERSON_VCARD)
    _assert_golden("person", organizer.generate_schema(path, "Person"))


def test_golden_fallback_document(organizer, temp_dir):
    """Unknown schema_type -> else branch (Document set_basic_info + set_file_info)."""
    path = _write(temp_dir, "sample_other.bin", "opaque-bytes")
    _assert_golden("fallback_document",
                   organizer.generate_schema(path, "CreativeWork"))
