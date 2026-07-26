"""Unified scoring engine (docs/architecture/UNIFIED_SCORING_PLAN.md).

Replaces the first-match-wins tier chain in
``ContentOrganizer.detect_file_category`` with a weighted multi-signal
scorer. The legacy chain and shadow mode were removed in Phase 5.
"""

from .context import FileContext
from .scorer import Scorer
from .types import (
    SCORER_DEFAULT,
    SCORER_MODES,
    SCORER_UNIFIED,
    CategoryScore,
    ClassificationDecision,
    Signal,
)

# ``build_default_signals`` is exposed lazily (PEP 562): the registry imports
# every signal module, and several of those import ``shared.*`` — which is
# only on ``sys.path`` once a CLI subcommand has inserted ``scripts/``.
# Importing ``src.scoring.types`` (e.g. for the --scorer flag definition)
# must not cascade into that dependency.
_LAZY_EXPORTS = {"build_default_signals": ("src.scoring.registry", "build_default_signals")}


def __getattr__(name: str):
    try:
        module_name, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    import importlib

    return getattr(importlib.import_module(module_name), attr)


__all__ = [
    "CategoryScore",
    "ClassificationDecision",
    "FileContext",
    "SCORER_DEFAULT",
    "SCORER_MODES",
    "SCORER_UNIFIED",
    "Scorer",
    "Signal",
    "build_default_signals",
]
