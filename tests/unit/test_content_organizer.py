"""Unit tests for ContentOrganizer."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.organizers.base_organizer import BaseOrganizer
from src.organizers.content_organizer import ContentOrganizer


@pytest.fixture()
def mock_classifier() -> MagicMock:
    clf = MagicMock()
    clf.extract_company_names.return_value = []
    clf.extract_people_names.return_value = []
    clf.sanitize_company_name.side_effect = lambda name: name
    clf.classify_content.return_value = ("uncategorized", "other", None, [])
    return clf


@pytest.fixture()
def organizer(tmp_path: Path, mock_classifier: MagicMock) -> ContentOrganizer:
    return ContentOrganizer(base_path=tmp_path, content_classifier=mock_classifier)


# ------------------------------------------------------------------ #
# BaseOrganizer                                                        #
# ------------------------------------------------------------------ #

class TestBaseOrganizer:
    def test_stores_attrs(self, tmp_path: Path) -> None:
        base = BaseOrganizer(
            base_path=tmp_path,
            organize_by_date=True,
            organize_by_location=False,
            enable_cost_tracking=True,
            db_path="results/test.db",
        )
        assert base.base_path == tmp_path
        assert base.organize_by_date is True
        assert base.organize_by_location is False
        assert base.enable_cost_tracking is True
        assert base.db_path == "results/test.db"

    def test_expands_home(self) -> None:
        base = BaseOrganizer(base_path=Path("~/Documents"))
        assert "~" not in str(base.base_path)

    def test_defaults(self, tmp_path: Path) -> None:
        base = BaseOrganizer(base_path=tmp_path)
        assert base.organize_by_date is False
        assert base.organize_by_location is False
        assert base.enable_cost_tracking is False
        assert base.db_path is None


# ------------------------------------------------------------------ #
# classify_by_filepath                                                 #
# ------------------------------------------------------------------ #

class TestClassifyByFilepath:
    def test_python_file(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filepath(Path("/some/project/script.py"))
        assert result is not None
        assert "Technical/Python" in result

    def test_typescript_file(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filepath(Path("/home/user/src/index.ts"))
        assert result is not None
        assert "Technical/TypeScript" in result

    def test_exact_filename_match(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filepath(Path("/project/Makefile"))
        assert result == "Technical/Build"

    def test_double_extension(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filepath(Path("/logs/output.log.gz"))
        assert result == "Technical/Logs"

    def test_unknown_extension_returns_none(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filepath(Path("/files/data.xyz123"))
        assert result is None

    def test_json_file(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filepath(Path("/home/user/config/settings.json"))
        assert result is not None
        assert "Technical/Config" in result


# ------------------------------------------------------------------ #
# classify_game_asset                                                  #
# ------------------------------------------------------------------ #

class TestClassifyGameAsset:
    def test_ogg_game_music(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_game_asset(Path("/sounds/dungeon.ogg"))
        assert result == ('game_assets', 'music')

    def test_wav_game_sfx(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_game_asset(Path("/sounds/sword_attack.wav"))
        assert result == ('game_assets', 'audio')

    def test_png_sprite_frame(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_game_asset(Path("/sprites/frame_1.png"))
        assert result == ('game_assets', 'sprites')

    def test_ttf_font(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_game_asset(Path("/fonts/arial.ttf"))
        assert result == ('fonts', 'truetype')

    def test_otf_font(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_game_asset(Path("/fonts/comic.otf"))
        assert result == ('fonts', 'opentype')

    def test_regular_jpg_returns_none(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_game_asset(Path("/photos/vacation.jpg"))
        assert result is None

    def test_mp3_non_game_returns_none(self, organizer: ContentOrganizer) -> None:
        # "song.mp3" has extension .mp3 but no game keywords — classify_game_asset returns None
        result = organizer.classify_game_asset(Path("/music/vacation_song.mp3"))
        assert result is None


# ------------------------------------------------------------------ #
# should_skip_file                                                     #
# ------------------------------------------------------------------ #

class TestShouldSkipFile:
    def test_ds_store(self, organizer: ContentOrganizer) -> None:
        assert organizer.should_skip_file(Path("/docs/.DS_Store")) is True

    def test_thumbs_db(self, organizer: ContentOrganizer) -> None:
        assert organizer.should_skip_file(Path("/docs/Thumbs.db")) is True

    def test_hidden_file(self, organizer: ContentOrganizer) -> None:
        assert organizer.should_skip_file(Path("/docs/.hidden_file")) is True

    def test_gitignore_not_skipped(self, organizer: ContentOrganizer) -> None:
        assert organizer.should_skip_file(Path("/project/.gitignore")) is False

    def test_env_example_not_skipped(self, organizer: ContentOrganizer) -> None:
        assert organizer.should_skip_file(Path("/project/.env.example")) is False

    def test_pycache_dir(self, organizer: ContentOrganizer) -> None:
        assert organizer.should_skip_file(Path("/project/__pycache__/module.pyc")) is True

    def test_node_modules(self, organizer: ContentOrganizer) -> None:
        assert organizer.should_skip_file(Path("/project/node_modules/lib/index.js")) is True

    def test_savepage_sidecar_files(self, organizer: ContentOrganizer) -> None:
        # Browser "Save Page As" asset folder (English suffix).
        assert organizer.should_skip_file(
            Path("/Desktop/love_drawing.jpg_files/CVg8QFElfQG.js")
        ) is True

    def test_savepage_sidecar_locale_suffix(self, organizer: ContentOrganizer) -> None:
        # Non-English browser locale suffix (German).
        assert organizer.should_skip_file(
            Path("/Desktop/seite-Dateien/asset.css")
        ) is True

    def test_sidecar_suffix_in_filename_not_skipped(self, organizer: ContentOrganizer) -> None:
        # A regular file whose own name ends in a sidecar suffix must not match;
        # only ancestor directories count.
        assert organizer.should_skip_file(Path("/Desktop/report_files")) is False

    def test_regular_file_not_skipped(self, organizer: ContentOrganizer) -> None:
        assert organizer.should_skip_file(Path("/project/report.pdf")) is False


# ------------------------------------------------------------------ #
# get_destination_path                                                 #
# ------------------------------------------------------------------ #

class TestGetDestinationPath:
    def test_returns_path(self, organizer: ContentOrganizer, tmp_path: Path) -> None:
        result = organizer.get_destination_path(
            file_path=Path("/src/report.pdf"),
            category="financial",
            subcategory="invoices",
        )
        assert isinstance(result, Path)

    def test_uncategorized_fallback(self, organizer: ContentOrganizer, tmp_path: Path) -> None:
        result = organizer.get_destination_path(
            file_path=Path("/src/unknown.xyz"),
            category="unknown_cat",
            subcategory="unknown_sub",
        )
        assert "Uncategorized" in str(result)

    def test_organization_with_company(self, organizer: ContentOrganizer, tmp_path: Path) -> None:
        result = organizer.get_destination_path(
            file_path=Path("/src/invoice.pdf"),
            category="organization",
            subcategory="vendors",
            company_name="Acme Corp",
        )
        assert "Acme Corp" in str(result)
        assert "Organization" in str(result)

    def test_personal_contacts_ignores_people_names(
        self, organizer: ContentOrganizer, tmp_path: Path
    ) -> None:
        # Option C: `person` is demoted to a graph relationship, not a filing
        # category — people_names no longer creates a name subfolder here.
        result = organizer.get_destination_path(
            file_path=Path("/src/resume.pdf"),
            category="personal",
            subcategory="contacts",
            people_names=["Jane Doe"],
        )
        assert "Personal" in str(result)
        assert "Contacts" in str(result)
        assert "Jane Doe" not in str(result)

    def test_filepath_category_uses_subcategory_as_path(
        self, organizer: ContentOrganizer, tmp_path: Path
    ) -> None:
        result = organizer.get_destination_path(
            file_path=Path("/src/script.py"),
            category="filepath",
            subcategory="Technical/Python/MyProject",
        )
        assert "Technical/Python/MyProject" in str(result)

    def test_media_photos_travel(self, organizer: ContentOrganizer, tmp_path: Path) -> None:
        result = organizer.get_destination_path(
            file_path=Path("/photos/img.jpg"),
            category="media",
            subcategory="photos_travel",
        )
        assert "Travel" in str(result)

    def test_date_organization_overrides_path(
        self, tmp_path: Path, mock_classifier: MagicMock
    ) -> None:
        org = ContentOrganizer(
            base_path=tmp_path,
            content_classifier=mock_classifier,
            organize_by_date=True,
        )
        result = org.get_destination_path(
            file_path=Path("/photos/img.jpg"),
            category="media",
            subcategory="photos_other",
            image_metadata={"year": 2024, "month": 6},
        )
        assert "Photos/2024/06" in str(result)


# ------------------------------------------------------------------ #
# classify_by_filename_patterns                                        #
# ------------------------------------------------------------------ #

class TestClassifyByFilenamePatterns:
    def test_log_file(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(Path("/logs/system.log"))
        assert result is not None
        assert result[0] == 'technical'
        assert result[1] == 'logs'

    def test_timestamped_duplicate_skipped(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(
            Path("/docs/report_20241201_123456.pdf")
        )
        assert result is not None
        assert result[0] == 'skip'

    def test_software_screenshot_detected(self, organizer: ContentOrganizer) -> None:
        # Structured software-screenshot pattern ("<kind>_<8 hex>") is classified
        # at the filename stage.
        result = organizer.classify_by_filename_patterns(Path("/photos/terminal_12ab34cd.png"))
        assert result is not None
        assert 'screenshot' in result[1]

    def test_bare_screenshot_deferred(self, organizer: ContentOrganizer) -> None:
        # A generic "screenshot_*" name is NOT matched here; screenshot routing
        # for these happens later via OCR/SCREENSHOT_KEYWORDS, matching the
        # production organizer's filename-pattern contract.
        result = organizer.classify_by_filename_patterns(Path("/photos/screenshot_2024.png"))
        assert result is None

    def test_resume_pdf_with_name(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(
            Path("/docs/Alyshia_Ledlie_Resume.pdf")
        )
        assert result is not None
        assert result[0] == 'personal'
        assert result[1] == 'contacts'
        assert len(result[3]) > 0  # people_names

    def test_nda_document(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(Path("/docs/nda_2024.pdf"))
        assert result is not None
        assert result[0] == 'legal'
        assert result[1] == 'contracts'

    def test_unknown_returns_none(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(Path("/random/xyzxyz_unique_file.pdf"))
        assert result is None

    def test_travel_document_maps_to_personal_other(self, organizer: ContentOrganizer) -> None:
        # Option C: person/travel is retired; travel docs file under personal/other.
        result = organizer.classify_by_filename_patterns(Path("/docs/austin_to_bombay.docx"))
        assert result is not None
        assert result[0] == 'personal'
        assert result[1] == 'other'

    def test_event_document_maps_to_personal_other(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(Path("/docs/Oct25Event.docx"))
        assert result is not None
        assert result[0] == 'personal'
        assert result[1] == 'other'

    def test_journal_entry_maps_to_personal_other(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(Path("/docs/dream_journal.docx"))
        assert result is not None
        assert result[0] == 'personal'
        assert result[1] == 'other'

    def test_cover_letter_maps_to_personal_contacts(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(Path("/docs/cover_letter.pdf"))
        assert result is not None
        assert result[0] == 'personal'
        assert result[1] == 'contacts'

    def test_no_person_category_ever_returned(self, organizer: ContentOrganizer) -> None:
        # Option C: `person` must never appear as a filing category anymore —
        # only as a graph relationship (file.people via GraphStore).
        candidates = [
            "/docs/Alyshia_Ledlie_Resume.pdf",
            "/docs/cover_letter.pdf",
            "/docs/austin_to_bombay.docx",
            "/docs/Oct25Event.docx",
            "/docs/dream_journal.docx",
            "/docs/Sumedh3.docx",
        ]
        for candidate in candidates:
            result = organizer.classify_by_filename_patterns(Path(candidate))
            if result is not None:
                assert result[0] != 'person'


# ------------------------------------------------------------------ #
# OCR confidence gating in detect_file_category                       #
# ------------------------------------------------------------------ #

class TestOcrConfidenceGating:
    """detect_file_category must skip keyword classification for low-confidence OCR."""

    def _make_organizer(self, tmp_path: Path, mock_classifier: MagicMock) -> "ContentOrganizer":
        org = ContentOrganizer(base_path=tmp_path, content_classifier=mock_classifier)
        # Stub out all heavyweight dependencies used inside detect_file_category
        org.enricher = MagicMock()
        org.enricher.detect_mime_type.return_value = "application/pdf"
        org.classify_by_filename_patterns = MagicMock(return_value=None)
        org.classify_by_organization = MagicMock(return_value=None)
        org.classify_by_person = MagicMock(return_value=None)
        org.classify_game_asset = MagicMock(return_value=None)
        org.classify_by_filepath = MagicMock(return_value=None)
        org.classify_media_file = MagicMock(return_value=None)
        org.image_analyzer = MagicMock()
        org.image_analyzer.vision_available = False
        return org

    def test_high_confidence_ocr_classifies(
        self, tmp_path: Path, mock_classifier: MagicMock
    ) -> None:
        from src.analyzers.text_extractor import ExtractionResult

        org = self._make_organizer(tmp_path, mock_classifier)
        mock_classifier.classify_content.return_value = ("legal", "contracts", None, [])

        legal_text = "contract terms and conditions agreement"
        org.extract_rich = lambda _p: ExtractionResult(
            text=legal_text, confidence=0.85, language="en", source="ocr"
        )

        fake_pdf = tmp_path / "doc.pdf"
        fake_pdf.write_bytes(b"%PDF")

        cat, subcat, *_ = org.detect_file_category(fake_pdf)

        # classify_content called with the real text (high confidence)
        mock_classifier.classify_content.assert_called_once()
        args = mock_classifier.classify_content.call_args[0]
        assert args[0] == legal_text

    def test_low_confidence_ocr_skips_keyword_classification(
        self, tmp_path: Path, mock_classifier: MagicMock
    ) -> None:
        from src.analyzers.text_extractor import ExtractionResult

        org = self._make_organizer(tmp_path, mock_classifier)
        mock_classifier.classify_content.return_value = ("uncategorized", "other", None, [])

        legal_text = "contract terms and conditions"
        org.extract_rich = lambda _p: ExtractionResult(
            text=legal_text, confidence=0.15, language="en", source="ocr"
        )

        fake_pdf = tmp_path / "blurry_scan.pdf"
        fake_pdf.write_bytes(b"%PDF")

        org.detect_file_category(fake_pdf)

        # classify_content must be called with empty string, not the low-confidence text
        mock_classifier.classify_content.assert_called_once()
        args = mock_classifier.classify_content.call_args[0]
        assert args[0] == ""

    def test_no_extract_rich_falls_back_to_extract_text(
        self, tmp_path: Path, mock_classifier: MagicMock
    ) -> None:
        org = self._make_organizer(tmp_path, mock_classifier)
        mock_classifier.classify_content.return_value = ("financial", "invoices", None, [])

        org.extract_text = lambda _p: "invoice payment amount"

        fake_pdf = tmp_path / "invoice.pdf"
        fake_pdf.write_bytes(b"%PDF")

        org.detect_file_category(fake_pdf)

        mock_classifier.classify_content.assert_called_once()
        args = mock_classifier.classify_content.call_args[0]
        assert args[0] == "invoice payment amount"
