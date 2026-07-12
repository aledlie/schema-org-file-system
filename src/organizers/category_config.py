"""Category-to-destination path configuration for file organizers.

Maps each (category, subcategory) pair to a relative destination path under
the organizer's base directory. A category may map to a plain string when it
has no subcategories. Extracted from ``scripts/file_organizer.py``
(``FileOrganizer.category_paths``).
"""

from typing import Dict, Union

CATEGORY_PATHS: Dict[str, Union[str, Dict[str, str]]] = {
    'images': {
        'screenshots': 'Images/Screenshots',
        'photos': 'Images/Photos',
        'graphics': 'Images/Graphics',
        'other': 'Images/Other'
    },
    'documents': {
        'pdf': 'Documents/PDFs',
        'word': 'Documents/Word',
        'spreadsheets': 'Documents/Spreadsheets',
        'presentations': 'Documents/Presentations',
        'text': 'Documents/Text',
        'markdown': 'Documents/Markdown',
        'other': 'Documents/Other'
    },
    'media': {
        'videos': 'Media/Videos',
        'audio': 'Media/Audio',
        'music': 'Media/Music',
        'other': 'Media/Other'
    },
    'archives': {
        'zip': 'Archives/Compressed',
        'other': 'Archives/Other'
    },
    'software': {
        'installers': 'Software/Installers',
        'packages': 'Software/Packages',
        'other': 'Software/Other'
    },
    'code': {
        'python': 'Code/Python',
        'javascript': 'Code/JavaScript',
        'other': 'Code/Other'
    },
    'data': {
        'json': 'Data/JSON',
        'csv': 'Data/CSV',
        'databases': 'Data/Databases',
        'other': 'Data/Other'
    },
    'research': {
        'papers': 'Research/Papers',
        'notes': 'Research/Notes',
        'other': 'Research/Other'
    },
    'contacts': {
        'people': 'Contacts/People',
        'vcards': 'Contacts/vCards',
        'other': 'Contacts/Other'
    },
    'business': {
        'companies': 'Business/Companies',
        'clients': 'Business/Clients',
        'invoices': 'Business/Invoices',
        'contracts': 'Business/Contracts',
        'other': 'Business/Other'
    },
    'game_assets': {
        'sprites': 'GameAssets/Sprites',
        'textures': 'GameAssets/Textures',
        'fonts': 'GameAssets/Fonts',
        'audio': 'GameAssets/Audio',
        'music': 'GameAssets/Music',
        'other': 'GameAssets/Other'
    },
    'fonts': {
        'truetype': 'CreativeWork/Fonts/TrueType',
        'opentype': 'CreativeWork/Fonts/OpenType',
        'web': 'CreativeWork/Fonts/Web',
        'other': 'CreativeWork/Fonts/Other'
    },
    'other': 'Other'
}
