"""InteriorSignal — trained linear probe over cached CLIP embeddings (C1).

The durable fix from docs/reviews/INTERIOR_DETECTION_DURABLE_FIX_ANALYSIS.md:
a StandardScaler + logistic-regression probe on the frozen ``ViT-B-32``
embeddings the pipeline already caches, replacing the softmax-floor-blind
zero-shot interior gate in ``ImageContentAnalyzer``. Confirmed interiors the
zero-shot gate scored ~0.096 (below its 0.30 threshold) the probe scores
~0.99; the held-out reference render went from a 0.516 coin-flip to 0.994.

Deployment (why W_INTERIOR is high): a firing interior vote must outscore both
the demoted source-provenance filename (``photos_chatgpt`` at 0.4 × W_FILENAME
= 0.44) and ``photo_composition``'s ``photos_social`` (0.8 × W_PEOPLE_PHOTO =
0.52). At W_INTERIOR a P >= ~0.66 interior clears both with margin. A trained
supervised probe legitimately outranks the zero-shot ClipVisionSignal (0.7).

Artifact: ``results/interior_probe.joblib`` — a dict ``{"pipeline", "meta"}``
produced by ``scripts/prototype_interior_probe.py train``. The signal no-ops
(``applies_to`` False) when the artifact, joblib/sklearn, or CLIP is absent, so
lightweight/test organizers and fresh clones degrade gracefully.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from shared.clip_cache import get_or_compute_embedding

from ..types import EVIDENCE_SCHEMA_TYPE, CategoryScore
from ..weights import W_INTERIOR
from .photo_composition import PROPERTY_PHOTO_CATEGORY as INTERIOR_CATEGORY
from .photo_composition import ROOM_SCHEMA_TYPE

# Repo-root-relative so the signal finds the artifact regardless of cwd.
_PROBE_PATH = Path(__file__).resolve().parents[3] / "results" / "interior_probe.joblib"

# Only vote when the probe is at least this confident the image is an interior;
# below it, defer to other signals (and the source-filename fallback).
INTERIOR_MIN_PROB = 0.5

# Signal-local evidence key carrying the raw probe probability.
EVIDENCE_INTERIOR_PROB = "interior_prob"

# Signal identity + the human phrase surfaced in schema.org descriptions for a
# probe-detected interior. Replaces the zero-shot CLIP label whose softmax-floor
# confidence (~5%) understated these images (the probe's calibrated P is ~99%);
# ContentOrganizer._stash_decision_state prefers this when the probe wins.
INTERIOR_SIGNAL_NAME = "interior"
INTERIOR_DESCRIPTION_LABEL = "an interior room"


def _load_probe(path: Path) -> Optional[Any]:
    """Load the persisted sklearn pipeline, or None if unavailable."""
    try:
        import joblib

        artifact = joblib.load(path)
        return artifact["pipeline"]
    except Exception:
        return None


class InteriorSignal:
    """Votes ``media/interiors_other`` (schema.org ``Room``) from the C1 probe."""

    name = INTERIOR_SIGNAL_NAME
    weight = W_INTERIOR
    cost_tier = "heavy"

    def __init__(self, probe_path: Optional[Path] = None) -> None:
        self._pipeline = _load_probe(Path(probe_path) if probe_path else _PROBE_PATH)

    def applies_to(self, ctx: Any) -> bool:
        return ctx.is_image and self._pipeline is not None

    def run(self, ctx: Any) -> List[CategoryScore]:
        emb = get_or_compute_embedding(ctx.path)
        if emb is None:
            return []
        prob = float(self._pipeline.predict_proba(emb.reshape(1, -1))[0, 1])
        if prob < INTERIOR_MIN_PROB:
            return []
        category, subcategory = INTERIOR_CATEGORY
        return [
            CategoryScore(
                category=category,
                subcategory=subcategory,
                confidence=prob,
                signal_name=self.name,
                evidence={
                    EVIDENCE_SCHEMA_TYPE: ROOM_SCHEMA_TYPE,
                    EVIDENCE_INTERIOR_PROB: round(prob, 4),
                },
            )
        ]
