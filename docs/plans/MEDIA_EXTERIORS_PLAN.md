# Plan: Media/Exteriors + Media/Place scene classification

**Status:** Complete — decisions locked 2026-07-17; swap completed 2026-07-18 (see §Status at bottom). v2 refinements (`Accommodation` backoff) remain future work.
**Priority:** P2
**Source:** ChatGPT content-run audit, 2026-07-17 — AI real-estate renders routed to `Media/Interiors`/`Room`; no `Media/` bucket for building exteriors or outdoor/place scenes.
**Extends:** [`docs/architecture/UNIFIED_SCORING_PLAN.md`](../architecture/UNIFIED_SCORING_PLAN.md) (unified scorer), [`docs/reviews/INTERIOR_DETECTION_DURABLE_FIX_ANALYSIS.md`](../reviews/INTERIOR_DETECTION_DURABLE_FIX_ANALYSIS.md) (the C1 interior probe this generalizes).

## Motivation

The unified scorer's `InteriorSignal` (a binary CLIP-embedding probe) is the only content signal strong enough to override the demoted `photos_chatgpt` provenance filename. It votes exactly one destination — `media/interiors_other` (schema.org `Room`) — so every property render it fires on lands in `Media/Interiors`, including house facades, porches, and patios that are not interiors. There is no `Media/` subcategory for exterior/outdoor scenes, and the probe cannot express one (it is interior-vs-not).

Audit of `organize-files content --source ~/Documents/Media/Photos/ChatGPT --limit 10` (session `88f17e9e`, 2026-07-17): 10/10 AI property renders → `Media/Interiors`/`Room`, probe P 0.85–0.999. Sampled 4 — 2 bedrooms (correct), 1 house exterior/porch, 1 covered patio (both mis-typed `Room`).

## Locked decisions (2026-07-17)

1. **Three buckets, keeping the schema.org hierarchy** `Place ⊃ Accommodation ⊃ {Room, House}`:

   | Subcategory | Folder | schema.org @type |
   |---|---|---|
   | `interiors_other` | `Media/Interiors` | `Room` (Accommodation) |
   | `exteriors_other` | `Media/Exteriors` | `House` (Accommodation, sibling of Room) |
   | `place_other` | `Media/Place` | `Place` (generic superclass) |

2. **Place semantics:** outdoor / landscape / travel and non-residential or commercial scenes.
3. **Boundary:** residential/building incl. **attached porches & patios → Exteriors/House**; landscape/travel/commercial → Place.
4. **One multi-class probe.** Replace binary `InteriorSignal` with a single `SceneSignal` — softmax over `{neither, interior, exterior, place}`, emit the argmax positive class if it clears a probability threshold. Mutually exclusive by construction (no double-fire, no close-vote split to Uncategorized).
5. **Retire** `photo_composition`'s `is_property_mgmt → interiors_other` vote once `SceneSignal` is live (keeps `has_people → photos_social`). Resolves the BACKLOG `PHOTO_PROPERTY_CONFIDENCE` re-tune item.
6. **v1 = strict argmax-leaf** (`Room`/`House`/`Place`/none). The hierarchy is encoded + documented; the **`Accommodation` backoff** for a thin interior-vs-exterior (Room-vs-House) margin is a **v2** refinement, gated on measured thin-margin rates from the backtest.

## Design

### Taxonomy
`src/organizers/category_config.py` — `media.exteriors` and `media.place` blocks alongside `media.interiors`. The underscore resolver (`ContentOrganizer.get_destination_path`, `content_organizer.py:1600-1640`) turns `exteriors_other`/`place_other` into `Media/Exteriors`/`Media/Place` with no resolver change. Schema `@type` comes from the winning signal's `EVIDENCE_SCHEMA_TYPE` via `Scorer._schema_type_override` — no scorer change.

### Scene model
`SceneSignal` (`src/scoring/signals/scene.py`, replacing `interior.py`): loads `results/scene_probe.joblib`, runs the cached CLIP embedding through a class-balanced multinomial logistic regression, takes the argmax over `{interior, exterior, place}`; if its probability ≥ `SCENE_MIN_PROB` it emits one `CategoryScore` with the mapped `(category, schema_type)`, else no vote (defers to other signals / the source-filename fallback). No-ops when the joblib / sklearn / CLIP is absent, so lightweight & test organizers and fresh clones degrade gracefully.

The schema map encodes the hierarchy:

```python
SCENE_SCHEMA = {"interior": "Room", "exterior": "House", "place": "Place"}
STRUCTURE_PARENT = "Accommodation"   # v2 backoff: common ancestor of Room & House
```

### Weights
`W_SCENE` (from `W_INTERIOR = 0.85`); one weight, all classes share it (the signal emits one vote per file). Same invariant: a confident scene vote must clear the demoted `photos_chatgpt` (0.44) by `MIN_DECISION_MARGIN`. Re-tune with a `results/file_organization.db` backtest committed with its report (versioned-data rule, `weights.py` header).

### Trainer
`scripts/prototype_scene_probe.py` — 4-class generalization of `prototype_interior_probe.py` (`gather`/`eval`/`train`, same production embedding cache and sklearn pipeline). Persists `results/scene_probe.joblib` with `meta.classes` (the LR class order, so the signal maps `predict_proba` columns → scene names). The binary interior trainer is **kept intact** until the scene model replaces it — retraining/renaming it now would break the shipped `interior_probe.joblib` workflow mid-transition.

## File-by-file

| File | Change | Step |
|---|---|---|
| `organizers/category_config.py` | add `exteriors` + `place` media blocks | 1 ✅ |
| `tests/unit/test_content_organizer.py` | `get_destination_path` → `Media/Exteriors`, `Media/Place` | 1 ✅ |
| `scripts/prototype_scene_probe.py` | new 4-class trainer | ✅ |
| `results/scene_labels/` | hand-labeling corpus (git-ignored images) | ✅ |
| `signals/interior.py` → `signals/scene.py` | `SceneSignal`, multi-class emit + `SCENE_SCHEMA` | 2 |
| `signals/photo_composition.py` | remove `is_property_mgmt` branch + orphan constants | 2 |
| `scoring/weights.py` | `W_INTERIOR` → `W_SCENE` | 2 |
| `scoring/registry.py` | `InteriorSignal()` → `SceneSignal()` | 2 |
| `test_signal_interior.py` → `test_signal_scene.py` | 4-class cases | 2 |
| `test_registry.py`, `test_signal_photo_composition.py` | signal list; drop interior expectation | 2 |
| golden suite | add exterior + place cases (`UPDATE_GOLDEN=1`) | 2 |

## Sequencing — regression guard

Swapping `interior.py` **and** retiring the `photo_composition` interior vote removes all interior detection if `scene_probe.joblib` is absent (`SceneSignal` no-ops without it). Therefore:

1. **Step 1 (safe now):** taxonomy + `get_destination_path` tests. New buckets exist; nothing routes to them yet; zero behaviour change to live classification.
2. **Label → train → commit `scene_probe.joblib`.**
3. **Step 2 (one change):** land `SceneSignal` + weights + registry + `photo_composition` retirement **together with** the artifact. Never merge the model swap ahead of a trained artifact.
4. Backtest the weight; re-record goldens.

## Labeling protocol

Hand-sort into `results/scene_labels/{interior,exterior,place,neither}/` (see its `README.md`). Boundary: attached porch/patio → `exterior/`; landscape/travel/commercial → `place/`; non-scene (documents, portraits, products, sprites) → `neither/`. Target ~150–300 per positive class; a few hundred easy `neither/` images balance it.

```bash
python scripts/prototype_scene_probe.py gather --label-dirs
python scripts/prototype_scene_probe.py eval
python scripts/prototype_scene_probe.py train   # -> results/scene_probe.joblib
```

## v2 / future

- **`Accommodation` backoff** for thin Room-vs-House margins (needs a folder target — likely keep the leaf folder and soften only `@type` — decided from backtest thin-margin rates).
- Interiors already scaffold subtypes (`HotelRoom`/`MeetingRoom`); an exterior `House` vs commercial `CivicStructure`/`LandmarksOrHistoricalBuildings` split is a later signal.
- A `place` GPS/EXIF cross-check (the pipeline already extracts location) could corroborate the probe's `place` votes.

## Status of this landing (complete 2026-07-18)

- **Done:** taxonomy (`category_config.py`) + `get_destination_path` tests; `scripts/prototype_scene_probe.py` (+ a 5th `graphic` class, added beyond this plan's original four — see the graphic-probe item in `docs/BACKLOG.md`); `results/scene_labels/` corpus (835 rows at train time: neither 118, interior 178, exterior 158, place 347, graphic 33 — Places365 sampling filled place/exterior/interior).
- **Done:** `SceneSignal` (`src/scoring/signals/scene.py`) + `W_SCENE` + registry wiring, initially behind an artifact-gated swap per §Sequencing.
- **Done (swap completion):** `scene_probe.joblib` trained + committed (5-fold eval acc 0.92; interior F1 0.97, place 0.93, exterior 0.86, neither 0.92, graphic 0.70 — conservative graphic recall accepted by explicit decision); `interior.py` + registry fallback deleted; `photo_composition`'s `is_property_mgmt` vote retired (people-only now; `ROOM_SUBTYPE_SCHEMA` moved to `scene.py`); `W_INTERIOR` collapsed into `W_SCENE`; `backtest_scoring.WEIGHT_SIGNALS` row → `("W_SCENE", "scene")`; health check ported (`scene_probe` feature, 11/11); `_IMAGE_SCHEMA_TYPES` in `file_processor.py` extended with `House`/`Place`/`Accommodation` (scene @types would otherwise persist as `DigitalDocument`); `ContentOrganizer._stash_decision_state` ports the probe-wins description override via `SCENE_DESCRIPTION_LABELS`.
- **Backtest (2026-07-18, 202-row replay of `results/file_organization.db`):** `W_SCENE` ±20% flips 4/0 decisions — prior is stable at 0.85. Caveat: the replay classifies under `original_path` (pre-move, by design), so disk-dependent signals like the scene probe mostly no-op on rows whose files have since been organized away — replay disagreements on `Media/Interiors` rows are a harness limitation, not live misroutes. Reports: `results/backtest_scene_swap_20260718.json`, `results/backtest_scene_swap_sensitivity_20260718.json`.
- **Remaining (v2 / follow-ups):** `Accommodation` backoff for thin Room-vs-House margins (exterior↔place remains the hard boundary: ~20 swaps each way in eval); graphic-class recall (corpus volume — see BACKLOG); goldens for exterior/place cases if golden coverage is extended.
