"""MIME-type and extension based file classification.

Maps a file's MIME type and extension to a ``(category, subcategory,
schema_type)`` triple whose category/subcategory key into
``CATEGORY_PATHS``. Extracted from ``scripts/file_organizer.py``
(``FileOrganizer.detect_file_category`` fallback chain and
``FileOrganizer._classify_font``).
"""

from pathlib import Path
from typing import Dict, Optional, Tuple

from shared.constants import (
    ARCHIVE_EXTENSIONS,
    SOFTWARE_INSTALLER_EXTENSIONS,
    SOFTWARE_PACKAGE_EXTENSIONS,
)

# .zip is classified separately (archives/zip); the rest route to archives/other.
_NON_ZIP_ARCHIVE_EXTENSIONS = ARCHIVE_EXTENSIONS - {".zip"}

# Image and audio format splits (photos vs graphics; music vs plain audio).
_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".heic"}
_MUSIC_EXTENSIONS = {".mp3", ".m4a", ".flac"}

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

    Canonical format-fallback classifier. When ``mime_type`` is provided the
    MIME branches take precedence; otherwise every supported format is resolved
    from the extension alone, so callers may pass ``mime_type=None`` (the type
    organizer does). Always returns a classification, defaulting to
    ``('other', 'other', 'CreativeWork')``. Screenshot detection by name applies
    only to the image/* MIME branch; extension-only callers that need it should
    pre-check the filename (as the type organizer does).
    """
    file_name = file_path.name.lower()
    file_ext = file_path.suffix.lower()

    # Fonts (extension-only; no competing MIME type)
    font = classify_font(file_ext)
    if font is not None:
        return font

    # Images
    if mime_type and mime_type.startswith('image/'):
        if 'screenshot' in file_name or file_name.startswith('screen'):
            return ('images', 'screenshots', 'ImageObject')
        elif file_ext in _PHOTO_EXTENSIONS:
            return ('images', 'photos', 'Photograph')
        else:
            return ('images', 'graphics', 'ImageObject')
    elif file_ext in _PHOTO_EXTENSIONS:
        return ('images', 'photos', 'Photograph')
    elif file_ext in ['.png', '.gif', '.bmp', '.webp', '.svg']:
        return ('images', 'graphics', 'ImageObject')

    # Documents
    elif mime_type in ['application/pdf'] or file_ext == '.pdf':
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

    # Markdown before the text/ branch so .md keeps its markdown subcategory
    elif file_ext == '.md':
        if 'research' in str(file_path.parent).lower():
            return ('research', 'notes', 'Article')
        return ('documents', 'markdown', 'Article')

    elif mime_type and mime_type.startswith('text/'):
        return ('documents', 'text', 'DigitalDocument')

    elif file_ext in ['.doc', '.docx']:
        return ('documents', 'word', 'DigitalDocument')

    elif file_ext in ['.xls', '.xlsx']:
        return ('documents', 'spreadsheets', 'DigitalDocument')

    elif file_ext in ['.ppt', '.pptx']:
        return ('documents', 'presentations', 'DigitalDocument')

    elif file_ext in ['.txt', '.rtf']:
        return ('documents', 'text', 'DigitalDocument')

    # Media
    elif mime_type and mime_type.startswith('video/'):
        return ('media', 'videos', 'VideoObject')

    elif file_ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
        return ('media', 'videos', 'VideoObject')

    elif mime_type and mime_type.startswith('audio/'):
        if 'music' in file_name or file_ext in _MUSIC_EXTENSIONS:
            return ('media', 'music', 'MusicRecording')
        return ('media', 'audio', 'AudioObject')

    elif file_ext in _MUSIC_EXTENSIONS:
        return ('media', 'music', 'MusicRecording')

    elif file_ext in ['.wav', '.ogg', '.aac']:
        return ('media', 'audio', 'AudioObject')

    # Archives
    elif mime_type in ['application/zip', 'application/x-zip-compressed'] or file_ext == '.zip':
        return ('archives', 'zip', 'DigitalDocument')

    elif file_ext in _NON_ZIP_ARCHIVE_EXTENSIONS:
        return ('archives', 'other', 'DigitalDocument')

    # Software
    elif file_ext in SOFTWARE_INSTALLER_EXTENSIONS:
        return ('software', 'installers', 'SoftwareApplication')

    elif file_ext in SOFTWARE_PACKAGE_EXTENSIONS:
        return ('software', 'packages', 'SoftwareApplication')

    # Code
    elif file_ext == '.py':
        return ('code', 'python', 'SoftwareSourceCode')

    elif file_ext in ['.ts', '.tsx']:
        return ('code', 'typescript', 'SoftwareSourceCode')

    elif file_ext in ['.js', '.jsx', '.mjs']:
        return ('code', 'javascript', 'SoftwareSourceCode')

    elif file_ext == '.dart':
        return ('code', 'dart', 'SoftwareSourceCode')

    elif file_ext in ['.sh', '.bash', '.zsh']:
        return ('code', 'shell', 'SoftwareSourceCode')

    elif file_ext in ['.html', '.css', '.scss', '.sass']:
        return ('code', 'web', 'SoftwareSourceCode')

    # Data
    elif file_ext == '.json':
        return ('data', 'json', 'Dataset')

    elif file_ext == '.csv':
        return ('data', 'csv', 'Dataset')

    elif file_ext in ['.yaml', '.yml']:
        return ('data', 'yaml', 'Dataset')

    elif file_ext == '.xml':
        return ('data', 'xml', 'Dataset')

    elif file_ext in ['.conf', '.config', '.ini', '.env', '.toml']:
        return ('data', 'config', 'Dataset')

    elif file_ext in ['.db', '.sqlite', '.sqlite3']:
        return ('data', 'databases', 'Dataset')

    # Default
    return ('other', 'other', 'CreativeWork')
