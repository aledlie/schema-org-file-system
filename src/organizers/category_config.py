"""Category-to-destination path configuration for file organizers.

Maps each (category, subcategory) pair to a relative destination path under
the organizer's base directory. A category may map to a plain string when it
has no subcategories.

``CATEGORY_PATHS`` was extracted from ``scripts/file_organizer.py``
(``FileOrganizer.category_paths``). ``CONTENT_CATEGORY_PATHS`` is the
content-based taxonomy shared by ``ContentOrganizer`` and
``scripts/file_organizer_content_based.py``; consumers must ``deepcopy`` it
before mutating (the content-based script extends the screenshots sub-dict
per instance).
"""

from typing import Any, Dict, Union

# Single source for the GameAssets subcategory→folder map, shared by both
# taxonomies below (previously duplicated verbatim in each). Consumers that
# mutate a taxonomy already deepcopy it first, so the shared reference is safe.
GAME_ASSETS_PATHS: Dict[str, str] = {
    'sprites': 'GameAssets/Sprites',
    'textures': 'GameAssets/Textures',
    'fonts': 'GameAssets/Fonts',
    'audio': 'GameAssets/Audio',
    'music': 'GameAssets/Music',
    'other': 'GameAssets/Other',
}

# Single source for the CreativeWork fonts subcategory→folder map, shared by
# both taxonomies below (previously duplicated verbatim in each).
FONTS_PATHS: Dict[str, str] = {
    'truetype': 'CreativeWork/Fonts/TrueType',
    'opentype': 'CreativeWork/Fonts/OpenType',
    'web': 'CreativeWork/Fonts/Web',
    'other': 'CreativeWork/Fonts/Other',
}

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
        'typescript': 'Code/TypeScript',
        'dart': 'Code/Flutter',
        'shell': 'Code/Shell',
        'web': 'Code/Web',
        'other': 'Code/Other'
    },
    'data': {
        'json': 'Data/JSON',
        'csv': 'Data/CSV',
        'yaml': 'Data/YAML',
        'xml': 'Data/XML',
        'config': 'Data/Config',
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
    'game_assets': GAME_ASSETS_PATHS,
    'fonts': FONTS_PATHS,
    'other': 'Other'
}

CONTENT_CATEGORY_PATHS: Dict[str, Any] = {
    "legal": {
        "contracts": "Legal/Contracts",
        "real_estate": "Legal/RealEstate",
        "litigation": "Legal/Litigation",
        "corporate": "Legal/Corporate",
        "other": "Legal/Other",
    },
    "financial": {
        "tax": "Financial/Tax",
        "invoices": "Financial/Invoices",
        "statements": "Financial/Statements",
        "insurance": "Financial/Insurance",
        "other": "Financial/Other",
    },
    "business": {
        "planning": "Business/Planning",
        "marketing": "Business/Marketing",
        "proposals": "Business/Proposals",
        "presentations": "Business/Presentations",
        "crm": "Business/CRM",
        "hr": "Business/HR",
        "meeting_notes": "Business/MeetingNotes",
        "clients": "Business/Clients",  # Legacy - prefer crm/hr
        "other": "Business/Other",
    },
    "personal": {
        "contacts": "Personal/Contacts",
        "employment": "Personal/Employment",
        "identification": "Personal/Identification",
        "certificates": "Personal/Certificates",
        "journal": "Personal/Journal",
        "events": "Personal/Events",
        "legal": "Personal/Legal",
        "records": "Personal/Records",
        "other": "Personal/Other",
    },
    "medical": {
        "records": "Medical/Records",
        "insurance": "Medical/Insurance",
        "prescriptions": "Medical/Prescriptions",
        "other": "Medical/Other",
    },
    "property": {
        "leases": "Property/Leases",
        "maintenance": "Property/Maintenance",
        "other": "Property/Other",
    },
    "education": {
        "coursework": "Education/Coursework",
        "research": "Education/Research",
        "records": "Education/Records",
        "other": "Education/Other",
    },
    "research": {
        "arxiv": "Research/Papers/arXiv",
        "ssrn": "Research/Papers/SSRN",
        "doi": "Research/Papers/DOI",
        "other": "Research/Papers/Other",
    },
    "technical": {
        "documentation": "Technical/Documentation",
        "architecture": "Technical/Architecture",
        "config": "Technical/Config",
        "data": "Technical/Data",
        "logs": "Technical/Logs",
        "web": "Technical/Web",
        "software_packages": "Technical/Software_Packages",
        "other": "Technical/Other",
    },
    "creative": {
        "design": "Creative/Design",
        "branding": "Creative/Branding",
        "photos": "Creative/Photos",
        "other": "Creative/Other",
    },
    "property_management": "Property_Management",
    "zouk": {"events": "Zouk/Events", "classes": "Zouk/Classes", "other": "Zouk/Other"},
    # Organization: root folder with entity-named subfolders
    # Structure: Organization/{OrgName}/ for most types
    # Exception: Organization/Clients/{OrgName}/ for clients (nested)
    "organization": {
        "clients": "Organization/Clients",  # Gets nested subfolders
        "vendors": "Organization",  # Root folder, entity name added dynamically
        "partners": "Organization",
        "employers": "Organization",
        "government": "Organization",
        "healthcare": "Organization",
        "property_management": "Organization",
        "financial": "Organization",
        "educational": "Organization",
        "nonprofit": "Organization",
        "meeting_notes": "Organization",  # Gets Meeting Notes subfolder after company
        "other": "Organization",
    },
    "game_assets": GAME_ASSETS_PATHS,
    "fonts": FONTS_PATHS,
    "media": {
        "photos": {
            "screenshots": {
                "browser": "Media/Photos/Screenshots/Browser",
                "terminal": "Media/Photos/Screenshots/Terminal",
                "code": "Media/Photos/Screenshots/CodeEditors",
                "docs": "Media/Photos/Screenshots/Docs",
                "settings": "Media/Photos/Screenshots/Settings",
                "products": "Media/Photos/Screenshots/Products",
                "dashboard": "Media/Photos/Screenshots/Dashboards",
                "chat": "Media/Photos/Screenshots/Chat",
                "other": "Media/Photos/Screenshots",
            },
            "travel": "Media/Photos/Travel",
            "portraits": "Media/Photos/Portraits",
            "events": "Media/Photos/Events",
            "documents": "Media/Photos/Documents",
            "social": "Media/Photos/Social",
            "chatgpt": "Media/Photos/ChatGPT",
            "facebook": "Media/Photos/Facebook",
            "logos": "Media/Photos/Logos",
            "stock": "Media/Photos/Stock",
            "nature": "Media/Photos/Nature",
            "lifestyle": "Media/Photos/Lifestyle",
            "products": "Media/Photos/Products",
            "other": "Media/Photos/Other",
        },
        "videos": {
            "recordings": "Media/Videos/Recordings",
            "exports": "Media/Videos/Exports",
            "screencasts": "Media/Videos/Screencasts",
            "other": "Media/Videos/Other",
        },
        "audio": {
            "recordings": "Media/Audio/Recordings",
            "music": "Media/Audio/Music",
            "podcasts": "Media/Audio/Podcasts",
            "other": "Media/Audio/Other",
        },
        "graphics": {
            "vector": "Media/Graphics/Vector",
            "icons": "Media/Graphics/Icons",
            "other": "Media/Graphics/Other",
        },
        # Interior/room photos. The user-facing folder is ``Media/Interiors``
        # but the schema.org @type stays ``Room`` (schema.org has no "Interior"
        # type) plus its two direct subtypes (``HotelRoom``, ``MeetingRoom``).
        # Reached via the underscored ``interiors_<subtype>`` subcategory form
        # that get_destination_path resolves through the media_type_subcat
        # split; ``interiors_other`` is the generic ``Room`` and lands directly
        # in ``Media/Interiors``. See ROOM_SUBTYPE_SCHEMA in
        # src/scoring/signals/photo_composition.py for the folder→schema map.
        "interiors": {
            "hotel": "Media/Interiors/HotelRoom",
            "meeting": "Media/Interiors/MeetingRoom",
            "other": "Media/Interiors",
        },
        # Building/house exteriors — facades, porches, and attached patios.
        # schema.org @type ``House`` (Accommodation, sibling of Room), emitted by
        # the scene signal's schema_type evidence; folder ``Media/Exteriors``.
        # Reached via the underscored ``exteriors_other`` subcategory form. See
        # docs/plans/MEDIA_EXTERIORS_PLAN.md for the scene taxonomy + schema map.
        "exteriors": {
            "other": "Media/Exteriors",
        },
        # Outdoor / landscape / travel and non-residential or commercial scenes.
        # schema.org @type ``Place`` (the generic superclass of Accommodation);
        # folder ``Media/Place``. Reached via the underscored ``place_other`` form.
        "place": {
            "other": "Media/Place",
        },
        "other": "Media/Other",
    },
    "uncategorized": "Uncategorized",
}
