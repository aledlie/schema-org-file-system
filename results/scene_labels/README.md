# Scene-probe labeling corpus

Hand-labeled images for the scene probe (`scripts/prototype_scene_probe.py`),
consumed by the `SceneSignal`. Full design: [`docs/plans/MEDIA_EXTERIORS_PLAN.md`](../../docs/plans/MEDIA_EXTERIORS_PLAN.md).

Drop images (copies or symlinks) into the class dir that matches. `interior/`,
`exterior/`, `place/` and `neither/` are git-ignored (personal images); `graphic/`
is tracked **except** third-party pulls matching `crello_*` — see
[Sourcing `graphic/`](#sourcing-graphic) below.

| Dir | Scene class | Routes to | schema.org @type | What belongs here |
|-----|-------------|-----------|------------------|-------------------|
| `interior/` | interior | `Media/Interiors` | `Room` | indoor rooms — bedrooms, kitchens, offices, hotel/meeting rooms |
| `exterior/` | exterior | `Media/Exteriors` | `House` | house/building facades **and attached porches & patios** |
| `place/`    | place    | `Media/Place`     | `Place` | outdoor / landscape / travel; non-residential or commercial scenes |
| `graphic/`  | graphic  | `Media/Graphics`  | `ImageObject` | non-photographic imagery: logos, marketing/text posters, icon sets, diagrams/infographics, data-viz (maps w/ overlays), flat/vector illustrations |
| `neither/`  | neither  | *(no vote)*       | —       | reject class — real photographs that aren't a scene (portraits, product shots, still-lifes), plus documents & UI screenshots |

Boundary rules (locked 2026-07-17; `graphic/` added 2026-07-18):
- A **covered patio or porch attached to a residence → `exterior/`** (not place).
- **Landscapes, streetscapes, parks, travel, storefronts, commercial buildings → `place/`.**
- **`graphic/` vs `neither/` is the graphic-vs-photograph split.** Anything
  synthetic — a logo, text poster, icon set, diagram, chart, map-with-overlays,
  or flat/vector illustration → `graphic/`. A **real (or photorealistic)
  photograph** of a product, person, or object → `neither/`. A photorealistic
  AI render (e.g. a staged product still-life) is a **photograph → `neither/`**,
  not a graphic. This class is the fix for opaque full-bleed graphics that leak
  past the cheap `GraphicDetectionSignal` gate to `photos_*` — do **not** file
  logos/posters in `neither/` (that trains the probe to reject the very thing it
  must catch).
- When unsure whether an image is even a scene (a person portrait, a product, a
  document photo), put it in `neither/` — the reject class keeps the probe from
  forcing every image into a room/house/place/graphic.

Aim for **150–300 per positive class** for a reliable probe; a few hundred easy
`neither/` images (any non-scene photo) balance it.

> **`graphic/` is live in the code (2026-07-18).** `SCENE_CLASSES` includes
> `"graphic": 4` (`gather --label-dirs` ingests `graphic/`; `--graphic DIR` adds
> external roots) and `src/scoring/signals/scene.py` maps it to
> `("media", "graphics_other")` / `ImageObject`. Corpus volume is what remains —
> see the graphic-probe item in [`docs/BACKLOG.md`](../../docs/BACKLOG.md).

## Sourcing `graphic/`

Local sources of *pure* graphics are tapped out, so the bulk of this class comes
from the **Crello** template dataset (`cyberagent/crello`):

```bash
python scripts/download_crello_graphics.py     # -> graphic/crello_*.jpg
```

The script selects on Crello's own `format` label (Logo, Poster, Infographic,
Web Banner, Flyer, ad creatives…), drops any template containing an
`ImageElement` (those embed photographs and belong nearer `neither/`), and takes
one template per `cluster_index` so near-duplicate variants can't leak across CV
folds. Previews are re-encoded to JPEG at 512px rather than kept as native PNG —
`place/` is 100% JPEG at ~256px and the hand-collected `graphic/` images are
mostly PNG at ~1536px, so unfiltered PNG imports would deepen an
encoding-correlates-with-class shortcut.

**These images are git-ignored and must not be committed.** CyberAgent does not
own the templates; the dataset is CDLA-Permissive-2.0 but conditioned on the
VistaCreate license agreements, and the curators do not redistribute source
files. Local training is fine, redistribution is not — the script is how a fresh
clone reproduces the corpus, the same arrangement as
`scripts/download_census_names.py` and the gitignored surname gazetteer.

Then:

```bash
python scripts/prototype_scene_probe.py gather --label-dirs
python scripts/prototype_scene_probe.py eval          # CV metrics + confusion matrix
python scripts/prototype_scene_probe.py train         # -> results/scene_probe.joblib
```
