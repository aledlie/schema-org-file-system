#!/usr/bin/env python3
"""Generate a fully synthetic SPECIMEN ID card for the `identification` test class.

Provenance note: this image is rendered from fabricated constants only — there is
NO real-image input and no biometric data. It exists to give the content
classifier `identification`-class coverage (card layout + ID keywords) without
committing any real driver's-license PII to version control. See docs/BACKLOG.md
(P1 biometric-PII item) for why the real license was removed from history.

Run: python scripts/generate_specimen_id.py --output results/test_set_augmentation/redacted
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Card geometry (ID-1 ratio ~1.586, upscaled for legible OCR).
_CARD_W, _CARD_H = 1004, 680
_MARGIN = 28
_PHOTO_BOX = (_MARGIN, 120, _MARGIN + 250, 120 + 320)  # left silhouette placeholder

# All values below are fabricated — obviously-fake placeholders, never real.
_HEADER = "SAMPLE STATE  ·  DRIVER LICENSE"
_FIELDS = [
    ("DL", "S000-0000-0000"),
    ("CLASS", "C"),
    ("LN", "SAMPLE"),
    ("FN", "JORDAN A"),
    ("DOB", "01/01/1990"),
    ("ISS", "01/01/2020"),
    ("EXP", "01/01/2028"),
    ("SEX", "X"),
    ("HGT", "5'-10\""),
    ("EYES", "BRN"),
    ("ADDR", "100 EXAMPLE AVE"),
    ("", "ANYTOWN ST 00000"),
]
_WATERMARK = "SPECIMEN — NOT A REAL ID"

_FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_PATHS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_specimen_id(out_path: Path) -> Path:
    img = Image.new("RGB", (_CARD_W, _CARD_H), (232, 238, 244))
    draw = ImageDraw.Draw(img)

    # Header bar.
    draw.rectangle([0, 0, _CARD_W, 88], fill=(28, 62, 110))
    draw.text((_MARGIN, 26), _HEADER, font=_font(40), fill=(255, 255, 255))

    # Photo placeholder: gray silhouette, explicitly not a real face.
    draw.rectangle(list(_PHOTO_BOX), fill=(150, 158, 168))
    cx = (_PHOTO_BOX[0] + _PHOTO_BOX[2]) // 2
    draw.ellipse([cx - 55, 175, cx + 55, 285], fill=(120, 128, 138))  # head
    draw.ellipse([cx - 95, 300, cx + 95, 470], fill=(120, 128, 138))  # shoulders
    draw.text((_PHOTO_BOX[0] + 6, _PHOTO_BOX[3] + 8), "NO PHOTO", font=_font(24), fill=(90, 96, 104))

    # Field block, right of the photo.
    x = _PHOTO_BOX[2] + 40
    y = 130
    label_font, value_font = _font(24), _font(34)
    for label, value in _FIELDS:
        if label:
            draw.text((x, y), label, font=label_font, fill=(70, 80, 92))
        draw.text((x + 110, y - 4), value, font=value_font, fill=(18, 24, 32))
        y += 44

    # Diagonal SPECIMEN watermark so the file can never be mistaken for a real ID.
    wm = Image.new("RGBA", (_CARD_W, _CARD_H), (0, 0, 0, 0))
    wdraw = ImageDraw.Draw(wm)
    wdraw.text((70, _CARD_H // 2 - 30), _WATERMARK, font=_font(56), fill=(200, 40, 40, 120))
    wm = wm.rotate(18, expand=False, center=(_CARD_W // 2, _CARD_H // 2))
    img.paste(wm, (0, 0), wm)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="results/test_set_augmentation/redacted",
                        help="Directory to write the specimen PNG into")
    parser.add_argument("--name", default="specimen_drivers_license.png",
                        help="Output filename")
    args = parser.parse_args()
    path = render_specimen_id(Path(args.output) / args.name)
    print(f"Wrote synthetic specimen ID: {path}")


if __name__ == "__main__":
    main()
