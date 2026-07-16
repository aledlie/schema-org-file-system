"""Golden integration tests for the unified scorer (UNIFIED_SCORING_PLAN §8.3).

Runs the REAL registry (all 15 signals), REAL ContentClassifier keyword
vocabularies, and REAL Scorer aggregation over synthetic FileContext
extraction providers (fake OCR/CLIP/KIE payloads — no models, no disk I/O
beyond filenames). Each golden asserts the chosen (category, subcategory),
a minimum decision margin ("right answer, fragile reasons" detector), and —
for person-bearing fixtures — the emitted people_names (Option C graph-edge
parity).

The §3.3 emergent behaviors each fixture group enforces:
- legal-outscores-personal replaces the hard person-tier veto,
- text-outscores-game subsumes _ocr_document_override,
- shared (cat, sub) accumulation fixes PDF/PNG format drift,
- MimeFallback (0.3) cannot override content evidence.
"""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import pytest

from shared.constants import GAME_SPRITE_KEYWORDS
from shared.ocr_classifier import SCREENSHOT_KEYWORDS
from src.classifiers.content_classifier import ContentClassifier
from src.organizers.category_config import CONTENT_CATEGORY_PATHS
from src.scoring.context import FileContext
from src.scoring.registry import build_default_signals
from src.scoring.scorer import Scorer
from src.scoring.signals.screenshot_ocr import ScreenshotOcrSignal
from src.scoring.types import ClassificationDecision

# --------------------------------------------------------------------------- #
# Harness                                                                      #
# --------------------------------------------------------------------------- #

OCR_CONFIDENCE_STRONG = 0.9
COMMITTED = "committed"


def build_screenshots_dict() -> Dict[str, Any]:
    """Replicate ContentOrganizer.__init__'s screenshots-taxonomy extension."""
    screenshots = deepcopy(CONTENT_CATEGORY_PATHS)["media"]["photos"]["screenshots"]
    for key in SCREENSHOT_KEYWORDS:
        if key not in screenshots:
            folder = key.replace("_", " ").title().replace(" ", "")
            screenshots[key] = f"Media/Photos/Screenshots/{folder}"
    return screenshots


@dataclass
class GoldenCase:
    """One labeled fixture: synthetic extraction inputs + expected decision."""

    name: str
    filename: str
    schema_type: str
    expected: Tuple[str, str]
    mime_type: Optional[str] = None
    text: Optional[str] = None  # non-image text extraction
    ocr_text: Optional[str] = None  # image OCR extraction
    ocr_confidence: float = OCR_CONFIDENCE_STRONG
    ocr_language: str = "en"
    clip: Optional[Dict[str, float]] = None
    image_metadata: Optional[Dict[str, Any]] = None
    kie_fields: Optional[Dict[str, List[Tuple[str, float]]]] = None
    screenshot_ocr: Optional[Tuple[str, float, Dict[str, float], str]] = None
    min_margin: float = 0.05
    expected_state: str = COMMITTED
    expected_schema_type: Optional[str] = None
    people_contains: Optional[str] = None
    company_contains: Optional[str] = None

    def context(self) -> FileContext:
        ocr = None
        if self.ocr_text is not None:
            ocr = SimpleNamespace(
                text=self.ocr_text,
                confidence=self.ocr_confidence,
                language=self.ocr_language,
            )
        kie = None
        if self.kie_fields is not None:
            kie = SimpleNamespace(
                fields={
                    cls: [
                        SimpleNamespace(value=value, confidence=confidence)
                        for value, confidence in entries
                    ]
                    for cls, entries in self.kie_fields.items()
                }
            )
        return FileContext(
            path=Path("/golden") / self.filename,
            schema_type=self.schema_type,
            mime_type=self.mime_type,
            text_provider=(lambda _path: self.text or "") if self.text is not None else None,
            ocr_provider=(lambda _path: ocr) if ocr is not None else None,
            clip_provider=(lambda _path: self.clip) if self.clip is not None else None,
            image_metadata_provider=(
                (lambda _path: self.image_metadata) if self.image_metadata is not None else None
            ),
            kie_provider=(lambda _path: kie) if kie is not None else None,
        )


def golden_scorer(
    screenshot_ocr_result: Optional[Tuple[str, float, Dict[str, float], str]] = None,
) -> Scorer:
    classifier = ContentClassifier()
    screenshots_dict = build_screenshots_dict()
    signals = build_default_signals(
        classifier=classifier,
        screenshot_classifier=classifier,
        image_analyzer=None,  # PhotoCompositionSignal gates itself off
        category_paths={"media": {"photos": {"screenshots": screenshots_dict}}},
        game_sprite_keywords=list(GAME_SPRITE_KEYWORDS),
    )
    if screenshot_ocr_result is not None:
        signals = [
            (
                ScreenshotOcrSignal(
                    screenshot_classifier=classifier,
                    screenshots_dict=screenshots_dict,
                    ocr_classify=lambda _path, content_classifier=None: screenshot_ocr_result,
                )
                if signal.name == "screenshot_ocr"
                else signal
            )
            for signal in signals
        ]
    return Scorer(signals)


def classify(case: GoldenCase) -> ClassificationDecision:
    return golden_scorer(case.screenshot_ocr).classify(case.context())


# --------------------------------------------------------------------------- #
# Fixture corpus (§8.3 table)                                                  #
# --------------------------------------------------------------------------- #

VENDOR_INVOICE_TEXT = (
    "INVOICE #2041 from Morning Train LLC. Purchase order PO-118 attached. "
    "Bill to: Integrity Studio. Payment terms net 30; supplier vendor id 88. "
    "Remit payment upon receipt of this invoice."
)

HEALTHCARE_LETTER_TEXT = (
    "Leora Home Health medical center patient summary. The clinic physicians "
    "reviewed your lab results and prescription refills. Contact the hospital "
    "pharmacy for medication questions. Insurance claim filed under Medicare."
)

GOVERNMENT_NOTICE_TEXT = (
    "Department of Public Safety, State of Texas. This government agency "
    "notice concerns your records. The bureau and commission require a "
    "response within 30 days. Lone Star Compliance LLC administers this "
    "government program for the agency."
)

UNIVERSITY_LETTER_TEXT = (
    "University of Texas registrar enrollment confirmation. Your transcript "
    "and degree audit for the semester are attached. Financial aid and "
    "tuition details follow. Course registration opens Monday. "
    "Office of the Registrar, University of Texas."
)

OFFER_LETTER_TEXT = (
    "Offer letter and employment agreement from Acme Corp. Payroll and "
    "benefits enrollment begin on your start date. Human resources will "
    "collect your W-2 forms. Employee id issued by HR department."
)

COURT_NOTICE_TEXT = (
    "NOTICE OF COURT SETTING. Cause No 2026-441 on the docket. "
    "Plaintiff: Mr. John Doe vs defendant. A hearing is set before the "
    "judicial officer. District Clerk contact info — phone: 512-555-0100, "
    "email: clerk@court.gov, address: 100 Main St. Contact the clerk."
)

COURT_MOTION_TEXT = (
    "Motion for continuance, Cause No 2026-512. Petitioner: Ms. Jane Smith "
    "and respondent appear before the court. The hearing docket lists the "
    "plaintiff and defendant. Clerk contact — phone: 512-555-0111, "
    "email: filings@court.gov."
)

BLOODWORK_OCR_TEXT = (
    "Laboratory lab results for patient. Blood panel diagnosis reviewed by "
    "doctor at the hospital clinic. Prescription and treatment plan enclosed. "
    "Medical record number 4417."
)

RESEARCH_PAPER_TEXT = (
    "Abstract. This research paper presents a thesis on distributed systems. "
    "We survey prior dissertation work from the university literature and "
    "publish our findings. Keywords: research, thesis, paper."
)

RESUME_TEXT = (
    "Jane Smith. Senior engineer resume. Contact: phone: 512-555-0199, "
    "email: jane.smith@example.com, linkedin.com/in/janesmith. "
    "Employment history and references available."
)

CV_TEXT = (
    "Curriculum vitae — John Doe. Contact information: phone: 415-555-0143, "
    "email: john.doe@example.com, address: 42 Oak Lane. Employment history, "
    "publications, and references follow."
)

INVOICE_OCR_TEXT = (
    "Invoice from Acme Corp. Total amount due $412.00 by invoice date "
    "2026-06-30. Billing statement and payment details enclosed."
)

GOLDEN_CASES = [
    # ---- Group 1: org-named PDFs (person/org confusion) ------------------- #
    GoldenCase(
        # Neutral filename: the brand-vs-person confusion under test is a
        # CONTENT phenomenon ("Morning Train" reads person-ish); a filename
        # containing "agreement" would legitimately fire the legal rule first.
        name="org_vendor_invoice_brand_name",
        filename="morning-train-2041.pdf",
        schema_type="DigitalDocument",
        mime_type="application/pdf",
        text=VENDOR_INVOICE_TEXT,
        expected=("organization", "vendors"),
        company_contains="Morning Train",
    ),
    GoldenCase(
        name="org_healthcare_letter",
        filename="care-summary.pdf",
        schema_type="DigitalDocument",
        mime_type="application/pdf",
        text=HEALTHCARE_LETTER_TEXT,
        expected=("organization", "healthcare"),
        company_contains="Leora",
    ),
    GoldenCase(
        name="org_government_notice",
        filename="dps-notice.pdf",
        schema_type="DigitalDocument",
        mime_type="application/pdf",
        text=GOVERNMENT_NOTICE_TEXT,
        expected=("organization", "government"),
    ),
    GoldenCase(
        # No legal-suffix org name in the text → the org signal (which
        # requires an extractable company) stays silent and the keyword
        # taxonomy files it under education/records — the sensible
        # content-only outcome (transcript/degree/enrollment vocabulary).
        name="university_letter_content_only",
        filename="registrar-letter.pdf",
        schema_type="DigitalDocument",
        mime_type="application/pdf",
        text=UNIVERSITY_LETTER_TEXT,
        expected=("education", "records"),
    ),
    GoldenCase(
        name="org_employer_offer_letter",
        filename="offer-letter.pdf",
        schema_type="DigitalDocument",
        mime_type="application/pdf",
        text=OFFER_LETTER_TEXT,
        expected=("organization", "employers"),
        company_contains="Acme",
    ),
    # ---- Group 4: court notices (legal outscores personal) ---------------- #
    GoldenCase(
        name="legal_court_notice_clerk_contacts",
        filename="notice-of-ct-setting.pdf",
        schema_type="DigitalDocument",
        mime_type="application/pdf",
        text=COURT_NOTICE_TEXT,
        expected=("legal", "litigation"),
        people_contains="John Doe",
    ),
    GoldenCase(
        name="legal_court_motion_clerk_contacts",
        filename="motion-for-continuance.pdf",
        schema_type="DigitalDocument",
        mime_type="application/pdf",
        text=COURT_MOTION_TEXT,
        expected=("legal", "litigation"),
        people_contains="Jane Smith",
    ),
    # ---- Group 5: game-keyword collisions (text outscores game) ----------- #
    GoldenCase(
        name="bloodwork_ocr_beats_game_keyword",
        filename="medellin_bloodwork.png",
        schema_type="ImageObject",
        mime_type="image/png",
        ocr_text=BLOODWORK_OCR_TEXT,
        expected=("medical", "records"),
    ),
    GoldenCase(
        # Filename game rule (sprites) + game-asset keyword (textures) both
        # fire; with no document text to compete the file stays a game asset.
        # The filename rule's `sprites` outweighs the keyword tier's
        # `textures` — subcat granularity is a Phase-3 calibration nit.
        name="texture_without_document_text_stays_game",
        filename="stone_texture_atlas.png",
        schema_type="ImageObject",
        mime_type="image/png",
        ocr_text="",  # OCR ran, found nothing
        expected=("game_assets", "sprites"),
        min_margin=0.01,
    ),
    # ---- Group 3: academic PDFs (content-only + prefixed control) --------- #
    GoldenCase(
        # Neutral filename ("survey" would fire the questionnaire rule);
        # content-only academic detection is the §1 residual gap — the
        # keyword taxonomy's best current answer is education/research.
        name="research_content_only_routes_education_research",
        filename="consensus-methods-2026.pdf",
        schema_type="DigitalDocument",
        mime_type="application/pdf",
        text=RESEARCH_PAPER_TEXT,
        expected=("education", "research"),
    ),
    GoldenCase(
        name="research_content_only_second_sample",
        filename="ml-evaluation-notes-v2.pdf",
        schema_type="DigitalDocument",
        mime_type="application/pdf",
        text=RESEARCH_PAPER_TEXT + " Dissertation committee approved.",
        expected=("education", "research"),
    ),
    GoldenCase(
        name="research_prefixed_control_ssrn",
        filename="ssrn-4123456.pdf",
        schema_type="DigitalDocument",
        mime_type="application/pdf",
        expected=("research", "ssrn"),
        expected_schema_type="ScholarlyArticle",
    ),
    # ---- Group 7: renamed game assets -------------------------------------- #
    GoldenCase(
        name="sprite_numbered_frame",
        filename="frame_12.png",
        schema_type="ImageObject",
        mime_type="image/png",
        expected=("game_assets", "sprites"),
    ),
    GoldenCase(
        name="sprite_weapon_variant",
        filename="2h_axe_3.png",
        schema_type="ImageObject",
        mime_type="image/png",
        expected=("game_assets", "sprites"),
    ),
    GoldenCase(
        name="sprite_grey_variant",
        filename="10_grey.png",
        schema_type="ImageObject",
        mime_type="image/png",
        expected=("game_assets", "sprites"),
    ),
    # ---- Group 9: resumes/CVs (Option C people edges) ---------------------- #
    GoldenCase(
        name="resume_files_personal_contacts",
        filename="Jane_Smith_Resume.pdf",
        schema_type="DigitalDocument",
        mime_type="application/pdf",
        text=RESUME_TEXT,
        expected=("personal", "contacts"),
        people_contains="Jane Smith",
    ),
    GoldenCase(
        # KNOWN GAP (Phase-3 calibration target): without a filename-rule
        # match, personal/contacts (personal_doc 0.81) and
        # personal/employment (text_content 0.71) compete within the same
        # category and the margin lands just under MIN_DECISION_MARGIN —
        # the file routes to the fallback bucket. Same-category subcat
        # competition should likely aggregate, not split (§11 OQ).
        name="cv_without_filename_rule_is_low_margin",
        filename="john-doe-cv.pdf",
        schema_type="DigitalDocument",
        mime_type="application/pdf",
        text=CV_TEXT,
        expected=("uncategorized", "other"),
        expected_state="low_margin",
        min_margin=0.0,
    ),
    # ---- Group 10: invoices (KIE) ------------------------------------------ #
    GoldenCase(
        name="kie_invoice_vendor_and_amount",
        filename="scan_0021.png",
        schema_type="ImageObject",
        mime_type="image/png",
        ocr_text=INVOICE_OCR_TEXT,
        kie_fields={
            "vendor_name": [("Acme Corp", 0.92)],
            "total_amount": [("$412.00", 0.88)],
        },
        expected=("financial", "invoices"),
        company_contains="Acme",
    ),
    GoldenCase(
        name="kie_invoice_vendor_and_date",
        filename="scan_0022.png",
        schema_type="ImageObject",
        mime_type="image/png",
        ocr_text=INVOICE_OCR_TEXT,
        kie_fields={
            "vendor_name": [("Acme Corp", 0.9)],
            "invoice_date": [("2026-06-30", 0.86)],
        },
        expected=("financial", "invoices"),
        company_contains="Acme",
    ),
    GoldenCase(
        # Name dodges BOTH legacy naming traps shared by the two engines:
        # the sprite regex ^[a-z]+_\d+$ ("scan_0023") and the "Hyphenated
        # asset" filename rule ("invoice-page-march") — §1 naming
        # brittleness, §11 OQ#5 calibration markers.
        name="kie_insufficient_falls_back_to_text",
        filename="billing-page-2.png",
        schema_type="ImageObject",
        mime_type="image/png",
        ocr_text=INVOICE_OCR_TEXT + " Amount due and account balance summary enclosed below.",
        kie_fields={"vendor_name": [("Acme Corp", 0.9)]},  # no amount/date
        expected=("financial", "invoices"),
    ),
    # ---- Group 11: generic media ------------------------------------------- #
    GoldenCase(
        # "meeting_*" would fire the meeting-notes filename rule (legacy
        # parity: tier 0b files it business/ too), so use a screen capture.
        name="media_video_screencast",
        filename="screen_capture_04.mp4",
        schema_type="VideoObject",
        mime_type="video/mp4",
        expected=("media", "videos_screencasts"),
    ),
    GoldenCase(
        # Every .mp3 hits the filename module's "Audio file" rule first —
        # in BOTH engines — so generic audio files land in audio_other;
        # the heuristic's podcast refinement is a Phase-3 calibration item.
        name="media_audio_filename_rule_wins",
        filename="podcast_episode_12.mp3",
        schema_type="AudioObject",
        mime_type="audio/mpeg",
        expected=("media", "audio_other"),
    ),
    GoldenCase(
        # Hyphenated name: "IMG_2043" matches the sprite regex ^[a-z]+_\d+$
        # in BOTH engines (pre-existing legacy bug, see §1 naming
        # brittleness) — the GPS-travel routing under test needs a camera
        # name that dodges it.
        name="media_photo_gps_travel",
        filename="img-vacation-004.jpg",
        schema_type="ImageObject",
        mime_type="image/jpeg",
        ocr_text="",
        image_metadata={"gps_coordinates": (30.2672, -97.7431)},
        expected=("media", "photos_travel"),
    ),
]

SCREENSHOT_CASES = [
    GoldenCase(
        name="screenshot_ocr_terminal",
        filename="Screenshot 2026-03-01 at 9.15.03 AM.png",
        schema_type="ImageObject",
        mime_type="image/png",
        screenshot_ocr=("terminal_session", 0.15, {"terminal_session": 0.15}, "zsh $ ls"),
        expected=("media", "photos_screenshots_terminal_session"),
    ),
    GoldenCase(
        name="screenshot_ocr_dashboard",
        filename="Screenshot 2026-03-02 at 10.00.00 AM.png",
        schema_type="ImageObject",
        mime_type="image/png",
        screenshot_ocr=("dashboard", 0.14, {"dashboard": 0.14}, "metrics uptime"),
        expected=("media", "photos_screenshots_dashboard"),
    ),
    GoldenCase(
        name="screenshot_ocr_api_response",
        filename="Screenshot 2026-03-03 at 11.30.00 AM.png",
        schema_type="ImageObject",
        mime_type="image/png",
        screenshot_ocr=("api_response", 0.2, {"api_response": 0.2}, '{"status": 200}'),
        expected=("media", "photos_screenshots_api_response"),
    ),
    GoldenCase(
        name="screenshot_weak_ocr_clip_rescues",
        filename="Screenshot 2026-03-04 at 12.00.00 PM.png",
        schema_type="ImageObject",
        mime_type="image/png",
        screenshot_ocr=("browser", 0.05, {"browser": 0.05}, "sparse"),  # below 0.10
        clip={"screenshot: a computer screen": 0.6},
        expected=("media", "photos_screenshots_other"),
        min_margin=0.01,
    ),
]

ALL_CASES = GOLDEN_CASES + SCREENSHOT_CASES


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.integration
class TestGoldenDecisions:
    @pytest.mark.parametrize("case", ALL_CASES, ids=lambda case: case.name)
    def test_golden(self, case: GoldenCase):
        decision = classify(case)
        emissions = [
            (s.signal_name, s.category, s.subcategory, round(s.confidence, 2))
            for s in decision.all_scores
        ]
        assert (decision.category, decision.subcategory) == case.expected, (
            f"{case.name}: got {decision.category}/{decision.subcategory} "
            f"(state={decision.decision_state}, signals={decision.winning_signals}, "
            f"all={emissions})"
        )
        assert decision.decision_state == case.expected_state
        assert decision.margin >= case.min_margin, (
            f"{case.name}: margin {decision.margin:.3f} < {case.min_margin} — "
            f"right answer, fragile reasons"
        )
        if case.expected_schema_type is not None:
            assert decision.schema_type == case.expected_schema_type
        if case.people_contains is not None:
            assert any(
                case.people_contains in person for person in decision.people_names
            ), f"{case.name}: {case.people_contains!r} not in {decision.people_names}"
        if case.company_contains is not None:
            assert decision.company_name and case.company_contains in decision.company_name


@pytest.mark.integration
class TestFormatDrift:
    """Group 2: the same content as PDF and PNG must land in one folder."""

    # Filename stems chosen to dodge strong filename rules on both sides:
    # the .pdf matches nothing; the .png matches only the weak "Hash/ID
    # image" catch-all (photos_other @ FILENAME_WEAK_CONFIDENCE), so the
    # extracted content decides — the drift scenario under test.
    PAIRS = [
        ("vendordoc2041", VENDOR_INVOICE_TEXT, ("organization", "vendors")),
        ("courtdoc441", COURT_NOTICE_TEXT, ("legal", "litigation")),
    ]

    @pytest.mark.parametrize("stem,content,expected", PAIRS, ids=lambda p: str(p))
    def test_pdf_and_png_converge(self, stem, content, expected):
        pdf_case = GoldenCase(
            name=f"{stem}_pdf",
            filename=f"{stem}.pdf",
            schema_type="DigitalDocument",
            mime_type="application/pdf",
            text=content,
            expected=expected,
        )
        png_case = GoldenCase(
            name=f"{stem}_png",
            filename=f"{stem}.png",
            schema_type="ImageObject",
            mime_type="image/png",
            ocr_text=content,
            expected=expected,
        )
        pdf_decision = classify(pdf_case)
        png_decision = classify(png_case)
        assert (pdf_decision.category, pdf_decision.subcategory) == expected
        assert (png_decision.category, png_decision.subcategory) == (
            pdf_decision.category,
            pdf_decision.subcategory,
        ), (
            f"format drift: PDF={pdf_decision.category}/{pdf_decision.subcategory} "
            f"PNG={png_decision.category}/{png_decision.subcategory}"
        )


@pytest.mark.integration
class TestMisleadingExtensions:
    """Group 6: Photos.zip must not route to Media by its stem."""

    @pytest.mark.parametrize("filename", ["Photos.zip", "Vacation Photos.zip", "photos_backup.zip"])
    def test_photo_named_archive_never_lands_in_media(self, filename):
        case = GoldenCase(
            name="misnamed_archive",
            filename=filename,
            schema_type="DigitalDocument",
            mime_type="application/zip",
            expected=("", ""),  # unused — asserted manually below
        )
        decision = classify(case)
        assert decision.category != "media", (
            f"{filename} routed to media/{decision.subcategory} via " f"{decision.winning_signals}"
        )
