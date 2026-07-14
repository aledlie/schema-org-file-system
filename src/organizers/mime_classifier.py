"""MIME-type and extension based file classification.

Maps a file's MIME type and extension to a ``(category, subcategory,
schema_type)`` triple whose category/subcategory key into
``CATEGORY_PATHS``. Extracted from ``scripts/file_organizer.py``
(``FileOrganizer.detect_file_category`` fallback chain and
``FileOrganizer._classify_font``).
"""

from pathlib import Path
from typing import Dict, Optional, Tuple

try:
    from shared.constants import ARCHIVE_EXTENSIONS
except ImportError:  # scripts/shared not on sys.path (e.g. direct-import tests)
    ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".rar", ".7z", ".bz2"}

# .zip is classified separately (archives/zip); the rest route to archives/other.
_NON_ZIP_ARCHIVE_EXTENSIONS = ARCHIVE_EXTENSIONS - {".zip"}

Classification = Tuple[str, str, str]

FONT_EXTENSIONS: Dict[str, Classification] = {
    '.ttf': ('fonts', 'truetype', 'DigitalDocument'),
    '.otf': ('fonts', 'opentype', 'DigitalDocument'),
    '.woff': ('fonts', 'web', 'DigitalDocument'),
    '.woff2': ('fonts', 'web', 'DigitalDocument'),
    '.eot': ('fonts', 'web', 'DigitalDocument'),
    '.fon': ('fonts', 'other', 'DigitalDocument'),
    '.fnt': ('fonts', 'other', 'DigitalDocument'),
}


def classify_font(file_ext: str) -> Optional[Classification]:
    """Classify font files based on extension.

    Returns:
        Classification triple or None if not a font extension.
    """
    return FONT_EXTENSIONS.get(file_ext.lower())


def classify_by_mime(file_path: Path, mime_type: Optional[str]) -> Classification:
    """Classify a file by MIME type and extension.

    Lowest-priority fallback: runs after contact/business/font/game-asset
    detection. Always returns a classification, defaulting to
    ``('other', 'other', 'CreativeWork')``.
    """
    file_name = file_path.name.lower()
    file_ext = file_path.suffix.lower()

    # Images
    if mime_type and mime_type.startswith('image/'):
        if 'screenshot' in file_name or file_name.startswith('screen'):
            return ('images', 'screenshots', 'ImageObject')
        elif file_ext in ['.jpg', '.jpeg', '.heic']:
            return ('images', 'photos', 'Photograph')
        else:
            return ('images', 'graphics', 'ImageObject')

    # Documents
    elif mime_type in ['application/pdf']:
        # Check if in research directory
        if 'research' in str(file_path.parent).lower():
            return ('research', 'papers', 'ScholarlyArticle')
        return ('documents', 'pdf', 'DigitalDocument')

    elif mime_type in ['application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                       'application/msword']:
        return ('documents', 'word', 'DigitalDocument')

    elif mime_type in ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                       'application/vnd.ms-excel']:
        return ('documents', 'spreadsheets', 'DigitalDocument')

    elif mime_type in ['application/vnd.openxmlformats-officedocument.presentationml.presentation',
                       'application/vnd.ms-powerpoint']:
        return ('documents', 'presentations', 'DigitalDocument')

    elif file_ext == '.md':
        if 'research' in str(file_path.parent).lower():
            return ('research', 'notes', 'Article')
        return ('documents', 'markdown', 'Article')

    elif mime_type and mime_type.startswith('text/'):
        return ('documents', 'text', 'DigitalDocument')

    # Media
    elif mime_type and mime_type.startswith('video/'):
        return ('media', 'videos', 'VideoObject')

    elif mime_type and mime_type.startswith('audio/'):
        if 'music' in file_name or file_ext in ['.mp3', '.m4a', '.flac']:
            return ('media', 'music', 'MusicRecording')
        return ('media', 'audio', 'AudioObject')

    # Archives
    elif mime_type in ['application/zip', 'application/x-zip-compressed'] or file_ext == '.zip':
        return ('archives', 'zip', 'DigitalDocument')

    elif file_ext in _NON_ZIP_ARCHIVE_EXTENSIONS:
        return ('archives', 'other', 'DigitalDocument')

    # Software
    elif file_ext in ['.dmg', '.pkg', '.exe', '.msi', '.deb', '.rpm']:
        return ('software', 'installers', 'SoftwareApplication')

    # Code
    elif file_ext == '.py':
        return ('code', 'python', 'SoftwareSourceCode')

    elif file_ext in ['.js', '.ts', '.jsx', '.tsx']:
        return ('code', 'javascript', 'SoftwareSourceCode')

    # Data
    elif file_ext == '.json':
        return ('data', 'json', 'Dataset')

    elif file_ext == '.csv':
        return ('data', 'csv', 'Dataset')

    elif file_ext in ['.db', '.sqlite', '.sqlite3']:
        return ('data', 'databases', 'Dataset')

    # Default
    return ('other', 'other', 'CreativeWork')
