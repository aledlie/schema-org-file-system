# Scene-probe labeling corpus

Hand-labeled images for the 4-class scene probe (`scripts/prototype_scene_probe.py`),
consumed by the future `SceneSignal`. Full design: [`docs/plans/MEDIA_EXTERIORS_PLAN.md`](../../docs/plans/MEDIA_EXTERIORS_PLAN.md).

Drop images (copies or symlinks) into the class dir that matches. The image
contents are git-ignored (see `.gitignore` here) — only this README is tracked.

| Dir | Scene class | Routes to | schema.org @type | What belongs here |
|-----|-------------|-----------|------------------|-------------------|
| `interior/` | interior | `Media/Interiors` | `Room` | indoor rooms — bedrooms, kitchens, offices, hotel/meeting rooms |
| `exterior/` | exterior | `Media/Exteriors` | `House` | house/building facades **and attached porches & patios** |
| `place/`    | place    | `Media/Place`     | `Place` | outdoor / landscape / travel; non-residential or commercial scenes |
| `neither/`  | neither  | *(no vote)*       | —       | non-scene images: documents, screenshots, sprites, portraits, product shots |

Boundary rules (locked 2026-07-17):
- A **covered patio or porch attached to a residence → `exterior/`** (not place).
- **Landscapes, streetscapes, parks, travel, storefronts, commercial buildings → `place/`.**
- When unsure whether an image is even a scene (a person portrait, a product, a
  document photo), put it in `neither/` — the reject class keeps the probe from
  forcing every image into a room/house/place.

Aim for **150–300 per positive class** for a reliable probe; a few hundred easy
`neither/` images (any non-scene photo) balance it. Then:

```bash
python scripts/prototype_scene_probe.py gather --label-dirs
python scripts/prototype_scene_probe.py eval          # CV metrics + confusion matrix
python scripts/prototype_scene_probe.py train         # -> results/scene_probe.joblib
```
