# Interior-Room Detection — Durable-Fix Analysis

**Date:** 2026-07-17
**Method:** empirical CLIP probing of a single failing image (open_clip `ViT-B-32`, reusing the production `CLIPClassifier` API) plus code inspection of the interior-detection path (`src/analyzers/image_analyzer.py`, `src/scoring/signals/photo_composition.py`, `scripts/shared/clip_utils.py`).
**Scope:** why the interior detector fails to route an obvious interior photo to `Media/Interiors` (schema.org `Room`), and a pros/cons comparison of three durable fixes — CLIP `ViT-L-14`, SigLIP, and a small purpose-trained binary interior classifier.
**Trigger:** `Media/Interiors` / schema.org `Room` folder addition (2026-07-17). The auto-routing signal (`PhotoCompositionSignal` interior flag) never fires on a representative AI-generated interior render.

---

## Reference image

`~/Downloads/ChatGPT Image Oct 31, 2025, 01_30_52 PM.png` — an AI-generated interior render of a laundry room (stacked washer/dryer, wood cabinet + stone counter, floating shelves with a plant and framed botanical prints, torchiere lamp, patterned floor). Unambiguously an interior room to a human.

---

## Measured failure

Two separate CLIP passes touch this image in production, and both miss.

### 1. `ImageContentAnalyzer.analyze_for_organization` (the interior gate)

11-label softmax over `_ALL_CATEGORIES`; `is_interior = interior_score > _INTERIOR_SCORE_THRESHOLD (0.30)`.

| Label | Score |
|---|---|
| a photo of a home interior room | **0.0963** |
| a photo of a kitchen | 0.0952 |
| a photo of furniture | 0.0934 |
| a photo of a bathroom | 0.0920 |
| a photo of a bedroom | 0.0909 |
| a photo of a living room | 0.0907 |
| a photo of people | 0.0888 |
| a screenshot of a computer screen | 0.0885 |
| a photo of a house exterior | 0.0883 |
| a photo of outdoors | 0.0882 |
| a photo of nature | 0.0876 |

`interior_score = 0.0963` vs threshold `0.30` → **misses by ~3×**. `has_people=False`, `is_home_interior_no_people=False`. The scores are pinned to the softmax uniform floor (1/11 ≈ 0.0909); the true label wins by ~0.005.

### 2. `ClipVisionSignal` (20-prompt vocab, unified scorer)

Top interior-adjacent label `"an interior room"` scored **0.0527** and mapped to `property_management/other` — also at floor, and it loses to `mime_fallback` regardless.

### Net effect

`PhotoCompositionSignal` emits nothing → no `Room` schema override → the file commits to `media/graphics_other` → `ImageObject` via `mime_fallback` (`0.4 × 1.0 = 0.4`). Confirmed against the shadow log.

### Does a binary contrast rescue it? Partially.

Re-scoring the same image with smaller label sets (reusing the production softmax path):

| Contrast | Interior score | Runner-up | Verdict |
|---|---|---|---|
| 11-way (current) | 0.0963 | 0.0952 | fails hard |
| interior vs outdoor | **0.5161** | 0.4839 | barely wins (Δ 0.03) |
| interior / outdoor / screenshot | 0.3474 | 0.3269 | near-tie |
| interior vs 7 broad alternatives | 0.1302 | 0.1262 | floor again |

The binary contrast is a **51.6% coin-flip** — better than the diluted 0.096, but not a confident interior. Every added label steals softmax mass and drags the target back to the floor.

---

## Root cause — two tangled causes

1. **Softmax dilution.** Scoring the interior label against many competing labels in one softmax collapses every probability toward the uniform floor; adding labels makes it strictly worse. This is a scoring-shape problem, independent of the backbone.
2. **Weak zero-shot separability.** Even head-to-head, `ViT-B-32` barely distinguishes this AI render from "outdoor scene". This is a backbone/representation problem.

The two demand different fixes, and the recommendation hinges on **which dominates** — which the sequence below is designed to determine cheaply.

> This is the same softmax-floor failure documented in the BACKLOG item *"Logo/icon/graphic detection needs a non-CLIP signal"*. Interiors are a milder case (binary contrast at least crosses 0.5), but the mechanism is identical.

---

## Grounding facts (current system)

- Backbone: open_clip **`ViT-B-32`**, OpenAI pretrained, 224px input, **512-dim** embeddings (`scripts/shared/clip_utils.py`).
- Embedding cache: `.cache/clip_embeddings_v2/` (fp32 `.npy` per image), consumed by `image_analyzer` and `clip_cache`.
- CLIP is a **`heavy`** cost-tier signal; the corpus is 265k+ files, inference runs locally on macOS (MPS weak/CPU-bound for several models).
- Any change to routing weights/thresholds is **versioned data** requiring a `results/file_organization.db` backtest committed with its report (`src/scoring/weights.py` header; Phase-3 process).

---

## Options

### Comparison matrix

| Dimension | CLIP `ViT-L-14` | SigLIP (base/L) | Trained probe on embeddings |
|---|---|---|---|
| Integration effort | **Low** (open_clip drop-in) | Medium (new HF/transformers path) | **Low** (sklearn head, no backbone change) |
| Fixes softmax dilution | No (still softmax) | **Yes** (sigmoid, per-label) | **Yes** (learns boundary directly) |
| Fixes weak separability | Partially | Partially–Yes | Only if features already separable |
| Needs labeled data | No | No | **Yes** (~few hundred) |
| Cache invalidation | **Yes** (768-dim re-encode) | **Yes** (new space) | **No** (reuses cache) |
| Latency / memory | High (~3–5×) | Med–High | **Negligible** (one matmul) |
| Lifts *other* CLIP signals | **Yes** | Yes (if full migration) | No (interiors only) |
| Ongoing ownership | None | Low | **Retrain / maintain** |

### Option A — CLIP `ViT-L-14` (open_clip)

**Pros**
- True drop-in: swap `MODEL_NAME` / `PRETRAINED` in the `CLIPClassifier` singleton; identical API.
- Much stronger zero-shot (~75% vs ~63% ImageNet-1k) → sharper scene discrimination; better odds on hard renders.
- No labeled data.
- A backbone upgrade lifts **every** CLIP-based signal (photos, screenshots, geographic), not just interiors.

**Cons**
- ~1.7 GB model, ~3–5× slower inference, higher RAM — material on the 265k-file batch path and local MPS/CPU.
- **Invalidates the entire 512-dim embedding cache** (`ViT-L-14` is 768-dim), forcing a full corpus re-encode and touching every consumer that assumes 512.
- Still softmax → **does not fix dilution** unless paired with a binary/scene-set contrast.
- Improvement on AI renders is probabilistic, not guaranteed; still needs threshold recalibration + backtest.

### Option B — SigLIP

**Pros**
- Trained with a **sigmoid pairwise loss**: each image–text pair is scored *independently*, with no softmax denominator stealing mass. This is the most principled answer to the measured dilution — `P(interior)` stays stable regardless of how many other labels exist, so the threshold doesn't collapse.
- SOTA zero-shot; SigLIP2-L is very strong on scene understanding.
- Per-label calibrated probability → a stable, interpretable operating point.

**Cons**
- Not a clean open_clip swap: needs a `transformers`/timm loading path, its own preprocessing (resize/normalization), and a separate cache namespace.
- Running it *alongside* open_clip (for the other signals) roughly doubles resident model memory; a full migration is a larger project.
- Sigmoid scores are absolute and need per-model calibration (temperature/bias).
- Larger variants are heavy; SigLIP-base is lighter and still competitive.

### Option C — small purpose-trained binary interior classifier

**C1 — linear/MLP probe on existing cached embeddings** (logistic regression on the 512-dim `ViT-B-32` features already in `.cache/clip_embeddings_v2/`).

**Pros**
- Near-free: trains in seconds on CPU, **zero cache invalidation**, one matmul at inference on the already-computed embedding.
- Optimizes the *actual* interior-vs-not boundary on **this** distribution (including AI renders) instead of generic zero-shot semantics — it learns exactly what zero-shot gets wrong.
- Deterministic, versionable artifact (`.joblib`/`.npz`) — fits the Phase-3 "versioned data + backtest" process cleanly.
- Labels are sourceable from the existing evaluation test-set + correction-feedback infrastructure.
- Integrates as a new `InteriorSignal` emitting `media/interiors_other` + the `Room` override.

**Cons**
- Ceiling = the frozen `ViT-B-32` features. If the embedding genuinely doesn't encode "interior" for a render, a linear probe can't invent it (though a probe routinely extracts far more than zero-shot prompting — see insight).
- Requires a labeled set + held-out eval; risk of overfitting the small set; needs a balanced AI-render vs real-photo split.
- Interiors-only — no lift to other signals.
- Ongoing ownership: retrain as the distribution drifts.

**C2 — standalone small CNN** (MobileNetV3 / EfficientNet-lite, binary fine-tune): most robust to the backbone ceiling, but adds a second model + training infra + its own inference cost. Overkill unless C1 *and* a backbone bump both underperform.

---

## Key insight

The **0.516 coin-flip was a zero-shot *prompting* result, not proof the embedding lacks the signal.** A supervised probe learns the "interior direction" directly in embedding space and commonly turns a near-floor zero-shot score into strong linear separability. So the cheapest experiment (C1) is also the most diagnostic: it tells you whether the failure is *scoring shape* (fixable without touching the backbone) or *representation* (needs A/B).

---

## Recommendation — staged

1. **Prototype C1 on the current `ViT-B-32` embeddings.** Label a few hundred interiors + hard negatives (products on white, other AI renders, outdoors), fit logistic regression on cached embeddings, measure AUC / precision-recall **and** false-positive spillover onto real photos.
   - **Separates well** → ship C1 as an `InteriorSignal` (`media/interiors_other` + `Room` override). No backbone change, no re-encode.
   - **Underperforms** → the `ViT-B-32` embedding is the ceiling. Upgrade the backbone, preferring **SigLIP** for this task (sigmoid scoring is the right tool for "presence of interior"), or **`ViT-L`** to stay in open_clip and lift all signals at once — accepting the latency + full re-encode. Optionally re-fit the C1 probe on the new embeddings (best of both).
2. **Whichever wins:** recalibrate the threshold and run the **Phase-3 backtest against `results/file_organization.db`**, committing the report — the same gate as the `PHOTO_PROPERTY_CONFIDENCE` re-tune item.

**One-line verdict:** don't reach for a heavier backbone first — a linear probe on the embeddings already cached is the highest-ROI move and often resolves the issue; treat `ViT-L`/SigLIP as the fallback if the probe proves the `ViT-B-32` features are the ceiling, with SigLIP the more principled of the two for this dilution-shaped failure.

---

## Prototype status (2026-07-17)

The C1 harness exists: **`scripts/prototype_interior_probe.py`** — `gather` (build a labeled manifest from directory-per-class roots, explicit files, or the graph DB) and `eval` (load embeddings via the production `clip_cache`, fit a `StandardScaler` + class-balanced `LogisticRegression`, stratified k-fold CV, ROC-AUC / average-precision / threshold sweep). Reuses the exact cache, so it also warms it; sklearn is now a dev dependency.

**Mechanism validated on the current cache.** A proxy binary task (`game_assets/sprites` vs `media/photos`, both populated in the DB, 11 vs 34 real cached `ViT-B-32` embeddings) scored **ROC-AUC 0.987 / AP 0.972** under 5-fold CV — the linear-probe-on-cached-embeddings pipeline extracts strongly separable signal, confirming the approach is sound end-to-end.

**Blocker: no interior labels.** The graph DB contains **zero interior positives** — the weak detector this probe replaces never produced any, so there is nothing to bootstrap from. The one known interior (the reference render) is a single positive; an actual interior eval needs a hand-labeled set. Next step is purely data-gathering:

```
python scripts/prototype_interior_probe.py gather \
    --interior /path/to/interior_photos --db-negatives
python scripts/prototype_interior_probe.py eval --score-reference
```

Target ~150–300 interiors (mixing AI renders + real photos) against the DB-derived negatives, then read ROC-AUC / AP and the false-positive column. If it separates, ship C1 as an `InteriorSignal`; if not, that is the empirical trigger to move to SigLIP / `ViT-L`.

---

## Related

- Shipped taxonomy + routing: `src/organizers/category_config.py` (`media.interiors`), `src/scoring/signals/photo_composition.py` (`PROPERTY_PHOTO_CATEGORY`, `ROOM_SUBTYPE_SCHEMA`), tests in `tests/unit/scoring/test_signal_photo_composition.py`.
- Commit-margin follow-up: `docs/BACKLOG.md` → *`PHOTO_PROPERTY_CONFIDENCE` re-tune for `Media/Interiors` commit margin* (a distinct issue — that tunes the commit margin once the interior flag is `True`; this analysis is about making the flag fire in the first place).
- Prior art on the softmax-floor failure mode: `docs/BACKLOG.md` → *Logo/icon/graphic detection needs a non-CLIP signal*.
