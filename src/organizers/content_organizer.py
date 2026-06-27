"""Content-based file organizer with classification/routing methods."""

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.organizers.base_organizer import BaseOrganizer
from shared.filename_classifier import (
    classify_by_filename_patterns as _classify_by_filename_patterns,
)

try:
    from src.classifiers import ContentClassifier
except ImportError:
    ContentClassifier = Any  # type: ignore[assignment,misc]

try:
    from src.analyzers.text_extractor import ExtractionResult as _ExtractionResult
    _EXTRACTION_RESULT_AVAILABLE = True
except ImportError:
    _EXTRACTION_RESULT_AVAILABLE = False

_OCR_CONFIDENCE_THRESHOLD = 0.3

# CLIP enhancement constants
try:
    from shared.constants import (
        CLIP_CATEGORY_PROMPTS,
        CLIP_CONTENT_LABELS,
        CLIP_ENHANCE_HIGH_THRESHOLD,
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
    CLIP_ENHANCE_HIGH_THRESHOLD: float = 0.6

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    from PIL import Image as PILImage
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class ContentOrganizer(BaseOrganizer):
    """
    Organizer that classifies files by content, filename patterns, and entities.

    Extracted from ContentBasedFileOrganizer in scripts/file_organizer_content_based.py.
    Heavy dependencies (ContentClassifier, image_analyzer) are injected.
    """

    _GEOGRAPHIC_LABELS = frozenset({
        "travel photo", "landscape", "nature", "beach", "mountain",
        "city", "architecture", "outdoor",
    })

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
    ) -> None:
        super().__init__(
            base_path=base_path,
            organize_by_date=organize_by_date,
            organize_by_location=organize_by_location,
            enable_cost_tracking=enable_cost_tracking,
            db_path=db_path,
        )
        self.classifier = content_classifier

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

        # Content-based organization structure
        self.category_paths: Dict[str, Any] = {
            'legal': {
                'contracts': 'Legal/Contracts',
                'real_estate': 'Legal/RealEstate',
                'corporate': 'Legal/Corporate',
                'other': 'Legal/Other',
            },
            'financial': {
                'tax': 'Financial/Tax',
                'invoices': 'Financial/Invoices',
                'statements': 'Financial/Statements',
                'other': 'Financial/Other',
            },
            'business': {
                'planning': 'Business/Planning',
                'marketing': 'Business/Marketing',
                'proposals': 'Business/Proposals',
                'presentations': 'Business/Presentations',
                'crm': 'Business/CRM',
                'hr': 'Business/HR',
                'meeting_notes': 'Business/MeetingNotes',
                'clients': 'Business/Clients',
                'other': 'Business/Other',
            },
            'personal': {
                'employment': 'Personal/Employment',
                'identification': 'Personal/Identification',
                'certificates': 'Personal/Certificates',
                'other': 'Personal/Other',
            },
            'medical': {
                'records': 'Medical/Records',
                'insurance': 'Medical/Insurance',
                'prescriptions': 'Medical/Prescriptions',
                'other': 'Medical/Other',
            },
            'property': {
                'leases': 'Property/Leases',
                'maintenance': 'Property/Maintenance',
                'other': 'Property/Other',
            },
            'education': {
                'coursework': 'Education/Coursework',
                'research': 'Education/Research',
                'records': 'Education/Records',
                'other': 'Education/Other',
            },
            'technical': {
                'documentation': 'Technical/Documentation',
                'architecture': 'Technical/Architecture',
                'config': 'Technical/Config',
                'data': 'Technical/Data',
                'logs': 'Technical/Logs',
                'web': 'Technical/Web',
                'software_packages': 'Technical/Software_Packages',
                'other': 'Technical/Other',
            },
            'creative': {
                'design': 'Creative/Design',
                'branding': 'Creative/Branding',
                'photos': 'Creative/Photos',
                'other': 'Creative/Other',
            },
            'property_management': 'Property_Management',
            'zouk': {
                'events': 'Zouk/Events',
                'classes': 'Zouk/Classes',
                'other': 'Zouk/Other',
            },
            'organization': {
                'clients': 'Organization/Clients',
                'vendors': 'Organization',
                'partners': 'Organization',
                'employers': 'Organization',
                'government': 'Organization',
                'healthcare': 'Organization',
                'property_management': 'Organization',
                'financial': 'Organization',
                'educational': 'Organization',
                'nonprofit': 'Organization',
                'meeting_notes': 'Organization',
                'other': 'Organization',
            },
            'person': {
                'contacts': 'Person',
                'employees': 'Person',
                'clients': 'Person',
                'family': 'Person',
                'references': 'Person',
                'travel': 'Person/Travel',
                'events': 'Person/Events',
                'journal': 'Person/Journal',
                'other': 'Person',
            },
            'game_assets': {
                'audio': 'GameAssets/Audio',
                'music': 'GameAssets/Music',
                'sprites': 'GameAssets/Sprites',
                'textures': 'GameAssets/Textures',
                'fonts': 'GameAssets/Fonts',
                'other': 'GameAssets/Other',
            },
            'fonts': {
                'truetype': 'CreativeWork/Fonts/TrueType',
                'opentype': 'CreativeWork/Fonts/OpenType',
                'web': 'CreativeWork/Fonts/Web',
                'other': 'CreativeWork/Fonts/Other',
            },
            'media': {
                'photos': {
                    'screenshots': {
                        'browser': 'Media/Photos/Screenshots/Browser',
                        'terminal': 'Media/Photos/Screenshots/Terminal',
                        'code': 'Media/Photos/Screenshots/CodeEditors',
                        'docs': 'Media/Photos/Screenshots/Docs',
                        'settings': 'Media/Photos/Screenshots/Settings',
                        'products': 'Media/Photos/Screenshots/Products',
                        'dashboard': 'Media/Photos/Screenshots/Dashboards',
                        'chat': 'Media/Photos/Screenshots/Chat',
                        'other': 'Media/Photos/Screenshots',
                    },
                    'travel': 'Media/Photos/Travel',
                    'portraits': 'Media/Photos/Portraits',
                    'events': 'Media/Photos/Events',
                    'documents': 'Media/Photos/Documents',
                    'social': 'Media/Photos/Social',
                    'chatgpt': 'Media/Photos/ChatGPT',
                    'facebook': 'Media/Photos/Facebook',
                    'logos': 'Media/Photos/Logos',
                    'stock': 'Media/Photos/Stock',
                    'nature': 'Media/Photos/Nature',
                    'lifestyle': 'Media/Photos/Lifestyle',
                    'products': 'Media/Photos/Products',
                    'other': 'Media/Photos/Other',
                },
                'videos': {
                    'recordings': 'Media/Videos/Recordings',
                    'exports': 'Media/Videos/Exports',
                    'screencasts': 'Media/Videos/Screencasts',
                    'other': 'Media/Videos/Other',
                },
                'audio': {
                    'recordings': 'Media/Audio/Recordings',
                    'music': 'Media/Audio/Music',
                    'podcasts': 'Media/Audio/Podcasts',
                    'other': 'Media/Audio/Other',
                },
                'graphics': {
                    'vector': 'Media/Graphics/Vector',
                    'icons': 'Media/Graphics/Icons',
                    'other': 'Media/Graphics/Other',
                },
                'other': 'Media/Other',
            },
            'uncategorized': 'Uncategorized',
        }

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

        self.game_sprite_keywords: List[str] = [
            'frame', 'item', 'segment', 'sprite', 'texture', 'tile',
            'leg', 'arm', 'head', 'torso', 'body', 'wing', 'tail',
            'hair', 'face', 'eye', 'mouth', 'hand', 'foot',
            'beard', 'bling', 'hiero', 'mustache', 'scar', 'tattoo',
            'earring', 'necklace', 'bracelet', 'glasses', 'mask', 'hood',
            'wall', 'floor', 'ceiling', 'door', 'window', 'stairs',
            'tree', 'rock', 'grass', 'water', 'lava', 'cloud',
            'sword', 'shield', 'armor', 'helmet', 'boot', 'glove',
            'potion', 'scroll', 'wand', 'staff', 'ring', 'amulet',
            'coin', 'gem', 'crystal', 'ore', 'metal', 'wood',
            'monster', 'enemy', 'npc', 'character', 'player', 'hero',
            'icon', 'button', 'ui', 'hud', 'menu', 'cursor',
            'particle', 'effect', 'explosion', 'smoke', 'blood',
            'corner', 'edge', 'border', 'container', 'btn', 'talent',
            'bar', 'over', 'down', 'up', 'left', 'right', 'main',
            'bottom', 'top', 'extension', 'descend', 'ascend',
            'mad_carpenter', 'no_more', 'bedroom', 'front', 'back',
            'upper', 'lower', 'middle', 'dead', 'alive', 'sleeping',
            'female', 'male', 'white', 'black', 'red', 'blue', 'green',
            'silver', 'gold', 'bronze', 'iron', 'steel', 'mithril',
            'hills', 'road', 'path', 'bridge', 'gate', 'fence',
            'tentacle', 'shadow', 'altar', 'dungeon', 'throne', 'torch',
            'cloak', 'champion', 'curse', 'warning', 'mouse', 'slider',
            'decal', 'column', 'banner', 'sewer', 'statue', 'pillar',
            'orc', 'dwarf', 'elf', 'hurth', 'helf', 'troll', 'goblin',
            'fire', 'ice', 'sand', 'mount', 'tmount', 'deco', 'entrance',
            'pupils', 'shoulders', 'stunned', 'poisoned', 'blind', 'deaf',
            'slowed', 'levitating', 'hungry', 'strained', 'next', 'prev',
            'groove', 'handle', 'cube', 'psf', 'inventory',
            '2h_axe', '2h_hammer', '1h_sword', '1h_axe', 'crossbow', 'longbow',
            'dagger', 'mace', 'flail', 'spear', 'halberd', 'scimitar',
            'assassins_deed', 'atonement', 'backstab', 'cleave', 'smite',
            'fireball', 'lightning', 'heal', 'buff', 'debuff', 'aura',
            'arrow_v', 'arrow_h', 'checkbox', 'radio', 'toggle', 'add',
            '_grey', '_gray', '_disabled', '_hover', '_active', '_pressed',
            '_selected', '_normal', '_highlight', '_glow', '_dark', '_light',
        ]

        self.game_sprite_patterns: List[re.Pattern[str]] = [
            re.compile(r'^\d+_\d+$'),
            re.compile(r'^\d+_grey(_\d+)?$', re.IGNORECASE),
            re.compile(r'^\d+_f(_\d+)?$', re.IGNORECASE),
            re.compile(r'^[a-z]+_\d+$', re.IGNORECASE),
            re.compile(r'^[a-z]+_[a-z]+_\d+$', re.IGNORECASE),
            re.compile(r'^\d+h_[a-z]+(_\d+)?$', re.IGNORECASE),
            re.compile(r'^[a-z]+_v(_\d+)?$', re.IGNORECASE),
            re.compile(r'^[a-z]+_h(_\d+)?$', re.IGNORECASE),
            re.compile(r'^(head|torso|arm|leg|body|wing|hair)_\w+', re.IGNORECASE),
            re.compile(r'^(weapon|armor|item|sprite|frame|tile)\d*_', re.IGNORECASE),
        ]

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
        filename = file_path.name
        if filename in self.filepath_patterns:
            return self.filepath_patterns[filename]

        ext = file_path.suffix.lower()
        if ext in self.filepath_patterns:
            base_path = self.filepath_patterns[ext]
            project_name = self.extract_project_name(file_path)
            if project_name:
                return f"{base_path}/{project_name}"
            return base_path

        if len(file_path.suffixes) >= 2:
            double_ext = ''.join(file_path.suffixes[-2:]).lower()
            if double_ext in self.filepath_patterns:
                return self.filepath_patterns[double_ext]

        return None

    def extract_project_name(self, file_path: Path) -> Optional[str]:
        """
        Extract project name from file path.

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
        parts = file_path.parts
        for i in range(len(parts) - 2, -1, -1):
            dir_name = parts[i].lower()
            if dir_name in skip_dirs:
                continue
            if dir_name.startswith('.'):
                continue
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

        clean_stem = re.sub(r'_\d{8}_\d{6}$', '', stem)

        if ext in ['.wav', '.ogg', '.mp3', '.flac', '.aac']:
            if ext == '.ogg':
                for keyword in self.game_music_keywords:
                    if keyword in stem:
                        return ('game_assets', 'music')
            for keyword in self.game_audio_keywords:
                if keyword in stem:
                    return ('game_assets', 'audio')

        if ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tga', '.dds']:
            for keyword in self.game_font_keywords:
                if keyword in stem or keyword in clean_stem:
                    return ('game_assets', 'fonts')

            for pattern in self.game_sprite_patterns:
                if pattern.match(clean_stem):
                    return ('game_assets', 'sprites')

            for keyword in self.game_sprite_keywords:
                if keyword in stem or keyword in clean_stem:
                    if any(kw in stem or kw in clean_stem for kw in self._SPRITE_DISCRIMINATOR_KEYWORDS):
                        return ('game_assets', 'sprites')
                    else:
                        return ('game_assets', 'textures')

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

        Returns:
            Tuple of (category, subcategory, org_name) or None
        """
        if not text or len(text) < 50:
            return None

        text_lower = text.lower()

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

        for org_type, keywords in org_indicators.items():
            matches = sum(1 for kw in keywords if kw in text_lower)
            if matches >= 2:
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

        Returns:
            Tuple of (category, subcategory, person_names) or None
        """
        if not text or len(text) < 50:
            return None

        text_lower = text.lower()
        filename_lower = filename.lower()

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

        resume_patterns = ['resume', 'cv', 'curriculum', 'vitae']
        if any(pat in filename_lower for pat in resume_patterns):
            people = self.classifier.extract_people_names(text)
            return ('person', 'contacts', people if people else [])

        for person_type, keywords in person_indicators.items():
            matches = sum(1 for kw in keywords if kw in text_lower)
            if matches >= 2:
                people = self.classifier.extract_people_names(text)
                if people:
                    return ('person', person_type, people)

        return None

    def classify_media_file(
        self, file_path: Path, image_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Tuple[str, str, str]]:
        """
        Classify media files (photos, videos, audio) into subcategories.

        Returns:
            Tuple of (category, media_type, subcategory) or None
        """
        filename_lower = file_path.name.lower()
        stem = file_path.stem.lower()
        ext = file_path.suffix.lower()

        if ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v', '.flv', '.wmv']:
            if 'screen' in stem or 'recording' in stem or 'capture' in stem:
                return ('media', 'videos', 'screencasts')
            elif 'export' in stem or 'render' in stem or 'final' in stem or 'cut' in stem:
                return ('media', 'videos', 'exports')
            else:
                return ('media', 'videos', 'recordings')

        if ext in ['.mp3', '.m4a', '.aac', '.flac', '.wma']:
            if 'podcast' in stem or 'episode' in stem or 'interview' in stem:
                return ('media', 'audio', 'podcasts')
            elif 'song' in stem or 'album' in stem or 'track' in stem or 'music' in stem:
                return ('media', 'audio', 'music')
            elif 'recording' in stem or 'voice' in stem or 'memo' in stem or 'audio' in stem:
                return ('media', 'audio', 'recordings')
            else:
                return ('media', 'audio', 'recordings')

        if ext in ['.jpg', '.jpeg', '.png', '.heic', '.gif', '.webp', '.bmp', '.tiff', '.tif']:
            if filename_lower.startswith('screenshot') or 'screen shot' in filename_lower:
                return ('media', 'photos', 'screenshots')

            if 'scan' in stem or 'receipt' in stem or 'document' in stem or 'invoice' in stem:
                return ('media', 'photos', 'documents')

            if image_metadata and image_metadata.get('gps_coordinates'):
                return ('media', 'photos', 'travel')

            if image_metadata and image_metadata.get('datetime'):
                return ('media', 'photos', 'other')

            if ext in ['.jpg', '.jpeg', '.heic']:
                return ('media', 'photos', 'other')

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
        )

    def enhance_weak_image_classification(
        self,
        file_path: Path,
        image_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Tuple[str, str]]:
        """Run full 20-category CLIP + OCR fallback for weakly classified images.

        Returns (category, subcategory) or None to keep original classification.
        """
        if not ENHANCED_CLIP_AVAILABLE:
            return None
        if not TORCH_AVAILABLE or not PIL_AVAILABLE:
            return None

        # image_analyzer must be injected externally if needed — check attribute
        image_analyzer = getattr(self, 'image_analyzer', None)
        if image_analyzer is None:
            return None
        if not image_analyzer.vision_available:
            return None
        if not image_analyzer.model or not image_analyzer.processor:
            return None

        try:
            image = PILImage.open(file_path)
        except Exception as e:
            print(f"  CLIP enhance: cannot open image: {e}")
            return None

        try:
            inputs = image_analyzer.processor(
                text=CLIP_CATEGORY_PROMPTS, images=image,
                return_tensors="pt", padding=True,
            )
            with torch.no_grad():
                probs = image_analyzer.model(**inputs).logits_per_image.softmax(dim=1)
            scores = {label: float(probs[0][i]) for i, label in enumerate(CLIP_CONTENT_LABELS)}
            best_label = max(scores, key=scores.get)
            best_score = scores[best_label]
            print(f"  CLIP enhance: {best_label} ({best_score:.1%})")
        except Exception as e:
            print(f"  CLIP enhance error: {e}")
            return None

        if best_score < CLIP_ENHANCE_THRESHOLD:
            return None

        if best_score >= CLIP_ENHANCE_HIGH_THRESHOLD:
            result = self._map_clip_label(best_label, image_metadata)
            if result:
                print(f"  CLIP enhance → {result[0]}/{result[1]} (high confidence)")
                return result

        ocr_text = getattr(self, '_extract_text_from_image', lambda p: None)(file_path)
        if ocr_text and len(ocr_text) >= 30:
            text_cat, text_subcat, _, _ = self.classifier.classify_content(ocr_text, file_path.name)
            if text_cat != "uncategorized":
                print(f"  CLIP enhance → {text_cat}/{text_subcat} (OCR fallback)")
                return (text_cat, text_subcat)

        result = self._map_clip_label(best_label, image_metadata)
        if result:
            print(f"  CLIP enhance → {result[0]}/{result[1]} (medium confidence)")
        return result

    def _map_clip_label(
        self,
        label: str,
        image_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Tuple[str, str]]:
        """Map a CLIP label to (category, subcategory), upgrading to travel if GPS present."""
        mapping = CLIP_LABEL_TO_ORGANIZER.get(label)
        if not mapping:
            return None
        cat, subcat = mapping
        if image_metadata and image_metadata.get("gps_coordinates") and label in self._GEOGRAPHIC_LABELS:
            cat, subcat = "media", "photos_travel"
        return (cat, subcat)

    def detect_file_category(
        self, file_path: Path
    ) -> Tuple[str, str, str, str, Optional[str], List[str], Dict[str, Any]]:
        """
        Detect file category based on content.

        Returns:
            Tuple of (main_category, subcategory, schema_type, extracted_text,
                      company_name, people_names, image_metadata)
        """
        enricher = getattr(self, 'enricher', None)
        mime_type = enricher.detect_mime_type(str(file_path)) if enricher else None
        if mime_type:
            if mime_type.startswith('image/'):
                schema_type = 'ImageObject'
            elif mime_type == 'application/pdf':
                schema_type = 'DigitalDocument'
            elif mime_type.startswith('video/'):
                schema_type = 'VideoObject'
            elif mime_type.startswith('audio/'):
                schema_type = 'AudioObject'
            else:
                schema_type = 'DigitalDocument'
        else:
            schema_type = 'DigitalDocument'

        filename_result = self.classify_by_filename_patterns(file_path)
        if filename_result:
            category, subcategory, company_name, people_names = filename_result
            if category == 'skip':
                return ('skip', subcategory, schema_type, '', None, [], {})
            if subcategory == 'photos_other' and schema_type == 'ImageObject':
                enhanced = self.enhance_weak_image_classification(file_path)
                if enhanced:
                    return (enhanced[0], enhanced[1], schema_type, '', None, [], {})
            return (category, subcategory, schema_type, '', company_name, people_names, {})

        extracted_text = ''
        if schema_type == 'DigitalDocument' or mime_type == 'application/pdf':
            print("  Checking for Organization/Person entities...")
            extract_text = getattr(self, 'extract_text', None)
            if extract_text:
                extracted_text = extract_text(file_path)

            if extracted_text and len(extracted_text) >= 50:
                org_result = self.classify_by_organization(extracted_text, file_path.name)
                if org_result:
                    category, subcategory, org_name = org_result
                    print(f"  ✓ Organization detected: {org_name} ({subcategory})")
                    return (category, subcategory, schema_type, extracted_text, org_name, [], {})

                person_result = self.classify_by_person(extracted_text, file_path.name)
                if person_result:
                    category, subcategory, people_names = person_result
                    names_str = ', '.join(people_names[:3]) if people_names else 'Unknown'
                    print(f"  ✓ Person detected: {names_str} ({subcategory})")
                    return (category, subcategory, schema_type, extracted_text, None, people_names, {})

        game_asset = self.classify_game_asset(file_path)
        if game_asset:
            category, subcategory = game_asset
            print(f"  ✓ Game asset detected: {subcategory}")
            return (category, subcategory, schema_type, '', None, [], {})

        filepath_category = self.classify_by_filepath(file_path)
        if filepath_category:
            print(f"  ✓ Filepath match: {filepath_category}")
            return ('filepath', filepath_category, schema_type, '', None, [], {})

        image_metadata: Dict[str, Any] = {}
        metadata_parser = getattr(self, 'metadata_parser', None)
        if schema_type == 'ImageObject' and metadata_parser and getattr(metadata_parser, 'metadata_available', False):
            print("  Extracting image metadata...")
            image_metadata = metadata_parser.get_metadata_summary(file_path)

        media_classification = self.classify_media_file(file_path, image_metadata)
        if media_classification:
            cat, media_type, subcat = media_classification
            if media_type == 'photos' and subcat == 'other':
                enhanced = self.enhance_weak_image_classification(file_path, image_metadata)
                if enhanced:
                    print(f"  ✓ Enhanced media: {enhanced[0]}/{enhanced[1]}")
                    return (enhanced[0], enhanced[1], schema_type, '', None, [], image_metadata)
            print(f"  ✓ Media file detected: {media_type}/{subcat}")
            return (cat, f"{media_type}_{subcat}", schema_type, '', None, [], image_metadata)

        image_analyzer = getattr(self, 'image_analyzer', None)
        if schema_type == 'ImageObject' and image_analyzer and getattr(image_analyzer, 'vision_available', False):
            print("  Analyzing image content...")
            has_people, is_property_mgmt, _ = image_analyzer.analyze_for_organization(file_path)
            if has_people:
                print("  ✓ Detected: Photo with people")
                return ('media', 'photos_social', schema_type, '', None, [], image_metadata)

            if is_property_mgmt:
                print("  ✓ Detected: Home interior without people")
                return ('property_management', 'other', schema_type, '', None, [], image_metadata)

        print("  Extracting content...")
        ocr_confidence: Optional[float] = None
        extract_rich = getattr(self, 'extract_rich', None)
        extract_text = getattr(self, 'extract_text', None)
        if extract_rich:
            rich_result = extract_rich(file_path)
            extracted_text = rich_result.text
            ocr_confidence = rich_result.confidence
        elif extract_text:
            extracted_text = extract_text(file_path)

        low_confidence = (
            ocr_confidence is not None and ocr_confidence < _OCR_CONFIDENCE_THRESHOLD
        )

        if extracted_text and not low_confidence:
            print(f"  Extracted {len(extracted_text)} characters")
            category, subcategory, company_name, people_names = self.classifier.classify_content(
                extracted_text, file_path.name
            )
        elif extracted_text and low_confidence:
            print(
                f"  Extracted {len(extracted_text)} characters "
                f"(OCR confidence {ocr_confidence:.2f} < {_OCR_CONFIDENCE_THRESHOLD} — skipping keyword classification)"
            )
            category, subcategory, company_name, people_names = self.classifier.classify_content(
                "", file_path.name
            )
        else:
            print("  No text extracted, using filename")
            category, subcategory, company_name, people_names = self.classifier.classify_content(
                "", file_path.name
            )

        if category == 'uncategorized' and schema_type == 'ImageObject':
            enhanced = self.enhance_weak_image_classification(file_path, image_metadata)
            if enhanced:
                print(f"  ✓ Enhanced uncategorized: {enhanced[0]}/{enhanced[1]}")
                return (enhanced[0], enhanced[1], schema_type, extracted_text, None, [], image_metadata)

        return (category, subcategory, schema_type, extracted_text, company_name, people_names, image_metadata)

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

        Returns:
            Destination path for the file
        """
        if category == 'filepath':
            relative_path = subcategory
        elif category == 'media' and '_' in subcategory:
            parts = subcategory.split('_', 1)
            if len(parts) == 2:
                media_type, media_subcat = parts
                if media_type in self.category_paths['media']:
                    media_dict = self.category_paths['media'][media_type]
                    if isinstance(media_dict, dict):
                        if '_' in media_subcat:
                            parent_key, child_key = media_subcat.split('_', 1)
                            parent_val = media_dict.get(parent_key)
                            if isinstance(parent_val, dict):
                                relative_path = parent_val.get(
                                    child_key,
                                    parent_val.get('other', f'Media/{media_type.capitalize()}/{parent_key.capitalize()}'),
                                )
                            else:
                                relative_path = media_dict.get(
                                    media_subcat,
                                    media_dict.get('other', f'Media/{media_type.capitalize()}/Other'),
                                )
                        else:
                            val = media_dict.get(media_subcat)
                            if isinstance(val, dict):
                                relative_path = val.get('other', f'Media/{media_type.capitalize()}/{media_subcat.capitalize()}')
                            elif val:
                                relative_path = val
                            else:
                                relative_path = media_dict.get('other', f'Media/{media_type.capitalize()}/Other')
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
                    relative_path = self.category_paths[category].get('other', f'{category.capitalize()}/Other')
            else:
                relative_path = self.category_paths[category]
        else:
            relative_path = 'Uncategorized'

        if category == 'organization' and company_name:
            sanitized_company = self.classifier.sanitize_company_name(company_name)
            if sanitized_company:
                if subcategory == 'clients':
                    relative_path = f"{relative_path}/{sanitized_company}"
                elif subcategory == 'meeting_notes':
                    relative_path = f"{relative_path}/{sanitized_company}/Meeting Notes"
                else:
                    relative_path = f"{relative_path}/{sanitized_company}"

        if category == 'person' and people_names:
            person_name = people_names[0] if people_names else 'Unknown'
            sanitized_person = self.classifier.sanitize_company_name(person_name)
            if sanitized_person:
                relative_path = f"{relative_path}/{sanitized_person}"
            else:
                relative_path = f"{relative_path}/Unknown"
        elif category == 'person' and not people_names:
            relative_path = f"{relative_path}/Unknown"

        if category == 'business' and subcategory == 'clients' and company_name:
            sanitized_company = self.classifier.sanitize_company_name(company_name)
            if sanitized_company:
                relative_path = f"{relative_path}/{sanitized_company}"

        if self.organize_by_date and image_metadata and image_metadata.get('year'):
            year = image_metadata['year']
            month = image_metadata['month']
            relative_path = f"Photos/{year}/{month:02d}"
        elif self.organize_by_location and image_metadata and image_metadata.get('location_name'):
            location = image_metadata['location_name']
            city = location.split(',')[0].strip()
            safe_city = re.sub(r'[<>:"/\\|?*]', '', city)
            relative_path = f"Photos/Locations/{safe_city}"

        dest_dir = self.base_path / relative_path
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest_path = dest_dir / file_path.name
        if dest_path.exists() and dest_path != file_path:
            stem_val = file_path.stem
            suffix = file_path.suffix
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_path = dest_dir / f"{stem_val}_{timestamp}{suffix}"

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

        return False
