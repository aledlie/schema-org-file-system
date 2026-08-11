"""Near-duplicate detection: faiss index over SSCD copy-detection descriptors.

Complements ``GraphStore.find_duplicates`` (exact ``content_hash`` grouping),
which by construction cannot see the same document re-encoded, resized, or
exported to another container.

Attributes are resolved lazily (PEP 562). This is load-bearing, not tidiness:
importing this package must not drag torch into a process that is about to run
faiss, or vice versa — see ``worker.py`` for why they cannot coexist.
"""

from typing import Any

from .types import DuplicateGroup, SimilarPair

__all__ = [
    "DESCRIPTORS_AVAILABLE",
    "DuplicateGroup",
    "DuplicateReport",
    "SimilarPair",
    "clear_model",
    "collect_files",
    "find_duplicates",
    "get_descriptors",
    "group_near_duplicates_isolated",
    "print_report",
    "unavailable_reason",
    "write_report",
]

_LAZY_EXPORTS = {
    "DESCRIPTORS_AVAILABLE": "descriptors",
    "clear_model": "descriptors",
    "get_descriptors": "descriptors",
    "DuplicateReport": "finder",
    "collect_files": "finder",
    "find_duplicates": "finder",
    "print_report": "finder",
    "unavailable_reason": "finder",
    "write_report": "finder",
    "group_near_duplicates_isolated": "worker",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(f".{module_name}", __name__), name)


def __dir__() -> list:
    return sorted(__all__)
