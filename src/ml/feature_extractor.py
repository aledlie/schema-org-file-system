"""Feature engineering for file-organization ML.

Extracted from scripts/data_preprocessing.py (TEST_AND_REFACTOR_PLAN Part 2,
"Large Script #4"). Turns a single organization-report record into a flat
feature dict consumed by DataPreprocessor.
"""

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

from shared.constants import DOCUMENT_PATTERNS, SCREENSHOT_PATTERNS

# Game asset patterns for filename matching (subset of game keywords as regex)
GAME_ASSET_PATTERNS = [
    r'sprite', r'frame', r'tile', r'texture',
    r'audio', r'sfx', r'bgm', r'music',
    r'icon', r'button', r'ui_',
]


class FileFeatureExtractor:
    """Extract ML features from file metadata."""

    def __init__(self):
        self.extension_map = self._build_extension_map()

    def _build_extension_map(self) -> Dict[str, str]:
        """Build mapping of extensions to general categories."""
        return {
            # Images
            '.jpg': 'image', '.jpeg': 'image', '.png': 'image',
            '.gif': 'image', '.bmp': 'image', '.webp': 'image',
            '.heic': 'image', '.heif': 'image', '.svg': 'image',
            '.tiff': 'image', '.ico': 'image',
            # Videos
            '.mp4': 'video', '.mov': 'video', '.avi': 'video',
            '.mkv': 'video', '.webm': 'video', '.m4v': 'video',
            # Audio
            '.mp3': 'audio', '.wav': 'audio', '.ogg': 'audio',
            '.flac': 'audio', '.aac': 'audio', '.m4a': 'audio',
            # Documents
            '.pdf': 'document', '.doc': 'document', '.docx': 'document',
            '.txt': 'text', '.rtf': 'document', '.odt': 'document',
            # Spreadsheets
            '.xls': 'spreadsheet', '.xlsx': 'spreadsheet', '.csv': 'data',
            # Code
            '.py': 'code', '.js': 'code', '.ts': 'code', '.jsx': 'code',
            '.tsx': 'code', '.html': 'code', '.css': 'code', '.json': 'data',
            '.xml': 'data', '.yaml': 'data', '.yml': 'data',
            # Archives
            '.zip': 'archive', '.tar': 'archive', '.gz': 'archive',
            '.rar': 'archive', '.7z': 'archive',
        }

    def extract_features(self, file_record: Dict) -> Dict[str, Any]:
        """Extract all features from a file record."""
        filename = file_record.get('schema', {}).get('name', '')
        filepath = file_record.get('source', '')
        category = file_record.get('category', 'uncategorized')
        subcategory = file_record.get('subcategory', '')

        features = {
            # Basic features
            'filename': filename,
            'filename_lower': filename.lower(),
            'filepath': filepath,
            'category': category,
            'subcategory': subcategory,

            # Extension features
            'extension': self._get_extension(filename),
            'extension_category': self._get_extension_category(filename),

            # Filename pattern features
            'filename_tokens': self._tokenize_filename(filename),
            'filename_length': len(filename),
            'has_numbers': bool(re.search(r'\d', filename)),
            'has_underscores': '_' in filename,
            'has_dashes': '-' in filename,
            'has_spaces': ' ' in filename,
            'starts_with_date': self._starts_with_date(filename),

            # Pattern detection
            'is_screenshot': self._matches_patterns(filename, SCREENSHOT_PATTERNS),
            'is_game_asset': self._matches_patterns(filename, GAME_ASSET_PATTERNS),
            'is_document': self._matches_patterns(filename, DOCUMENT_PATTERNS),

            # Metadata features
            'has_extracted_text': file_record.get('extracted_text_length', 0) > 0,
            'extracted_text_length': file_record.get('extracted_text_length', 0),
            'has_company_name': file_record.get('company_name') is not None,
            'has_people_names': len(file_record.get('people_names', [])) > 0,
            'people_count': len(file_record.get('people_names', [])),

            # Image metadata features
            'has_datetime': file_record.get('image_metadata', {}).get('datetime') is not None,
            'has_gps': file_record.get('image_metadata', {}).get('gps_coordinates') is not None,
            'has_location': file_record.get('image_metadata', {}).get('location_name') is not None,

            # Path features
            'path_depth': filepath.count('/') if filepath else 0,
            'parent_folder': self._get_parent_folder(filepath),

            # Derived features
            'filename_hash': self._hash_filename(filename),
        }

        return features

    def _get_extension(self, filename: str) -> str:
        """Get lowercase file extension."""
        return Path(filename).suffix.lower()

    def _get_extension_category(self, filename: str) -> str:
        """Get category based on extension."""
        ext = self._get_extension(filename)
        return self.extension_map.get(ext, 'other')

    def _tokenize_filename(self, filename: str) -> List[str]:
        """Tokenize filename into meaningful parts."""
        # Remove extension
        name = Path(filename).stem

        # Normalize unicode
        name = unicodedata.normalize('NFKD', name)

        # Split on common delimiters
        tokens = re.split(r'[_\-\s\.]+', name)

        # Split camelCase
        expanded_tokens = []
        for token in tokens:
            # Split on camelCase boundaries
            parts = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+', token)
            expanded_tokens.extend(parts if parts else [token])

        # Lowercase and filter
        return [t.lower() for t in expanded_tokens if t and len(t) > 1]

    def _starts_with_date(self, filename: str) -> bool:
        """Check if filename starts with a date pattern."""
        date_patterns = [
            r'^\d{8}',  # YYYYMMDD
            r'^\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'^\d{2}-\d{2}-\d{4}',  # MM-DD-YYYY
            r'^20\d{2}\d{4}',  # 20YYMMDD
        ]
        return any(re.match(p, filename) for p in date_patterns)

    def _matches_patterns(self, filename: str, patterns: List[str]) -> bool:
        """Check if filename matches any of the patterns."""
        filename_lower = filename.lower()
        return any(re.search(p, filename_lower) for p in patterns)

    def _get_parent_folder(self, filepath: str) -> str:
        """Get immediate parent folder name."""
        if not filepath:
            return ''
        parts = Path(filepath).parts
        return parts[-2] if len(parts) >= 2 else ''

    def _hash_filename(self, filename: str) -> str:
        """Create a hash of the filename for deduplication."""
        return hashlib.sha256(filename.encode()).hexdigest()[:8]
