"""Functional tests for src/organizers/name_organizer.py (FileNameOrganizer).

Covers the three categorization tiers (filename patterns, extension map,
filepath patterns) and their priority order, plus move/duplicate handling,
directory organization with stats, and report saving. save_report derives
its output directory from the module's __file__, so tests that trigger it
monkeypatch __file__ to keep writes inside tmp_path.
"""

import json
from pathlib import Path

import pytest

from src.organizers import name_organizer
from src.organizers.name_organizer import FileNameOrganizer


@pytest.fixture
def organizer(tmp_path: Path) -> FileNameOrganizer:
    return FileNameOrganizer(base_path=str(tmp_path / "organized"))


@pytest.fixture
def dry_organizer(tmp_path: Path) -> FileNameOrganizer:
    return FileNameOrganizer(base_path=str(tmp_path / "organized"), dry_run=True)


@pytest.fixture
def redirect_report_dir(tmp_path: Path, monkeypatch):
    """Point save_report's Path(__file__).parents[2]/'results' into tmp_path."""
    fake_module = tmp_path / "src" / "organizers" / "name_organizer.py"
    monkeypatch.setattr(name_organizer, "__file__", str(fake_module))
    return tmp_path / "results"


class TestCategorizeByExtension:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("bundle.js.map", ("Technical", "JavaScript")),
            ("styles.css.map", ("Technical", "JavaScript")),
            ("photo.jpg", ("Media/Photos", "Other")),
            ("photo.HEIC", ("Media/Photos", "Other")),  # case-insensitive suffix
            ("clip.mp4", ("Media/Videos", "Recordings")),
            ("song.flac", ("Media/Audio", "Other")),
            ("notes.pdf", ("Documents", "General")),
            ("budget.xlsx", ("Data", "Spreadsheets")),
            ("deck.pptx", ("Documents", "Presentations")),
            ("script.py", ("Technical", "Code")),
            ("config.yaml", ("Data", "Configs")),
            ("backup.tar", ("Data", "Archives")),
            ("server.pem", ("Technical", "Certificates")),
            ("slot1.sav", ("GameAssets", "SaveFiles")),
            ("mockup.psd", ("Creative", "Design")),
            ("model.blend", ("Creative", "3D")),
        ],
    )
    def test_known_extensions(self, organizer, filename, expected):
        assert organizer.categorize_by_extension(Path(filename)) == expected

    @pytest.mark.parametrize("filename", ["mystery.zzz", "no_extension"])
    def test_unknown_extension_returns_none(self, organizer, filename):
        assert organizer.categorize_by_extension(Path(filename)) is None


class TestCategorizeByFilename:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            # Build artifacts (trashed)
            ("module.pyc", (".Trash", "BuildArtifacts")),
            (".DS_Store", (".Trash", "BuildArtifacts")),
            ("bundle.min.js", (".Trash", "BuildArtifacts")),
            ("types.d.ts", (".Trash", "BuildArtifacts")),
            # Technical / docs
            ("makefile", ("Technical/Code", "Other")),
            (".eslintrc.json", ("Technical/Code", "Other")),
            ("LICENSE", ("Technical/Code", "Other")),
            ("README.md", ("Technical", "ReadMes")),
            ("CHANGELOG.md", ("Technical", "ReadMes")),
            ("server.log", ("Technical", "Logs")),
            ("settings.txt", ("Technical", "Other")),
            # Provenance-named images
            ("ChatGPT Image Jul 1.png", ("AI-Generated", "Images")),
            ("Screen Shot 2024-01-01.png", ("Media/Photos", "Screenshots")),
            ("screenshot_2024.png", ("Media/Photos", "Screenshots")),
            ("WhatsApp Image 2024-01-01.jpg", ("Media/Photos", "WhatsApp")),
            ("IMG_1234.jpg", ("Media/Photos", "Camera")),
            ("PXL_20240101_123456.jpg", ("Media/Photos", "Camera")),
            ("20240101_123456.jpg", ("Media/Photos", "Camera")),
            # Camera-vendor prefixes are single-homed in shared.constants and matched
            # with re.IGNORECASE, so both DSC_ (Sony/Nikon) and its no-underscore
            # variant, plus lowercase forms, route to Camera.
            ("DSC_5678.jpg", ("Media/Photos", "Camera")),
            ("DSC0001.JPG", ("Media/Photos", "Camera")),  # dsc_? — optional underscore
            ("img_9.jpg", ("Media/Photos", "Camera")),  # IGNORECASE — lowercase prefix
            ("123_456_789_012_345_n.jpg", ("Media/Photos", "Social_Media")),
            # Game assets: image extensions route to the photo view
            ("char_a_01.png", ("Media/Photos", "Games")),
            ("torso_2.xyz", ("GameAssets", "Sprites")),
            ("bg_forest.xyz", ("GameAssets", "Textures")),
            ("hp_mp_bar.xyz", ("GameAssets", "UI")),
            # Branding / icons / misc
            ("company-logo.png", ("Creative", "Branding")),
            ("icon_home.svg", ("Creative", "Icons")),
            ("calendar-2024.svg", ("Creative", "Icons")),
            ("medication-list.pdf", ("Medical", "General")),
            ("1f600.png", ("Creative", "Emoji")),
            ("Port_Moresby", ("Data", "LocationData")),
            ("12345.png", ("GameAssets", "Sprites")),
        ],
    )
    def test_pattern_matches(self, organizer, filename, expected):
        assert organizer.categorize_by_filename(Path(filename)) == expected

    def test_no_pattern_returns_none(self, organizer):
        assert organizer.categorize_by_filename(Path("quarterly_notes")) is None

    def test_artifact_patterns_beat_readme_patterns(self, organizer):
        # README* matches readme_files, but *.min.js is checked first.
        assert organizer.categorize_by_filename(Path("README.min.js")) == (
            ".Trash",
            "BuildArtifacts",
        )


class TestCategorizeByFilepath:
    def test_game_assets_path(self, organizer):
        result = organizer.categorize_by_filepath(Path("/x/GameAssets/foo.zzz"))
        assert result == ("GameAssets", "Other")

    def test_non_game_paths_fall_through_to_none(self, organizer):
        # Downloads/Documents/Pictures patterns match but assign nothing —
        # pinned as current behavior.
        assert organizer.categorize_by_filepath(Path("/u/Downloads/foo.zzz")) is None
        assert organizer.categorize_by_filepath(Path("/u/other/foo.zzz")) is None


class TestCategorizeFilePriority:
    def test_filename_pattern_beats_extension(self, organizer):
        # .png alone would give Media/Photos/Other; the screenshot name wins.
        assert organizer.categorize_file(Path("Screen Shot 1.png")) == (
            "Media/Photos",
            "Screenshots",
        )

    def test_extension_beats_filepath(self, organizer):
        assert organizer.categorize_file(Path("/x/GameAssets/notes.pdf")) == (
            "Documents",
            "General",
        )

    def test_filepath_when_name_and_extension_miss(self, organizer):
        assert organizer.categorize_file(Path("/x/GameAssets/foo.zzz")) == ("GameAssets", "Other")

    def test_uncategorized_fallback(self, organizer):
        assert organizer.categorize_file(Path("/tmp/blob.zzz")) == ("Uncategorized", "Other")


class TestGetDestinationPath:
    def test_joins_base_category_subcategory(self, organizer, tmp_path):
        destination = organizer.get_destination_path("Documents", "General", "a.pdf")
        assert destination == tmp_path / "organized" / "Documents" / "General" / "a.pdf"


class TestMoveFile:
    def test_moves_and_creates_parent_dirs(self, organizer, tmp_path):
        source = tmp_path / "in" / "a.pdf"
        source.parent.mkdir()
        source.write_text("content")
        destination = organizer.get_destination_path("Documents", "General", "a.pdf")

        assert organizer.move_file(source, destination) is True
        assert destination.read_text() == "content"
        assert not source.exists()

    def test_duplicate_destination_gets_numbered_suffix(self, organizer, tmp_path):
        destination = organizer.get_destination_path("Documents", "General", "a.pdf")
        destination.parent.mkdir(parents=True)
        destination.write_text("existing")
        (destination.parent / "a_1.pdf").write_text("also existing")

        source = tmp_path / "a.pdf"
        source.write_text("new")

        assert organizer.move_file(source, destination) is True
        assert (destination.parent / "a_2.pdf").read_text() == "new"
        assert destination.read_text() == "existing"

    def test_dry_run_moves_nothing(self, dry_organizer, tmp_path, capsys):
        source = tmp_path / "a.pdf"
        source.write_text("content")
        destination = dry_organizer.get_destination_path("Documents", "General", "a.pdf")

        assert dry_organizer.move_file(source, destination) is True
        assert source.exists()
        assert not destination.exists()
        assert "[DRY RUN]" in capsys.readouterr().out

    def test_missing_source_returns_false(self, organizer, tmp_path, capsys):
        source = tmp_path / "ghost.pdf"
        destination = organizer.get_destination_path("Documents", "General", "ghost.pdf")

        assert organizer.move_file(source, destination) is False
        assert "Error moving file" in capsys.readouterr().out


class TestOrganizeDirectory:
    def _make_source(self, tmp_path: Path) -> Path:
        source = tmp_path / "inbox"
        source.mkdir()
        (source / "notes.pdf").write_text("doc")
        (source / "Screen Shot 1.png").write_text("img")
        (source / "blob.zzz").write_text("?")
        return source

    def test_real_run_moves_files_and_counts(self, organizer, tmp_path, redirect_report_dir):
        source = self._make_source(tmp_path)

        organizer.organize_directory(str(source))

        base = tmp_path / "organized"
        assert (base / "Documents" / "General" / "notes.pdf").exists()
        assert (base / "Media/Photos" / "Screenshots" / "Screen Shot 1.png").exists()
        assert (base / "Uncategorized" / "Other" / "blob.zzz").exists()
        assert organizer.stats["total_files"] == 3
        assert organizer.stats["moved_files"] == 3
        assert organizer.stats["errors"] == 0
        assert organizer.stats["by_category"] == {
            "Documents/General": 1,
            "Media/Photos/Screenshots": 1,
            "Uncategorized/Other": 1,
        }

    def test_dry_run_counts_but_moves_nothing(self, dry_organizer, tmp_path, capsys):
        source = self._make_source(tmp_path)

        dry_organizer.organize_directory(str(source))

        assert (source / "notes.pdf").exists()
        # Known quirk: move_file mkdirs the destination tree before the
        # dry-run check, so directories appear even in dry-run — but no
        # files are ever written there.
        organized = tmp_path / "organized"
        moved_files = [p for p in organized.rglob("*") if p.is_file()]
        assert moved_files == []
        assert dry_organizer.stats["moved_files"] == 3
        out = capsys.readouterr().out
        assert "SUMMARY" in out
        assert "Total files: 3" in out

    def test_file_already_in_place_is_skipped(self, organizer, tmp_path, redirect_report_dir):
        in_place = tmp_path / "organized" / "Documents" / "General"
        in_place.mkdir(parents=True)
        (in_place / "notes.pdf").write_text("doc")

        organizer.organize_directory(str(in_place))

        assert organizer.stats["skipped_files"] == 1
        assert organizer.stats["moved_files"] == 0
        assert (in_place / "notes.pdf").exists()

    def test_limit_processes_first_n_files(self, dry_organizer, tmp_path):
        source = self._make_source(tmp_path)

        dry_organizer.organize_directory(str(source), limit=2)

        assert dry_organizer.stats["total_files"] == 2

    def test_recursive_includes_subdirectories(self, dry_organizer, tmp_path):
        source = self._make_source(tmp_path)
        nested = source / "sub"
        nested.mkdir()
        (nested / "deep.pdf").write_text("doc")

        dry_organizer.organize_directory(str(source), recursive=False)
        non_recursive_total = dry_organizer.stats["total_files"]
        dry_organizer.organize_directory(str(source), recursive=True)

        assert non_recursive_total == 3
        assert dry_organizer.stats["total_files"] == 4

    def test_missing_source_prints_error_and_returns(self, organizer, capsys):
        organizer.organize_directory("/nonexistent/inbox")

        assert "does not exist" in capsys.readouterr().out
        assert organizer.stats["total_files"] == 0


class TestSaveReport:
    def test_writes_json_report_with_stats(self, organizer, redirect_report_dir, capsys):
        organizer.stats["moved_files"] = 2
        organizer.stats["by_category"] = {"Documents/General": 2}

        organizer.save_report()

        reports = list(redirect_report_dir.glob("name_organization_report_*.json"))
        assert len(reports) == 1
        report = json.loads(reports[0].read_text())
        assert report["base_path"] == str(organizer.base_path)
        assert report["stats"]["moved_files"] == 2
        assert report["stats"]["by_category"] == {"Documents/General": 2}
        assert "Report saved" in capsys.readouterr().out

    def test_real_run_saves_report_dry_run_does_not(
        self, organizer, dry_organizer, tmp_path, redirect_report_dir
    ):
        source = tmp_path / "inbox"
        source.mkdir()
        (source / "notes.pdf").write_text("doc")

        dry_organizer.organize_directory(str(source))
        assert not redirect_report_dir.exists()

        organizer.organize_directory(str(source))
        assert len(list(redirect_report_dir.glob("*.json"))) == 1
