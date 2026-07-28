#!/usr/bin/env python3
"""Populate the scene-probe ``graphic/`` class from the Crello template dataset.

Source: ``cyberagent/crello`` on the Hugging Face Hub (23,302 graphic-design
templates, each carrying a pre-rendered raster ``preview``). Rows are selected
server-side by the dataset's own 67-value ``format`` label, so the flat-design
subtypes the ``graphic`` class is starved on -- logos, posters, flyers,
infographics, ad creatives -- are a metadata filter rather than a labeling pass.

Two filters make the pull usable as *positives* rather than raw volume:

- **No ``ImageElement``.** Crello templates may embed photographs under a text
  overlay, which are visually closer to ``neither`` than to flat design. Keeping
  only ``SvgElement`` / ``TextElement`` / ``ColoredBackground`` / ``SvgMaskElement``
  compositions yields pure vector-and-type artwork.
- **One per ``cluster_index`` per format.** Crello clusters near-identical
  template variants; taking one member each keeps the sample diverse and stops
  near-duplicates leaking across the probe's CV folds.

Previews are re-encoded to JPEG at ``_TARGET_LONGEST_SIDE`` rather than saved as
native PNG. The corpus already correlates encoding with class -- ``place/`` is
100% JPEG at ~256px, ``graphic/`` mostly PNG at ~1536px -- and dropping 250 more
large PNGs into ``graphic/`` would deepen a format-vs-label shortcut of exactly
the kind Grommelt et al. (arXiv:2403.17608) measured at ~11pp on generated-image
detectors.

**Licensing.** CyberAgent does not own the underlying templates: the dataset is
packaged CDLA-Permissive-2.0 but conditions use on the VistaCreate license
agreements (https://create.vista.com/faq/legal/licensing/license_agreements/),
and the curators deliberately do not redistribute source files. Training a local
probe is fine; committing the images is not. The outputs are therefore gitignored
(``results/scene_labels/.gitignore``) and this script is the way to reproduce
them, mirroring how ``scripts/download_census_names.py`` backs the gitignored
surname gazetteer.

    python scripts/download_crello_graphics.py            # ~250 images
    python scripts/download_crello_graphics.py --limit 60 --dry-run
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import requests
from PIL import Image

_FILTER_URL = "https://datasets-server.huggingface.co/filter"
_DATASET = "cyberagent/crello"
_CONFIG = "default"
_SPLITS = ("train", "validation", "test")

# Element-type ClassLabel index whose presence means the template embeds a
# raster photo (vocabulary: SvgElement, TextElement, ImageElement,
# ColoredBackground, SvgMaskElement).
_IMAGE_ELEMENT = 2

# Crello ``format`` ClassLabel index -> (slug, images to take). Caps spread the
# pull across subtypes so no single format dominates the class; they are ceilings,
# not quotas, and thin formats simply yield what they have.
_FORMAT_QUOTAS: Dict[int, tuple] = {
    22: ("logo", 30),
    6: ("poster", 30),
    5: ("facebook-ad", 30),
    7: ("instagram-ad", 30),
    11: ("flyer", 25),
    18: ("graphic", 25),
    20: ("poster-us", 25),
    27: ("gift-certificate", 15),
    30: ("business-card", 15),
    34: ("certificate", 15),
    39: ("coupon", 10),
    52: ("label", 10),
    61: ("infographic", 17),
    64: ("web-banner", 5),
}

_MAX_PER_CLUSTER = 1
_PAGE_SIZE = 100  # datasets-server /filter hard cap
_TARGET_LONGEST_SIDE = 512  # > CLIP's 224 input, < the class's 1536px PNG mode
_JPEG_QUALITY = 90
_TIMEOUT = 120
_INDEX_WARMUP_RETRIES = 6
_INDEX_WARMUP_DELAY = 15

_OUT_DIR = Path(__file__).resolve().parents[1] / "results/scene_labels/graphic"
_MANIFEST = _OUT_DIR / "crello_manifest.csv"
_FILE_PREFIX = "crello_"


def _get(params: dict) -> dict:
    """GET the filter endpoint, waiting out the dataset index's cold start."""
    for attempt in range(_INDEX_WARMUP_RETRIES):
        resp = requests.get(_FILTER_URL, params=params, timeout=_TIMEOUT)
        if resp.status_code == 200:
            return dict(resp.json())
        # The index builds on first query and 500s with an explicit message.
        if resp.status_code == 500 and "loading" in resp.text:
            time.sleep(_INDEX_WARMUP_DELAY)
            continue
        raise RuntimeError(f"HTTP {resp.status_code} from datasets-server: {resp.text[:200]}")
    raise RuntimeError("datasets-server index still loading after retries")


def _iter_rows(fmt: int, split: str) -> Iterable[dict]:
    offset = 0
    while True:
        page = _get(
            {
                "dataset": _DATASET,
                "config": _CONFIG,
                "split": split,
                "where": f'"format"={fmt}',
                "offset": offset,
                "length": _PAGE_SIZE,
            }
        )
        rows = page.get("rows", [])
        for entry in rows:
            yield dict(entry["row"])
        offset += len(rows)
        if not rows or offset >= page.get("num_rows_total", 0):
            return


def select_rows(fmt: int, quota: int) -> List[dict]:
    """Flat-design rows for ``fmt``, at most ``_MAX_PER_CLUSTER`` per cluster."""
    per_cluster: Dict[object, int] = {}
    picked: List[dict] = []
    for split in _SPLITS:
        for row in _iter_rows(fmt, split):
            if len(picked) >= quota:
                return picked
            if _IMAGE_ELEMENT in (row.get("type") or []):
                continue  # photo-backed template, not flat design
            cluster = row.get("cluster_index")
            if per_cluster.get(cluster, 0) >= _MAX_PER_CLUSTER:
                continue
            per_cluster[cluster] = per_cluster.get(cluster, 0) + 1
            picked.append(row)
    return picked


def _preview_url(row: dict) -> Optional[str]:
    preview = row.get("preview")
    if isinstance(preview, dict):
        src = preview.get("src")
        return str(src) if src else None
    return None


def save_preview(row: dict, slug: str, out_dir: Path) -> Optional[Path]:
    """Download one preview and write it as a size/quality-normalized JPEG."""
    url = _preview_url(row)
    if not url:
        return None
    resp = requests.get(url, timeout=_TIMEOUT)
    resp.raise_for_status()
    with Image.open(io.BytesIO(resp.content)) as img:
        rgb = img.convert("RGB")
        rgb.thumbnail((_TARGET_LONGEST_SIDE, _TARGET_LONGEST_SIDE), Image.Resampling.LANCZOS)
        dest = out_dir / f"{_FILE_PREFIX}{slug}_{row['id']}.jpg"
        rgb.save(dest, "JPEG", quality=_JPEG_QUALITY)
    return dest


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", default=str(_OUT_DIR), help="destination class dir")
    ap.add_argument("--limit", type=int, default=None, help="stop after N images total")
    ap.add_argument("--dry-run", action="store_true", help="select rows, download nothing")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: List[dict] = []
    selected = 0  # counts dry-run picks too, so --limit bounds both modes
    for fmt, (slug, quota) in _FORMAT_QUOTAS.items():
        if args.limit is not None and selected >= args.limit:
            break
        if args.limit is not None:
            quota = min(quota, args.limit - selected)
        try:
            rows = select_rows(fmt, quota)
        except RuntimeError as exc:
            print(f"  {slug:18s} SKIPPED ({exc})", file=sys.stderr)
            continue

        saved = 0
        selected += len(rows)
        for row in rows:
            if args.dry_run:
                saved += 1
                continue
            try:
                if save_preview(row, slug, out_dir):
                    saved += 1
                    written.append(
                        {
                            "file": f"{_FILE_PREFIX}{slug}_{row['id']}.jpg",
                            "crello_id": row["id"],
                            "format": slug,
                            "cluster_index": row.get("cluster_index"),
                            "canvas": f"{row.get('canvas_width')}x{row.get('canvas_height')}",
                        }
                    )
            except Exception as exc:  # a single dead asset URL must not kill the pull
                print(f"    {row.get('id')}: {type(exc).__name__} {exc}", file=sys.stderr)
        print(f"  {slug:18s} {saved:3d} images", flush=True)

    if args.dry_run:
        print("dry run — nothing written")
        return 0

    with _MANIFEST.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["file", "crello_id", "format", "cluster_index", "canvas"]
        )
        writer.writeheader()
        writer.writerows(written)

    print(f"\nwrote {len(written)} images to {out_dir}")
    print(f"manifest: {_MANIFEST}")
    print("\nNext: python scripts/prototype_scene_probe.py gather --label-dirs && ... eval")
    return 0


if __name__ == "__main__":
    sys.exit(main())
