"""ArchiveManifestSignal tests — zip member-listing classification."""

import zipfile
from pathlib import Path

import pytest

from src.scoring.context import FileContext
from src.scoring.signals.archive_manifest import (
    ALL_MEDIA_CONFIDENCE,
    ARCHIVE_SIGNAL_NAME,
    EVIDENCE_MEDIA_MEMBERS,
    EVIDENCE_MEDICAL_TOKENS,
    EVIDENCE_MEMBER_COUNT,
    MEDICAL_MATCH_CONFIDENCE,
    MOSTLY_MEDIA_CONFIDENCE,
    ArchiveManifestSignal,
    list_zip_members,
)


def make_zip(tmp_path: Path, members: list[str], name: str = "archive.zip") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        for member in members:
            archive.writestr(member, b"x")
    return path


def make_ctx(path: Path) -> FileContext:
    return FileContext(path=path, schema_type="DigitalDocument")


class TestAppliesTo:
    def test_zip_only(self, tmp_path: Path) -> None:
        signal = ArchiveManifestSignal()
        assert signal.applies_to(make_ctx(tmp_path / "a.zip")) is True
        assert signal.applies_to(make_ctx(tmp_path / "a.tar")) is False
        assert signal.applies_to(make_ctx(tmp_path / "a.pdf")) is False


class TestListZipMembers:
    def test_filters_junk_and_directories(self, tmp_path: Path) -> None:
        path = make_zip(
            tmp_path,
            [
                "photos/",
                "photos/IMG_1.heic",
                "__MACOSX/photos/._IMG_1.heic",
                "photos/.DS_Store",
                ".hidden",
            ],
        )
        assert list_zip_members(path) == ["photos/IMG_1.heic"]

    def test_unreadable_zip_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "corrupt.zip"
        path.write_bytes(b"this is not a zip")
        assert list_zip_members(path) is None


class TestRun:
    def test_all_image_archive_routes_to_photos(self, tmp_path: Path) -> None:
        path = make_zip(tmp_path, ["IMG_1.heic", "IMG_2.jpg"])
        scores = ArchiveManifestSignal().run(make_ctx(path))
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("media", "photos_other")
        assert score.confidence == ALL_MEDIA_CONFIDENCE
        assert score.signal_name == ARCHIVE_SIGNAL_NAME
        assert score.evidence[EVIDENCE_MEMBER_COUNT] == 2
        assert score.evidence[EVIDENCE_MEDIA_MEMBERS] == 2

    def test_mixed_photo_video_archive_routes_to_media_other(self, tmp_path: Path) -> None:
        # The Photos.zip shape: one Live Photo = .heic + .mov pair.
        path = make_zip(tmp_path, ["IMG_4784.heic", "IMG_4784.mov"])
        scores = ArchiveManifestSignal().run(make_ctx(path))
        assert len(scores) == 1
        assert (scores[0].category, scores[0].subcategory) == ("media", "other")

    def test_mostly_media_archive_downgraded_confidence(self, tmp_path: Path) -> None:
        # 4 photos + 1 sidecar text file = 0.8 fraction.
        path = make_zip(tmp_path, ["a.jpg", "b.jpg", "c.jpg", "d.jpg", "checksums.txt"])
        scores = ArchiveManifestSignal().run(make_ctx(path))
        assert len(scores) == 1
        assert (scores[0].category, scores[0].subcategory) == ("media", "photos_other")
        assert scores[0].confidence == MOSTLY_MEDIA_CONFIDENCE

    def test_medical_report_tokens_route_to_medical_records(self, tmp_path: Path) -> None:
        # The promethease.zip shape.
        path = make_zip(tmp_path, ["promethease.html", "report_metadata.txt"])
        scores = ArchiveManifestSignal().run(make_ctx(path))
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("medical", "records")
        assert score.confidence == MEDICAL_MATCH_CONFIDENCE
        assert score.evidence[EVIDENCE_MEDICAL_TOKENS] == ["promethease"]

    def test_medical_takes_precedence_over_media(self, tmp_path: Path) -> None:
        path = make_zip(tmp_path, ["genome_scan.jpg", "genome_scan2.jpg"])
        scores = ArchiveManifestSignal().run(make_ctx(path))
        assert len(scores) == 1
        assert scores[0].category == "medical"

    def test_code_archive_emits_nothing(self, tmp_path: Path) -> None:
        path = make_zip(tmp_path, ["src/main.py", "README.md", "setup.cfg"])
        assert ArchiveManifestSignal().run(make_ctx(path)) == []

    def test_corrupt_zip_emits_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "corrupt.zip"
        path.write_bytes(b"not a zip at all")
        assert ArchiveManifestSignal().run(make_ctx(path)) == []

    def test_empty_zip_emits_nothing(self, tmp_path: Path) -> None:
        path = make_zip(tmp_path, [])
        assert ArchiveManifestSignal().run(make_ctx(path)) == []


class TestSignalMetadata:
    def test_signal_metadata(self) -> None:
        signal = ArchiveManifestSignal()
        assert signal.name == ARCHIVE_SIGNAL_NAME
        assert signal.cost_tier == "mid"
        assert signal.weight == pytest.approx(0.9)
