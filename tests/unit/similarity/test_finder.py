"""File collection and report serialisation for the near-duplicate scan."""

import json
from pathlib import Path

import pytest

from src.similarity.finder import (
    DuplicateReport,
    collect_files,
    supported_extensions,
    write_report,
)
from src.similarity.types import DuplicateGroup, SimilarPair


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """A small tree mixing describable and non-describable files."""
    (tmp_path / "nested").mkdir()
    for relative in (
        "photo.jpg",
        "scan.PNG",
        "map.pdf",
        "notes.txt",
        "archive.zip",
        "nested/deep.jpeg",
    ):
        (tmp_path / relative).write_bytes(b"x")
    return tmp_path


class TestCollectFiles:
    def test_finds_images_recursively(self, corpus: Path):
        found = collect_files([corpus])

        assert corpus / "photo.jpg" in found
        assert corpus / "nested" / "deep.jpeg" in found

    def test_extension_match_is_case_insensitive(self, corpus: Path):
        assert corpus / "scan.PNG" in collect_files([corpus])

    def test_undescribable_files_excluded(self, corpus: Path):
        found = collect_files([corpus])

        assert corpus / "notes.txt" not in found
        assert corpus / "archive.zip" not in found

    def test_pdfs_included_by_default(self, corpus: Path):
        assert corpus / "map.pdf" in collect_files([corpus])

    def test_pdfs_excluded_when_disabled(self, corpus: Path):
        assert corpus / "map.pdf" not in collect_files([corpus], include_pdfs=False)

    def test_accepts_a_file_path_directly(self, corpus: Path):
        assert collect_files([corpus / "photo.jpg"]) == [corpus / "photo.jpg"]

    def test_missing_source_is_skipped_not_raised(self, corpus: Path):
        found = collect_files([corpus / "does-not-exist", corpus])

        assert corpus / "photo.jpg" in found

    def test_limit_selects_the_same_subset_across_runs(self, corpus: Path):
        assert collect_files([corpus], limit=2) == collect_files([corpus], limit=2)
        assert len(collect_files([corpus], limit=2)) == 2

    def test_no_sources_yields_nothing(self):
        assert collect_files([]) == []


class TestSupportedExtensions:
    def test_pdf_toggles_with_the_flag(self):
        assert ".pdf" in supported_extensions(include_pdfs=True)
        assert ".pdf" not in supported_extensions(include_pdfs=False)

    def test_common_raster_formats_supported(self):
        extensions = supported_extensions()

        assert {".jpg", ".png", ".heic", ".webp"} <= extensions


def _report() -> DuplicateReport:
    left, right = Path("/corpus/map.pdf"), Path("/corpus/map_300dpi.png")
    group = DuplicateGroup(
        paths=(left, right),
        pairs=(SimilarPair(left, right, 0.94123),),
    )
    return DuplicateReport(groups=[group], scanned=10, described=9, threshold=0.85)


class TestReportSerialisation:
    def test_counts_files_across_groups(self):
        assert _report().duplicate_file_count == 2

    def test_dict_carries_scan_provenance(self):
        payload = _report().to_dict()

        assert payload["files_scanned"] == 10
        assert payload["files_described"] == 9
        assert payload["threshold"] == 0.85
        assert payload["group_count"] == 1

    def test_dict_paths_are_strings(self):
        payload = _report().to_dict()

        assert payload["groups"][0]["paths"] == ["/corpus/map.pdf", "/corpus/map_300dpi.png"]

    def test_similarity_rounded_for_readability(self):
        assert _report().to_dict()["groups"][0]["pairs"][0]["similarity"] == 0.9412

    def test_empty_report_serialises(self):
        payload = DuplicateReport(groups=[], scanned=3, described=3, threshold=0.85).to_dict()

        assert payload["groups"] == []
        assert payload["duplicate_file_count"] == 0

    def test_write_report_creates_parent_directories(self, tmp_path: Path):
        output = tmp_path / "nested" / "dupes.json"

        write_report(_report(), output)

        assert json.loads(output.read_text())["group_count"] == 1
