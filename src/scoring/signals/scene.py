"""SceneSignal — multinomial scene probe over cached CLIP embeddings.

Generalizes the binary C1 interior probe (``interior.py``) to the four scene
classes locked in docs/plans/MEDIA_EXTERIORS_PLAN.md: ``neither`` (the reject
class — other signals decide), ``interior`` (Room), ``exterior`` (House —
facades plus attached porches & patios), and ``place`` (generic Place —
landscape / travel / commercial scenes). One probe, one vote per file: the
argmax positive class is emitted when its probability clears
``SCENE_MIN_PROB``, so the classes are mutually exclusive by construction
(no double-fire, no close-vote split to Uncategorized).

schema.org hierarchy preserved: ``Place ⊃ Accommodation ⊃ {Room, House}``.
v1 emits the strict argmax leaf; the ``Accommodation`` backoff for a thin
Room-vs-House margin is a v2 refinement (``STRUCTURE_PARENT``), gated on
measured thin-margin rates from the backtest.

Artifact: ``results/scene_probe.joblib`` — a dict ``{"pipeline", "meta"}``
produced by ``scripts/prototype_scene_probe.py train``; ``meta["classes"]``
records the LogisticRegression class order so ``predict_proba`` columns map
back to scene names. The signal no-ops (``applies_to`` False) when the
artifact, joblib/sklearn, or CLIP is absent.

Transition (MEDIA_EXTERIORS_PLAN sequencing guard): the registry swaps this
signal in for ``InteriorSignal`` only when the artifact is present — never
ahead of a trained probe. ``interior.py`` and ``photo_composition``'s
``is_property_mgmt`` vote are retired when the swap completes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import FileContext

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..types import EVIDENCE_SCHEMA_TYPE, CategoryScore
from ..weights import W_SCENE

# Repo-root-relative so the signal finds the artifact regardless of cwd.
PROBE_PATH = Path(__file__).resolve().parents[3] / "results" / "scene_probe.joblib"

# Only vote when the probe's argmax positive class is at least this confident;
# below it, defer to other signals. At >= 0.5 the winning positive class also
# beats every other class combined (incl. ``neither``), so the reject class is
# honoured implicitly. Re-tune from the `eval` threshold sweep + backtest.
SCENE_MIN_PROB = 0.5

# Scene class -> (category, subcategory). ``neither`` is deliberately absent:
# it is the reject class and never votes. Folder targets landed with the
# taxonomy step (category_config.py media.{interiors,exteriors,place}).
SCENE_CATEGORY: Dict[str, Tuple[str, str]] = {
    "interior": ("media", "interiors_other"),
    "exterior": ("media", "exteriors_other"),
    "place": ("media", "place_other"),
    # ``graphics_other`` resolves through the media split to Media/Graphics/Other
    # (same target GraphicDetectionSignal emits): the trained probe is the heavy
    # voter for opaque graphics the cheap pixel gate cannot see.
    "graphic": ("media", "graphics_other"),
}

# Scene class -> schema.org @type (plan §Design — hierarchy encoded here).
SCENE_SCHEMA: Dict[str, str] = {
    "interior": "Room",
    "exterior": "House",
    "place": "Place",
    "graphic": "ImageObject",  # not a Place/Accommodation — generic image @type
}
STRUCTURE_PARENT = "Accommodation"  # v2 backoff: common ancestor of Room & House

# Trainer label ints -> names (mirrors SCENE_CLASSES in
# scripts/prototype_scene_probe.py); fallback when meta lacks class_names.
_INT_CLASS_NAMES: Dict[int, str] = {
    0: "neither",
    1: "interior",
    2: "exterior",
    3: "place",
    4: "graphic",
}

# Signal-local evidence keys: the winning class name + its raw probability.
EVIDENCE_SCENE_CLASS = "scene_class"
EVIDENCE_SCENE_PROB = "scene_prob"

SCENE_SIGNAL_NAME = "scene"


def _get_embedding(path: Path) -> Optional[Any]:
    """Cached CLIP embedding via shared.clip_cache, or None if unavailable.

    Resolved lazily per call: keeps this module importable without scripts/
    on sys.path (mirrors ``interior._get_embedding``).
    """
    try:
        from shared.clip_cache import get_or_compute_embedding
    except ImportError:
        return None
    return get_or_compute_embedding(path)


def load_probe(path: Path) -> Optional[Tuple[Any, List[str]]]:
    """Load ``(pipeline, class names in predict_proba column order)``.

    Returns None when the artifact, joblib/sklearn, or the ``meta.classes``
    contract is absent — the signal then no-ops.
    """
    try:
        import joblib

        artifact = joblib.load(path)
        pipeline = artifact["pipeline"]
        meta = artifact["meta"]
        names = meta.get("class_names", {})
        order = [str(names.get(c) or _INT_CLASS_NAMES.get(int(c), str(c))) for c in meta["classes"]]
        return pipeline, order
    except Exception:
        return None


class SceneSignal:
    """Votes one of ``media/{interiors,exteriors,place}_other`` from the probe."""

    name = SCENE_SIGNAL_NAME
    weight = W_SCENE
    cost_tier = "heavy"

    def __init__(self, probe_path: Optional[Path] = None) -> None:
        loaded = load_probe(Path(probe_path) if probe_path else PROBE_PATH)
        self._pipeline, self._class_order = loaded if loaded else (None, [])

    @property
    def is_loaded(self) -> bool:
        """True when the trained artifact loaded — the registry's swap gate."""
        return self._pipeline is not None

    def applies_to(self, ctx: FileContext) -> bool:
        return ctx.is_image and self._pipeline is not None

    def run(self, ctx: FileContext) -> List[CategoryScore]:
        if self._pipeline is None:
            return []
        emb = _get_embedding(ctx.path)
        if emb is None:
            return []
        probs = self._pipeline.predict_proba(emb.reshape(1, -1))[0]

        best_name: Optional[str] = None
        best_prob = 0.0
        for column, class_name in enumerate(self._class_order):
            if class_name in SCENE_CATEGORY and float(probs[column]) > best_prob:
                best_name, best_prob = class_name, float(probs[column])
        if best_name is None or best_prob < SCENE_MIN_PROB:
            return []

        category, subcategory = SCENE_CATEGORY[best_name]
        return [
            CategoryScore(
                category=category,
                subcategory=subcategory,
                confidence=best_prob,
                signal_name=self.name,
                evidence={
                    EVIDENCE_SCHEMA_TYPE: SCENE_SCHEMA[best_name],
                    EVIDENCE_SCENE_CLASS: best_name,
                    EVIDENCE_SCENE_PROB: round(best_prob, 4),
                },
            )
        ]
