# Scene-probe labeling corpus

Hand-labeled images for the scene probe (`scripts/prototype_scene_probe.py`),
consumed by the `SceneSignal`. Full design: [`docs/plans/MEDIA_EXTERIORS_PLAN.md`](../../docs/plans/MEDIA_EXTERIORS_PLAN.md).

Drop images (copies or symlinks) into the class dir that matches. The image
contents are git-ignored (see `.gitignore` here) — only this README is tracked.

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

> **`graphic/` is staged ahead of the code.** `SCENE_CLASSES` in
> `scripts/prototype_scene_probe.py` is still 4 classes, so `gather --label-dirs`
> currently **skips** `graphic/`. To train on it, add `"graphic": 4` to
> `SCENE_CLASSES` (+ `_POSITIVE_NAMES`) and map the class in
> `src/scoring/signals/scene.py` (`SCENE_CATEGORY` → `("media", "graphics_other")`,
> `SCENE_SCHEMA` → `ImageObject`). See the graphic-probe item in
> [`docs/BACKLOG.md`](../../docs/BACKLOG.md).

Then:

```bash
python scripts/prototype_scene_probe.py gather --label-dirs
python scripts/prototype_scene_probe.py eval          # CV metrics + confusion matrix
python scripts/prototype_scene_probe.py train         # -> results/scene_probe.joblib
```
