"""Unit tests for ContentOrganizer."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from src.organizers.base_organizer import BaseOrganizer
from src.organizers.category_config import CONTENT_CATEGORY_PATHS
from src.organizers.content_organizer import (
    _SIGNAL_AGREEMENT_BOOST,
    _TEXT_LENGTH_FULL_CHARS,
    _TEXT_MIN_CHARS,
    _TEXT_SIGNAL_PRIOR,
    SCREENSHOT_SCENE_SUBCATEGORY,
    ContentOrganizer,
    _mime_result_to_content_category,
)
from src.scoring.context import FileContext
from src.scoring.scorer import Scorer
from src.scoring.signals.scene import SCENE_CATEGORY, SCENE_DESCRIPTION_LABELS
from src.scoring.types import CategoryScore, ClassificationDecision

MODULE = "src.organizers.content_organizer"


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
    # Pin to legacy so Phase-0 tests keep exercising the 10-tier priority chain;
    # the base ContentOrganizer now defaults to SCORER_DEFAULT (unified) after the
    # Phase-5 default flip.
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
        assert result == ("game_assets", "music")

    def test_wav_game_sfx(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_game_asset(Path("/sounds/sword_attack.wav"))
        assert result == ("game_assets", "audio")

    def test_png_sprite_frame(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_game_asset(Path("/sprites/frame_1.png"))
        assert result == ("game_assets", "sprites")

    def test_ttf_font(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_game_asset(Path("/fonts/arial.ttf"))
        assert result == ("fonts", "truetype")

    def test_otf_font(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_game_asset(Path("/fonts/comic.otf"))
        assert result == ("fonts", "opentype")

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
        assert (
            organizer.should_skip_file(Path("/Desktop/love_drawing.jpg_files/CVg8QFElfQG.js"))
            is True
        )

    def test_savepage_sidecar_locale_suffix(self, organizer: ContentOrganizer) -> None:
        # Non-English browser locale suffix (German).
        assert organizer.should_skip_file(Path("/Desktop/seite-Dateien/asset.css")) is True

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

    def test_media_exteriors_other(self, organizer: ContentOrganizer, tmp_path: Path) -> None:
        # Scene taxonomy: exteriors_other -> Media/Exteriors (schema.org House).
        result = organizer.get_destination_path(
            file_path=Path("/photos/house.jpg"),
            category="media",
            subcategory="exteriors_other",
        )
        assert "Media/Exteriors" in str(result)

    def test_media_place_other(self, organizer: ContentOrganizer, tmp_path: Path) -> None:
        # Scene taxonomy: place_other -> Media/Place (schema.org Place).
        result = organizer.get_destination_path(
            file_path=Path("/photos/park.jpg"),
            category="media",
            subcategory="place_other",
        )
        assert "Media/Place" in str(result)

    @pytest.mark.parametrize(
        ("subcategory", "folder"),
        [
            ("photos_screenshots_interiors", "Media/Photos/Screenshots/Interiors"),
            ("photos_screenshots_exteriors", "Media/Photos/Screenshots/Exteriors"),
            ("photos_screenshots_places", "Media/Photos/Screenshots/Places"),
        ],
    )
    def test_screenshot_scene_subcategories(
        self, organizer: ContentOrganizer, subcategory: str, folder: str
    ) -> None:
        # Scene-classified screenshots (SCREENSHOT_SCENE_SUBCATEGORY reroute)
        # resolve under the Screenshots subtree, not Media/{Interiors,...}.
        result = organizer.get_destination_path(
            file_path=Path("/shots/Screenshot 2026-05-30 at 12.45.50 AM.png"),
            category="media",
            subcategory=subcategory,
        )
        assert folder in str(result)

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
        assert result[0] == "technical"
        assert result[1] == "logs"

    def test_timestamped_duplicate_skipped(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(Path("/docs/report_20241201_123456.pdf"))
        assert result is not None
        assert result[0] == "skip"

    def test_software_screenshot_detected(self, organizer: ContentOrganizer) -> None:
        # Structured software-screenshot pattern ("<kind>_<8 hex>") is classified
        # at the filename stage.
        result = organizer.classify_by_filename_patterns(Path("/photos/terminal_12ab34cd.png"))
        assert result is not None
        assert "screenshot" in result[1]

    def test_bare_screenshot_deferred(self, organizer: ContentOrganizer) -> None:
        # A generic "screenshot_*" name is NOT matched here; screenshot routing
        # for these happens later via OCR/SCREENSHOT_KEYWORDS, matching the
        # production organizer's filename-pattern contract.
        result = organizer.classify_by_filename_patterns(Path("/photos/screenshot_2024.png"))
        assert result is None

    def test_resume_pdf_with_name(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(Path("/docs/Alyshia_Ledlie_Resume.pdf"))
        assert result is not None
        assert result[0] == "personal"
        assert result[1] == "contacts"
        assert len(result[3]) > 0  # people_names

    def test_nda_document(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(Path("/docs/nda_2024.pdf"))
        assert result is not None
        assert result[0] == "legal"
        assert result[1] == "contracts"

    def test_unknown_returns_none(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(Path("/random/xyzxyz_unique_file.pdf"))
        assert result is None

    def test_travel_document_maps_to_personal_other(self, organizer: ContentOrganizer) -> None:
        # Option C: person/travel is retired; travel docs file under personal/other.
        result = organizer.classify_by_filename_patterns(Path("/docs/austin_to_bombay.docx"))
        assert result is not None
        assert result[0] == "personal"
        assert result[1] == "other"

    def test_event_document_maps_to_personal_events(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(Path("/docs/Oct25Event.docx"))
        assert result is not None
        assert result[0] == "personal"
        assert result[1] == "events"

    def test_event_document_allows_separated_month_day(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(Path("/docs/nov_15_party.docx"))
        assert result is not None
        assert result[0] == "personal"
        assert result[1] == "events"

    def test_bare_year_is_not_an_event_document(self, organizer: ContentOrganizer) -> None:
        # "may 2026" has no month+day adjacency (2026 is a year), so the
        # event heuristic must not fire.
        result = organizer.classify_by_filename_patterns(Path("/docs/xyzzy may 2026.pdf"))
        assert result is None

    def test_billing_statement_maps_to_financial(self, organizer: ContentOrganizer) -> None:
        # Regression: previously matched the event heuristic ("may" + digits)
        # and filed under personal/events before content extraction ran.
        result = organizer.classify_by_filename_patterns(
            Path("/docs/May 2026 Billing Statement (2).pdf")
        )
        assert result is not None
        assert result[0] == "financial"
        assert result[1] == "statements"

    def test_bare_billing_maps_to_financial_invoices(self, organizer: ContentOrganizer) -> None:
        # Guards the financial_doc_keywords reorder: a bare "billing" stem (no
        # "statement") routes to financial/invoices. "statement" precedes
        # "billing" in the dict, so "Billing Statement" above still → statements.
        result = organizer.classify_by_filename_patterns(Path("/docs/acme_billing.pdf"))
        assert result is not None
        assert result[0] == "financial"
        assert result[1] == "invoices"

    def test_invoice_filename_maps_to_financial_invoices(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(Path("/docs/acme_invoice_march.pdf"))
        assert result is not None
        assert result[0] == "financial"
        assert result[1] == "invoices"

    def test_receipt_filename_maps_to_financial_other(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(Path("/docs/store_receipt.pdf"))
        assert result is not None
        assert result[0] == "financial"
        assert result[1] == "other"

    def test_journal_entry_maps_to_personal_journal(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(Path("/docs/dream_journal.docx"))
        assert result is not None
        assert result[0] == "personal"
        assert result[1] == "journal"

    def test_cover_letter_maps_to_personal_contacts(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filename_patterns(Path("/docs/cover_letter.pdf"))
        assert result is not None
        assert result[0] == "personal"
        assert result[1] == "contacts"

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
                assert result[0] != "person"


# ------------------------------------------------------------------ #
# __init__ taxonomy wiring                                             #
# ------------------------------------------------------------------ #


class TestInitTaxonomy:
    def test_screenshots_extended_from_ocr_keywords(self, organizer: ContentOrganizer) -> None:
        # SCREENSHOT_KEYWORDS keys not already in the taxonomy get a derived folder.
        screenshots = organizer.category_paths["media"]["photos"]["screenshots"]
        assert screenshots["terminal_session"] == "Media/Photos/Screenshots/TerminalSession"

    def test_shared_taxonomy_not_mutated(self, organizer: ContentOrganizer) -> None:
        # The instance deepcopies CONTENT_CATEGORY_PATHS; extending screenshots
        # must not leak into the shared module-level dict.
        shared_screenshots = CONTENT_CATEGORY_PATHS["media"]["photos"]["screenshots"]
        assert "terminal_session" not in shared_screenshots

    def test_classifier_patterns_extend_screenshots(
        self, tmp_path: Path, mock_classifier: MagicMock
    ) -> None:
        mock_classifier.patterns = {"jira": ["board", "sprint"]}
        org = ContentOrganizer(base_path=tmp_path, content_classifier=mock_classifier)
        screenshots = org.category_paths["media"]["photos"]["screenshots"]
        assert screenshots["jira"] == "Media/Photos/Screenshots/Jira"


# ------------------------------------------------------------------ #
# extract_project_name                                                 #
# ------------------------------------------------------------------ #


class TestExtractProjectName:
    def test_finds_project_dir(self, organizer: ContentOrganizer) -> None:
        result = organizer.extract_project_name(Path("code/myproject/src/main.py"))
        assert result == "myproject"

    def test_all_generic_dirs_returns_none(self, organizer: ContentOrganizer) -> None:
        result = organizer.extract_project_name(Path("src/tests/main.py"))
        assert result is None

    def test_skips_hidden_dirs(self, organizer: ContentOrganizer) -> None:
        result = organizer.extract_project_name(Path(".config/myapp/settings.py"))
        assert result == "myapp"

    def test_project_name_appended_to_filepath_category(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_by_filepath(Path("repos/MyProject/src/script.py"))
        assert result == "Technical/Python/MyProject"

    def test_skips_home_directory_name(self, organizer: ContentOrganizer) -> None:
        """Files straight out of ~/Downloads must not use the username as project name."""
        from pathlib import Path as _Path

        home_name = _Path.home().name
        # Simulate ~/Downloads/index.html → parts include username before 'Downloads'
        path = _Path("/Users") / home_name / "Downloads" / "index.html"
        result = organizer.extract_project_name(path)
        # 'Downloads' and 'Users' are both in skip_dirs / user_container guard;
        # no valid project segment remains.
        assert result is None

    def test_skips_other_user_directories(self, organizer: ContentOrganizer) -> None:
        """Segments that are direct children of /Users or /home are also skipped."""
        result = organizer.extract_project_name(Path("/Users/otheruser/Downloads/report.pdf"))
        assert result is None


# ------------------------------------------------------------------ #
# classify_by_organization                                             #
# ------------------------------------------------------------------ #


class TestClassifyByOrganization:
    VENDOR_TEXT = (
        "Invoice #1234 issued under purchase order PO-99. "
        "Payment terms: net 30. Please remit to the address on file."
    )

    def test_short_text_returns_none(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        assert organizer.classify_by_organization("invoice", "doc.pdf") is None
        mock_classifier.extract_company_names.assert_not_called()

    def test_vendor_keywords_with_company(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        mock_classifier.extract_company_names.return_value = ["Acme Corp"]
        result = organizer.classify_by_organization(self.VENDOR_TEXT, "invoice.pdf")
        assert result == ("organization", "vendors", "Acme Corp")

    def test_no_company_name_returns_none(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        mock_classifier.extract_company_names.return_value = []
        result = organizer.classify_by_organization(self.VENDOR_TEXT, "invoice.pdf")
        assert result is None

    def test_single_keyword_not_enough(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        mock_classifier.extract_company_names.return_value = ["Acme Corp"]
        text = "This invoice covers consulting delivered during the spring engagement window."
        result = organizer.classify_by_organization(text, "doc.pdf")
        assert result is None


# ------------------------------------------------------------------ #
# classify_by_person                                                   #
# ------------------------------------------------------------------ #


class TestClassifyByPerson:
    def test_short_text_returns_none(self, organizer: ContentOrganizer) -> None:
        assert organizer.classify_by_person("contact", "card.pdf") is None

    def test_resume_filename_routes_to_contacts(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        mock_classifier.extract_people_names.return_value = ["Jane Doe"]
        text = "Experienced engineer with ten years of distributed systems background."
        result = organizer.classify_by_person(text, "Jane_Doe_Resume.pdf")
        assert result == ("personal", "contacts", ["Jane Doe"])

    def test_employee_keywords_map_to_employment(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        # Option C: person/employees is retired; employee docs file under
        # personal/employment.
        mock_classifier.extract_people_names.return_value = ["John Smith"]
        text = (
            "Employee: John Smith. Hire date: 2024-01-15. "
            "Position: Senior Analyst reporting to operations."
        )
        with patch(f"{MODULE}._has_human_name_signal", return_value=True):
            result = organizer.classify_by_person(text, "record.pdf")
        assert result == ("personal", "employment", ["John Smith"])

    def test_no_human_name_signal_returns_none(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        mock_classifier.extract_people_names.return_value = ["Spurious Match"]
        text = (
            "Employee: John Smith. Hire date: 2024-01-15. "
            "Position: Senior Analyst reporting to operations."
        )
        with patch(f"{MODULE}._has_human_name_signal", return_value=False):
            result = organizer.classify_by_person(text, "record.pdf")
        assert result is None

    def test_no_people_extracted_returns_none(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        mock_classifier.extract_people_names.return_value = []
        text = (
            "Employee: (redacted). Hire date: 2024-01-15. "
            "Position: Senior Analyst reporting to operations."
        )
        with patch(f"{MODULE}._has_human_name_signal", return_value=True):
            result = organizer.classify_by_person(text, "record.pdf")
        assert result is None

    def test_court_notice_vetoed_despite_contact_indicators(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        # Regression: "NOTICE OF CT SETTING" filed under Personal/Contacts
        # because the clerk's contact footer matched the generic indicators.
        # Legal signals must veto the person tier so content analysis (which
        # classifies these as legal) decides. Text has 3 contacts hits
        # ('contact', 'phone:', 'email:'), so this isolates the veto from the
        # contacts threshold.
        mock_classifier.extract_people_names.return_value = ["Alyshia Ledlie"]
        text = (
            "NOTICE OF COURT SETTING. Cause No 24-1234. A hearing is set. "
            "Contact the clerk with questions. Phone: 512-555-0100. "
            "Email: clerk@county.gov."
        )
        with patch(f"{MODULE}._has_human_name_signal", return_value=True):
            result = organizer.classify_by_person(text, "NOTICE OF CT SETTING FOR 040126.pdf")
        assert result is None

    def test_two_generic_contact_hits_are_just_a_letterhead(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        # 'contact' + 'phone:' appear in the footer of virtually any official
        # letter; two hits must not classify a document as a contact card.
        mock_classifier.extract_people_names.return_value = ["Jane Doe"]
        text = (
            "Thank you for your inquiry about our spring schedule. "
            "Contact the front office with questions. Phone: 555-0100."
        )
        with patch(f"{MODULE}._has_human_name_signal", return_value=True):
            result = organizer.classify_by_person(text, "letter.pdf")
        assert result is None

    def test_contact_card_layout_still_routes_to_contacts(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        # A genuine vCard-style document clears the raised contacts threshold.
        mock_classifier.extract_people_names.return_value = ["Jane Doe"]
        text = (
            "Jane Doe — contact card. Phone: 555-0100. Mobile: 555-0101. "
            "Email: jane@example.com. Address: 123 Main St, Austin TX."
        )
        with patch(f"{MODULE}._has_human_name_signal", return_value=True):
            result = organizer.classify_by_person(text, "jane_doe_contact.pdf")
        assert result == ("personal", "contacts", ["Jane Doe"])


# ------------------------------------------------------------------ #
# classify_media_file                                                  #
# ------------------------------------------------------------------ #


class TestClassifyMediaFile:
    def test_screen_recording_video(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_media_file(Path("/vids/screen_recording.mp4"))
        assert result == ("media", "videos", "screencasts")

    def test_export_video(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_media_file(Path("/vids/final_cut.mov"))
        assert result == ("media", "videos", "exports")

    def test_default_video_is_recording(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_media_file(Path("/vids/birthday.mp4"))
        assert result == ("media", "videos", "recordings")

    def test_podcast_audio(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_media_file(Path("/audio/podcast_ep1.mp3"))
        assert result == ("media", "audio", "podcasts")

    def test_music_audio(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_media_file(Path("/audio/album_01.m4a"))
        assert result == ("media", "audio", "music")

    def test_default_audio_is_recording(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_media_file(Path("/audio/untitled.m4a"))
        assert result == ("media", "audio", "recordings")

    def test_screenshot_photo_defers_to_later_tiers(self, organizer: ContentOrganizer) -> None:
        # Screenshots fall through so Priority 4.5 OCR/CLIP can sub-classify.
        result = organizer.classify_media_file(Path("/pics/Screenshot 2026-01-01.png"))
        assert result is None

    def test_receipt_photo_is_document(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_media_file(Path("/pics/receipt_2024.jpg"))
        assert result == ("media", "photos", "documents")

    def test_gps_metadata_routes_to_travel(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_media_file(
            Path("/pics/img_100.png"), {"gps_coordinates": (30.27, -97.74)}
        )
        assert result == ("media", "photos", "travel")

    def test_camera_datetime_routes_to_other(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_media_file(Path("/pics/img_100.png"), {"datetime": object()})
        assert result == ("media", "photos", "other")

    def test_bare_jpg_defaults_to_other(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_media_file(Path("/pics/img_100.jpg"))
        assert result == ("media", "photos", "other")

    def test_bare_png_falls_through(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_media_file(Path("/pics/img_100.png"))
        assert result is None

    def test_non_media_returns_none(self, organizer: ContentOrganizer) -> None:
        result = organizer.classify_media_file(Path("/docs/notes.txt"))
        assert result is None


# ------------------------------------------------------------------ #
# _map_clip_label                                                      #
# ------------------------------------------------------------------ #


class TestMapClipLabel:
    def test_known_label_maps(self, organizer: ContentOrganizer) -> None:
        assert organizer._map_clip_label("food or a meal") == ("media", "photos_lifestyle")

    def test_unknown_label_returns_none(self, organizer: ContentOrganizer) -> None:
        assert organizer._map_clip_label("a completely unknown label") is None

    def test_geographic_label_with_gps_upgrades_to_travel(
        self, organizer: ContentOrganizer
    ) -> None:
        result = organizer._map_clip_label(
            "a landscape or nature scene", {"gps_coordinates": (30.27, -97.74)}
        )
        assert result == ("media", "photos_travel")

    def test_geographic_label_without_gps_keeps_mapping(self, organizer: ContentOrganizer) -> None:
        result = organizer._map_clip_label("a landscape or nature scene")
        assert result == ("media", "photos_nature")


# ------------------------------------------------------------------ #
# _merge_clip_text_scores                                               #
# ------------------------------------------------------------------ #


class TestMergeClipTextScores:
    def test_clip_only(self, organizer: ContentOrganizer) -> None:
        merged = organizer._merge_clip_text_scores(("media", "photos_nature"), 0.5, None, 0)
        assert merged is not None
        winner, score, src = merged
        assert winner == ("media", "photos_nature")
        assert score == pytest.approx(0.5)
        assert "CLIP" in src

    def test_text_only_full_length(self, organizer: ContentOrganizer) -> None:
        merged = organizer._merge_clip_text_scores(
            None, 0.0, ("financial", "invoices"), _TEXT_LENGTH_FULL_CHARS
        )
        assert merged is not None
        winner, score, src = merged
        assert winner == ("financial", "invoices")
        assert score == pytest.approx(_TEXT_SIGNAL_PRIOR)
        assert "text" in src

    def test_text_score_scales_with_length(self, organizer: ContentOrganizer) -> None:
        half = _TEXT_LENGTH_FULL_CHARS // 2
        merged = organizer._merge_clip_text_scores(None, 0.0, ("financial", "invoices"), half)
        assert merged is not None
        _, score, _ = merged
        assert score == pytest.approx(_TEXT_SIGNAL_PRIOR * 0.5)

    def test_text_below_min_chars_ignored(self, organizer: ContentOrganizer) -> None:
        merged = organizer._merge_clip_text_scores(
            None, 0.0, ("financial", "invoices"), _TEXT_MIN_CHARS - 1
        )
        assert merged is None

    def test_agreement_boost(self, organizer: ContentOrganizer) -> None:
        merged = organizer._merge_clip_text_scores(
            ("financial", "invoices"), 0.5, ("financial", "invoices"), _TEXT_LENGTH_FULL_CHARS
        )
        assert merged is not None
        winner, score, src = merged
        assert winner == ("financial", "invoices")
        assert score == pytest.approx(0.5 + _TEXT_SIGNAL_PRIOR + _SIGNAL_AGREEMENT_BOOST)
        assert "agree" in src

    def test_long_text_beats_weak_clip(self, organizer: ContentOrganizer) -> None:
        merged = organizer._merge_clip_text_scores(
            ("media", "photos_nature"), 0.5, ("financial", "invoices"), _TEXT_LENGTH_FULL_CHARS
        )
        assert merged is not None
        winner, _, _ = merged
        assert winner == ("financial", "invoices")

    def test_no_signals_returns_none(self, organizer: ContentOrganizer) -> None:
        assert organizer._merge_clip_text_scores(None, 0.0, None, 0) is None


# ------------------------------------------------------------------ #
# _run_clip_signal                                                      #
# ------------------------------------------------------------------ #

NATURE_PROMPT = "a photo of a landscape or nature scene"


class TestRunClipSignal:
    def _vision_organizer(self, organizer: ContentOrganizer) -> ContentOrganizer:
        organizer.image_analyzer = MagicMock()
        organizer.image_analyzer.vision_available = True
        return organizer

    def test_vision_unavailable_returns_none(self, organizer: ContentOrganizer) -> None:
        assert organizer.image_analyzer is None
        assert organizer._run_clip_signal(Path("/pics/img.png")) == (None, 0.0)

    def test_maps_top_prompt_to_candidate(self, organizer: ContentOrganizer) -> None:
        org = self._vision_organizer(organizer)
        clip = MagicMock()
        clip.classify_raw.return_value = [(NATURE_PROMPT, 0.5)]
        with (
            patch(f"{MODULE}.ENHANCED_CLIP_AVAILABLE", True),
            patch(f"{MODULE}.CLIP_CACHE_AVAILABLE", False),
            patch(f"{MODULE}.get_clip_classifier", return_value=clip),
        ):
            candidate, score = org._run_clip_signal(Path("/pics/img.png"))
        assert candidate == ("media", "photos_nature")
        assert score == pytest.approx(0.5)

    def test_below_threshold_returns_none(self, organizer: ContentOrganizer) -> None:
        org = self._vision_organizer(organizer)
        clip = MagicMock()
        clip.classify_raw.return_value = [(NATURE_PROMPT, 0.2)]
        with (
            patch(f"{MODULE}.ENHANCED_CLIP_AVAILABLE", True),
            patch(f"{MODULE}.CLIP_CACHE_AVAILABLE", False),
            patch(f"{MODULE}.CLIP_ENHANCE_THRESHOLD", 0.3),
            patch(f"{MODULE}.get_clip_classifier", return_value=clip),
        ):
            assert org._run_clip_signal(Path("/pics/img.png")) == (None, 0.0)

    def test_classifier_error_swallowed(self, organizer: ContentOrganizer) -> None:
        org = self._vision_organizer(organizer)
        clip = MagicMock()
        clip.classify_raw.side_effect = RuntimeError("model load failed")
        with (
            patch(f"{MODULE}.ENHANCED_CLIP_AVAILABLE", True),
            patch(f"{MODULE}.CLIP_CACHE_AVAILABLE", False),
            patch(f"{MODULE}.get_clip_classifier", return_value=clip),
        ):
            assert org._run_clip_signal(Path("/pics/img.png")) == (None, 0.0)

    def test_stashes_label_for_description(self, organizer: ContentOrganizer) -> None:
        org = self._vision_organizer(organizer)
        clip = MagicMock()
        clip.classify_raw.return_value = [(NATURE_PROMPT, 0.5)]
        with (
            patch(f"{MODULE}.ENHANCED_CLIP_AVAILABLE", True),
            patch(f"{MODULE}.CLIP_CACHE_AVAILABLE", False),
            patch(f"{MODULE}.get_clip_classifier", return_value=clip),
        ):
            org._run_clip_signal(Path("/pics/img.png"))
        label, score = org._last_file_state["clip_description"]
        assert label == "a landscape or nature scene"
        assert score == pytest.approx(0.5)

    def test_stashes_label_even_below_threshold(self, organizer: ContentOrganizer) -> None:
        """A weak CLIP signal is rejected for classification but still feeds
        the schema.org description (which states its confidence)."""
        org = self._vision_organizer(organizer)
        clip = MagicMock()
        clip.classify_raw.return_value = [(NATURE_PROMPT, 0.2)]
        with (
            patch(f"{MODULE}.ENHANCED_CLIP_AVAILABLE", True),
            patch(f"{MODULE}.CLIP_CACHE_AVAILABLE", False),
            patch(f"{MODULE}.CLIP_ENHANCE_THRESHOLD", 0.3),
            patch(f"{MODULE}.get_clip_classifier", return_value=clip),
        ):
            assert org._run_clip_signal(Path("/pics/img.png")) == (None, 0.0)
        assert org._last_file_state["clip_description"][0] == "a landscape or nature scene"

    def test_error_leaves_no_description_stash(self, organizer: ContentOrganizer) -> None:
        org = self._vision_organizer(organizer)
        clip = MagicMock()
        clip.classify_raw.side_effect = RuntimeError("model load failed")
        with (
            patch(f"{MODULE}.ENHANCED_CLIP_AVAILABLE", True),
            patch(f"{MODULE}.CLIP_CACHE_AVAILABLE", False),
            patch(f"{MODULE}.get_clip_classifier", return_value=clip),
        ):
            org._run_clip_signal(Path("/pics/img.png"))
        assert "clip_description" not in org._last_file_state

    def test_per_file_results_cached(self, organizer: ContentOrganizer) -> None:
        org = self._vision_organizer(organizer)
        clip = MagicMock()
        clip.classify_raw.return_value = [(NATURE_PROMPT, 0.5)]
        with (
            patch(f"{MODULE}.ENHANCED_CLIP_AVAILABLE", True),
            patch(f"{MODULE}.CLIP_CACHE_AVAILABLE", False),
            patch(f"{MODULE}.get_clip_classifier", return_value=clip),
        ):
            org._run_clip_signal(Path("/pics/img.png"))
            org._run_clip_signal(Path("/pics/img.png"))
        assert clip.classify_raw.call_count == 1


class TestStashDecisionStateSceneDescription:
    """A probe-detected scene describes itself from its calibrated
    P(class), overriding the zero-shot CLIP label's softmax-floor score."""

    @staticmethod
    def _score(signal_name: str, evidence: dict, confidence: float = 0.9) -> SimpleNamespace:
        return SimpleNamespace(
            signal_name=signal_name,
            category="media",
            subcategory="interiors_other",
            confidence=confidence,
            evidence=evidence,
        )

    def _decision(self, winning: list, scores: list) -> ClassificationDecision:
        # Duck-typed stand-in: _stash_decision_state only reads the fields
        # populated below, so a SimpleNamespace covers it without building a
        # full ClassificationDecision (company_name/people_names included).
        return cast(
            ClassificationDecision,
            SimpleNamespace(
                category="media",
                subcategory="interiors_other",
                schema_type="Room",
                confidence=0.85,
                margin=0.4,
                decision_state="committed",
                winning_signals=winning,
                all_scores=scores,
            ),
        )

    def test_scene_win_overrides_clip_floor(self, organizer: ContentOrganizer) -> None:
        # clip_vision listed first to prove the precedence is order-independent,
        # not merely first-write-wins on all_scores ordering.
        decision = self._decision(
            winning=["scene"],
            scores=[
                self._score("clip_vision", {"clip_label": "an interior room", "clip_score": 0.05}),
                self._score(
                    "scene",
                    {"scene_class": "interior", "scene_prob": 0.9991},
                    confidence=0.9991,
                ),
            ],
        )
        organizer._stash_decision_state(decision, scorer_label="unified")
        label, score = organizer._last_file_state["clip_description"]
        assert label == SCENE_DESCRIPTION_LABELS["interior"]
        assert score == pytest.approx(0.9991)

    def test_scene_not_winner_keeps_clip_label(self, organizer: ContentOrganizer) -> None:
        decision = self._decision(
            winning=["clip_vision"],
            scores=[
                self._score(
                    "scene", {"scene_class": "interior", "scene_prob": 0.72}, confidence=0.72
                ),
                self._score("clip_vision", {"clip_label": "food or a meal", "clip_score": 0.8}),
            ],
        )
        organizer._stash_decision_state(decision, scorer_label="unified")
        label, score = organizer._last_file_state["clip_description"]
        assert label == "food or a meal"
        assert score == pytest.approx(0.8)


class TestScreenshotSceneReroute:
    """Provenance reroute: a scene-class win on a screenshot-named file
    refiles under Media/Photos/Screenshots/* keeping the scene @type.

    Corroboration guard (P2 item 1): when SceneSignal is the *sole* winner its
    calibrated ~0.99 confidence inflates the decision margin past the
    low_margin gate even when all other signals score 1-12%.  A solo scene win
    on a screenshot-named file routes to the generic screenshots fallback
    instead of committing the scene-class bucket.  When another signal also
    voted for the winning (category, subcategory) the specific bucket applies.
    """

    SCREENSHOT_NAME = "Screenshot 2026-05-30 at 12.45.50 AM.png"
    PHOTO_NAME = "20240426_living_room.heic"

    @staticmethod
    def _ctx(name: str) -> FileContext:
        return FileContext(path=Path(f"/shots/{name}"), schema_type="ImageObject")

    @staticmethod
    def _decision(
        category: str = "media",
        subcategory: str = "interiors_other",
        schema_type: str = "Room",
        winning_signals: "list[str] | None" = None,
    ) -> ClassificationDecision:
        return ClassificationDecision(
            category=category,
            subcategory=subcategory,
            schema_type=schema_type,
            confidence=0.95,
            margin=0.5,
            winning_signals=winning_signals if winning_signals is not None else ["scene"],
            all_scores=[],
            company_name=None,
            people_names=[],
        )

    @pytest.mark.parametrize(
        ("subcategory", "rerouted"),
        sorted(SCREENSHOT_SCENE_SUBCATEGORY.items()),
    )
    def test_corroborated_scene_win_on_screenshot_reroutes(
        self, subcategory: str, rerouted: str
    ) -> None:
        # When a second signal also voted for the scene category the specific
        # screenshot subfolder applies (e.g. photos_screenshots_interiors).
        decision = ContentOrganizer._reroute_screenshot_scene(
            self._ctx(self.SCREENSHOT_NAME),
            self._decision(subcategory=subcategory, winning_signals=["scene", "clip_vision"]),
        )
        assert decision.subcategory == rerouted
        assert decision.category == "media"

    @pytest.mark.parametrize(
        "subcategory",
        sorted(SCREENSHOT_SCENE_SUBCATEGORY),
    )
    def test_solo_scene_win_on_screenshot_falls_back_to_generic(self, subcategory: str) -> None:
        # SceneSignal alone (no corroboration) on a screenshot-named file:
        # the probe's high confidence must not commit the scene-class bucket.
        # Routes to the generic screenshots fallback instead.
        decision = ContentOrganizer._reroute_screenshot_scene(
            self._ctx(self.SCREENSHOT_NAME),
            self._decision(subcategory=subcategory, winning_signals=["scene"]),
        )
        assert decision.subcategory == "photos_screenshots_other"
        assert decision.category == "media"

    def test_schema_type_kept_on_corroborated_reroute(self) -> None:
        # Content-first typing: the folder changes, the depicted-scene @type
        # does not (corroborated case uses the specific reroute).
        decision = ContentOrganizer._reroute_screenshot_scene(
            self._ctx(self.SCREENSHOT_NAME),
            self._decision(schema_type="Room", winning_signals=["scene", "clip_vision"]),
        )
        assert decision.subcategory == "photos_screenshots_interiors"
        assert decision.schema_type == "Room"

    def test_schema_type_kept_on_solo_fallback(self) -> None:
        # The @type is preserved even when falling back to the generic bucket.
        decision = ContentOrganizer._reroute_screenshot_scene(
            self._ctx(self.SCREENSHOT_NAME),
            self._decision(schema_type="Room", winning_signals=["scene"]),
        )
        assert decision.subcategory == "photos_screenshots_other"
        assert decision.schema_type == "Room"

    def test_non_screenshot_name_unchanged(self) -> None:
        decision = self._decision()
        assert (
            ContentOrganizer._reroute_screenshot_scene(self._ctx(self.PHOTO_NAME), decision)
            is decision
        )

    def test_graphic_win_on_screenshot_unchanged(self) -> None:
        # graphics_other is deliberately outside the reroute: the
        # graphic-vs-screenshot boundary belongs to the probe corpus.
        decision = self._decision(subcategory="graphics_other", schema_type="ImageObject")
        assert (
            ContentOrganizer._reroute_screenshot_scene(self._ctx(self.SCREENSHOT_NAME), decision)
            is decision
        )

    def test_non_media_category_unchanged(self) -> None:
        decision = self._decision(category="financial", subcategory="interiors_other")
        assert (
            ContentOrganizer._reroute_screenshot_scene(self._ctx(self.SCREENSHOT_NAME), decision)
            is decision
        )

    def test_reroute_map_covers_all_scene_targets_except_graphic(self) -> None:
        # Parity lock with SCENE_CATEGORY: adding a scene class without
        # deciding its screenshot reroute must fail here, not silently file
        # screenshots into Media/*.
        scene_targets = {sub for cls, (_cat, sub) in SCENE_CATEGORY.items() if cls != "graphic"}
        assert set(SCREENSHOT_SCENE_SUBCATEGORY) == scene_targets

    def test_unified_path_applies_reroute_when_corroborated(
        self, tmp_path: Path, mock_classifier: MagicMock
    ) -> None:
        # Wiring: _detect_file_category_unified returns the scene-specific
        # rerouted subcategory when signals are corroborated, and the
        # persisted decision snapshot matches it.
        org = ContentOrganizer(
            base_path=tmp_path, content_classifier=mock_classifier, scorer="unified"
        )
        corroborated = self._decision(winning_signals=["scene", "clip_vision"])
        stub_scorer = SimpleNamespace(classify=lambda ctx: corroborated)
        org._get_unified_scorer = lambda: cast(Scorer, stub_scorer)  # type: ignore[method-assign]
        result = org._detect_file_category_unified(Path(f"/shots/{self.SCREENSHOT_NAME}"))
        assert (result[0], result[1], result[2]) == (
            "media",
            "photos_screenshots_interiors",
            "Room",
        )
        snapshot = org._last_file_state["scoring_decision"]
        assert snapshot["decision"]["subcategory"] == "photos_screenshots_interiors"

    def test_unified_path_solo_scene_falls_back(
        self, tmp_path: Path, mock_classifier: MagicMock
    ) -> None:
        # Wiring: when SceneSignal is the sole winner the generic screenshots
        # bucket is committed, not the scene-class subfolder.
        org = ContentOrganizer(
            base_path=tmp_path, content_classifier=mock_classifier, scorer="unified"
        )
        solo = self._decision(winning_signals=["scene"])
        stub_scorer = SimpleNamespace(classify=lambda ctx: solo)
        org._get_unified_scorer = lambda: cast(Scorer, stub_scorer)  # type: ignore[method-assign]
        result = org._detect_file_category_unified(Path(f"/shots/{self.SCREENSHOT_NAME}"))
        assert (result[0], result[1]) == ("media", "photos_screenshots_other")
        snapshot = org._last_file_state["scoring_decision"]
        assert snapshot["decision"]["subcategory"] == "photos_screenshots_other"


class TestPeoplePhotoSubcategoryRefinement:
    """Generic photos_other wins refine to photos_social when the composition
    pass detected people (PhotoCompositionSignal's vote is in all_scores).
    Specific winners are never overridden by people presence.
    """

    @staticmethod
    def _people_score() -> CategoryScore:
        return CategoryScore(
            category="media",
            subcategory="photos_social",
            confidence=0.8,
            signal_name="photo_composition",
            evidence={},
        )

    @staticmethod
    def _decision(
        category: str = "media",
        subcategory: str = "photos_other",
        all_scores: "list[CategoryScore] | None" = None,
    ) -> ClassificationDecision:
        return ClassificationDecision(
            category=category,
            subcategory=subcategory,
            schema_type="ImageObject",
            confidence=0.92,
            margin=0.4,
            winning_signals=["media_heuristic", "mime_fallback"],
            all_scores=all_scores or [],
            company_name=None,
            people_names=[],
        )

    def test_generic_photo_with_people_vote_refines_to_social(self) -> None:
        decision = ContentOrganizer._refine_people_photo_subcategory(
            self._decision(all_scores=[self._people_score()])
        )
        assert (decision.category, decision.subcategory) == ("media", "photos_social")

    def test_generic_photo_without_people_vote_stays_other(self) -> None:
        decision = ContentOrganizer._refine_people_photo_subcategory(self._decision())
        assert decision.subcategory == "photos_other"

    def test_specific_subcategory_not_overridden_by_people(self) -> None:
        # People in a screenshot don't make it a social photo.
        decision = ContentOrganizer._refine_people_photo_subcategory(
            self._decision(
                subcategory="photos_screenshots_terminal",
                all_scores=[self._people_score()],
            )
        )
        assert decision.subcategory == "photos_screenshots_terminal"

    def test_non_media_winner_untouched(self) -> None:
        decision = ContentOrganizer._refine_people_photo_subcategory(
            self._decision(
                category="personal", subcategory="contacts", all_scores=[self._people_score()]
            )
        )
        assert (decision.category, decision.subcategory) == ("personal", "contacts")

    def test_other_signals_social_vote_does_not_refine(self) -> None:
        # Only the people detector's vote counts — a CLIP social label alone
        # (flat-softmax noise) must not rewrite the generic bucket.
        clip_social = CategoryScore(
            category="media",
            subcategory="photos_social",
            confidence=0.05,
            signal_name="clip_vision",
            evidence={},
        )
        decision = ContentOrganizer._refine_people_photo_subcategory(
            self._decision(all_scores=[clip_social])
        )
        assert decision.subcategory == "photos_other"

    def test_applied_in_unified_flow(self, tmp_path: Path, mock_classifier: MagicMock) -> None:
        org = ContentOrganizer(base_path=tmp_path, content_classifier=mock_classifier)
        org.enricher = MagicMock()
        org.enricher.detect_mime_type.return_value = "image/jpeg"
        refined = self._decision(all_scores=[self._people_score()])
        stub_scorer = SimpleNamespace(classify=lambda ctx: refined)
        org._get_unified_scorer = lambda: cast(Scorer, stub_scorer)  # type: ignore[method-assign]
        result = org._detect_file_category_unified(Path("/photos/love10.jpg"))
        assert (result[0], result[1]) == ("media", "photos_social")
        snapshot = org._last_file_state["scoring_decision"]
        assert snapshot["decision"]["subcategory"] == "photos_social"


# ------------------------------------------------------------------ #
# _cross_check_with_clip                                                #
# ------------------------------------------------------------------ #


class TestCrossCheckWithClip:
    def test_no_clip_signal_keeps_original(self, organizer: ContentOrganizer) -> None:
        organizer._run_clip_signal = MagicMock(  # type: ignore[method-assign]
            return_value=(None, 0.0)
        )
        result = organizer._cross_check_with_clip(
            Path("/pics/img.png"), None, "financial", "invoices", 100
        )
        assert result == ("financial", "invoices")

    def test_clip_outscores_sparse_text(self, organizer: ContentOrganizer) -> None:
        organizer._run_clip_signal = MagicMock(  # type: ignore[method-assign]
            return_value=(("media", "photos_nature"), 0.9)
        )
        result = organizer._cross_check_with_clip(
            Path("/pics/img.png"), None, "financial", "invoices", 0
        )
        assert result == ("media", "photos_nature")

    def test_long_text_survives_weak_clip(self, organizer: ContentOrganizer) -> None:
        organizer._run_clip_signal = MagicMock(  # type: ignore[method-assign]
            return_value=(("media", "photos_nature"), 0.2)
        )
        result = organizer._cross_check_with_clip(
            Path("/pics/img.png"), None, "financial", "invoices", _TEXT_LENGTH_FULL_CHARS
        )
        assert result == ("financial", "invoices")


# ------------------------------------------------------------------ #
# enhance_weak_image_classification                                     #
# ------------------------------------------------------------------ #


class TestEnhanceWeakImageClassification:
    def test_ocr_text_decides_when_clip_silent(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        organizer._run_clip_signal = MagicMock(  # type: ignore[method-assign]
            return_value=(None, 0.0)
        )
        organizer.ocr_available = True
        organizer.extract_text_from_image = MagicMock(  # type: ignore[method-assign]
            return_value="x" * 200
        )
        mock_classifier.classify_content.return_value = ("financial", "invoices", None, [])
        result = organizer.enhance_weak_image_classification(Path("/pics/statement.png"))
        assert result == ("financial", "invoices")

    def test_clip_decides_when_ocr_unavailable(self, organizer: ContentOrganizer) -> None:
        organizer._run_clip_signal = MagicMock(  # type: ignore[method-assign]
            return_value=(("media", "photos_nature"), 0.5)
        )
        organizer.ocr_available = False
        result = organizer.enhance_weak_image_classification(Path("/pics/img.png"))
        assert result == ("media", "photos_nature")

    def test_uncategorized_text_yields_none(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        organizer._run_clip_signal = MagicMock(  # type: ignore[method-assign]
            return_value=(None, 0.0)
        )
        organizer.ocr_available = True
        organizer.extract_text_from_image = MagicMock(  # type: ignore[method-assign]
            return_value="x" * 200
        )
        mock_classifier.classify_content.return_value = ("uncategorized", "other", None, [])
        assert organizer.enhance_weak_image_classification(Path("/pics/img.png")) is None

    def test_ocr_error_swallowed(self, organizer: ContentOrganizer) -> None:
        organizer._run_clip_signal = MagicMock(  # type: ignore[method-assign]
            return_value=(None, 0.0)
        )
        organizer.ocr_available = True
        organizer.extract_text_from_image = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("ocr died")
        )
        assert organizer.enhance_weak_image_classification(Path("/pics/img.png")) is None


# ------------------------------------------------------------------ #
# extract_text dispatch                                                 #
# ------------------------------------------------------------------ #


class TestExtractTextDispatch:
    def _wired_organizer(self, organizer: ContentOrganizer, mime: str | None) -> ContentOrganizer:
        organizer.enricher = MagicMock()
        organizer.enricher.detect_mime_type.return_value = mime
        organizer.text_extractor = MagicMock()
        organizer.ocr_available = True
        return organizer

    def test_image_reuses_cached_ocr_text(self, organizer: ContentOrganizer) -> None:
        org = self._wired_organizer(organizer, "image/png")
        org._last_file_ocr_text = "cached ocr text"
        assert org.extract_text(Path("/pics/img.png")) == "cached ocr text"
        org.text_extractor.extract_text_from_image.assert_not_called()

    def test_image_without_cache_calls_extractor(self, organizer: ContentOrganizer) -> None:
        org = self._wired_organizer(organizer, "image/png")
        org.text_extractor.extract_text_from_image.return_value = "fresh"
        assert org.extract_text(Path("/pics/img.png")) == "fresh"

    def test_image_without_ocr_returns_empty(self, organizer: ContentOrganizer) -> None:
        org = self._wired_organizer(organizer, "image/png")
        org.ocr_available = False
        assert org.extract_text(Path("/pics/img.png")) == ""
        org.text_extractor.extract_text_from_image.assert_not_called()

    def test_pdf_routes_to_pdf_extractor(self, organizer: ContentOrganizer) -> None:
        org = self._wired_organizer(organizer, "application/pdf")
        org.text_extractor.extract_text_from_pdf.return_value = "pdf text"
        assert org.extract_text(Path("/docs/report.pdf")) == "pdf text"

    def test_pdf_without_ocr_returns_empty(self, organizer: ContentOrganizer) -> None:
        org = self._wired_organizer(organizer, "application/pdf")
        org.ocr_available = False
        assert org.extract_text(Path("/docs/report.pdf")) == ""

    def test_docx_routes_by_extension(self, organizer: ContentOrganizer) -> None:
        org = self._wired_organizer(organizer, None)
        org.text_extractor.extract_text_from_docx.return_value = "docx text"
        assert org.extract_text(Path("/docs/letter.docx")) == "docx text"

    def test_xlsx_routes_by_extension(self, organizer: ContentOrganizer) -> None:
        org = self._wired_organizer(organizer, None)
        org.text_extractor.extract_text_from_xlsx.return_value = "sheet text"
        assert org.extract_text(Path("/docs/budget.xlsx")) == "sheet text"

    def test_other_types_use_generic_extractor(self, organizer: ContentOrganizer) -> None:
        org = self._wired_organizer(organizer, "text/plain")
        org.text_extractor.extract_text.return_value = "plain text"
        path = Path("/docs/notes.txt")
        assert org.extract_text(path) == "plain text"
        org.text_extractor.extract_text.assert_called_once_with(path, "text/plain")

    def test_no_extractor_returns_empty(self, organizer: ContentOrganizer) -> None:
        org = self._wired_organizer(organizer, "text/plain")
        org.text_extractor = None
        assert org.extract_text(Path("/docs/notes.txt")) == ""


# ------------------------------------------------------------------ #
# _mime_result_to_content_category (last-resort format translation)     #
# ------------------------------------------------------------------ #


class TestMimeResultToContentCategory:
    @pytest.mark.parametrize(
        "mime_result,expected",
        [
            (("images", "graphics"), ("media", "graphics_other")),
            (("images", "photos"), ("media", "photos_other")),
            (("images", "screenshots"), ("media", "photos_screenshots")),
            (("media", "videos"), ("media", "videos_other")),
            (("media", "music"), ("media", "audio_music")),
            (("media", "audio"), ("media", "audio_other")),
            (("fonts", "truetype"), ("fonts", "truetype")),
            (("software", "packages"), ("technical", "software_packages")),
            (("code", "python"), ("technical", "other")),
            (("code", "dart"), ("technical", "other")),
            (("code", "web"), ("technical", "web")),
            (("data", "json"), ("technical", "data")),
            (("data", "config"), ("technical", "config")),
            (("research", "papers"), ("research", "other")),
        ],
    )
    def test_translates_into_content_taxonomy(self, mime_result: tuple, expected: tuple) -> None:
        assert _mime_result_to_content_category(*mime_result) == expected

    @pytest.mark.parametrize(
        "mime_result",
        [("documents", "pdf"), ("archives", "zip"), ("other", "other")],
    )
    def test_no_content_home_returns_none(self, mime_result: tuple) -> None:
        # Text-classifiable / homeless formats stay uncategorized.
        assert _mime_result_to_content_category(*mime_result) is None

    def test_all_targets_resolve_in_content_taxonomy(
        self, tmp_path: Path, mock_classifier: MagicMock
    ) -> None:
        # Every translated (category, subcategory) must produce a real path (not
        # the Uncategorized default) via get_destination_path.
        org = ContentOrganizer(base_path=tmp_path, content_classifier=mock_classifier)
        for mime_result in [
            ("images", "graphics"),
            ("images", "photos"),
            ("images", "screenshots"),
            ("media", "videos"),
            ("media", "music"),
            ("media", "audio"),
            ("fonts", "truetype"),
            ("software", "packages"),
            ("code", "python"),
            ("data", "json"),
            ("research", "papers"),
        ]:
            translated = _mime_result_to_content_category(*mime_result)
            assert translated is not None
            dest = org.get_destination_path(Path("/x/f.bin"), translated[0], translated[1])
            assert "Uncategorized" not in str(dest)


# ------------------------------------------------------------------ #
# _classify_screenshot_ocr (Priority 4.5)                               #
# ------------------------------------------------------------------ #


class TestClassifyScreenshotOcr:
    SCREENSHOT = Path("/pics/Screenshot 2026-01-01 at 09.00.png")

    def test_non_screenshot_returns_none(self, organizer: ContentOrganizer) -> None:
        result = organizer._classify_screenshot_ocr(Path("/pics/vacation.png"), "ImageObject", {})
        assert result is None

    def test_structured_renamed_screenshot_excluded(self, organizer: ContentOrganizer) -> None:
        # Already-classified names ("browser_*") bypass this tier even though
        # "screenshot" appears in the stem.
        result = organizer._classify_screenshot_ocr(
            Path("/pics/browser_screenshot_1.png"), "ImageObject", {}
        )
        assert result is None

    def test_ocr_subclass_accepted(self, organizer: ContentOrganizer) -> None:
        ocr = MagicMock(return_value=("dashboard", 0.25, {}, "cpu usage graphs"))
        with patch(f"{MODULE}._shared_classify_by_ocr", ocr):
            result = organizer._classify_screenshot_ocr(self.SCREENSHOT, "ImageObject", {})
        assert result is not None
        assert result[0] == "media"
        assert result[1] == "photos_screenshots_dashboard"
        # OCR text cached for downstream reuse
        assert organizer._last_file_ocr_text == "cpu usage graphs"

    def test_low_confidence_ocr_falls_back(self, organizer: ContentOrganizer) -> None:
        ocr = MagicMock(return_value=("dashboard", 0.05, {}, "noise"))
        organizer.enhance_weak_image_classification = MagicMock(  # type: ignore[method-assign]
            return_value=None
        )
        with patch(f"{MODULE}._shared_classify_by_ocr", ocr):
            result = organizer._classify_screenshot_ocr(self.SCREENSHOT, "ImageObject", {})
        assert result is not None
        assert result[1] == "photos_screenshots_other"

    def test_ocr_non_screenshot_category_reclassifies(self, organizer: ContentOrganizer) -> None:
        ocr = MagicMock(return_value=("financial_invoices", 0.5, {}, "invoice total due"))
        with patch(f"{MODULE}._shared_classify_by_ocr", ocr):
            result = organizer._classify_screenshot_ocr(self.SCREENSHOT, "ImageObject", {})
        assert result is not None
        assert result[0] == "financial"
        assert result[1] == "financial_invoices"

    def test_clip_reclassifies_non_media(self, organizer: ContentOrganizer) -> None:
        organizer.enhance_weak_image_classification = MagicMock(  # type: ignore[method-assign]
            return_value=("game_assets", "sprites")
        )
        with patch(f"{MODULE}._shared_classify_by_ocr", MagicMock(return_value=None)):
            result = organizer._classify_screenshot_ocr(self.SCREENSHOT, "ImageObject", {})
        assert result is not None
        assert (result[0], result[1]) == ("game_assets", "sprites")

    def test_clip_screenshot_subcategory_accepted(self, organizer: ContentOrganizer) -> None:
        organizer.enhance_weak_image_classification = MagicMock(  # type: ignore[method-assign]
            return_value=("media", "photos_screenshots_terminal")
        )
        with patch(f"{MODULE}._shared_classify_by_ocr", MagicMock(return_value=None)):
            result = organizer._classify_screenshot_ocr(self.SCREENSHOT, "ImageObject", {})
        assert result is not None
        assert (result[0], result[1]) == ("media", "photos_screenshots_terminal")

    def test_unhelpful_clip_falls_back_to_other(self, organizer: ContentOrganizer) -> None:
        # A generic media guess (not a screenshot subfolder) is not a
        # reclassification — keep the generic screenshots folder.
        organizer.enhance_weak_image_classification = MagicMock(  # type: ignore[method-assign]
            return_value=("media", "photos_nature")
        )
        with patch(f"{MODULE}._shared_classify_by_ocr", MagicMock(return_value=None)):
            result = organizer._classify_screenshot_ocr(self.SCREENSHOT, "ImageObject", {})
        assert result is not None
        assert (result[0], result[1]) == ("media", "photos_screenshots_other")


# ------------------------------------------------------------------ #
# _classify_photo_composition (Priority 5)                              #
# ------------------------------------------------------------------ #


class TestClassifyPhotoComposition:
    def _vision_organizer(
        self, organizer: ContentOrganizer, has_people: bool, is_property: bool
    ) -> ContentOrganizer:
        organizer.image_analyzer = MagicMock()
        organizer.image_analyzer.vision_available = True
        organizer.image_analyzer.analyze_for_organization.return_value = (
            has_people,
            is_property,
            {},
        )
        return organizer

    def test_vision_unavailable_returns_none(self, organizer: ContentOrganizer) -> None:
        assert (
            organizer._classify_photo_composition(Path("/pics/img.jpg"), "ImageObject", {}) is None
        )

    def test_non_image_returns_none(self, organizer: ContentOrganizer) -> None:
        org = self._vision_organizer(organizer, True, False)
        assert (
            org._classify_photo_composition(Path("/docs/report.pdf"), "DigitalDocument", {}) is None
        )

    def test_people_route_to_social(self, organizer: ContentOrganizer) -> None:
        org = self._vision_organizer(organizer, True, False)
        result = org._classify_photo_composition(Path("/pics/img.jpg"), "ImageObject", {})
        assert result is not None
        assert (result[0], result[1]) == ("media", "photos_social")

    def test_interior_routes_to_property_management(self, organizer: ContentOrganizer) -> None:
        org = self._vision_organizer(organizer, False, True)
        result = org._classify_photo_composition(Path("/pics/img.jpg"), "ImageObject", {})
        assert result is not None
        assert (result[0], result[1]) == ("property_management", "other")

    def test_no_composition_match_returns_none(self, organizer: ContentOrganizer) -> None:
        org = self._vision_organizer(organizer, False, False)
        assert org._classify_photo_composition(Path("/pics/img.jpg"), "ImageObject", {}) is None


# ------------------------------------------------------------------ #
# _classify_by_content_and_kie (Priority 6)                             #
# ------------------------------------------------------------------ #


class TestClassifyByContentAndKie:
    def test_kie_classification_preferred(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        organizer.extract_text = MagicMock(return_value="x" * 100)  # type: ignore[method-assign]
        organizer._last_file_state["kie_result"] = {"total": "42.00"}
        mock_classifier.classify_with_kie.return_value = ("financial", "invoices", "Acme", [])
        result = organizer._classify_by_content_and_kie(
            Path("/docs/inv.pdf"), "DigitalDocument", {}
        )
        assert (result[0], result[1]) == ("financial", "invoices")
        assert result[4] == "Acme"
        mock_classifier.classify_content.assert_not_called()

    def test_falls_back_to_content_classifier(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        organizer.extract_text = MagicMock(return_value="x" * 100)  # type: ignore[method-assign]
        mock_classifier.classify_content.return_value = ("legal", "contracts", None, [])
        result = organizer._classify_by_content_and_kie(
            Path("/docs/nda.pdf"), "DigitalDocument", {}
        )
        assert (result[0], result[1]) == ("legal", "contracts")
        assert result[3] == "x" * 100  # extracted text propagated

    def test_no_text_classifies_by_filename(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        organizer.extract_text = MagicMock(return_value="")  # type: ignore[method-assign]
        mock_classifier.classify_content.return_value = ("financial", "invoices", None, [])
        organizer._classify_by_content_and_kie(Path("/docs/invoice.pdf"), "DigitalDocument", {})
        args = mock_classifier.classify_content.call_args[0]
        assert args == ("", "invoice.pdf")

    def test_uncategorized_image_enhanced_as_last_resort(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        # Point C: uncategorized images get one more CLIP+OCR attempt.
        organizer.extract_text = MagicMock(return_value="x" * 100)  # type: ignore[method-assign]
        mock_classifier.classify_content.return_value = ("uncategorized", "other", None, [])
        organizer.enhance_weak_image_classification = MagicMock(  # type: ignore[method-assign]
            return_value=("technical", "data_visualization")
        )
        result = organizer._classify_by_content_and_kie(Path("/pics/chart.png"), "ImageObject", {})
        assert (result[0], result[1]) == ("technical", "data_visualization")
        assert result[3] == "x" * 100


# ------------------------------------------------------------------ #
# get_destination_path — entity nesting and collision handling          #
# ------------------------------------------------------------------ #


class TestGetDestinationPathNesting:
    def test_meeting_notes_nested_under_company(self, organizer: ContentOrganizer) -> None:
        result = organizer.get_destination_path(
            file_path=Path("/docs/notes.pdf"),
            category="organization",
            subcategory="meeting_notes",
            company_name="Acme Corp",
        )
        assert "Acme Corp/Meeting Notes" in str(result)

    def test_clients_nested_under_clients_folder(self, organizer: ContentOrganizer) -> None:
        result = organizer.get_destination_path(
            file_path=Path("/docs/sow.pdf"),
            category="organization",
            subcategory="clients",
            company_name="Acme Corp",
        )
        assert "Clients" in str(result)
        assert "Acme Corp" in str(result)

    def test_invalid_company_name_omitted(
        self, organizer: ContentOrganizer, mock_classifier: MagicMock
    ) -> None:
        mock_classifier.sanitize_company_name.side_effect = lambda name: ""
        result = organizer.get_destination_path(
            file_path=Path("/docs/invoice.pdf"),
            category="organization",
            subcategory="vendors",
            company_name="please remit payment to",
        )
        assert "please remit payment to" not in str(result)

    def test_legacy_business_clients_nested(self, organizer: ContentOrganizer) -> None:
        result = organizer.get_destination_path(
            file_path=Path("/docs/proposal.pdf"),
            category="business",
            subcategory="clients",
            company_name="Acme Corp",
        )
        assert "Acme Corp" in str(result)

    def test_location_organization(self, tmp_path: Path, mock_classifier: MagicMock) -> None:
        org = ContentOrganizer(
            base_path=tmp_path,
            content_classifier=mock_classifier,
            organize_by_location=True,
        )
        result = org.get_destination_path(
            file_path=Path("/pics/img.jpg"),
            category="media",
            subcategory="photos_other",
            image_metadata={"location_name": "Austin, TX, USA"},
        )
        assert "Photos/Locations/Austin" in str(result)

    def test_duplicate_filename_gets_timestamp_suffix(
        self, organizer: ContentOrganizer, tmp_path: Path
    ) -> None:
        first = organizer.get_destination_path(
            file_path=Path("/src/report.pdf"),
            category="financial",
            subcategory="invoices",
        )
        first.write_bytes(b"existing")
        second = organizer.get_destination_path(
            file_path=Path("/src/report.pdf"),
            category="financial",
            subcategory="invoices",
        )
        assert second != first
        assert second.parent == first.parent
        assert second.name.startswith("report_")
        assert second.suffix == ".pdf"

    def test_three_level_media_nesting(self, organizer: ContentOrganizer) -> None:
        result = organizer.get_destination_path(
            file_path=Path("/pics/shot.png"),
            category="media",
            subcategory="photos_screenshots_browser",
        )
        assert "Screenshots/Browser" in str(result)

    def test_legal_litigation_path(self, organizer: ContentOrganizer) -> None:
        result = organizer.get_destination_path(
            file_path=Path("/docs/notice_of_setting.pdf"),
            category="legal",
            subcategory="litigation",
        )
        assert "Legal/Litigation" in str(result)
