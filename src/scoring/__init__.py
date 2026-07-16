"""Unified scoring engine (docs/architecture/UNIFIED_SCORING_PLAN.md).

Replaces the first-match-wins tier chain in
``ContentOrganizer.detect_file_category`` with a weighted multi-signal
scorer, behind ``organize-files content --scorer {legacy,unified,shadow}``.
"""

from .context import FileContext
from .registry import build_default_signals
from .scorer import Scorer
from .types import (
    SCORER_DEFAULT,
    SCORER_LEGACY,
    SCORER_MODES,
    SCORER_SHADOW,
    SCORER_UNIFIED,
    CategoryScore,
    ClassificationDecision,
    Signal,
)

__all__ = [
    "CategoryScore",
    "ClassificationDecision",
    "FileContext",
    "SCORER_DEFAULT",
    "SCORER_LEGACY",
    "SCORER_MODES",
    "SCORER_SHADOW",
    "SCORER_UNIFIED",
    "Scorer",
    "Signal",
    "build_default_signals",
]
