"""Content-based file organizer with classification/routing methods.

Owns the full classification layer of the production organizer
(``scripts/file_organizer_content_based.py``): filename/filepath patterns,
game-asset detection, entity (organization/person) detection, media routing,
identification-document OCR, screenshot OCR+CLIP sub-classification, and the
unified CLIP+text scoring used for weak-image enhancement.

``ContentBasedFileOrganizer`` in the script subclasses this and adds only
pipeline concerns (schema generation, graph persistence, renaming, moves).
"""

import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.classifiers.entity_detector import _has_human_name_signal
from src.organizers.base_organizer import BaseOrganizer
from src.organizers.category_config import CONTENT_CATEGORY_PATHS
from shared.constants import GAME_SPRITE_KEYWORDS, SIDECAR_DIR_SUFFIXES
from shared.filename_classifier import (
    RESEARCH_CATEGORY,
    SCHOLARLY_ARTICLE_SCHEMA_TYPE,
)
from shared.filename_classifier import (
    classify_by_filename_patterns as _classify_by_filename_patterns,
)

# OCR (docTR via shared.ocr_classifier) and PDF availability probe.
# pypdf and PIL are imported here (even though extraction lives in
# src.analyzers.text_extractor) so that OCR_AVAILABLE keeps gating the
# pipeline on the full dependency set, matching historical behavior.
try:
    import pypdf  # noqa: F401 — availability probe
    from PIL import Image  # noqa: F401 — availability probe
    from shared.ocr_classifier import SCREENSHOT_KEYWORDS
    from shared.ocr_classifier import classify_by_ocr as _shared_classify_by_ocr
    from shared.ocr_classifier import (
        extract_ocr_with_confidence,
        is_ocr_available,
    )

    OCR_AVAILABLE = is_ocr_available()

    # HEIC support
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:
        pass
except ImportError:
    OCR_AVAILABLE = False
    SCREENSHOT_KEYWORDS: Dict[str, List[str]] = {}
    _shared_classify_by_ocr = None
    extract_ocr_with_confidence = None

# KIE (Key Information Extraction) imports
try:
    from shared.kie_utils import extract_kie_fields, is_kie_available

    KIE_AVAILABLE = is_kie_available()
except ImportError:
    KIE_AVAILABLE = False

# CLIP enhancement constants for weak image classification
try:
    from shared.constants import (
        CLIP_CATEGORY_PROMPTS,
        CLIP_CONTENT_LABELS,
        CLIP_ENHANCE_THRESHOLD,
        CLIP_LABEL_TO_ORGANIZER,
    )

    ENHANCED_CLIP_AVAILABLE = True
except ImportError:
    ENHANCED_CLIP_AVAILABLE = False
    CLIP_CATEGORY_PROMPTS: List[str] = []
    CLIP_CONTENT_LABELS: List[str] = []
    CLIP_LABEL_TO_ORGANIZER: Dict[str, Tuple[str, str]] = {}
    CLIP_ENHANCE_THRESHOLD: float = 0.3

# CLIP classifier — used by the weak-image enhancement signal (_run_clip_signal).
# Image composition/face detection lives in the injected image_analyzer.
try:
    from shared.clip_utils import get_clip_classifier
except ImportError:
    get_clip_classifier = None
    print("Warning: Vision libraries not available. Install open-clip-torch, torch, opencv-python")

# CLIP cache support
try:
    from shared.clip_cache import CLIP_CACHE_AVAILABLE, get_cached_embedding
except ImportError:
    CLIP_CACHE_AVAILABLE = False

# Reverse map: full CLIP prompt → short CLIP_CONTENT_LABELS key.
# Built once at import time; used by _run_clip_signal.
_CLIP_PROMPT_TO_LABEL: dict = (
    dict(zip(CLIP_CATEGORY_PROMPTS, CLIP_CONTENT_LABELS)) if ENHANCED_CLIP_AVAILABLE else {}
)

# Minimum OCR confidence required to treat text as reliable for ID doc detection.
# Low-confidence OCR on a photo (e.g. a blurry selfie) must not trigger passport detection.
# Uses docTR word-level confidence (true 0–1 scale).
_OCR_CONFIDENCE_THRESHOLD = 0.3

# Minimum keyword-hit ratio to accept a screenshot OCR sub-classification.
# classify_by_ocr() scores as hits/len(keywords), so this is calibrated to that
# scale — NOT to CLIP probability space.  With SCREENSHOT_MIN_HITS=2 and the
# largest category having 14 keywords, 2 hits = 14.3%.  A threshold of 0.10
# accepts any category that cleared SCREENSHOT_MIN_HITS (the real quality bar);
# the 0.30 gate previously used was copied from _OCR_CONFIDENCE_THRESHOLD and
# silently rejected valid 3–18% scores as "low confidence".
_SCREENSHOT_OCR_KEYWORD_THRESHOLD = 0.10

# Unified-scoring weights for the image classification path.
# CLIP score (already 0-1) is used as-is; OCR-text contributes a prior scaled by
# extraction length, plus an agreement boost when both signals point at the same
# (category, subcategory). Values are tuned so that text — which is typically
# more semantically specific than CLIP — wins ties on longer OCR extractions,
# while CLIP retains primacy when text extraction is sparse or unparseable.
_TEXT_SIGNAL_PRIOR = 0.80
_TEXT_LENGTH_FULL_CHARS = 200
_TEXT_MIN_CHARS = 30
_SIGNAL_AGREEMENT_BOOST = 0.15

# Option C: `person` is demoted from a category to a graph relationship.
# classify_by_person() still detects *which kind* of person document this is,
# but now maps that detection onto the `personal` category's subcategories
# instead of returning a separate `person` category. See
# docs/changelog/2.1.0/PERSON_TAXONOMY_OPTION_C_PLAN.md for the full rationale.
_PERSON_SUBCAT_TO_PERSONAL_SUBCAT = {
    "contacts": "contacts",
    "employees": "employment",
    "references": "employment",
    "clients": "other",
    "travel": "other",
    "events": "events",
    "journal": "journal",
    "family": "other",
    "other": "other",
}

# Person-detection keyword thresholds. The generic person types need two
# indicator hits; `contacts` needs three because its indicators ('contact',
# 'phone:', '@', …) appear in the footer of virtually any official letter —
# two hits is just a letterhead, three implies an actual contact-card layout.
_PERSON_MIN_KEYWORD_HITS = 2
_CONTACTS_MIN_KEYWORD_HITS = 3

# Legal-document veto for the person keyword tier: court documents carry clerk
# contact blocks that satisfy the generic contacts indicators and were misfiled
# under Personal/Contacts (e.g. "NOTICE OF CT SETTING"). When at least
# _LEGAL_SIGNAL_MIN_HITS of these appear, classify_by_person defers so content
# analysis (which classifies these as legal) decides; person attribution still
# lands via the people_names that classification returns.
_LEGAL_DOCUMENT_SIGNALS = frozenset({
    "court", "cause no", "docket", "plaintiff", "defendant",
    "hearing", "petitioner", "respondent", "judicial",
})
_LEGAL_SIGNAL_MIN_HITS = 2

# Content categories that indicate a *document* (as opposed to a photo, game
# asset, or generic media). Used to let clean, high-confidence OCR text override
# a filename-driven game-asset/media guess — e.g. "medellin_bloodwork" matches
# the game sprite keyword "blood" but OCRs as Spanish lab results → medical.
# Excludes 'media', 'game_assets', and 'uncategorized' on purpose.
_DOCUMENT_CONTENT_CATEGORIES = frozenset(
    {"financial", "medical", "legal", "business", "personal", "technical", "research", "education"}
)


class ContentOrganizer(BaseOrganizer):
    """
    Organizer that classifies files by content, filename patterns, and entities.

    Heavy dependencies (content classifier, image analyzer, metadata parser,
    text extractor, MIME enricher) are injected; all default to ``None`` so the
    organizer stays constructible in lightweight/test contexts.
    """

    _GEOGRAPHIC_LABELS = frozenset(
        {
            "a landscape or nature scene",
            "a cityscape or urban scene",
            "a building or architecture",
        }
    )

    # Subset of game_sprite_keywords that implies sprite (vs texture) classification.
    _SPRITE_DISCRIMINATOR_KEYWORDS = frozenset({
        'frame', 'sprite', 'leg', 'arm', 'head', 'torso', 'body',
        'wing', 'hair', 'face', 'mouth', '_grey', '_gray',
        'assassins', 'atonement', 'arrow_v', 'arrow_h', 'add',
        '2h_', '1h_', 'dagger', 'sword', 'axe', 'hammer', 'mace',
        'beard', 'bling', 'hiero', 'mustache', 'scar', 'tattoo',
        'earring', 'necklace', 'bracelet', 'glasses', 'mask', 'hood',
    })

    def __init__(
        self,
        base_path: Path,
        content_classifier: Any,
        organize_by_date: bool = False,
        organize_by_location: bool = False,
        enable_cost_tracking: bool = False,
        db_path: str | None = None,
        *,
        image_analyzer: Any = None,
        metadata_parser: Any = None,
        text_extractor: Any = None,
        enricher: Any = None,
        screenshot_content_classifier: Any = None,
        ocr_available: Optional[bool] = None,
    ) -> None:
        super().__init__(
            base_path=base_path,
            organize_by_date=organize_by_date,
            organize_by_location=organize_by_location,
            enable_cost_tracking=enable_cost_tracking,
            db_path=db_path,
        )
        self.classifier = content_classifier
        self.image_analyzer = image_analyzer
        self.metadata_parser = metadata_parser
        self.text_extractor = text_extractor
        self.enricher = enricher
        # ContentClassifier used for screenshot OCR sub-classification (the
        # production script passes its image renamer's classifier here).
        self.screenshot_content_classifier = screenshot_content_classifier
        self.ocr_available = OCR_AVAILABLE if ocr_available is None else ocr_available

        # Temporary OCR metadata for the current file being processed.
        # Set inside detect_file_category; consumed by downstream persistence.
        self._last_file_ocr_confidence: Optional[float] = None
        self._last_file_detected_language: Optional[str] = None
        self._last_file_ocr_text: Optional[str] = None  # cached OCR text to avoid re-running
        # Structured per-file outputs (KIE result, research-paper metadata).
        # Keyed dict so new metadata types can land here without growing the
        # attribute surface.
        self._last_file_state: Dict[str, Any] = {}
        # Per-file CLIP enhance cache: (file_path, tuple(labels)) -> List of results
        self._clip_enhance_cache: Dict[tuple, list] = {}

        # Filepath-based classification (checked FIRST before content analysis)
        self.filepath_patterns: Dict[str, str] = {
            # Log files
            '.log': 'Technical/Logs',
            '.log.gz': 'Technical/Logs',
            '.out': 'Technical/Logs',
            # Python
            '.py': 'Technical/Python',
            '.pyc': 'Technical/Python/Compiled',
            '.pyw': 'Technical/Python',
            '.pyx': 'Technical/Python',
            '.pyd': 'Technical/Python',
            # JavaScript/TypeScript
            '.js': 'Technical/JavaScript',
            '.jsx': 'Technical/JavaScript',
            '.mjs': 'Technical/JavaScript',
            '.cjs': 'Technical/JavaScript',
            '.ts': 'Technical/TypeScript',
            '.tsx': 'Technical/TypeScript',
            # Web
            '.html': 'Technical/Web',
            '.htm': 'Technical/Web',
            '.css': 'Technical/Web',
            '.scss': 'Technical/Web',
            '.sass': 'Technical/Web',
            '.less': 'Technical/Web',
            # Shell scripts
            '.sh': 'Technical/Shell',
            '.bash': 'Technical/Shell',
            '.zsh': 'Technical/Shell',
            '.fish': 'Technical/Shell',
            # Config files
            '.json': 'Technical/Config',
            '.yaml': 'Technical/Config',
            '.yml': 'Technical/Config',
            '.toml': 'Technical/Config',
            '.ini': 'Technical/Config',
            '.conf': 'Technical/Config',
            '.config': 'Technical/Config',
            '.env': 'Technical/Config',
            # Database
            '.sql': 'Technical/Database',
            '.db': 'Technical/Database',
            '.sqlite': 'Technical/Database',
            '.sqlite3': 'Technical/Database',
            # Java/Kotlin
            '.java': 'Technical/Java',
            '.class': 'Technical/Java/Compiled',
            '.jar': 'Technical/Java/Archives',
            '.kt': 'Technical/Kotlin',
            '.kts': 'Technical/Kotlin',
            # C/C++
            '.c': 'Technical/C',
            '.cpp': 'Technical/C++',
            '.cc': 'Technical/C++',
            '.cxx': 'Technical/C++',
            '.h': 'Technical/C/Headers',
            '.hpp': 'Technical/C++/Headers',
            # Go
            '.go': 'Technical/Go',
            # Rust
            '.rs': 'Technical/Rust',
            # Ruby
            '.rb': 'Technical/Ruby',
            '.rake': 'Technical/Ruby',
            # PHP
            '.php': 'Technical/PHP',
            # Swift
            '.swift': 'Technical/Swift',
            # Markdown and docs
            '.md': 'Technical/Documentation',
            '.markdown': 'Technical/Documentation',
            '.rst': 'Technical/Documentation',
            '.adoc': 'Technical/Documentation',
            # Version control
            '.gitignore': 'Technical/VersionControl',
            '.gitattributes': 'Technical/VersionControl',
            # Build/Package files
            'Makefile': 'Technical/Build',
            'Dockerfile': 'Technical/Build',
            'docker-compose.yml': 'Technical/Build',
            'package.json': 'Technical/Build',
            'package-lock.json': 'Technical/Build',
            'yarn.lock': 'Technical/Build',
            'Cargo.toml': 'Technical/Build',
            'go.mod': 'Technical/Build',
            'requirements.txt': 'Technical/Build',
            'Pipfile': 'Technical/Build',
            'pyproject.toml': 'Technical/Build',
        }

        # Content-based organization structure: shared taxonomy, deepcopied
        # because __init__ extends the screenshots sub-dict per instance.
        self.category_paths: Dict[str, Any] = deepcopy(CONTENT_CATEGORY_PATHS)

        # Extend screenshot sub-folders from classifier taxonomies so that
        # content labels map directly to folder paths without a separate lookup.
        _screenshots = self.category_paths["media"]["photos"]["screenshots"]
        for key in SCREENSHOT_KEYWORDS:
            if key not in _screenshots:
                folder = key.replace("_", " ").title().replace(" ", "")
                _screenshots[key] = f"Media/Photos/Screenshots/{folder}"
        for key in getattr(self.classifier, "patterns", None) or []:
            if key not in _screenshots:
                _screenshots[key] = f"Media/Photos/Screenshots/{key.title()}"

        # Game asset detection patterns
        self.game_audio_keywords: List[str] = [
            'bolt', 'spell', 'magic', 'cast', 'chirp', 'crossbow', 'dagger',
            'sword', 'arrow', 'bow', 'heal', 'potion', 'lightning', 'fire',
            'ice', 'acid', 'poison', 'explosion', 'blast', 'summon', 'dispel',
            'petrification', 'neutralize', 'slow', 'darkness', 'achievement',
            'quest', 'unlock', 'lock', 'door', 'chest', 'coin', 'pickup',
            'attack', 'hit', 'damage', 'death', 'footstep', 'jump', 'land',
            'monster', 'creature', 'enemy', 'boss', 'battle', 'combat',
            'starving', 'hunger', 'thirst', 'eat', 'drink', 'sleep',
            'fiddle', 'lute', 'mandoline', 'glockenspiel', 'instrument',
            'identify', 'greater', 'mental',
        ]

        self.game_music_keywords: List[str] = [
            'battle', 'boss', 'dungeon', 'castle', 'forest', 'town', 'village',
            'temple', 'ruins', 'cave', 'mountain', 'ocean', 'desert', 'snow',
            'victory', 'defeat', 'theme', 'menu', 'credits', 'intro', 'outro',
            'mysterious', 'dark', 'light', 'epic', 'calm', 'peaceful', 'tension',
            'chaos', 'hope', 'despair', 'triumph', 'march', 'symphony', 'monotony',
            'drakalor', 'altar', 'lawful', 'chaotic', 'neutral', 'alignment',
            'dwarven', 'elven', 'orcish', 'halls', 'abandon', 'corrupting',
            'breeze', 'clockwork', 'knowledge', 'oddisey', 'final', 'welcome',
        ]

        # Single-homed in shared.constants (same list the production script used).
        self.game_sprite_keywords: List[str] = GAME_SPRITE_KEYWORDS

        # Regex patterns for game asset detection (numbered sprites, variants)
        self.game_sprite_patterns: List[re.Pattern[str]] = [
            re.compile(r'^\d+_\d+$'),  # 42_8, 51_3, 16_3 (sprite sheets)
            re.compile(r'^\d+_grey(_\d+)?$', re.IGNORECASE),  # 10_grey, 10_grey_1
            re.compile(r'^\d+_f(_\d+)?$', re.IGNORECASE),  # 283_f, 283_f_1
            re.compile(r'^[a-z]+_\d+$', re.IGNORECASE),  # frame_1, item_42
            re.compile(r'^[a-z]+_[a-z]+_\d+$', re.IGNORECASE),  # assassins_deed_1
            re.compile(r'^\d+h_[a-z]+(_\d+)?$', re.IGNORECASE),  # 2h_axe, 2h_axe_1
            re.compile(r'^[a-z]+_v(_\d+)?$', re.IGNORECASE),  # arrow_v, arrow_v_1
            re.compile(r'^[a-z]+_h(_\d+)?$', re.IGNORECASE),  # arrow_h, arrow_h_1
            re.compile(r'^(head|torso|arm|leg|body|wing|hair)_\w+', re.IGNORECASE),  # body parts
            re.compile(r'^(weapon|armor|item|sprite|frame|tile)\d*_', re.IGNORECASE),  # game prefixes
        ]

        # Game font sprite sheet patterns
        self.game_font_keywords: List[str] = [
            'broguefont', 'gamefont', 'pixelfont', 'bitfont', 'font_',
            '_font', 'fontsheet', 'font_atlas', 'fontatlas', 'charset',
            'glyphs', 'tilefont', 'asciifont', 'ascii_font',
        ]

    # ------------------------------------------------------------------ #
    # Classification methods                                               #
    # ------------------------------------------------------------------ #

    def classify_by_filepath(self, file_path: Path) -> Optional[str]:
        """
        Classify file based on filepath patterns (extension, filename).

        Returns:
            Category path string if matched, None otherwise
        """
        # Check exact filename matches first (e.g., Makefile, Dockerfile)
        filename = file_path.name
        if filename in self.filepath_patterns:
            return self.filepath_patterns[filename]

        # Check file extension
        ext = file_path.suffix.lower()
        if ext in self.filepath_patterns:
            base_path = self.filepath_patterns[ext]

            # Try to extract project name from path
            project_name = self.extract_project_name(file_path)
            if project_name:
                # Add project subdirectory (e.g., Technical/Python/MyProject)
                return f"{base_path}/{project_name}"

            return base_path

        # Check double extensions (e.g., .log.gz)
        if len(file_path.suffixes) >= 2:
            double_ext = ''.join(file_path.suffixes[-2:]).lower()
            if double_ext in self.filepath_patterns:
                return self.filepath_patterns[double_ext]

        return None

    def extract_project_name(self, file_path: Path) -> Optional[str]:
        """
        Extract project name from file path.

        Looks for common project indicators in path:
        - Directory names like 'myproject', 'my-app', etc.
        - Skips common non-project directories

        Returns:
            Project name if found, None otherwise
        """
        skip_dirs = {
            'src', 'lib', 'bin', 'dist', 'build', 'out', 'target',
            'node_modules', 'venv', '.venv', 'env', '__pycache__',
            'scripts', 'tests', 'test', 'docs', 'doc', 'examples',
            'static', 'public', 'assets', 'resources', 'config',
            'home', 'users', 'documents', 'downloads', 'desktop',
            'code', 'projects', 'dev', 'work', 'repos', 'git',
        }

        # Get all parent directories
        parts = file_path.parts

        # Look backwards from the file for a likely project directory
        for i in range(len(parts) - 2, -1, -1):  # Skip the filename itself
            dir_name = parts[i].lower()

            # Skip common non-project directories
            if dir_name in skip_dirs:
                continue

            # Skip hidden directories
            if dir_name.startswith('.'):
                continue

            # Found a likely project directory
            # Return with original case preserved
            return parts[i]

        return None

    def classify_game_asset(self, file_path: Path) -> Optional[Tuple[str, str]]:
        """
        Classify file as a game asset based on filename patterns.

        Returns:
            Tuple of (category, subcategory) or None if not a game asset
        """
        stem = file_path.stem.lower()
        ext = file_path.suffix.lower()

        # Remove timestamp suffixes for pattern matching (e.g., _20251120_164506)
        clean_stem = re.sub(r'_\d{8}_\d{6}$', '', stem)

        # Check for audio files (.wav, .ogg, .mp3)
        if ext in ['.wav', '.ogg', '.mp3', '.flac', '.aac']:
            # Check for game music patterns (usually .ogg files with specific names)
            if ext == '.ogg':
                for keyword in self.game_music_keywords:
                    if keyword in stem:
                        return ('game_assets', 'music')

            # Check for game sound effects
            for keyword in self.game_audio_keywords:
                if keyword in stem:
                    return ('game_assets', 'audio')

        # Check for image files that are game sprites/textures
        # Exclude files with 'screenshot' in name — those are screen captures
        if ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tga', '.dds'] and 'screenshot' not in stem:
            # Check for game font sprite sheets first
            for keyword in self.game_font_keywords:
                if keyword in stem or keyword in clean_stem:
                    return ('game_assets', 'fonts')

            # Check regex patterns for numbered sprites and variants
            for pattern in self.game_sprite_patterns:
                if pattern.match(clean_stem):
                    return ('game_assets', 'sprites')

            # Check for sprite/texture keyword patterns
            for keyword in self.game_sprite_keywords:
                if keyword in stem or keyword in clean_stem:
                    # Distinguish between sprites and textures
                    if any(kw in stem or kw in clean_stem for kw in self._SPRITE_DISCRIMINATOR_KEYWORDS):
                        return ('game_assets', 'sprites')
                    else:
                        return ('game_assets', 'textures')

        # Check for font files
        if ext in ['.ttf', '.otf', '.woff', '.woff2', '.eot', '.fon', '.fnt']:
            if ext == '.ttf':
                return ('fonts', 'truetype')
            elif ext == '.otf':
                return ('fonts', 'opentype')
            elif ext in ['.woff', '.woff2', '.eot']:
                return ('fonts', 'web')
            else:
                return ('fonts', 'other')

        return None

    def classify_by_organization(
        self, text: str, filename: str
    ) -> Optional[Tuple[str, str, str]]:
        """
        Classify file primarily by Organization entity detection.

        Looks for strong organization indicators like:
        - Company names in headers/footers
        - Official letterheads
        - Business correspondence
        - Invoices, contracts with company names

        Returns:
            Tuple of (category, subcategory, org_name) or None if no strong organization match
        """
        if not text or len(text) < 50:
            return None

        text_lower = text.lower()

        # Organization type indicators
        org_indicators: Dict[str, List[str]] = {
            'government': [
                'department of', 'internal revenue', 'irs', 'social security',
                'state of', 'county of', 'city of', 'municipality', 'federal',
                'government', 'agency', 'bureau', 'commission', 'dmv',
                'passport', 'immigration', 'customs', 'treasury',
            ],
            'healthcare': [
                'hospital', 'clinic', 'medical center', 'health system',
                'healthcare', 'physicians', 'doctor', 'patient', 'diagnosis',
                'prescription', 'pharmacy', 'insurance claim', 'medicare',
                'medicaid', 'hipaa', 'medical record', 'lab results',
            ],
            'financial': [
                'bank', 'credit union', 'investment', 'brokerage', 'mortgage',
                'loan', 'account statement', 'transaction', 'wire transfer',
                'routing number', 'account number', 'fdic', 'securities',
            ],
            'educational': [
                'university', 'college', 'school', 'academy', 'institute',
                'transcript', 'diploma', 'degree', 'enrollment', 'registrar',
                'financial aid', 'tuition', 'semester', 'course', 'student id',
            ],
            'nonprofit': [
                'foundation', 'charity', 'nonprofit', 'non-profit', '501(c)',
                'donation', 'volunteer', 'mission', 'charitable',
            ],
            'employers': [
                'offer letter', 'employment agreement', 'w-2', 'w2', 'pay stub',
                'payroll', 'human resources', 'hr department', 'employee id',
                'benefits enrollment', 'performance review', 'termination',
            ],
            'vendors': [
                'invoice', 'purchase order', 'po number', 'vendor id',
                'supplier', 'bill to', 'ship to', 'payment terms', 'net 30',
            ],
            'clients': [
                'client', 'customer', 'service agreement', 'statement of work',
                'sow', 'proposal', 'quote', 'estimate', 'engagement letter',
            ],
        }

        # Check for organization type indicators
        for org_type, keywords in org_indicators.items():
            matches = sum(1 for kw in keywords if kw in text_lower)
            if matches >= 2:  # Require at least 2 keyword matches
                # Try to extract organization name
                companies = self.classifier.extract_company_names(text)
                org_name = companies[0] if companies else None
                if org_name:
                    return ('organization', org_type, org_name)

        return None

    def classify_by_person(
        self, text: str, filename: str
    ) -> Optional[Tuple[str, str, List[str]]]:
        """
        Classify file primarily by Person entity detection.

        Looks for strong person indicators like:
        - Resumes/CVs
        - Contact information (vCards)
        - Personal identification documents
        - Reference letters

        Returns:
            Tuple of (category, subcategory, person_names) or None if no strong person match
        """
        if not text or len(text) < 50:
            return None

        text_lower = text.lower()
        filename_lower = filename.lower()

        # Person type indicators
        person_indicators: Dict[str, List[str]] = {
            'contacts': [
                'contact', 'phone:', 'email:', 'address:', 'mobile:',
                'tel:', 'fax:', 'linkedin', 'twitter', '@',
            ],
            'employees': [
                'employee', 'staff', 'team member', 'department:', 'title:',
                'hire date', 'start date', 'position:', 'role:',
            ],
            'references': [
                'reference', 'recommendation', 'letter of', 'to whom it may concern',
                'i am pleased to', 'i highly recommend', 'worked with',
            ],
            'clients': [
                'client profile', 'customer profile', 'client information',
                'account holder', 'policyholder',
            ],
        }

        # Check filename patterns for resumes/CVs
        resume_patterns = ['resume', 'cv', 'curriculum', 'vitae']
        if any(pat in filename_lower for pat in resume_patterns):
            people = self.classifier.extract_people_names(text)
            return ('personal', 'contacts', people if people else [])

        # Legal-document veto: court filings carry clerk contact info that
        # satisfies the generic indicators below; defer to content analysis.
        legal_hits = sum(1 for kw in _LEGAL_DOCUMENT_SIGNALS if kw in text_lower)
        if legal_hits >= _LEGAL_SIGNAL_MIN_HITS:
            return None

        # Check for person type indicators
        for person_type, keywords in person_indicators.items():
            matches = sum(1 for kw in keywords if kw in text_lower)
            min_hits = (
                _CONTACTS_MIN_KEYWORD_HITS
                if person_type == 'contacts'
                else _PERSON_MIN_KEYWORD_HITS
            )
            if matches >= min_hits:
                people = self.classifier.extract_people_names(text)
                if people and _has_human_name_signal(text):
                    subcat = _PERSON_SUBCAT_TO_PERSONAL_SUBCAT[person_type]
                    return ('personal', subcat, people)

        return None

    def classify_media_file(
        self, file_path: Path, image_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Tuple[str, str, str]]:
        """
        Classify media files (photos, videos, audio) into subcategories.

        Returns:
            Tuple of (category, media_type, subcategory) or None if not a media file
            Example: ('media', 'photos', 'documents') or ('media', 'videos', 'recordings')
        """
        filename = file_path.name.lower()
        stem = file_path.stem.lower()
        ext = file_path.suffix.lower()

        # Videos - .mp4, .mov, .avi, .mkv, .webm, .m4v
        if ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v', '.flv', '.wmv']:
            # Screen recordings
            if 'screen' in stem or 'recording' in stem or 'capture' in stem:
                return ('media', 'videos', 'screencasts')
            # Exports (from video editors)
            elif 'export' in stem or 'render' in stem or 'final' in stem or 'cut' in stem:
                return ('media', 'videos', 'exports')
            # Default to recordings
            else:
                return ('media', 'videos', 'recordings')

        # Audio - .mp3, .wav, .m4a, .aac, .flac, .ogg (but not game music)
        if ext in ['.mp3', '.m4a', '.aac', '.flac', '.wma']:
            # Podcasts
            if 'podcast' in stem or 'episode' in stem or 'interview' in stem:
                return ('media', 'audio', 'podcasts')
            # Music
            elif 'song' in stem or 'album' in stem or 'track' in stem or 'music' in stem:
                return ('media', 'audio', 'music')
            # Voice recordings
            elif 'recording' in stem or 'voice' in stem or 'memo' in stem or 'audio' in stem:
                return ('media', 'audio', 'recordings')
            # Default to recordings
            else:
                return ('media', 'audio', 'recordings')

        # Photos - .jpg, .jpeg, .png, .heic, .gif, .webp, .bmp
        if ext in ['.jpg', '.jpeg', '.png', '.heic', '.gif', '.webp', '.bmp', '.tiff', '.tif']:
            # Screenshots — fall through to None so CLIP/OCR sub-classification
            # at Priority 4.5 can route to Browser/Terminal/Docs/etc.
            if (
                filename.startswith('screenshot')
                or 'screen shot' in filename
                or 'screenshot' in stem
            ):
                return None

            # Scanned documents/receipts (OCR will detect text)
            if 'scan' in stem or 'receipt' in stem or 'document' in stem or 'invoice' in stem:
                return ('media', 'photos', 'documents')

            # Travel photos (has GPS metadata)
            if image_metadata and image_metadata.get('gps_coordinates'):
                # If we have GPS coordinates, it's likely a travel photo
                return ('media', 'photos', 'travel')

            # Photos with datetime (camera photos) - organize by type
            if image_metadata and image_metadata.get('datetime'):
                # Photos with camera EXIF data are likely personal photos
                # Default to 'other' category for general photos
                return ('media', 'photos', 'other')

            # Photos without metadata - still categorize as media if they're actual photos
            # (as opposed to game sprites which would be caught earlier)
            if ext in ['.jpg', '.jpeg', '.heic']:
                return ('media', 'photos', 'other')

            # PNG files without clear classification fall through
            # (could be screenshots, documents, or game assets that weren't caught)
            return None

        return None

    def classify_by_filename_patterns(
        self, file_path: Path
    ) -> Optional[Tuple[str, str, Optional[str], List[str]]]:
        """
        Classify file based on filename patterns before content extraction.

        Delegates to the shared ``filename_classifier`` so the rule set is
        single-homed with ``scripts/file_organizer_content_based.py``. Returns
        ``(category, subcategory, company_name, people_names)`` or ``None``.
        """
        return _classify_by_filename_patterns(
            file_path,
            game_sprite_keywords=self.game_sprite_keywords,
            last_file_state=self._last_file_state,
        )

    # ------------------------------------------------------------------ #
    # Text extraction (cache-aware wrappers over the injected extractor)   #
    # ------------------------------------------------------------------ #

    def extract_text_from_image(self, image_path: Path) -> str:
        """Extract text from image using docTR OCR.

        Reuses cached OCR text from ID detection or the image renamer
        when available, avoiding a redundant OCR pass. The cache is
        organizer state; the pure extraction lives in TextExtractor.
        """
        if not self.ocr_available:
            return ""

        # Return cached OCR text from an earlier pipeline stage if available.
        if self._last_file_ocr_text:
            return self._last_file_ocr_text

        if self.text_extractor is None:
            return ""
        return self.text_extractor.extract_text_from_image(image_path)

    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract text from PDF (searchable or scanned)."""
        if not self.ocr_available or self.text_extractor is None:
            return ""
        return self.text_extractor.extract_text_from_pdf(pdf_path)

    def extract_text_from_docx(self, docx_path: Path) -> str:
        """Extract text from Word document."""
        if self.text_extractor is None:
            return ""
        return self.text_extractor.extract_text_from_docx(docx_path)

    def extract_text_from_xlsx(self, xlsx_path: Path) -> str:
        """Extract text from Excel spreadsheet."""
        if self.text_extractor is None:
            return ""
        return self.text_extractor.extract_text_from_xlsx(xlsx_path)

    def extract_text(self, file_path: Path) -> str:
        """Extract text from various file types.

        MIME detection stays here (organizer owns the enricher); the image
        branch routes through the cache-aware wrapper above, everything else
        dispatches through the organizer methods so overrides keep working.
        """
        mime_type = (
            self.enricher.detect_mime_type(str(file_path)) if self.enricher is not None else None
        )
        file_ext = file_path.suffix.lower()

        if mime_type and mime_type.startswith("image/"):
            return self.extract_text_from_image(file_path)
        elif mime_type == "application/pdf" or file_ext == ".pdf":
            return self.extract_text_from_pdf(file_path)
        elif file_ext in [".docx", ".doc"]:
            return self.extract_text_from_docx(file_path)
        elif file_ext in [".xlsx", ".xls"]:
            return self.extract_text_from_xlsx(file_path)

        # Text files and unknown types: pure extraction, no organizer state.
        if self.text_extractor is None:
            return ""
        return self.text_extractor.extract_text(file_path, mime_type)

    # ------------------------------------------------------------------ #
    # CLIP / unified-scoring signals                                       #
    # ------------------------------------------------------------------ #

    def _map_clip_label(
        self, label: str, image_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Tuple[str, str]]:
        """Map a CLIP label to (category, subcategory), upgrading to travel if GPS present."""
        mapping = CLIP_LABEL_TO_ORGANIZER.get(label)
        if not mapping:
            return None
        cat, subcat = mapping
        if (
            image_metadata
            and image_metadata.get("gps_coordinates")
            and label in self._GEOGRAPHIC_LABELS
        ):
            cat, subcat = "media", "photos_travel"
        return (cat, subcat)

    def _merge_clip_text_scores(
        self,
        clip_candidate: Optional[Tuple[str, str]],
        clip_score: float,
        text_candidate: Optional[Tuple[str, str]],
        text_chars: int,
    ) -> Optional[Tuple[Tuple[str, str], float, str]]:
        """Combine CLIP and OCR-text signals into a per-(category, subcategory)
        weighted score. Returns (winner, total_score, sources_str) or None.

        Used by both the main image path and enhance_weak_image_classification
        so that PDF/PNG sibling files of the same content converge on the same
        category regardless of which extraction modality dominates.
        """
        scores: Dict[Tuple[str, str], float] = {}
        sources: Dict[Tuple[str, str], List[str]] = {}
        if clip_candidate and clip_score > 0:
            scores[clip_candidate] = scores.get(clip_candidate, 0.0) + clip_score
            sources.setdefault(clip_candidate, []).append(f"CLIP {clip_score:.2f}")
        if text_candidate and text_chars >= _TEXT_MIN_CHARS:
            text_score = _TEXT_SIGNAL_PRIOR * min(1.0, text_chars / _TEXT_LENGTH_FULL_CHARS)
            scores[text_candidate] = scores.get(text_candidate, 0.0) + text_score
            sources.setdefault(text_candidate, []).append(f"text {text_score:.2f}")
        if clip_candidate and text_candidate and clip_candidate == text_candidate:
            scores[clip_candidate] += _SIGNAL_AGREEMENT_BOOST
            sources[clip_candidate].append("agree")
        if not scores:
            return None
        winner, top = max(scores.items(), key=lambda kv: kv[1])
        return winner, top, ", ".join(sources[winner])

    def _cross_check_with_clip(
        self,
        file_path: Path,
        image_metadata: Optional[Dict],
        category: str,
        subcategory: str,
        text_chars: int,
    ) -> Tuple[str, str]:
        """Cross-check a text-derived image classification against CLIP and
        return the merged winner, swapping (cat, sub) only when CLIP outscores
        the text candidate.
        """
        clip_candidate, clip_score = self._run_clip_signal(file_path, image_metadata)
        if not clip_candidate:
            return (category, subcategory)
        merged = self._merge_clip_text_scores(
            clip_candidate,
            clip_score,
            (category, subcategory),
            text_chars,
        )
        if not merged:
            return (category, subcategory)
        (m_cat, m_sub), m_score, m_src = merged
        if (m_cat, m_sub) == (category, subcategory):
            return (category, subcategory)
        print(f"  Unified → {m_cat}/{m_sub} ({m_src}; total {m_score:.2f})")
        return (m_cat, m_sub)

    def _run_clip_signal(
        self,
        file_path: Path,
        image_metadata: Optional[Dict] = None,
    ) -> Tuple[Optional[Tuple[str, str]], float]:
        """Run the 20-category CLIP classifier and map its top label.

        Returns (candidate, score) or (None, 0.0) if CLIP is unavailable or
        below the enhancement threshold.
        """
        if (
            not ENHANCED_CLIP_AVAILABLE
            or self.image_analyzer is None
            or not self.image_analyzer.vision_available
        ):
            return (None, 0.0)
        enhance_cache_key = (str(file_path), tuple(CLIP_CATEGORY_PROMPTS))
        try:
            if enhance_cache_key in self._clip_enhance_cache:
                results = self._clip_enhance_cache[enhance_cache_key]
            elif CLIP_CACHE_AVAILABLE:
                results = get_cached_embedding(file_path, CLIP_CATEGORY_PROMPTS, prompt_prefix="")
                self._clip_enhance_cache[enhance_cache_key] = results
            else:
                results = get_clip_classifier().classify_raw(file_path, CLIP_CATEGORY_PROMPTS)
                self._clip_enhance_cache[enhance_cache_key] = results
            best_prompt, best_score = results[0]
            best_label = _CLIP_PROMPT_TO_LABEL.get(best_prompt, best_prompt)
        except Exception as e:
            print(f"  CLIP signal error: {e}")
            return (None, 0.0)
        if best_score < CLIP_ENHANCE_THRESHOLD:
            return (None, 0.0)
        return (self._map_clip_label(best_label, image_metadata), best_score)

    def enhance_weak_image_classification(
        self, file_path: Path, image_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Tuple[str, str]]:
        """Run full 20-category CLIP + OCR fallback for weakly classified images.

        Only called for images that would otherwise land in photos_other or uncategorized.
        Returns (category, subcategory) or None to keep original classification.
        """
        clip_candidate, clip_score = self._run_clip_signal(file_path, image_metadata)
        # Do NOT bail when CLIP is weak — that is exactly when OCR text should
        # decide. _merge_clip_text_scores tolerates a missing CLIP signal and
        # returns None only when neither CLIP nor text yields a candidate.

        text_candidate: Optional[Tuple[str, str]] = None
        text_chars = 0
        if self.ocr_available:
            try:
                ocr_text = self.extract_text_from_image(file_path)
                if ocr_text and len(ocr_text) >= _TEXT_MIN_CHARS:
                    text_chars = len(ocr_text)
                    text_cat, text_subcat, _, _ = self.classifier.classify_content(
                        ocr_text, file_path.name
                    )
                    if text_cat != "uncategorized":
                        text_candidate = (text_cat, text_subcat)
            except Exception as e:
                print(f"  CLIP enhance OCR error: {e}")

        merged = self._merge_clip_text_scores(
            clip_candidate,
            clip_score,
            text_candidate,
            text_chars,
        )
        if not merged:
            return None
        winner, top_score, src = merged
        print(f"  Unified → {winner[0]}/{winner[1]} ({src}; total {top_score:.2f})")
        return winner

    def _ocr_document_override(self, file_path: Path) -> Optional[Tuple[str, str]]:
        """Return a (category, subcategory) from OCR content when a document image
        was misrouted by a filename heuristic (e.g. "bloodwork" → game "blood").

        Runs OCR (reusing cached text when present), classifies it, and returns the
        content category only when OCR is reliable and maps to a genuine document
        category (_DOCUMENT_CONTENT_CATEGORIES). Returns None otherwise so the
        caller keeps its original classification.
        """
        if not getattr(self, "ocr_available", False):
            return None
        ocr_text = self._last_file_ocr_text
        if not ocr_text:
            _res = extract_ocr_with_confidence(file_path, max_chars=0)
            if _res:
                ocr_text = _res.text
                self._last_file_ocr_confidence = _res.confidence
                self._last_file_detected_language = _res.language
                if ocr_text:
                    self._last_file_ocr_text = ocr_text
        conf = self._last_file_ocr_confidence
        if not ocr_text or len(ocr_text) < _TEXT_MIN_CHARS:
            return None
        if conf is not None and conf < _OCR_CONFIDENCE_THRESHOLD:
            return None
        cat, subcat, _, _ = self.classifier.classify_content(ocr_text, file_path.name)
        if cat in _DOCUMENT_CONTENT_CATEGORIES:
            return (cat, subcat)
        return None

    # ------------------------------------------------------------------ #
    # Category detection pipeline                                          #
    # ------------------------------------------------------------------ #

    def detect_file_category(
        self,
        file_path: Path,
        display_path: Path | None = None,
    ) -> Tuple[str, str, str, str, Optional[str], List[str], Dict[str, Any]]:
        """
        Detect file category based on content.

        Args:
            file_path: Physical path to the file on disk (used for content reading).
            display_path: Optional override path whose *name* is used for
                filename-pattern classification.  When the image renamer proposes
                a rename in dry-run mode, display_path carries the descriptive
                name while file_path still points to the original file.

        Priority order (executed in this exact sequence; first match wins):
        0a. Renamed-screenshot content routing (display_path vs file_path)
        0b. Filename pattern detection (fastest - no content extraction needed)
        1.  Organization / Person entity detection (document-type files)
        3.  Game asset detection (audio, sprites, textures)
        3.  Filepath-based classification (file extensions, filenames)
        3.5 Identification-document detection via OCR (passport, ID, license)
        4.  Media file classification (photos, videos, audio)
        4.5 Screenshot sub-classification via OCR + CLIP
        5.  Photo composition analysis (people / home interior)
        6.  Regular text extraction and content/KIE classification

        Returns:
            Tuple of (main_category, subcategory, schema_type, extracted_text,
            company_name, people_names, image_metadata)
        """
        self._last_file_ocr_confidence = None
        self._last_file_detected_language = None
        self._last_file_ocr_text = None
        self._last_file_state.clear()
        self._clip_enhance_cache.clear()

        pattern_path = display_path or file_path

        # Determine schema type and MIME type early (needed for multiple paths)
        mime_type = (
            self.enricher.detect_mime_type(str(file_path)) if self.enricher is not None else None
        )
        if mime_type:
            if mime_type.startswith("image/"):
                schema_type = "ImageObject"
            elif mime_type == "application/pdf":
                schema_type = "DigitalDocument"
            elif mime_type.startswith("video/"):
                schema_type = "VideoObject"
            elif mime_type.startswith("audio/"):
                schema_type = "AudioObject"
            else:
                schema_type = "DigitalDocument"
        else:
            schema_type = "DigitalDocument"

        # PRIORITY 0a: Renamed screenshots → route to category sub-folder
        # When the image renamer classified a screenshot (e.g. "Screenshot ..." →
        # "20260320_terminal_session.png"), match the content label against
        # _SCREENSHOT_KEYWORDS and ContentClassifier.patterns keys directly.
        if display_path and display_path != file_path and "screenshot" in file_path.stem.lower():
            renamed_stem = display_path.stem.lower()
            screenshots_dict = self.category_paths["media"]["photos"]["screenshots"]
            # Check longer keys first so "terminal_session" matches before "terminal"
            for key in sorted(screenshots_dict, key=len, reverse=True):
                if key != "other" and key in renamed_stem:
                    print(f"  ✓ Screenshot content: {key}")
                    return ("media", f"photos_screenshots_{key}", schema_type, "", None, [], {})

        # PRIORITY 0b: Filename pattern detection (fastest - no content extraction needed)
        # Handles: Google invoices, resumes, technical files, legal docs,
        # business docs, entity files
        filename_result = self.classify_by_filename_patterns(pattern_path)
        if filename_result:
            category, subcategory, company_name, people_names = filename_result
            # Handle skip category for duplicates
            if category == "skip":
                return ("skip", subcategory, schema_type, "", None, [], {})
            if category == RESEARCH_CATEGORY:
                schema_type = SCHOLARLY_ARTICLE_SCHEMA_TYPE
            # Point A: enhance weak photos_other from filename patterns for images
            if subcategory == "photos_other" and schema_type == "ImageObject":
                enhanced = self.enhance_weak_image_classification(file_path)
                if enhanced:
                    return (enhanced[0], enhanced[1], schema_type, "", None, [], {})
            return (category, subcategory, schema_type, "", company_name, people_names, {})

        # PRIORITY 1: Organization and Person detection for document-type files
        # Only apply to document/PDF types (not images, audio, video)
        if schema_type == "DigitalDocument" or mime_type == "application/pdf":
            print("  Checking for Organization/Person entities...")
            extracted_text = self.extract_text(file_path)

            if extracted_text and len(extracted_text) >= 50:
                # Try Organization detection first
                org_result = self.classify_by_organization(extracted_text, file_path.name)
                if org_result:
                    category, subcategory, org_name = org_result
                    print(f"  ✓ Organization detected: {org_name} ({subcategory})")
                    return (category, subcategory, schema_type, extracted_text, org_name, [], {})

                # Try Person detection second
                person_result = self.classify_by_person(extracted_text, file_path.name)
                if person_result:
                    category, subcategory, people_names = person_result
                    print(
                        f"  ✓ Person detected: {', '.join(people_names[:3]) if people_names else 'Unknown'} ({subcategory})"  # noqa: E501
                    )
                    return (
                        category,
                        subcategory,
                        schema_type,
                        extracted_text,
                        None,
                        people_names,
                        {},
                    )

        # PRIORITY 3: Check for game assets (before filepath patterns)
        game_asset = self.classify_game_asset(file_path)
        if game_asset:
            category, subcategory = game_asset
            # A game keyword can collide with a real word (e.g. "blood" in
            # "bloodwork"). For the ambiguous "textures" bucket on images, let
            # clean high-confidence OCR document text override the guess.
            if subcategory == "textures" and schema_type == "ImageObject":
                override = self._ocr_document_override(file_path)
                if override:
                    print(
                        f"  ✓ OCR document override: {override[0]}/{override[1]} "
                        f"(was game_assets/{subcategory})"
                    )
                    return (
                        override[0],
                        override[1],
                        schema_type,
                        self._last_file_ocr_text or "",
                        None,
                        [],
                        {},
                    )
            print(f"  ✓ Game asset detected: {subcategory}")
            return (category, subcategory, schema_type, "", None, [], {})

        # PRIORITY 3: Check filepath patterns (most efficient and accurate for code files)
        filepath_category = self.classify_by_filepath(file_path)
        if filepath_category:
            print(f"  ✓ Filepath match: {filepath_category}")
            # Return filepath-based category as a special marker
            # We'll handle this in get_destination_path
            return ("filepath", filepath_category, schema_type, "", None, [], {})

        # Extract metadata for images
        image_metadata: Dict[str, Any] = {}
        if (
            schema_type == "ImageObject"
            and self.metadata_parser is not None
            and self.metadata_parser.metadata_available
        ):
            print("  Extracting image metadata...")
            image_metadata = self.metadata_parser.get_metadata_summary(file_path)

            if image_metadata.get("datetime"):
                dt = image_metadata["datetime"]
                print(f"  ✓ Photo taken: {dt.strftime('%Y-%m-%d %H:%M:%S')}")

            if image_metadata.get("gps_coordinates"):
                coords = image_metadata["gps_coordinates"]
                print(f"  ✓ GPS: {coords[0]:.6f}, {coords[1]:.6f}")

            if image_metadata.get("location_name"):
                print(f"  ✓ Location: {image_metadata['location_name']}")

        # PRIORITY 3.5: Check for identification documents in images (passport, ID, license)
        # These should go to Personal/Identification, not Media/
        id_result = self._classify_identification_document(
            file_path,
            schema_type,
            image_metadata,
        )
        if id_result is not None:
            return id_result

        # PRIORITY 4: Check for media files (photos, videos, audio)
        # This runs after metadata extraction so we can use GPS/datetime for classification
        media_classification = self.classify_media_file(file_path, image_metadata)
        if media_classification:
            category, media_type, subcategory = media_classification
            # Point B: enhance weak photos/other for images
            if media_type == "photos" and subcategory == "other":
                enhanced = self.enhance_weak_image_classification(file_path, image_metadata)
                if enhanced:
                    print(f"  ✓ Enhanced media: {enhanced[0]}/{enhanced[1]}")
                    return (enhanced[0], enhanced[1], schema_type, "", None, [], image_metadata)
            print(f"  ✓ Media file detected: {media_type}/{subcategory}")
            return (
                category,
                f"{media_type}_{subcategory}",
                schema_type,
                "",
                None,
                [],
                image_metadata,
            )

        # PRIORITY 4.5: Screenshot sub-classification via OCR + CLIP
        screenshot_result = self._classify_screenshot_ocr(
            file_path,
            schema_type,
            image_metadata,
        )
        if screenshot_result is not None:
            return screenshot_result

        # PRIORITY 5: Check for photos with people (social) / home interior
        photo_result = self._classify_photo_composition(
            file_path,
            schema_type,
            image_metadata,
        )
        if photo_result is not None:
            return photo_result

        # PRIORITY 6: Regular text extraction and classification
        return self._classify_by_content_and_kie(
            file_path,
            schema_type,
            image_metadata,
        )

    def _classify_identification_document(
        self,
        file_path: Path,
        schema_type: str,
        image_metadata: Dict[str, Any],
    ) -> Optional[Tuple[str, str, str, str, Optional[str], List[str], Dict[str, Any]]]:
        """PRIORITY 3.5: Detect identification documents in images (passport, ID, license).

        These should go to Person/ folder, not Media/.  Always runs OCR + KIE side
        effects (storing OCR confidence/language/text and any KIE result on self) so
        that downstream tiers can reuse them; returns the person tuple on a match or
        None to fall through.
        """
        if not (schema_type == "ImageObject" and self.ocr_available):
            return None
        # Extract text from image via OCR with confidence metadata.
        # Low-confidence results (e.g. blurry photos) must not trigger ID detection.
        _ocr_result = (
            extract_ocr_with_confidence(file_path, max_chars=0) if self.ocr_available else None
        )
        ocr_text = _ocr_result.text if _ocr_result else ""
        _ocr_conf = _ocr_result.confidence if _ocr_result else None
        _ocr_lang = _ocr_result.language if _ocr_result else None
        # Store for later persistence (consumed by _persist_to_graph_store).
        self._last_file_ocr_confidence = _ocr_conf
        self._last_file_detected_language = _ocr_lang
        # Cache OCR text so extract_text_from_image can reuse it.
        if ocr_text:
            self._last_file_ocr_text = ocr_text
        # Attempt KIE structured field extraction when OCR is reliable.
        if KIE_AVAILABLE and _ocr_conf is not None and _ocr_conf >= _OCR_CONFIDENCE_THRESHOLD:
            self._last_file_state["kie_result"] = extract_kie_fields(file_path)
        _id_conf_ok = _ocr_conf is None or _ocr_conf >= _OCR_CONFIDENCE_THRESHOLD
        if ocr_text and len(ocr_text) >= 30 and _id_conf_ok:
            ocr_lower = ocr_text.lower()
            # Check for identification document keywords
            id_keywords = [
                "passport",
                "driver license",
                "driver's license",
                "identification",
                "united states of america",
                "department of state",
                "nationality",
                "date of birth",
                "place of birth",
                "surname",
                "given names",
                "social security",
                "state id",
                "national id",
            ]
            if any(kw in ocr_lower for kw in id_keywords):
                print("  ✓ Identification document detected via OCR")
                people_names = []

                # Method 1: Parse passport MRZ (Machine Readable Zone)
                # Format: P<COUNTRY{SURNAME}<<{GIVEN_NAME}<...
                mrz_match = re.search(r"P<[A-Z]{3}([A-Z]+)<<([A-Z]+)<", ocr_text)
                if mrz_match:
                    surname = mrz_match.group(1).title()
                    given = mrz_match.group(2).title()
                    people_names = [f"{given} {surname}"]

                # Method 2: Look for name fields with values on next line or after colon
                # Passport format: "Surname\nLEDLIE" or "Surname/Nom\nLEDLIE"
                if not people_names:
                    # Find surname (all caps, standalone on line)
                    surname_match = re.search(
                        r"(?:surname|nom|apellidos)[/\w\s]*\n\s*([A-Z]{2,})\b",
                        ocr_text,
                        re.IGNORECASE,
                    )
                    given_match = re.search(
                        r"(?:given\s*names?|pr[ée]noms?|nombres)[/\w\s]*\n\s*([A-Z]{2,})\b",
                        ocr_text,
                        re.IGNORECASE,
                    )
                    if surname_match and given_match:
                        people_names = [
                            f"{given_match.group(1).title()} {surname_match.group(1).title()}"
                        ]

                # Method 3: General name extraction patterns
                if not people_names:
                    people_names = self.classifier.extract_people_names(ocr_text)

                if people_names:
                    print(f"  ✓ Person identified: {people_names[0]}")
                return (
                    "personal",
                    "identification",
                    schema_type,
                    ocr_text,
                    None,
                    people_names,
                    image_metadata,
                )

        return None

    def _classify_screenshot_ocr(
        self,
        file_path: Path,
        schema_type: str,
        image_metadata: Dict[str, Any],
    ) -> Optional[Tuple[str, str, str, str, Optional[str], List[str], Dict[str, Any]]]:
        """PRIORITY 4.5: Screenshot sub-classification via OCR + CLIP.

        Raw screenshots (e.g. "Screenshot 2025-*") that bypassed Priority 4 because
        classify_media_file returned None.  Try OCR first (reliable for screenshots
        with text), then CLIP for non-text images.  Returns a classification tuple
        for any screenshot-named image, or None for non-screenshots.
        """
        _stem_lower = file_path.stem.lower()
        if not (
            schema_type == "ImageObject"
            and (
                _stem_lower.startswith("screenshot")
                or "screen shot" in _stem_lower
                or (
                    "screenshot" in _stem_lower
                    and not re.match(
                        r"^(browser|terminal|code|docs|settings|product|chat|dashboard)_",
                        _stem_lower,
                    )
                )
            )
        ):
            return None

        screenshots_dict = self.category_paths["media"]["photos"]["screenshots"]

        # Step 1: OCR-based sub-classification (dashboard, terminal, etc.)
        ocr_result = None
        if _shared_classify_by_ocr is not None:
            ocr_result = _shared_classify_by_ocr(
                file_path,
                content_classifier=self.screenshot_content_classifier,
            )
        if ocr_result:
            ocr_category, ocr_confidence, _ocr_scores, ocr_text = ocr_result
            if ocr_text:
                self._last_file_ocr_text = ocr_text
            if ocr_confidence < _SCREENSHOT_OCR_KEYWORD_THRESHOLD:
                print(
                    f"  ↪ Screenshot OCR low confidence ({ocr_confidence:.0%} < "
                    f"{_SCREENSHOT_OCR_KEYWORD_THRESHOLD:.0%}) — falling back to CLIP"
                )
            elif ocr_category in screenshots_dict:
                print(f"  ✓ Screenshot OCR sub-class: {ocr_category} ({ocr_confidence:.0%})")
                return (
                    "media",
                    f"photos_screenshots_{ocr_category}",
                    schema_type,
                    "",
                    None,
                    [],
                    image_metadata,
                )
            # OCR matched a non-screenshot Schema.org category — use it
            elif "_" in ocr_category:
                print(f"  ✓ Screenshot OCR reclassified: {ocr_category} ({ocr_confidence:.0%})")
                return (
                    ocr_category.split("_")[0],
                    ocr_category,
                    schema_type,
                    "",
                    None,
                    [],
                    image_metadata,
                )

        # Step 2: CLIP enhancement for images OCR couldn't classify
        enhanced = self.enhance_weak_image_classification(file_path, image_metadata)
        if enhanced:
            ecat, esubcat = enhanced
            # CLIP identified non-media content (e.g. game_assets) — use that
            if ecat not in ("media",):
                print(f"  ✓ Screenshot reclassified: {ecat}/{esubcat}")
                return (ecat, esubcat, schema_type, "", None, [], image_metadata)
            # CLIP identified a specific screenshot subcategory
            if "screenshots" in esubcat and esubcat != "photos_screenshots_other":
                print(f"  ✓ Screenshot CLIP sub-class: {esubcat}")
                return ("media", esubcat, schema_type, "", None, [], image_metadata)

        # Fallback: generic screenshot folder
        print("  ✓ Screenshot (unclassified)")
        return ("media", "photos_screenshots_other", schema_type, "", None, [], image_metadata)

    def _classify_photo_composition(
        self,
        file_path: Path,
        schema_type: str,
        image_metadata: Dict[str, Any],
    ) -> Optional[Tuple[str, str, str, str, Optional[str], List[str], Dict[str, Any]]]:
        """PRIORITY 5: Photo composition analysis (people / home interior).

        Returns a media/property_management tuple on a vision match, or None when
        vision is unavailable or no composition matched.
        """
        if not (
            schema_type == "ImageObject"
            and self.image_analyzer is not None
            and self.image_analyzer.vision_available
        ):
            return None
        print("  Analyzing image content...")

        # Single CLIP pass yields both composition flags (people / home interior).
        has_people, is_property_mgmt, scores = self.image_analyzer.analyze_for_organization(
            file_path
        )

        if has_people:
            print("  ✓ Detected: Photo with people")
            if scores:
                top_categories = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
                print(
                    f"  Top matches: {', '.join([f'{cat}: {score:.2%}' for cat, score in top_categories])}"  # noqa: E501
                )
            return ("media", "photos_social", schema_type, "", None, [], image_metadata)

        if is_property_mgmt:
            print("  ✓ Detected: Home interior without people")
            if scores:
                top_categories = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
                print(
                    f"  Top matches: {', '.join([f'{cat}: {score:.2%}' for cat, score in top_categories])}"  # noqa: E501
                )
            return ("property_management", "other", schema_type, "", None, [], image_metadata)

        return None

    def _classify_by_content_and_kie(
        self,
        file_path: Path,
        schema_type: str,
        image_metadata: Dict[str, Any],
    ) -> Tuple[str, str, str, str, Optional[str], List[str], Dict[str, Any]]:
        """PRIORITY 6: Regular text extraction and content/KIE classification.

        Terminal tier — always returns a result tuple (the fall-through default for
        detect_file_category).
        """
        print("  Extracting content...")
        extracted_text = self.extract_text(file_path)

        if extracted_text:
            print(f"  Extracted {len(extracted_text)} characters")

            kie_result = self._last_file_state.get("kie_result")
            kie_classification = None
            if kie_result is not None:
                kie_classification = self.classifier.classify_with_kie(
                    kie_result,
                    extracted_text,
                    file_path.name,
                )
            if kie_classification is not None:
                category, subcategory, company_name, people_names = kie_classification
                print(f"  ✓ KIE classification: {category}/{subcategory}")
            else:
                category, subcategory, company_name, people_names = (
                    self.classifier.classify_content(extracted_text, file_path.name)
                )

            if company_name:
                print(f"  Detected company: {company_name}")
            if people_names:
                print(
                    f"  Detected people: {', '.join(people_names[:3])}{' ...' if len(people_names) > 3 else ''}"  # noqa: E501
                )
            print(f"  Classified as: {category}/{subcategory}")

            if schema_type == "ImageObject" and category != "uncategorized":
                category, subcategory = self._cross_check_with_clip(
                    file_path,
                    image_metadata,
                    category,
                    subcategory,
                    len(extracted_text),
                )
        else:
            print("  No text extracted, using filename")
            category, subcategory, company_name, people_names = self.classifier.classify_content(
                "", file_path.name
            )

        # Point C: last-resort enhancement for uncategorized images
        if category == "uncategorized" and schema_type == "ImageObject":
            enhanced = self.enhance_weak_image_classification(file_path, image_metadata)
            if enhanced:
                print(f"  ✓ Enhanced uncategorized: {enhanced[0]}/{enhanced[1]}")
                return (
                    enhanced[0],
                    enhanced[1],
                    schema_type,
                    extracted_text,
                    None,
                    [],
                    image_metadata,
                )

        return (
            category,
            subcategory,
            schema_type,
            extracted_text,
            company_name,
            people_names,
            image_metadata,
        )

    def get_destination_path(
        self,
        file_path: Path,
        category: str,
        subcategory: str,
        company_name: Optional[str] = None,
        image_metadata: Optional[Dict[str, Any]] = None,
        people_names: Optional[List[str]] = None,
    ) -> Path:
        """
        Get the destination path for a file based on content category.

        Args:
            file_path: Path to the file
            category: Main category
            subcategory: Subcategory
            company_name: Optional company name for business/organization files
            image_metadata: Optional metadata for images (datetime, location)
            people_names: Optional list of people names for person-classified files

        Returns:
            Destination path for the file
        """
        # Special handling for filepath-based classification
        if category == 'filepath':
            # subcategory contains the full path (e.g., "Technical/Python/MyProject")
            relative_path = subcategory
        # Special handling for media files with nested structure
        elif category == 'media' and '_' in subcategory:
            # subcategory format: "photos_screenshots" or "photos_screenshots_browser"
            parts = subcategory.split('_', 1)  # Split into at most 2 parts
            if len(parts) == 2:
                media_type, media_subcat = parts
                if media_type in self.category_paths['media']:
                    media_dict = self.category_paths['media'][media_type]
                    if isinstance(media_dict, dict):
                        # Check for 3-level nesting (e.g., screenshots_browser)
                        if '_' in media_subcat:
                            parent_key, child_key = media_subcat.split('_', 1)
                            parent_val = media_dict.get(parent_key)
                            if isinstance(parent_val, dict):
                                relative_path = parent_val.get(
                                    child_key,
                                    parent_val.get(
                                        'other',
                                        f'Media/{media_type.capitalize()}/{parent_key.capitalize()}',
                                    ),
                                )
                            else:
                                relative_path = media_dict.get(
                                    media_subcat,
                                    media_dict.get('other', f'Media/{media_type.capitalize()}/Other'),
                                )
                        else:
                            val = media_dict.get(media_subcat)
                            if isinstance(val, dict):
                                relative_path = val.get(
                                    'other',
                                    f'Media/{media_type.capitalize()}/{media_subcat.capitalize()}',
                                )
                            elif val:
                                relative_path = val
                            else:
                                relative_path = media_dict.get(
                                    'other', f'Media/{media_type.capitalize()}/Other'
                                )
                    else:
                        relative_path = media_dict
                else:
                    relative_path = 'Media/Other'
            else:
                relative_path = 'Media/Other'
        elif category in self.category_paths:
            if isinstance(self.category_paths[category], dict):
                if subcategory in self.category_paths[category]:
                    relative_path = self.category_paths[category][subcategory]
                else:
                    relative_path = self.category_paths[category].get(
                        'other', f'{category.capitalize()}/Other'
                    )
            else:
                relative_path = self.category_paths[category]
        else:
            relative_path = 'Uncategorized'

        # Organization: Create entity-named subfolders under Organization/
        # Structure: Organization/{OrgName}/ for most types
        # Exception: Organization/Clients/{OrgName}/ for clients (nested subfolders)
        if category == 'organization' and company_name:
            sanitized_company = self.classifier.sanitize_company_name(company_name)
            # Only create company subfolder if name is valid (not a sentence fragment)
            if sanitized_company:
                if subcategory == 'clients':
                    # Clients get nested: Organization/Clients/{OrgName}/
                    relative_path = f"{relative_path}/{sanitized_company}"
                elif subcategory == 'meeting_notes':
                    # Meeting notes get nested: Organization/{OrgName}/Meeting Notes/
                    relative_path = f"{relative_path}/{sanitized_company}/Meeting Notes"
                else:
                    # All other org types: Organization/{OrgName}/
                    relative_path = f"{relative_path}/{sanitized_company}"

        # Legacy: client files from business category with company name
        if category == 'business' and subcategory == 'clients' and company_name:
            sanitized_company = self.classifier.sanitize_company_name(company_name)
            # Only create company subfolder if name is valid
            if sanitized_company:
                relative_path = f"{relative_path}/{sanitized_company}"

        # Date-based organization for images (if enabled and metadata available)
        if self.organize_by_date and image_metadata and image_metadata.get('year'):
            year = image_metadata['year']
            month = image_metadata['month']
            relative_path = f"Photos/{year}/{month:02d}"

        # Location-based organization for images (if enabled and location available)
        elif self.organize_by_location and image_metadata and image_metadata.get('location_name'):
            # Clean location name for folder
            location = image_metadata['location_name']
            # Take first part (usually city)
            city = location.split(',')[0].strip()
            # Sanitize for folder name
            safe_city = re.sub(r'[<>:"/\\|?*]', '', city)
            relative_path = f"Photos/Locations/{safe_city}"

        dest_dir = self.base_path / relative_path
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Handle duplicate filenames
        dest_path = dest_dir / file_path.name
        if dest_path.exists() and dest_path != file_path:
            stem = file_path.stem
            suffix = file_path.suffix
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_path = dest_dir / f"{stem}_{timestamp}{suffix}"

        return dest_path

    def should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped."""
        skip_files = {'.DS_Store', '.localized', 'Thumbs.db', 'desktop.ini'}
        skip_dirs = {'__pycache__', '.git', 'node_modules', '.venv', 'venv'}

        if file_path.name.startswith('.') and file_path.name not in {'.gitignore', '.env.example'}:
            return True

        if file_path.name in skip_files:
            return True

        if any(skip_dir in file_path.parts for skip_dir in skip_dirs):
            return True

        # Skip browser "Save Page As" sidecar folders (e.g. "foo_files/"): the
        # file lives under a parent dir whose name ends with a known suffix.
        if any(
            part.lower().endswith(SIDECAR_DIR_SUFFIXES)
            for part in file_path.parent.parts
        ):
            return True

        return False
