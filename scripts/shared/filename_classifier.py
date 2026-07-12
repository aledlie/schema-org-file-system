#!/usr/bin/env python3
"""Shared filename-pattern classifier.

Single source of truth for fast, content-free file classification by filename
and extension. Both organizers delegate here so the rule set cannot drift
between entry points:

- scripts/file_organizer_content_based.py (the live CLI organizer)
- src/organizers/content_organizer.py (test/library organizer)

The function returns (category, subcategory, organization, people) or
None when no filename pattern matches and content analysis is required.

Instance-specific inputs are passed explicitly:

- game_sprite_keywords: the caller's sprite-keyword vocabulary (the broad
  snake_case "Game asset (named)" rule is gated on a token match against it).
- last_file_state: optional mutable dict; when a research paper is detected
  the (publisher_key, identifier, publisher_name, url) tuple is stored under
  the "research" key so the caller can attach schema.org provenance. Pass
  None to skip side-channel capture (routing is unaffected).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Research category key and Schema.org type for scholarly articles.
# See: https://schema.org/ScholarlyArticle
RESEARCH_CATEGORY = "research"
SCHOLARLY_ARTICLE_SCHEMA_TYPE = "ScholarlyArticle"

# Publisher-prefix patterns for Schema.org ScholarlyArticle detection.
# Order matters: explicit publisher prefixes are checked before bare identifiers
# so "arxiv-2401.12345" is attributed to arXiv rather than matched twice.
_RESEARCH_PREFIX_PATTERNS = (
    (
        re.compile(r"^ssrn[-_]?(?:id)?[-_]?(\d{4,})", re.IGNORECASE),
        "ssrn",
        "SSRN",
        "https://ssrn.com/abstract={id}",
    ),
    (
        re.compile(r"^arxiv[-_:]?(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE),
        "arxiv",
        "arXiv",
        "https://arxiv.org/abs/{id}",
    ),
    (
        re.compile(r"^doi[-_:]?(10\.\d{4,}[/._-][^\s]+)", re.IGNORECASE),
        "doi",
        "DOI",
        "https://doi.org/{id}",
    ),
    (re.compile(r"^(\d{4}\.\d{4,5}(?:v\d+)?)$"), "arxiv", "arXiv", "https://arxiv.org/abs/{id}"),
    (re.compile(r"^(10\.\d{4,}[/._-][\w.\-/]+)"), "doi", "DOI", "https://doi.org/{id}"),
)


def _detect_research_publisher(filename_stem: str) -> Optional[Tuple[str, str, str, str]]:
    """Detect a scholarly publisher prefix in a filename stem.

    Returns (publisher_key, identifier, publisher_name, canonical_url) when the
    stem starts with a recognized prefix (ssrn-, arxiv-, doi-) or matches a
    bare arXiv ID / DOI pattern. Returns None otherwise. Publisher key is the
    lowercase subcategory; publisher_name is the display name used as the
    schema.org Organization label.
    """
    stem = filename_stem.strip().rstrip("._-")
    for pattern, publisher_key, publisher_name, url_template in _RESEARCH_PREFIX_PATTERNS:
        match = pattern.search(stem)
        if match:
            identifier = match.group(1)
            url = url_template.format(id=identifier)
            return (publisher_key, identifier, publisher_name, url)
    return None


def classify_by_filename_patterns(
    file_path: Path,
    *,
    game_sprite_keywords: List[str],
    last_file_state: Optional[Dict] = None,
) -> Optional[Tuple[str, str, Optional[str], List[str]]]:
    """Classify a file from its name/extension before content extraction.

    Handles common patterns identifiable by filename alone, avoiding expensive
    OCR/content analysis. Returns (category, subcategory, company_name,
    people_names) or None.
    """
    filename = file_path.name
    filename_lower = filename.lower()
    stem = file_path.stem.lower()
    ext = file_path.suffix.lower()
    original_stem = file_path.stem

    # =========================================================
    # DUPLICATE DETECTION: Files with _YYYYMMDD_HHMMSS suffix
    # These are timestamped copies - skip them
    # =========================================================
    if re.search(r"_\d{8}_\d{6}$", file_path.stem):
        print("  ⚠ Duplicate file (timestamped copy) - skipping")
        return ("skip", "duplicate", None, [])

    # =========================================================
    # RESEARCH PAPERS: arXiv, SSRN, DOI publisher prefixes
    # Schema.org ScholarlyArticle — fires first so academic PDFs aren't
    # captured by downstream legal/contract or technical/documentation
    # keyword matchers (e.g. SSRN papers containing "agreement").
    # =========================================================
    if ext == ".pdf":
        research = _detect_research_publisher(file_path.stem)
        if research:
            publisher_key, identifier, publisher_name, _url = research
            print(
                f"  ✓ Filename pattern: {SCHOLARLY_ARTICLE_SCHEMA_TYPE} ({publisher_name} {identifier})"  # noqa: E501
            )
            if last_file_state is not None:
                last_file_state["research"] = research
            return (RESEARCH_CATEGORY, publisher_key, publisher_name, [])

    # =========================================================
    # LOG FILES: System logs, reorganization logs → Technical/Logs
    # =========================================================
    log_patterns = [
        "reorganization-log",
        "reorganization_log",
        "system-log",
        "system_log",
        "error-log",
        "error_log",
        "debug-log",
        "debug_log",
        "access-log",
        "access_log",
    ]
    if any(p in stem for p in log_patterns) or (ext == ".log"):
        print("  ✓ Filename pattern: Log file")
        return ("technical", "logs", None, [])

    # =========================================================
    # LEGAL DOCUMENT PATTERNS: Contracts, Corporate docs
    # =========================================================
    # Certificate of Formation/Filing → Legal/Corporate
    corporate_legal_patterns = [
        "certificateofformation",
        "certificate_of_formation",
        "certificate-of-formation",
        "certificateoffiling",
        "certificate_of_filing",
        "certificate-of-filing",
        "articlesofincorporation",
        "articles_of_incorporation",
        "articles-of-incorporation",
        "bylaws",
        "operatingagreement",
        "operating_agreement",
        "operating-agreement",
    ]
    if any(p in stem for p in corporate_legal_patterns):
        print("  ✓ Filename pattern: Corporate legal document")
        return ("legal", "corporate", None, [])

    # Release of Liability, NDA, General Release → Legal/Contracts
    contract_legal_patterns = [
        "releaseofliability",
        "release_of_liability",
        "release-of-liability",
        "generalrelease",
        "general_release",
        "general-release",
        "non-disclosure",
        "nondisclosure",
        "confidentiality",
    ]
    # NDA needs special handling - must be whole word or at word
    # boundary (not inside 'calendar')
    is_nda = (
        stem == "nda"
        or stem.startswith("nda_")
        or stem.startswith("nda-")
        or "_nda" in stem
        or "-nda" in stem
        or stem.endswith("_nda")
        or stem.endswith("-nda")
    )
    if any(p in stem for p in contract_legal_patterns) or is_nda:
        print("  ✓ Filename pattern: Legal contract/release")
        return ("legal", "contracts", None, [])

    # =========================================================
    # TECHNICAL CONFIG: Login credentials, account recovery docs
    # =========================================================
    config_patterns = [
        "login",
        "recovery",
        "credentials",
        "password",
        "apikey",
        "api_key",
        "api-key",
        "techsoup",
        "zoho",
        "oauth",
        "token",
        "secret",
    ]
    if ext in {".docx", ".doc", ".txt", ".pdf"} and any(p in stem for p in config_patterns):
        print("  ✓ Filename pattern: Config/credentials document")
        return ("technical", "config", None, [])

    # =========================================================
    # MARKETING PATTERNS: Strategy docs, market maps, infographics
    # =========================================================
    marketing_patterns = [
        "marketingstrategy",
        "marketing_strategy",
        "marketing-strategy",
        "marketmap",
        "market_map",
        "market-map",
        "marketanalysis",
        "market_analysis",
        "competitoranalysis",
        "competitor_analysis",
        "brandstrategy",
        "brand_strategy",
        "contentcalendar",
        "content_calendar",
        "socialmedia",
        "social_media",
        "infographic",
        "info_graphic",
        "info-graphic",
    ]
    if any(p in stem for p in marketing_patterns):
        print("  ✓ Filename pattern: Marketing document")
        return ("business", "marketing", None, [])

    # =========================================================
    # COMPANY MEETING NOTES: Must be before generic company patterns
    # =========================================================
    # Integrity Studio meeting notes (IntegrityWeeklyCadence-*-NotesByGemini.docx)
    if "integrityweeklycadence" in stem or ("integrity" in stem and "cadence" in stem):
        print("  ✓ Filename pattern: Integrity Studio meeting notes")
        return ("organization", "meeting_notes", "Integrity Studio", [])

    # =========================================================
    # LEORA HOME HEALTH: Stock photos and business assets
    # =========================================================
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        leora_keywords = [
            "elderlycare",
            "caregiver",
            "home-health",
            "homehealth",
            "skilled-nursing",
            "skillednursing",
            "at-home-nurse",
            "compassionate-home",
            "grandparents-and",
            "get-started-seniors",
            "daughter-and-mother",
        ]
        leora_prefixes = ["atx-caregiver", "atx-nurse"]
        if any(kw in stem for kw in leora_keywords) or any(
            stem.startswith(p) for p in leora_prefixes
        ):
            print("  ✓ Filename pattern: Leora Home Health asset")
            return ("organization", "other", "Leora Home Health", [])

    # =========================================================
    # COMPANY-BASED ORGANIZATION: Files with company names
    # =========================================================
    company_patterns = {
        "integrity": ("organization", "other", "Integrity Studio"),
        "integrityai": ("organization", "other", "Integrity Studio"),
        "integritystudio": ("organization", "other", "Integrity Studio"),
        "integrity_studio": ("organization", "other", "Integrity Studio"),
        "integrity-studio": ("organization", "other", "Integrity Studio"),
        "integritycrm": ("organization", "other", "Integrity Studio"),
        "inspiredmovement": ("organization", "vendors", "Inspired Movement"),
        "inspired_movement": ("organization", "vendors", "Inspired Movement"),
        "inspired-movement": ("organization", "vendors", "Inspired Movement"),
        "inspired": ("organization", "vendors", "Inspired Movement"),
    }
    for pattern, (category, subcategory, company_name) in company_patterns.items():
        if pattern in stem:
            print(f"  ✓ Filename pattern: Company file ({company_name})")
            return (category, subcategory, company_name, [])

    # =========================================================
    # BUSINESS TYPE PATTERNS: CRM, HR, Operations, Planning
    # Skip code files - they go to Technical even if they have business keywords
    # =========================================================
    # Code file extensions that should NOT be matched by business patterns
    # Includes web build artifacts (css, scss) that often have hashed
    # names like client.063172a3.css
    business_skip_extensions = {
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".java",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".css",
        ".scss",
        ".less",
        ".sass",
        ".html",
        ".htm",
        ".vue",
        ".svelte",
    }

    # CRM files (but not code files like contacts.py, essentialcontacts_v1_client.py)
    if ext not in business_skip_extensions:
        if "crm" in stem or "microlender" in stem:
            print("  ✓ Filename pattern: CRM/Contacts file")
            return ("business", "crm", None, [])
        # Only match 'contacts' for spreadsheet/document files, not code
        if "contacts" in stem and ext in {".xlsx", ".xls", ".csv", ".docx", ".pdf"}:
            print("  ✓ Filename pattern: CRM/Contacts file")
            return ("business", "crm", None, [])
        # Third party vendor/partner evaluation files
        thirdparty_patterns = [
            "3rdparties",
            "3rdparty",
            "thirdparties",
            "thirdparty",
            "third_parties",
            "third_party",
            "third-parties",
            "third-party",
        ]
        if any(p in stem for p in thirdparty_patterns):
            print("  ✓ Filename pattern: Third-party vendor/partner list")
            return ("business", "crm", None, [])

    # HR/Job posting files (but not code files like application.py, linkedin.py)
    # Note: 'application' and 'linkedin' are common in code filenames
    hr_patterns = [
        "jobposting",
        "job_posting",
        "job-posting",
        "boardmember",
        "board_member",
        "hiring",
        "teamroster",
        "team_roster",
        "team-roster",
    ]
    # Only match 'application' or 'linkedin' for document files
    hr_doc_patterns = ["application", "linkedin"]
    if ext not in business_skip_extensions:
        if any(p in stem for p in hr_patterns):
            print("  ✓ Filename pattern: HR file")
            return ("business", "hr", None, [])
        if ext in {".xlsx", ".xls", ".csv", ".docx", ".pdf", ".webp", ".png", ".jpg"} and any(
            p in stem for p in hr_doc_patterns
        ):
            print("  ✓ Filename pattern: HR file")
            return ("business", "hr", None, [])

    # Project tracking and product planning files (but not code files)
    if ext not in business_skip_extensions:
        if "projecttrack" in stem or "project_track" in stem or "project-track" in stem:
            print("  ✓ Filename pattern: Project tracking")
            return ("business", "planning", None, [])
        # Product ideas, analysis, and roadmap files
        planning_patterns = [
            "productideas",
            "product_ideas",
            "product-ideas",
            "productanalysis",
            "product_analysis",
            "product-analysis",
            "productroadmap",
            "product_roadmap",
            "product-roadmap",
            "roadmap_product",
            "roadmap-product",
            "roadmapproduct",
        ]
        if any(p in stem for p in planning_patterns):
            print("  ✓ Filename pattern: Product planning/analysis")
            return ("business", "planning", None, [])

    # Operations/Dashboard files (but not code files like dashboard.py, operations.py)
    if ext not in business_skip_extensions:
        if "dashboard" in stem or "operations" in stem or "toolkit" in stem:
            print("  ✓ Filename pattern: Operations file")
            return ("business", "other", None, [])

    # Stand-up/meeting templates and notes
    meeting_patterns = [
        "standup",
        "stand-up",
        "stand_up",
        "meeting",
        "minutes",
        "agenda",
        "allhands",
        "all-hands",
        "all_hands",
        "retrospective",
        "retro",
    ]
    if ext not in business_skip_extensions and any(p in stem for p in meeting_patterns):
        print("  ✓ Filename pattern: Meeting notes/template")
        return ("business", "meeting_notes", None, [])

    # Shipping labels
    if "printlabel" in stem or "print_label" in stem or "shippinglabel" in stem:
        print("  ✓ Filename pattern: Shipping label")
        return ("business", "other", None, [])

    # =========================================================
    # GOOGLE INVOICES: 51xxxxx.pdf, 52xxxxx.pdf, 53xxxxx.pdf patterns
    # =========================================================
    if ext == ".pdf" and re.match(r"^5[123]\d{8,}", filename):
        print("  ✓ Filename pattern: Google invoice")
        return ("organization", "vendors", "Google", [])

    # =========================================================
    # SCREENSHOTS: Files with 'screenshot' in name
    # Image files fall through to CLIP/OCR sub-classification
    # (Priority 4.5) so they can be routed to Browser/Terminal/etc.
    # Non-image files with 'screenshot' in name are skipped (e.g.
    # ScreenshotResult.js.map is not a screenshot).
    # =========================================================

    # =========================================================
    # SURVEYS: Survey/questionnaire documents → Business/Other
    # =========================================================
    survey_patterns = ["survey", "questionnaire", "feedback-form", "feedback_form"]
    if ext in {".docx", ".doc", ".pdf", ".xlsx", ".xls"} and any(
        p in stem for p in survey_patterns
    ):
        print("  ✓ Filename pattern: Survey/questionnaire")
        return ("business", "other", None, [])

    # Known person name patterns (used in multiple places)
    known_person_patterns = {
        "ledlie": "Alyshia Ledlie",
        "alyshia": "Alyshia Ledlie",
    }

    # =========================================================
    # RESUME FILES: *resume*, *cv* - ONLY for document file types
    # Code files (.py, .js, .ts, .css) with "resume" are technical files
    # =========================================================
    document_extensions = {".pdf", ".docx", ".doc", ".rtf", ".odt", ".txt"}

    resume_patterns = ["resume", "curriculum_vitae", "curriculum-vitae"]
    # Match 'cv' if it's the whole filename, has separators, or starts with 'cv ' (space)
    stem_lower = stem.lower()
    is_cv_document = (
        stem_lower == "cv"
        or stem_lower.startswith("cv_")
        or stem_lower.startswith("cv-")
        or stem_lower.startswith("cv ")
        or "_cv" in stem_lower
        or "-cv" in stem_lower
        or " cv" in stem_lower
        or stem_lower.endswith("_cv")
        or stem_lower.endswith("-cv")
    )

    if ext in document_extensions and (
        any(p in filename_lower for p in resume_patterns) or is_cv_document
    ):
        # Try to extract person name from filename
        person_name = None

        # Pattern 1: CV/Resume at START followed by FirstName LastName
        # (e.g., "CV Isabel Budenz January")
        name_match = re.search(
            r"^(cv|resume)[_\-\s]+([A-Z][a-z]+)[_\-\s]+([A-Z][a-z]+)", filename, re.IGNORECASE
        )
        if name_match:
            person_name = f"{name_match.group(2)} {name_match.group(3)}"

        # Pattern 2: FirstName LastName at START followed by CV/Resume
        # (e.g., "Alyshia_Ledlie_Technical_Resume")
        # Take the FIRST two capitalized words as the name
        if not person_name:
            name_match = re.search(r"^([A-Z][a-z]+)[_\-\s]+([A-Z][a-z]+)", filename)
            if name_match:
                # Verify this file contains resume/cv somewhere
                if "resume" in filename_lower or is_cv_document:
                    candidate = f"{name_match.group(1)} {name_match.group(2)}"
                    # Skip template/style names that aren't person names
                    template_words = {
                        "modern",
                        "minimalist",
                        "professional",
                        "creative",
                        "simple",
                        "elegant",
                        "classic",
                        "template",
                        "standard",
                        "basic",
                        "clean",
                    }
                    first_word = name_match.group(1).lower()
                    second_word = name_match.group(2).lower()
                    if first_word not in template_words and second_word not in template_words:
                        person_name = candidate

        # Check for known person names if no name extracted yet
        if not person_name:
            for pattern, known_name in known_person_patterns.items():
                if pattern in filename_lower:
                    person_name = known_name
                    break

        # If name found in filename, return immediately
        if person_name:
            print(f"  ✓ Filename pattern: Resume ({person_name})")
            return ("personal", "contacts", None, [person_name])
        # If no name found, don't return - fall through to OCR content extraction
        # This allows "Modern Minimalist CV Resume.pdf" to get name from PDF content
        print("  ✓ Filename pattern: Resume (extracting name from content...)")

    # =========================================================
    # COVER LETTERS: *coverletter*, *cover_letter* - document files
    # =========================================================
    cover_letter_patterns = ["coverletter", "cover_letter", "cover-letter"]
    if ext in document_extensions and any(p in stem for p in cover_letter_patterns):
        # Try to extract person name from filename
        person_name = None
        for pattern, known_name in known_person_patterns.items():
            if pattern in filename_lower:
                person_name = known_name
                break
        print(
            "  ✓ Filename pattern: Cover letter" + (f" ({person_name})" if person_name else "")
        )
        return ("personal", "contacts", None, [person_name] if person_name else [])

    # Check for known person names in filename (e.g., ledlie) - non-resume files
    for pattern, person_name in known_person_patterns.items():
        if pattern in filename_lower:
            print(f"  ✓ Filename pattern: Person ({person_name})")
            return ("personal", "contacts", None, [person_name])

    # =========================================================
    # ENTITY-BASED FILES: Company names in filename (check BEFORE extension)
    # This ensures files like LeoraHomeHealth-Data.csv go to Organization/
    # rather than Technical/
    # =========================================================
    entity_patterns = {
        "integritystudio": ("organization", "vendors", "Integrity Studio"),
        "integrity_studio": ("organization", "vendors", "Integrity Studio"),
        "integrity-studio": ("organization", "vendors", "Integrity Studio"),
        "leora": ("organization", "healthcare", "Leora Home Health"),
        "leorahomehealth": ("organization", "healthcare", "Leora Home Health"),
        "ltchcssa": (
            "organization",
            "healthcare",
            "Leora Home Health",
        ),  # LTCHCSSA is Leora related
        "inspiredmovement": ("organization", "vendors", "Inspired Movement"),
        "inspired_movement": ("organization", "vendors", "Inspired Movement"),
        "inspired-movement": ("organization", "vendors", "Inspired Movement"),
        "fisterra": ("organization", "vendors", "Fisterra"),
        "dotfun": ("organization", "vendors", "DotFun"),
        "ensco": ("organization", "vendors", "EnsoCo"),
        "capitalcityvillage": ("organization", "property_management", "Capital City Village"),
        "capital_city_village": ("organization", "property_management", "Capital City Village"),
        "capital-city-village": ("organization", "property_management", "Capital City Village"),
        "google": ("organization", "vendors", "Google"),
        "microsoft": ("organization", "vendors", "Microsoft"),
        "adobe": ("organization", "vendors", "Adobe Systems"),
        "amazon": ("organization", "vendors", "Amazon"),
        "apple": ("organization", "vendors", "Apple"),
        "genius bar": ("organization", "vendors", "Apple"),
    }
    for pattern, (category, subcat, company_name) in entity_patterns.items():
        if pattern in stem:
            print(f"  ✓ Filename pattern: Entity ({company_name})")
            return (category, subcat, company_name, [])

    # =========================================================
    # TECHNICAL FILES: .py, .js, .ts, .csv, .json, .xml
    # (Only if no entity pattern matched above)
    # =========================================================
    technical_extensions = {
        ".py": "Technical",
        ".js": "Technical",
        ".ts": "Technical",
        ".jsx": "Technical",
        ".tsx": "Technical",
        ".csv": "Technical",
        ".json": "Technical",
        ".xml": "Technical",
        ".yaml": "Technical",
        ".yml": "Technical",
        ".sql": "Technical",
        ".sh": "Technical",
        ".bash": "Technical",
    }
    if ext in technical_extensions:
        print(f"  ✓ Filename pattern: Technical file ({ext})")
        return ("technical", "other", None, [])

    # =========================================================
    # SOFTWARE PACKAGES: .dmg, .pkg, .msi, .deb, .rpm, .exe, .app
    # =========================================================
    software_extensions = {
        ".dmg",
        ".pkg",
        ".msi",
        ".deb",
        ".rpm",
        ".exe",
        ".app",
        ".snap",
        ".flatpak",
        ".appimage",
    }
    if ext in software_extensions:
        print(f"  ✓ Filename pattern: Software package ({ext})")
        return ("technical", "software_packages", None, [])

    # =========================================================
    # LEGAL DOCUMENTS: Agreement, CLA, Operating, Reseller, Severance
    # =========================================================
    legal_patterns = [
        ("agreement", "contracts"),
        ("operating", "corporate"),
        ("reseller", "contracts"),
        ("severance", "contracts"),
        ("contract", "contracts"),
        ("amendment", "contracts"),
        ("certificateoffiling", "corporate"),
    ]
    for pattern, subcat in legal_patterns:
        if pattern in stem:
            print(f"  ✓ Filename pattern: Legal document ({pattern})")
            return ("legal", subcat, None, [])

    # CLA pattern - Contributor License Agreement
    # Be careful not to match "class", "clause", "claw", "eucla" (timezone), etc.
    # Only match explicit CLA patterns
    cla_patterns = [
        r"^cla[_\-\d.]",  # cla_signed, cla-2024, cla.pdf
        r"^cla$",  # just "cla"
        r"corporatecla",  # CorporateCLA
        r"individualcla",  # IndividualCLA
        r"contributorcla",  # ContributorCLA
        r"[_\-]cla[_\-\d.]",  # some_cla_file, my-cla-2024
        r"[_\-]cla$",  # some_cla, my-cla
    ]
    if any(re.search(p, stem) for p in cla_patterns):
        print("  ✓ Filename pattern: Legal document (CLA)")
        return ("legal", "contracts", None, [])

    # =========================================================
    # BUSINESS DOCUMENTS: BizAid, BizStart, Meeting
    # =========================================================
    business_patterns = [
        ("bizaid", "planning"),
        ("bizstart", "planning"),
        ("meeting", "other"),
        ("proposal", "proposals"),
    ]
    for pattern, subcat in business_patterns:
        if pattern in stem:
            print(f"  ✓ Filename pattern: Business document ({pattern})")
            return ("business", subcat, None, [])

    # =========================================================
    # DATA USAGE AGREEMENTS: Special case
    # =========================================================
    if (
        "datausageagreement" in stem
        or "data_usage_agreement" in stem
        or "data-usage-agreement" in stem
    ):
        print("  ✓ Filename pattern: Data Usage Agreement")
        return ("legal", "contracts", None, [])

    # =========================================================
    # DOCUMENTATION FILES: LICENSE, README, specs
    # =========================================================
    # LICENSE files
    if stem.startswith("license") or stem == "copying" or stem == "licence":
        print("  ✓ Filename pattern: License file")
        return ("technical", "documentation", None, [])

    # README files
    if stem.startswith("readme") or stem == "read_me" or stem == "read-me":
        print("  ✓ Filename pattern: README file")
        return ("technical", "documentation", None, [])

    # Specification/spec documents
    spec_patterns = ["specification", "spec_", "_spec", "-spec", "specs_", "_specs"]
    if any(p in stem for p in spec_patterns) or stem == "spec" or stem == "specs":
        print("  ✓ Filename pattern: Specification document")
        return ("technical", "documentation", None, [])

    # CHANGELOG files
    if stem.startswith("changelog") or stem == "changes" or stem == "history":
        print("  ✓ Filename pattern: Changelog file")
        return ("technical", "documentation", None, [])

    # =========================================================
    # COVER LETTERS: Go to Person folder
    # =========================================================
    if "coverletter" in stem or "cover_letter" in stem or "cover-letter" in stem:
        # Try to extract person name
        person_name = None
        for pattern, known_name in known_person_patterns.items():
            if pattern in filename_lower:
                person_name = known_name
                break
        print(
            "  ✓ Filename pattern: Cover letter" + (f" ({person_name})" if person_name else "")
        )
        return ("personal", "contacts", None, [person_name] if person_name else [])

    # =========================================================
    # CONFIG/MANIFEST FILES: Technical config
    # =========================================================
    config_patterns = [".manifest", ".config", ".ini", ".cfg", ".conf", ".plist"]
    if ext in config_patterns:
        print(f"  ✓ Filename pattern: Config file ({ext})")
        return ("technical", "config", None, [])

    # Config-like text files (settings.txt, config.txt, preferences.txt)
    config_txt_names = ["settings", "config", "preferences", "options", "configuration"]
    if ext == ".txt" and stem in config_txt_names:
        print(f"  ✓ Filename pattern: Config text file ({stem}.txt)")
        return ("technical", "config", None, [])

    # =========================================================
    # GIT HOOK SAMPLES: .sample files from .git/hooks/
    # =========================================================
    if ext == ".sample":
        print("  ✓ Filename pattern: Git hook sample")
        return ("technical", "config", None, [])

    # =========================================================
    # DOTFILES: .eslintrc, .editorconfig, .nycrc, .travis.yml, etc.
    # =========================================================
    if filename.startswith("."):
        dotfile_configs = [
            ".eslintrc",
            ".editorconfig",
            ".nycrc",
            ".travis",
            ".codecov",
            ".codeclimate",
            ".yarnrc",
            ".npmrc",
            ".prettierrc",
            ".babelrc",
            ".gitignore",
            ".gitattributes",
            ".dockerignore",
            ".env",
        ]
        if any(filename.startswith(cfg) for cfg in dotfile_configs):
            print(f"  ✓ Filename pattern: Dotfile config ({filename})")
            return ("technical", "config", None, [])
        # Generic dotfiles with common config extensions
        if ext in [".yml", ".yaml", ".json", ".toml"]:
            print(f"  ✓ Filename pattern: Dotfile config ({filename})")
            return ("technical", "config", None, [])

    # =========================================================
    # SOURCE MAP FILES: .map, .js.map, .d.ts.map → Technical/Config
    # =========================================================
    if ext == ".map" or filename.endswith(".js.map") or filename.endswith(".d.ts.map"):
        print("  ✓ Filename pattern: Source map file")
        return ("technical", "config", None, [])

    # =========================================================
    # MEETING NOTES: Generic meeting notes → Business/Other
    # (Company-specific meeting notes handled earlier in COMPANY MEETING NOTES section)
    # =========================================================
    meeting_patterns = [
        "weeklynotes",
        "weekly_notes",
        "weekly-notes",
        "meetingnotes",
        "meeting_notes",
        "meeting-notes",
        "notesby",
    ]
    if any(p in stem for p in meeting_patterns):
        print("  ✓ Filename pattern: Meeting notes")
        return ("business", "other", None, [])

    # =========================================================
    # DOCUMENTATION/NOTES FILES: Websites, personal notes
    # =========================================================
    if stem.startswith("websites") or "ivemade" in stem or "i'vemade" in stem.replace("'", "'"):
        print("  ✓ Filename pattern: Personal documentation")
        return ("business", "other", None, [])

    # =========================================================
    # AUDIO FILES: Check for game audio first, then Media/Audio
    # =========================================================
    audio_extensions = {".wav", ".ogg", ".mp3", ".flac", ".aac", ".m4a", ".wma"}
    if ext in audio_extensions:
        # Game audio keywords - sound effects and music
        # Note: Avoid 'cast' as it matches 'podcast'
        game_audio_keywords = [
            "bolt",
            "spell",
            "magic",
            "spellcast",
            "chirp",
            "crossbow",
            "dagger",
            "sword",
            "arrow",
            "bow",
            "heal",
            "potion",
            "lightning",
            "fire",
            "ice",
            "acid",
            "poison",
            "explosion",
            "blast",
            "summon",
            "dispel",
            "petrification",
            "neutralize",
            "slow",
            "darkness",
            "achievement",
            "quest",
            "unlock",
            "lock",
            "door",
            "chest",
            "coin",
            "pickup",
            "attack",
            "hit",
            "damage",
            "death",
            "footstep",
            "jump",
            "land",
            "monster",
            "creature",
            "enemy",
            "boss",
            "battle",
            "combat",
            "starving",
            "hunger",
            "thirst",
            "eat",
            "drink",
            "sleep",
            "fiddle",
            "lute",
            "mandoline",
            "glockenspiel",
            "instrument",
            "identify",
            "greater",
            "mental",
            "melee",
            "axe",
            "mace",
            "whip",
            "sabre",
            "staff",
            "thunder",
            "confusion",
            "telekinetic",
            "mind",
            "cure",
            "light",
            "firebolt",
            "fireball",
            "boomer",
            "skur",
            # Game music keywords
            "dungeon",
            "castle",
            "forest",
            "town",
            "village",
            "temple",
            "ruins",
            "cave",
            "mountain",
            "ocean",
            "desert",
            "snow",
            "victory",
            "defeat",
            "theme",
            "menu",
            "credits",
            "intro",
            "outro",
            "mysterious",
            "dark",
            "epic",
            "calm",
            "peaceful",
            "tension",
            "chaos",
            "hope",
            "despair",
            "triumph",
            "march",
            "symphony",
            "monotony",
            "drakalor",
            "altar",
            "lawful",
            "chaotic",
            "dwarven",
            "elven",
            "orcish",
            "halls",
            "abandon",
            "corrupting",
            "breeze",
            "clockwork",
            "knowledge",
            "final",
            "welcome",
            "khelavaster",
            "prophecy",
            "spiraling",
            "stairs",
            "windy",
            "growth",
            "warm",
            "folk",
            "peace",
            "heritage",
            "browsing",
            "dusty",
            "tomes",
            "dead",
            "silent",
            "ancardia",
            "goblin",
            "drums",
            "bird",
        ]
        stem_lower = stem.lower()
        for keyword in game_audio_keywords:
            if keyword in stem_lower:
                print(f"  ✓ Filename pattern: Game audio file ({stem}{ext}) → GameAssets/Audio")
                return ("game_assets", "audio", None, [])
        # Default to Media/Audio for non-game audio
        print(f"  ✓ Filename pattern: Audio file ({ext})")
        return ("media", "audio_other", None, [])

    # =========================================================
    # VECTOR GRAPHICS: .svg, .ai, .eps → Media/Graphics
    # =========================================================
    vector_extensions = {".svg", ".ai", ".eps"}
    if ext in vector_extensions:
        print(f"  ✓ Filename pattern: Vector graphics ({ext})")
        return ("media", "graphics_vector", None, [])

    # =========================================================
    # GAME DATA FILES: .noe (ADOM game data), etc → GameAssets
    # =========================================================
    game_data_extensions = {".noe"}
    if ext in game_data_extensions:
        print(f"  ✓ Filename pattern: Game data file ({ext})")
        return ("game_assets", "other", None, [])

    # =========================================================
    # DIAGRAM/DOCUMENTATION IMAGES: *Diagram*, *ClassDiagram*
    # =========================================================
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        if "diagram" in stem or "classdiagram" in stem:
            print("  ✓ Filename pattern: Diagram image")
            return ("technical", "documentation", None, [])

    # =========================================================
    # GAME ASSET SPRITES: claw_*, icon_class_*, icon_* prefixes
    # =========================================================
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        game_sprite_prefixes = [
            "claw_",
            "icon_class_",
            "icon_",
            "sword_",
            "shield_",
            "armor_",
            "weapon_",
            "item_",
            "enemy_",
            "player_",
            "tile_",
            "bg_",
            "effect_",
            "spell_",
            "skill_",
        ]
        if any(stem.startswith(p) for p in game_sprite_prefixes):
            print("  ✓ Filename pattern: Game sprite (prefix)")
            return ("game_assets", "sprites", None, [])
        # Pattern: animation frames (2frame01.png, 3frame05.png)
        if re.match(r"^\d+frame\d+$", stem):
            print("  ✓ Filename pattern: Animation frame")
            return ("game_assets", "sprites", None, [])
        # Pattern: BrogueFont files (BrogueFont1.png, etc.)
        if re.match(r"^broguefont\d+$", stem):
            print("  ✓ Filename pattern: Brogue font")
            return ("game_assets", "fonts", None, [])

    # =========================================================
    # NUMBERED SPRITE FILES: 0.png, 103.png, 0_timestamp.png
    # Common pattern for game sprite sheets
    # =========================================================
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".jp2"}:
        # EXCLUDE camera photo naming conventions from game asset detection
        # These are photos from cameras/phones, not game assets
        camera_prefixes = ("pxl_", "img_", "dsc_", "dcim_", "dscn_", "dscf_", "p_", "photo_")
        is_camera_photo = stem.startswith(camera_prefixes)

        # EXCLUDE screenshot renamer software prefixes from game asset detection
        # These are software screenshots renamed by screenshot_renamer.py
        # Pattern: prefix_8hexchars (e.g., terminal_7a7c3ac6, browser_826a2e1f)
        software_screenshot_pattern = re.match(
            r"^(dashboard|terminal|code|browser|chat|settings|shop|product|docs|landing|infographic)_[a-f0-9]{8}$",  # noqa: E501
            stem,
        )
        is_software_screenshot = software_screenshot_pattern is not None

        # Pattern: purely numeric filename (0.png, 103.png, 42_8.png)
        if not is_camera_photo and re.match(r"^\d+(_\d+)*$", stem):
            print("  ✓ Filename pattern: Numbered sprite")
            return ("game_assets", "sprites", None, [])
        # Pattern: numeric with timestamp suffix (103_20251120_164958.png)
        if not is_camera_photo and re.match(r"^\d+(_\d+)*_\d{8}_\d{6}$", stem):
            print("  ✓ Filename pattern: Numbered sprite (timestamped)")
            return ("game_assets", "sprites", None, [])
        # Pattern: font-related files - check BEFORE generic sprite patterns
        # (ascii_font.png, unicode_font.png, game_font.png, pixel_font.png)
        if not is_camera_photo and ("font" in stem or "glyph" in stem or "charset" in stem):
            print("  ✓ Filename pattern: Font asset")
            return ("game_assets", "fonts", None, [])
        # Pattern: software screenshot from screenshot_renamer.py
        if is_software_screenshot:
            if stem.startswith("dashboard_"):
                print("  ✓ Filename pattern: Software dashboard screenshot")
                return ("media", "photos_screenshots_dashboard", None, [])
            elif stem.startswith("terminal_"):
                print("  ✓ Filename pattern: Terminal screenshot")
                return ("media", "photos_screenshots_terminal", None, [])
            elif stem.startswith("browser_"):
                print("  ✓ Filename pattern: Browser screenshot")
                return ("media", "photos_screenshots_browser", None, [])
            elif stem.startswith("code_"):
                print("  ✓ Filename pattern: Code editor screenshot")
                return ("media", "photos_screenshots_code", None, [])
            elif stem.startswith("docs_"):
                print("  ✓ Filename pattern: Documentation screenshot")
                return ("media", "photos_screenshots_docs", None, [])
            elif stem.startswith(("shop_", "product_")):
                print("  ✓ Filename pattern: Product screenshot")
                return ("media", "photos_screenshots_products", None, [])
            elif stem.startswith("chat_"):
                print("  ✓ Filename pattern: Chat screenshot")
                return ("media", "photos_screenshots_chat", None, [])
            elif stem.startswith("settings_"):
                print("  ✓ Filename pattern: Settings screenshot")
                return ("media", "photos_screenshots_settings", None, [])
            elif stem.startswith(("landing_", "infographic_")):
                print("  ✓ Filename pattern: Marketing screenshot")
                return ("business", "marketing", None, [])
        # Pattern: name_hash.png (animal_57886bff.png, drop_2_6.png)
        # Exclude files where original stem has uppercase — those are
        # human-named, not generated assets
        has_uppercase = any(c.isupper() for c in original_stem)
        # Pre-split once; single-word kws require token match (word boundary);
        # underscore-prefixed kws (_grey) strip the prefix then check tokens;
        # compound kws (mad_carpenter, arrow_v) fall back to substring of stem.
        _stem_tokens = stem.split("_")
        if (
            not is_camera_photo
            and not is_software_screenshot
            and not has_uppercase
            and "screenshot" not in stem
            and re.match(r"^[a-z]+(_[a-z0-9]+)+$", stem)
            and any(
                (
                    kw in _stem_tokens
                    if "_" not in kw
                    else (
                        kw.lstrip("_") in _stem_tokens
                        if "_" not in kw.lstrip("_")
                        else kw in stem
                    )
                )
                for kw in game_sprite_keywords
            )
        ):
            print("  ✓ Filename pattern: Game asset (named)")
            return ("game_assets", "sprites", None, [])
        # Pattern: _hash or _name (starts with underscore, like _RWOIsUgWGL.png)
        if not is_camera_photo and re.match(r"^_[A-Za-z0-9]+(_\d{8}_\d{6})?$", stem):
            print("  ✓ Filename pattern: Game asset (underscore prefix)")
            return ("game_assets", "sprites", None, [])
        # Pattern: number_word (17_in.png, 17_out_1.png)
        # Exclude date-prefixed names (20260130_screenshot, 20260529_backyard):
        # an 8-digit YYYYMMDD prefix marks a timestamped photo/screenshot rename,
        # not a numbered sprite. The camera/screenshot origin is lost once the file
        # is renamed (PXL_*/Screenshot * -> YYYYMMDD_word), so guard on the date.
        if (
            not is_camera_photo
            and "screenshot" not in stem
            and not re.match(r"^\d{8}_", stem)
            and re.match(r"^\d+_[a-z]+(_\d+)?$", stem)
        ):
            print("  ✓ Filename pattern: Game asset (numbered)")
            return ("game_assets", "sprites", None, [])
        # Pattern: hex codes for emoji/unicode (1f4a8.png, 1f600.png)
        if not is_camera_photo and re.match(r"^[0-9a-f]{4,8}$", stem):
            print("  ✓ Filename pattern: Emoji/unicode asset")
            return ("game_assets", "sprites", None, [])
        # Pattern: date_category[_status]_id (ML training data)
        # Matches: 20190129_art_uncertain_100453.png, 20190129_pet_100453_1.png
        if not is_camera_photo and re.match(r"^\d{8}_[a-z]+(_[a-z]+)?_\d+(_\d+)*$", stem):
            print("  ✓ Filename pattern: ML training data")
            return ("game_assets", "sprites", None, [])
        # Pattern: Facebook photo (481566579_10162021550590804_5823185318886800843_n.png)
        if re.match(r"^\d+_\d+_\d+_n$", stem):
            print("  ✓ Filename pattern: Social media photo")
            return ("media", "photos_social", None, [])
        # Pattern: single word lowercase (achiever.png, sword.png)
        # Exclude data visualization and analytics terms
        data_viz_terms = {
            "pricing",
            "trace",
            "chart",
            "graph",
            "data",
            "analytics",
            "report",
            "metrics",
            "dashboard",
            "distribution",
            "histogram",
            "timeline",
            "funnel",
            "heatmap",
            "treemap",
            "scatter",
            "trend",
            "forecast",
            "summary",
            "overview",
            "statistics",
            "benchmark",
            "rework",
        }
        branding_terms = {"logo", "logos", "logotype", "favicon", "brandmark", "wordmark"}
        portrait_terms = {"profile", "headshot", "portrait", "avatar"}
        # Generic download names — no info about content, let fall through to CLIP/OCR
        generic_download_names = {
            "unnamed",
            "untitled",
            "image",
            "photo",
            "picture",
            "screenshot",
            "download",
        }
        # Tech product substrings — compound words describing real hardware, not game assets
        tech_product_substrings = {
            "macbook",
            "iphone",
            "ipad",
            "airpods",
            "android",
            "laptop",
            "tablet",
            "keyboard",
            "monitor",
            "charger",
            "adapter",
        }
        is_tech_product = any(t in stem for t in tech_product_substrings)
        if (
            re.match(r"^[a-z]+$", stem)
            and len(stem) > 2
            and stem not in data_viz_terms
            and stem not in branding_terms
            and stem not in portrait_terms
            and stem not in generic_download_names
            and not is_tech_product
        ):
            print("  ✓ Filename pattern: Game asset (single word)")
            return ("game_assets", "sprites", None, [])
        # Pattern: data visualization single word
        if re.match(r"^[a-z]+$", stem) and stem in data_viz_terms:
            print("  ✓ Filename pattern: Data visualization")
            return ("technical", "data_visualization", None, [])
        # Pattern: ChatGPT images (ChatGPTImageNov1,2025,01_49_23AM.png)
        if stem.startswith("chatgptimage"):
            print("  ✓ Filename pattern: ChatGPT AI-generated image")
            return ("media", "photos_chatgpt", None, [])
        # Pattern: Facebook images (481566579_10162021550590804_5823185318886800843_n.png)
        if re.match(r"^\d+_\d+_\d+_n$", stem):
            print("  ✓ Filename pattern: Facebook image")
            return ("media", "photos_facebook", None, [])
        # Pattern: Portrait/profile photos (profile.png, headshot.png, avatar.png)
        if stem in portrait_terms or stem.startswith("profile") or stem.startswith("headshot"):
            print("  ✓ Filename pattern: Portrait photo")
            return ("media", "photos_portraits", None, [])
        # Pattern: Logo images (logo-..., logotype-..., *-logo.png)
        if "logo" in stem or "logotype" in stem:
            print("  ✓ Filename pattern: Logo image")
            return ("organization", "other", "Integrity Studio", [])
        # Pattern: Leora Home Health stock photos (LHH-OG-*, nurse-*, medical-*)
        if stem.startswith("lhh-") or stem.startswith("lhh_"):
            print("  ✓ Filename pattern: Leora Home Health asset")
            return ("organization", "healthcare", "Leora Home Health", [])
        # Pattern: font-size files (courier-16.png, cp437-14_1.png, fantasy-16s.png)
        if re.match(r"^[a-z0-9]+-\d+[a-z]?(_\d+)?$", stem):
            print("  ✓ Filename pattern: Font/glyph file")
            return ("game_assets", "fonts", None, [])
        # Pattern: codepage/charset font files
        # (cp437-wide.png, cp437_wide_1.png, cp850-thin.png)
        if re.match(r"^cp\d+[_\-]", stem) or re.match(
            r"^(ascii|unicode|charset|codepage)[_\-]", stem
        ):
            print("  ✓ Filename pattern: Codepage font file")
            return ("game_assets", "fonts", None, [])
        # Pattern: game asset keywords with numbers (dungeon2, kitchen4, lightning1, interface2)
        # These are common game environment/effect/UI asset names
        game_asset_keywords = [
            "dungeon",
            "kitchen",
            "lightning",
            "interface",
            "items",
            "terinyo",
            "castle",
            "forest",
            "cave",
            "temple",
            "tower",
            "weapon",
            "armor",
            "potion",
            "scroll",
            "effect",
            "particle",
            "enemy",
            "monster",
            "creature",
            "npc",
            "player",
            "character",
        ]
        for keyword in game_asset_keywords:
            if stem.startswith(keyword) and re.match(rf"^{keyword}\d+$", stem):
                print(f"  ✓ Filename pattern: Game asset ({keyword})")
                return ("game_assets", "sprites", None, [])
        # Pattern: mixed case hash/ID (fSpW8I2Dxe6.png)
        if re.match(r"^[a-zA-Z0-9]{8,}$", stem) and not stem.isdigit() and not stem.isalpha():
            print("  ✓ Filename pattern: Hash/ID image")
            return ("media", "photos_other", None, [])
        # Pattern: portrait/headshot photos (Name-p-800.jpg, Monica-p-1080.png)
        # Single capitalized word with -p-size suffix - typically named portrait photos
        if re.match(r"^[A-Z][a-z]+-p-\d+$", file_path.stem):  # Use original stem for case
            print("  ✓ Filename pattern: Portrait photo")
            return ("media", "photos_portraits", None, [])
        # Pattern: hyphenated long names (stock photos with -p-500/-800/-1080 suffix)
        if re.match(r"^[a-z]+-[a-z]+-[a-z]+.*-p-\d+$", stem):
            print("  ✓ Filename pattern: Stock photo")
            return ("media", "photos_stock", None, [])
        # Pattern: hyphenated long names without -p- suffix (general descriptive names)
        if re.match(r"^[a-z]+-[a-z]+-[a-z]+.*-\d+$", stem):
            print("  ✓ Filename pattern: Stock photo")
            return ("media", "photos_stock", None, [])
        # Pattern: word_word (airbnb_earnings, austin_to_bombay)
        if re.match(r"^[a-z]+(_[a-z]+)+$", stem) and "_" in stem:
            print("  ✓ Filename pattern: Named image")
            return ("media", "photos_other", None, [])
        # Pattern: letter+number sprites (l10.png, l20_1.png, note01.png, img1.png)
        # Exclude uppercase-origin filenames — human-named files, not generated game assets
        if not has_uppercase and re.match(r"^[a-z]+\d+(_\d+)?$", stem):
            print("  ✓ Filename pattern: Sprite sequence")
            return ("game_assets", "sprites", None, [])
        # Pattern: word+number (drake2.png, grave2.png, void2.png)
        if not has_uppercase and re.match(r"^[a-z]+\d$", stem):
            print("  ✓ Filename pattern: Numbered variant")
            return ("game_assets", "sprites", None, [])
        # Pattern: hyphenated names (heart-beat.png, phone-call.png)
        # Exclude data visualization hyphenated terms
        data_viz_hyphenated = {
            "yearly-distribution",
            "monthly-distribution",
            "daily-distribution",
            "cost-breakdown",
            "revenue-chart",
            "sales-report",
            "time-series",
            "bar-chart",
            "pie-chart",
            "line-graph",
            "data-flow",
            "user-stats",
        }
        if re.match(r"^[a-z]+-[a-z]+(-[a-z]+)*(_\d{8}_\d{6})?(-copy)?$", stem):
            if stem in data_viz_hyphenated or any(
                term in stem
                for term in [
                    "distribution",
                    "chart",
                    "graph",
                    "report",
                    "stats",
                    "analytics",
                    "metrics",
                ]
            ):
                print("  ✓ Filename pattern: Data visualization")
                return ("technical", "data_visualization", None, [])
            print("  ✓ Filename pattern: Hyphenated asset")
            return ("game_assets", "sprites", None, [])
        # Pattern: two letters (dv.png, pv.png)
        if re.match(r"^[a-z]{2}$", stem):
            print("  ✓ Filename pattern: Two-letter asset")
            return ("game_assets", "sprites", None, [])
        # Pattern: tinyfont/font with numbers (tinyfont66_1.png)
        if re.match(r"^[a-z]+font\d+(_\d+)?$", stem):
            print("  ✓ Filename pattern: Font sprite")
            return ("game_assets", "fonts", None, [])
        # Pattern: repository templates
        if "repository" in stem or "template" in stem:
            print("  ✓ Filename pattern: Template image")
            return ("technical", "other", None, [])
        # Pattern: requests-logo type (word-word.png)
        if re.match(r"^[a-z]+-[a-z]+(-compressed)?$", stem):
            print("  ✓ Filename pattern: Logo/brand image")
            return ("media", "photos_other", None, [])
        # Pattern: hash ID with prefix (rs=xxx, shirt-xxx)
        if "=" in stem or re.match(r"^[a-z]+-\d+-[a-z0-9]+", stem):
            print("  ✓ Filename pattern: Generated ID image")
            return ("media", "photos_other", None, [])

    # =========================================================
    # ICON FILES: .ico → Technical/Config, .icns → GameAssets/Other
    # =========================================================
    # favicon.ico and other .ico files are typically web config
    if ext == ".ico":
        print(f"  ✓ Filename pattern: Icon file ({stem}.ico) → Technical/Config")
        return ("technical", "config", None, [])
    # .icns files are Mac app icons, often game-related
    if ext == ".icns":
        print(f"  ✓ Filename pattern: Mac icon file ({stem}.icns) → GameAssets/Other")
        return ("game_assets", "other", None, [])

    # =========================================================
    # ARCHIVE FILES: .zip, .tar, .gz, .rar → Technical/Archives
    # =========================================================
    archive_extensions = {".zip", ".tar", ".gz", ".rar", ".7z", ".bz2"}
    if ext in archive_extensions:
        print(f"  ✓ Filename pattern: Archive file ({ext})")
        return ("technical", "archives", None, [])

    # =========================================================
    # CERTIFICATE/KEY FILES: .pem, .crt, .key → Technical/Security
    # =========================================================
    cert_extensions = {".pem", ".crt", ".key", ".cer", ".p12", ".pfx"}
    if ext in cert_extensions:
        print(f"  ✓ Filename pattern: Certificate/key file ({ext})")
        return ("technical", "security", None, [])

    # =========================================================
    # TEMPLATE FILES: .tpl → Technical/Templates
    # =========================================================
    if ext == ".tpl":
        print("  ✓ Filename pattern: Template file")
        return ("technical", "templates", None, [])

    # =========================================================
    # FILES WITHOUT EXTENSION: Likely system/timezone data
    # =========================================================
    if not ext:
        # City/location names (timezone data): Abidjan, Accra, Adelaide, BajaNorte
        if re.match(r"^[A-Z][a-zA-Z-]+$", filename):
            print("  ✓ Filename pattern: Timezone/system data")
            return ("technical", "other", None, [])
        # ALL CAPS names or with underscores (system data): ACT, ADOM, ADOM_1
        if re.match(r"^[A-Z][A-Z0-9_]+$", filename):
            print("  ✓ Filename pattern: System data")
            return ("technical", "other", None, [])
        # Numeric IDs (social media): 2242610712719705
        if re.match(r"^\d{10,}$", filename):
            print("  ✓ Filename pattern: Numeric ID file")
            return ("technical", "other", None, [])
        # Hash strings: 93419027627913a58f0b3fbb9ba9decea2a6bb
        if re.match(r"^[0-9a-f]{20,}$", filename):
            print("  ✓ Filename pattern: Hash file")
            return ("technical", "other", None, [])
        # Script/tool names: activate-global-python-argcomplete
        if re.match(r"^[a-z]+(-[a-z]+)+$", filename):
            print("  ✓ Filename pattern: Script/tool")
            return ("technical", "other", None, [])
        # CamelCase system files: CodeDirectory, CodeResources
        if re.match(r"^[A-Z][a-z]+[A-Z][a-zA-Z0-9-]*$", filename):
            print("  ✓ Filename pattern: macOS system file")
            return ("technical", "other", None, [])
        # Lowercase with underscore and number: tsserver_1, bq
        if re.match(r"^[a-z]+(_\d+)?$", filename):
            print("  ✓ Filename pattern: System tool")
            return ("technical", "other", None, [])
        # GMT timezones: GMT-0, GMT-1, GMT+5
        if re.match(r"^(GMT|UTC)[+-]?\d+$", filename):
            print("  ✓ Filename pattern: Timezone data")
            return ("technical", "other", None, [])
        # ChangeLog files with timestamp: ChangeLog_20251210_203502
        if filename.startswith("ChangeLog"):
            print("  ✓ Filename pattern: ChangeLog")
            return ("technical", "documentation", None, [])
        # Tool with hyphen and alphanumeric: gcloud-crc32c, css2
        if re.match(r"^[a-z]+-?[a-z0-9]+$", filename):
            print("  ✓ Filename pattern: System utility")
            return ("technical", "other", None, [])
        # Query parameter style: m=b, m=core, m=RsR2Mc
        if re.match(r"^[a-z]=[a-zA-Z0-9]+$", filename):
            print("  ✓ Filename pattern: Query param file")
            return ("technical", "other", None, [])
        # Makefile patterns: Makefile, Makefile_timestamp
        if filename.startswith("Makefile"):
            print("  ✓ Filename pattern: Makefile")
            return ("technical", "other", None, [])
        # iframe_api, node-which_1 style
        if re.match(r"^[a-z]+[_-][a-z0-9]+(_\d+)?$", filename):
            print("  ✓ Filename pattern: System file")
            return ("technical", "other", None, [])
        # City names with underscore: Rio_Gallegos
        if re.match(r"^[A-Z][a-z]+_[A-Z][a-z]+$", filename):
            print("  ✓ Filename pattern: Location data")
            return ("technical", "other", None, [])
        # Hash with prefix: rs=AA2YrTskOaSug7MVZwlus97OpUaPcMM3bw
        if "=" in filename:
            print("  ✓ Filename pattern: Hash parameter file")
            return ("technical", "other", None, [])
        # Single JS-style file: js(1)
        if re.match(r"^[a-z]+\(\d+\)$", filename):
            print("  ✓ Filename pattern: Script copy")
            return ("technical", "other", None, [])

    # =========================================================
    # PRESENTATION FILES: .pptx, .ppt, .key → Business/Presentations
    # =========================================================
    presentation_extensions = {".pptx", ".ppt", ".key", ".odp"}
    if ext in presentation_extensions:
        print(f"  ✓ Filename pattern: Presentation ({ext})")
        return ("business", "presentations", None, [])

    # =========================================================
    # FINANCIAL XLSX FILES: earnings, budget, expenses, revenue
    # =========================================================
    if ext == ".xlsx":
        financial_keywords = [
            "earnings",
            "budget",
            "expenses",
            "revenue",
            "income",
            "profit",
            "loss",
            "financial",
        ]
        if any(kw in stem for kw in financial_keywords):
            print("  ✓ Filename pattern: Financial spreadsheet")
            return ("financial", "other", None, [])
        # Data exports: Users.xlsx, Users_timestamp.xlsx (use original stem for case)
        original_stem = file_path.stem
        if re.match(r"^[A-Z][a-z]+s(_\d{8}_\d{6})?$", original_stem):
            print("  ✓ Filename pattern: Data export")
            return ("technical", "data", None, [])

    # =========================================================
    # DOUBLE EXTENSION FILES: something.jpg.jp2
    # =========================================================
    if ".jpg.jp2" in filename.lower() or ".jpeg.jp2" in filename.lower():
        print("  ✓ Filename pattern: Converted photo")
        return ("media", "photos_other", None, [])

    # =========================================================
    # TRAVEL DOCUMENTS: austin_to_bombay, trip_to_paris
    # =========================================================
    if "_to_" in stem or "-to-" in stem:
        print("  ✓ Filename pattern: Travel document")
        return ("personal", "other", None, [])

    # =========================================================
    # ZOUK: Dance events and classes
    # =========================================================
    if "zouk" in stem:
        print("  ✓ Filename pattern: Zouk")
        return ("zouk", "events", None, [])

    # =========================================================
    # LEGAL/CONTRACT DOCUMENTS: DPA, NDA, SLA, TOS, MSA, SOW
    # Must check BEFORE event documents (dates in filenames)
    # =========================================================
    legal_keywords = [
        "dpa",
        "nda",
        "sla",
        "tos",
        "msa",
        "sow",
        "contract",
        "agreement",
        "terms",
        "privacy",
        "policy",
        "license",
        "eula",
        "gdpr",
        "hipaa",
        "compliance",
        "legal",
        "addendum",
        "amendment",
    ]
    if ext in {".pdf", ".docx", ".doc"}:
        if any(kw in stem for kw in legal_keywords):
            print("  ✓ Filename pattern: Legal/contract document")
            return ("business", "legal", None, [])

    # =========================================================
    # EVENT DOCUMENTS: Oct25Event, Nov15Party (month+day in name)
    # =========================================================
    month_patterns = [
        "jan",
        "feb",
        "mar",
        "apr",
        "may",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
    ]
    if ext in {".docx", ".doc", ".pdf"}:
        for month in month_patterns:
            if month in stem and re.search(r"\d{1,2}", stem):
                print("  ✓ Filename pattern: Event document")
                return ("personal", "other", None, [])

    # =========================================================
    # JOURNAL ENTRIES: Dream, Diary, Thoughts, Reflections
    # =========================================================
    journal_keywords = [
        "dream",
        "diary",
        "journal",
        "thoughts",
        "reflection",
        "memoir",
        "nightbefore",
        "morningafter",
        "dayof",
    ]
    if ext in {".docx", ".doc", ".txt", ".md"}:
        if any(kw in stem for kw in journal_keywords):
            print("  ✓ Filename pattern: Journal entry")
            return ("personal", "other", None, [])

    # =========================================================
    # PERSONAL DOCUMENTS: Short name + version (Sumedh3.docx)
    # =========================================================
    if ext in {".docx", ".doc"}:
        original_stem = file_path.stem
        # Short name followed by digit (personal documents)
        if re.match(r"^[A-Z][a-z]+\d$", original_stem):
            print("  ✓ Filename pattern: Personal document")
            return ("personal", "other", None, [])
        # PascalCase event names (ZoukSocial, DanceNight)
        if re.match(r"^([A-Z][a-z]+){2,}$", original_stem):
            print("  ✓ Filename pattern: Event document")
            return ("personal", "other", None, [])

    # =========================================================
    # PITCH/PROPOSAL FILES: Pitch, Proposal with version
    # =========================================================
    if ext in {".pptx", ".pdf", ".docx"}:
        if stem.startswith("pitch") or stem.startswith("proposal"):
            print("  ✓ Filename pattern: Business pitch/proposal")
            return ("business", "presentations", None, [])

    return None
