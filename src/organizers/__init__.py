"""Organizer modules for content-based file classification.

``ContentOrganizer`` and ``FileNameOrganizer`` are exposed lazily (PEP 562):
``content_organizer`` imports the unified-scoring signal modules, which import
``category_config``/``mime_classifier`` from this package — an eager import
here would close that cycle whenever a signal module loads first.
"""

from src.organizers.base_organizer import BaseOrganizer
from src.organizers.category_config import CATEGORY_PATHS, CONTENT_CATEGORY_PATHS
from src.organizers.mime_classifier import classify_by_mime, classify_font

__all__ = [
    "BaseOrganizer",
    "CATEGORY_PATHS",
    "CONTENT_CATEGORY_PATHS",
    "ContentOrganizer",
    "FileNameOrganizer",
    "classify_by_mime",
    "classify_font",
]

_LAZY_EXPORTS = {
    "ContentOrganizer": ("src.organizers.content_organizer", "ContentOrganizer"),
    "FileNameOrganizer": ("src.organizers.name_organizer", "FileNameOrganizer"),
}


def __getattr__(name: str):
    try:
        module_name, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    import importlib

    return getattr(importlib.import_module(module_name), attr)
