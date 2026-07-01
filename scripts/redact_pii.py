#!/usr/bin/env python3
"""Rasterize + OCR-redact PII from documents before adding them to version control.

Strategy (VCS-safe):
- PDF / image -> flatten to a bitmap (destroys any hidden text layer, embedded
  objects, and metadata -- the usual cause of "redacted" files still leaking),
  OCR the raster with docTR, paint OPAQUE black boxes over every token matching
  a PII pattern, then re-encode as a flat PNG with no metadata.
- Text (.txt/.md/.json) -> regex redaction (home-dir usernames, emails, secrets,
  tokens, and configured name terms).

Redaction is baked into pixels, not an overlay. Over-redaction is preferred to
under-redaction. Alphabetic PII with no digits (street names, third-party
names) is NOT reliably caught by the token patterns; rasterized documents are
therefore flagged `review_recommended` in the manifest so a human can verify
before `git add`.

Usage:
    python scripts/redact_pii.py <path>... --output DIR [--dpi 170] [--name TERM]...

<path> may be individual files or directories (scanned recursively for
supported extensions). Writes redacted copies plus a manifest.json to DIR.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None  # allow oversized inputs (maps, renders)

RASTER_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
TEXT_EXTS = {".txt", ".md", ".json", ".csv", ".log"}
SUPPORTED = RASTER_EXTS | IMAGE_EXTS | TEXT_EXTS

DEFAULT_DPI = 170
_BOX_PAD_PX = 2

# Any token matching these is blacked out / substituted. Digit-bearing PII
# (account, MRN, zip, ssn, phone, dates) plus emails are caught; alphabetic
# PII is not (see module docstring).
_TOKEN_PII = re.compile(
    r"("
    r"\d{3,}"                              # 3+ digit run
    r"|[\w.+-]+@[\w-]+\.[\w.-]+"          # email
    r"|\d{3}[-.\s]?\d{2}[-.\s]?\d{4}"    # ssn / phone-ish
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"    # date
    r")",
    re.I,
)


def is_pii_token(word: str, name_terms: list[str]) -> bool:
    w = word.strip()
    if not w:
        return False
    low = w.lower()
    if any(t in low for t in name_terms):
        return True
    return bool(_TOKEN_PII.search(w))


def redact_text(path: Path, name_terms: list[str]) -> tuple[str, int]:
    """Return (redacted_text, substitution_count)."""
    text = path.read_text(errors="ignore")
    count = 0

    def sub(pat: str, repl: str, s: str) -> str:
        nonlocal count
        s, c = re.subn(pat, repl, s)
        count += c
        return s

    text = sub(r"/Users/[^/\s\"']+", "/Users/<user>", text)
    text = sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<email>", text)
    text = sub(
        r"(?i)\b(api[_-]?key|token|secret|password|bearer|authorization)\b(\s*[:=]\s*)\S+",
        r"\1\2<redacted>",
        text,
    )
    text = sub(r"\beyJ[A-Za-z0-9_\-]{10,}\b", "<jwt>", text)
    text = sub(r"\b[A-Za-z0-9_\-]{32,}\b", "<redacted-token>", text)
    for term in name_terms:
        text = sub(rf"(?i)\b{re.escape(term)}\b", "<name>", text)
    return text, count


def redact_raster(png_paths: list[Path], model, name_terms: list[str]) -> int:
    """OCR each PNG in place and black out PII tokens. Returns boxes drawn."""
    from doctr.io import DocumentFile

    doc = DocumentFile.from_images([str(p) for p in png_paths])
    result = model(doc)
    boxes = 0
    for png, page in zip(png_paths, result.pages):
        im = Image.open(png).convert("RGB")
        width, height = im.size
        draw = ImageDraw.Draw(im)
        for block in page.blocks:
            for line in block.lines:
                for word in line.words:
                    if not is_pii_token(word.value, name_terms):
                        continue
                    (x0, y0), (x1, y1) = word.geometry
                    draw.rectangle(
                        [
                            x0 * width - _BOX_PAD_PX,
                            y0 * height - _BOX_PAD_PX,
                            x1 * width + _BOX_PAD_PX,
                            y1 * height + _BOX_PAD_PX,
                        ],
                        fill="black",
                    )
                    boxes += 1
        im.save(png, "PNG")  # overwrite flat, strips metadata
    return boxes


def rasterize_pdf(src: Path, stem: str, out_dir: Path, dpi: int) -> list[Path]:
    from pdf2image import convert_from_path

    outputs = []
    for i, page in enumerate(convert_from_path(str(src), dpi=dpi), 1):
        dst = out_dir / f"{stem}_p{i}.png"
        page.convert("RGB").save(dst, "PNG")
        outputs.append(dst)
    return outputs


def flatten_image(src: Path, stem: str, out_dir: Path) -> list[Path]:
    dst = out_dir / f"{stem}.png"
    Image.open(src).convert("RGB").save(dst, "PNG")  # convert() drops EXIF
    return [dst]


def _iter_inputs(paths: list[Path]):
    for p in paths:
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in SUPPORTED:
                    yield f
        elif p.is_file():
            yield p


def _stem(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", path.stem).strip("_").lower()


def redact(inputs: list[Path], out_dir: Path, dpi: int, name_terms: list[str]) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    model = None
    manifest: list[dict] = []
    for src in _iter_inputs(inputs):
        ext = src.suffix.lower()
        stem = _stem(src)
        entry: dict = {"source": str(src), "type": ext.lstrip(".")}
        try:
            if ext in TEXT_EXTS:
                text, n = redact_text(src, name_terms)
                dst = out_dir / f"{stem}{ext}"
                dst.write_text(text)
                entry.update(status="redacted", outputs=[dst.name],
                             text_subs=n, review_recommended=False)
            elif ext in RASTER_EXTS or ext in IMAGE_EXTS:
                if model is None:
                    from doctr.models import ocr_predictor
                    print("loading docTR model...", flush=True)
                    model = ocr_predictor(pretrained=True)
                pngs = (rasterize_pdf(src, stem, out_dir, dpi) if ext in RASTER_EXTS
                        else flatten_image(src, stem, out_dir))
                boxes = redact_raster(pngs, model, name_terms)
                entry.update(status="redacted", outputs=[p.name for p in pngs],
                             boxes_blacked=boxes, review_recommended=True)
            else:
                entry["status"] = "skipped_unsupported"
            print(f"OK  {src.name} -> {entry.get('outputs')}", flush=True)
        except Exception as e:  # keep going; one bad file must not abort the batch
            entry.update(status="error", error=repr(e))
            print(f"ERR {src.name}: {e}", flush=True)
        manifest.append(entry)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description="Rasterize + OCR-redact PII before committing files.")
    ap.add_argument("paths", nargs="+", type=Path, help="Files or directories to redact.")
    ap.add_argument("--output", type=Path, default=Path("results/redacted"),
                    help="Output directory (default: results/redacted).")
    ap.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="Rasterization DPI (default: 170).")
    ap.add_argument("--name", action="append", default=[], metavar="TERM",
                    help="Extra name term to redact (repeatable).")
    args = ap.parse_args()

    manifest = redact(args.paths, args.output, args.dpi, args.name)
    redacted = [m for m in manifest if m.get("status") == "redacted"]
    review = [m["source"] for m in redacted if m.get("review_recommended")]
    print(f"\n{len(redacted)}/{len(manifest)} redacted -> {args.output}")
    print(f"manifest -> {args.output / 'manifest.json'}")
    if review:
        print("\nHUMAN REVIEW REQUIRED before `git add` (alphabetic PII may remain):")
        for s in review:
            print(f"  - {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
