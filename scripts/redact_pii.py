#!/usr/bin/env python3
"""Rasterize + OCR-redact PII from documents before adding them to version control.

Strategy (VCS-safe):
- PDF / image -> flatten to a bitmap (destroys any hidden text layer, embedded
  objects, and metadata -- the usual cause of "redacted" files still leaking),
  detect and cover barcodes/QR codes (invisible to OCR), OCR the raster with
  docTR, paint OPAQUE black boxes over every token matching a PII pattern,
  then re-encode as a flat PNG with no metadata.
- Text (.txt/.md/.json) -> regex redaction (home-dir usernames, emails, secrets,
  tokens, and configured name/term lists).

Redaction is baked into pixels, not an overlay. Over-redaction is preferred to
under-redaction.

Known limitations (always review before `git add`):
- Alphabetic PII with no digits (street names, third-party names, health
  conditions) is NOT caught by token patterns unless supplied via --name or
  --redact-terms.
- Rotated text may be missed by the OCR detector.
- Low-contrast text (faint ink, dark-mode screenshots) can be missed by OCR.
- Barcodes that cannot be localised by the detector are flagged
  `barcode_unredacted: true` in the manifest and cause a non-zero exit.

Usage:
    python scripts/redact_pii.py <path>... --output DIR [--dpi 170]
        [--name TERM]... [--redact-terms TERM]...

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
# PII is not unless supplied via --name / --redact-terms (see module docstring).
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


def detect_and_cover_barcodes(png: Path) -> tuple[int, int]:
    """Detect barcodes and QR codes; paint solid black boxes over every one found.

    Uses cv2.barcode_BarcodeDetector (1-D / PDF417) and cv2.QRCodeDetector.
    If cv2 is not available the function is a no-op and returns (0, 0).

    Returns:
        (detected, covered) — detected = total barcode symbols found,
        covered = successfully blacked out. covered < detected signals that
        at least one barcode was detected but not localised; callers should
        treat that as a hard failure.
    """
    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
    except ImportError:
        return 0, 0

    img_bgr = cv2.imread(str(png))
    if img_bgr is None:
        return 0, 0

    all_polys: list[np.ndarray] = []

    # 1-D / PDF417 / DataMatrix barcodes
    # cv2 stubs omit the barcode module; the symbol exists at runtime.
    bd = cv2.barcode_BarcodeDetector()  # type: ignore[attr-defined]
    ok_bd, pts_bd = bd.detectMulti(img_bgr)
    if ok_bd and pts_bd is not None:
        for poly in pts_bd:
            all_polys.append(poly)

    # QR codes
    qr = cv2.QRCodeDetector()
    ok_qr, pts_qr = qr.detectMulti(img_bgr)
    if ok_qr and pts_qr is not None:
        for poly in pts_qr:
            # detectMulti may return (N,4,1,2) or (N,4,2)
            poly = np.asarray(poly)
            if poly.ndim == 3:
                poly = poly.reshape(-1, 2)
            all_polys.append(poly)

    detected = len(all_polys)
    if detected == 0:
        return 0, 0

    im = Image.open(png).convert("RGB")
    draw = ImageDraw.Draw(im)
    covered = 0
    for poly in all_polys:
        try:
            pts_flat = [(float(x), float(y)) for x, y in poly]
            if len(pts_flat) < 3:
                continue
            xs = [p[0] for p in pts_flat]
            ys = [p[1] for p in pts_flat]
            x0 = max(0.0, min(xs) - _BOX_PAD_PX)
            y0 = max(0.0, min(ys) - _BOX_PAD_PX)
            x1 = min(float(im.width), max(xs) + _BOX_PAD_PX)
            y1 = min(float(im.height), max(ys) + _BOX_PAD_PX)
            draw.rectangle([x0, y0, x1, y1], fill="black")
            covered += 1
        except (TypeError, ValueError):
            pass  # degenerate polygon — counted as unlocalized

    im.save(png, "PNG")
    return detected, covered


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


def redact_raster(
    png_paths: list[Path],
    model,
    name_terms: list[str],
) -> int:
    """OCR each PNG in place and black out PII tokens. Returns boxes drawn.

    name_terms: combined list of --name and --redact-terms values, all treated
    as case-insensitive substring matches against each OCR word token.
    """
    from doctr.io import DocumentFile  # noqa: PLC0415

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
    from pdf2image import convert_from_path  # noqa: PLC0415

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


def redact(
    inputs: list[Path],
    out_dir: Path,
    dpi: int,
    name_terms: list[str],
    sensitive_terms: list[str] | None = None,
) -> list[dict]:
    """Redact PII from each input file and write outputs + manifest to out_dir.

    name_terms: proper-name substrings to redact (--name).
    sensitive_terms: alphabetic sensitive terms (--redact-terms): health
        conditions, org names, etc. Treated identically to name_terms for OCR
        token matching; kept separate for caller clarity.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    all_terms = list(name_terms) + list(sensitive_terms or [])
    model = None
    manifest: list[dict] = []
    for src in _iter_inputs(inputs):
        ext = src.suffix.lower()
        stem = _stem(src)
        entry: dict = {"source": str(src), "type": ext.lstrip(".")}
        try:
            if ext in TEXT_EXTS:
                text, n = redact_text(src, all_terms)
                dst = out_dir / f"{stem}{ext}"
                dst.write_text(text)
                entry.update(status="redacted", outputs=[dst.name],
                             text_subs=n, review_recommended=False)
            elif ext in RASTER_EXTS or ext in IMAGE_EXTS:
                if model is None:
                    from doctr.models import ocr_predictor  # noqa: PLC0415
                    print("loading docTR model...", flush=True)
                    model = ocr_predictor(pretrained=True)
                pngs = (rasterize_pdf(src, stem, out_dir, dpi) if ext in RASTER_EXTS
                        else flatten_image(src, stem, out_dir))

                # --- barcode pass (before OCR so covered pixels don't confuse detector) ---
                bc_detected = bc_covered = 0
                for png in pngs:
                    det, cov = detect_and_cover_barcodes(png)
                    bc_detected += det
                    bc_covered += cov
                bc_unlocalized = bc_detected - bc_covered
                if bc_detected:
                    status_str = f"{bc_covered}/{bc_detected} covered"
                    if bc_unlocalized:
                        print(
                            f"BARCODE WARNING  {src.name}: {bc_unlocalized} barcode(s) detected"
                            " but NOT localised — manual redaction required",
                            flush=True,
                        )
                    else:
                        print(f"BARCODE  {src.name}: {status_str}", flush=True)

                boxes = redact_raster(pngs, model, all_terms)
                entry.update(
                    status="redacted",
                    outputs=[p.name for p in pngs],
                    boxes_blacked=boxes,
                    barcode_detected=bc_detected,
                    barcode_covered=bc_covered,
                    barcode_unredacted=bc_unlocalized > 0,
                    review_recommended=True,
                )
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
                    help="Proper-name substring to redact (repeatable). Matched case-insensitively"
                         " against each OCR word token.")
    ap.add_argument("--redact-terms", action="append", default=[], metavar="TERM",
                    dest="redact_terms",
                    help="Alphabetic sensitive term to redact (repeatable): health conditions,"
                         " org names, etc. Matched identically to --name but documented"
                         " separately for clarity.")
    args = ap.parse_args()

    manifest = redact(args.paths, args.output, args.dpi, args.name, args.redact_terms)
    redacted = [m for m in manifest if m.get("status") == "redacted"]
    review = [m["source"] for m in redacted if m.get("review_recommended")]
    unredacted_barcodes = [m["source"] for m in redacted if m.get("barcode_unredacted")]

    print(f"\n{len(redacted)}/{len(manifest)} redacted -> {args.output}")
    print(f"manifest -> {args.output / 'manifest.json'}")

    if unredacted_barcodes:
        print(
            "\nCRITICAL — barcode(s) detected but NOT covered (manual redaction required"
            " before `git add`):"
        )
        for s in unredacted_barcodes:
            print(f"  - {s}")

    if review:
        print(
            "\nHUMAN REVIEW REQUIRED before `git add`"
            " (alphabetic PII may remain; use --redact-terms for health conditions / org names):"
        )
        for s in review:
            print(f"  - {s}")

    return 1 if unredacted_barcodes else 0


if __name__ == "__main__":
    sys.exit(main())
