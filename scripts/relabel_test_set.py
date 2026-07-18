#!/usr/bin/env python3
"""Relabel the evaluation test set to fix obvious label rot.

The current test labels were produced by a prior production run; files that
the prior run failed to categorize ended up labeled ``uncategorized`` or
``media`` even when their location and filename clearly indicate the true
category. This script applies corrective passes.

Pass 1 (safe): every file under ``parent_folder == 'Games'`` becomes
``game_assets``.

Pass 2 (heuristic): files under ``parent_folder == 'Other'`` with an image
extension whose filename matches sprite-like patterns (sprite vocabulary +
numeric ID, or very short tokens + numeric ID) become ``game_assets``.

Pass 3 (triage sprite vocab): files in triage locations (``Uncategorized``,
``Desktop``, ``Downloads``) with an image extension whose filename contains
any token from ``GAME_SPRITE_KEYWORDS`` become ``game_assets``.

Pass 4 (triage screenshot): files in triage locations matching
``SCREENSHOT_PATTERNS`` become ``media`` / ``screenshot``.

Pass 5 (triage document): files in triage locations whose filename matches
``DOCUMENT_PATTERNS`` are routed to ``financial`` / ``legal`` / ``personal``
per the mapping below.

Pass 6 (misfiled-photo correction): sprites/textures are PNG/SVG, so a
``.jpg`` / ``.jpeg`` / ``.heic`` file labeled ``game_assets`` outside a
``Games/`` folder is a misfiled photo and is corrected to ``media`` /
``photos_other``. Pass 2 likewise never promotes a photo-extension file to
``game_assets``. (Games/ JPEGs are left untouched — pass 1 owns that folder.)

Triage passes only overwrite labels currently in
``_RELABEL_ELIGIBLE_CATEGORIES`` (``uncategorized``) so that already-confident
labels are preserved. ``media`` is intentionally excluded: the triage heuristics
are not strong enough to safely overwrite an existing ``media`` label, and doing
so was found to depress ``media`` precision/F1 on datasets with legitimate media
(see docs/BACKLOG.md "Verify relabel_test_set.py does not regress true media").
Files that are genuinely game assets but mislabeled ``media`` are still corrected
by the location-grounded passes 1 (``parent_folder == 'Games'``) and 2.

Usage::

    python scripts/relabel_test_set.py \\
        --input results/ml_data/test.json \\
        --output results/ml_data/test_relabeled.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from shared.constants import DOCUMENT_PATTERNS, GAME_SPRITE_KEYWORDS  # noqa: E402

SPRITE_VOCAB = frozenset(
    {
        "level",
        "lever",
        "blob",
        "spine",
        "bubble",
        "salamander",
        "heart",
        "beat",
        "map",
        "feet",
        "hair",
        "legs",
        "pupils",
        "mandible",
        "stats",
        "stat",
        "water",
        "pole",
        "arm",
        "glow",
        "mee",
        "gelf",
    }
)

_SPRITE_KEYWORD_SET = frozenset(k.lstrip("_").lower() for k in GAME_SPRITE_KEYWORDS)

# Map document-pattern hits to (category, subcategory). Keys must be a subset
# of DOCUMENT_PATTERNS; 'report' is intentionally excluded (too vague — avoids
# clobbering a 'media' label).  The assertion below guards against key drift if
# DOCUMENT_PATTERNS is updated without updating this map.
_DOCUMENT_LABEL_MAP: dict[str, tuple[str, str]] = {
    "invoice": ("financial", "invoice"),
    "receipt": ("financial", "receipt"),
    "statement": ("financial", "statement"),
    "tax": ("financial", "tax"),
    "contract": ("legal", "contract"),
    "resume": ("personal", "resume"),
    "cv": ("personal", "resume"),
    "letter": ("personal", "letter"),
}
# All keys must appear as substrings in at least one DOCUMENT_PATTERNS entry.
# Explicit ValueError (not assert) so it fires even under python -O.
# Substring check (not literal equality) so patterns like r"\binvoice\b" still
# satisfy the "invoice" key without breaking this guard.
_LABEL_KEYS_NOT_IN_PATTERNS = [
    k for k in _DOCUMENT_LABEL_MAP if not any(k in p for p in DOCUMENT_PATTERNS)
]
if _LABEL_KEYS_NOT_IN_PATTERNS:
    raise ValueError(
        f"_DOCUMENT_LABEL_MAP contains keys absent from DOCUMENT_PATTERNS: "
        f"{_LABEL_KEYS_NOT_IN_PATTERNS}; "
        "update shared.constants.DOCUMENT_PATTERNS or remove the stale key"
    )

_TRIAGE_PARENTS = frozenset({"Uncategorized", "Desktop", "Downloads"})
_TRIAGE_PATH_FRAGMENTS = ("/Desktop/", "/Downloads/", "/Uncategorized/")
_RELABEL_ELIGIBLE_CATEGORIES = frozenset({"uncategorized"})

_TOKEN_RE = re.compile(r"[_\-]")
_MAX_SHORT_TOKEN_LEN = 4
_MIN_TOKENS = 2

# Sprites/textures are PNG/SVG. A JPEG/HEIC labeled game_assets outside a
# Games/ folder is a misfiled photo, not an asset (pass 6 corrects these, and
# pass 2 never promotes them).
_PHOTO_EXTENSIONS = frozenset({".jpg", ".jpeg", ".heic"})


def _is_sprite_like(filename: str) -> bool:
    name = filename.rsplit(".", 1)[0].lower()
    tokens = _TOKEN_RE.split(name)
    has_digit = any(t.isdigit() for t in tokens)
    if not has_digit:
        return False
    if any(t in SPRITE_VOCAB for t in tokens):
        return True
    return len(tokens) >= _MIN_TOKENS and all(len(t) <= _MAX_SHORT_TOKEN_LEN for t in tokens)


def _filename_has_sprite_keyword(filename: str) -> bool:
    name = filename.rsplit(".", 1)[0].lower()
    tokens = set(t for t in _TOKEN_RE.split(name) if t)
    return bool(tokens & _SPRITE_KEYWORD_SET)


def _document_label(filename: str) -> tuple[str, str] | None:
    name = filename.rsplit(".", 1)[0].lower()
    for pattern, label in _DOCUMENT_LABEL_MAP.items():
        if re.search(rf"\b{re.escape(pattern)}\b", name):
            return label
    return None


def _is_triage_location(sample: dict) -> bool:
    if sample.get("parent_folder", "") in _TRIAGE_PARENTS:
        return True
    filepath = sample.get("filepath", "")
    return any(frag in filepath for frag in _TRIAGE_PATH_FRAGMENTS)


def relabel(samples: list[dict]) -> tuple[list[dict], dict[str, Counter[str]]]:
    counters: dict[str, Counter[str]] = {f"pass{i}": Counter() for i in range(1, 7)}
    out = []
    for s in samples:
        s = dict(s)
        parent = s.get("parent_folder", "")
        cat: str = s.get("category", "")
        filename = s.get("filename", "")
        ext_cat = s.get("extension_category")
        ext = s.get("extension", "").lower()

        if parent == "Games" and cat != "game_assets":
            counters["pass1"][cat] += 1
            s["category"] = "game_assets"
        elif (
            parent == "Other"
            and ext_cat == "image"
            and cat != "game_assets"
            and ext not in _PHOTO_EXTENSIONS
            and _is_sprite_like(filename)
        ):
            counters["pass2"][cat] += 1
            s["category"] = "game_assets"
        elif (
            cat == "game_assets"
            and parent != "Games"
            and ext in _PHOTO_EXTENSIONS
        ):
            # Misfiled photos: a JPEG/HEIC labeled game_assets outside Games/
            # is a photo, not a sprite/texture. Correct it to media.
            counters["pass6"][cat] += 1
            s["category"] = "media"
            s["subcategory"] = "photos_other"
        elif _is_triage_location(s) and cat in _RELABEL_ELIGIBLE_CATEGORIES:
            if ext_cat == "image" and _filename_has_sprite_keyword(filename):
                counters["pass3"][cat] += 1
                s["category"] = "game_assets"
            elif ext_cat == "image" and s.get("is_screenshot"):
                counters["pass4"][cat] += 1
                s["category"] = "media"
                s["subcategory"] = "screenshot"
            else:
                # Pass 5 (triage document): use the precomputed is_document flag
                # (set by FileFeatureExtractor via DOCUMENT_PATTERNS) as a cheap
                # prefilter before the word-boundary regex in _document_label.
                # Samples without the key (not from the feature extractor) still
                # run the regex, preserving backward compatibility.
                if s.get("is_document", True):
                    doc_label = _document_label(filename)
                    if doc_label is not None:
                        counters["pass5"][cat] += 1
                        s["category"], s["subcategory"] = doc_label
        out.append(s)
    return out, counters


_PASS_DESCRIPTIONS = {
    "pass1": "parent_folder=Games → game_assets",
    "pass2": "Other/ sprite-like → game_assets",
    "pass3": "triage/ sprite keyword → game_assets",
    "pass4": "triage/ screenshot pattern → media",
    "pass5": "triage/ document pattern → financial|legal|personal",
    "pass6": "non-Games JPEG/HEIC game_assets → media (misfiled photos)",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "-i", default="results/ml_data/test.json")
    parser.add_argument("--output", "-o", default="results/ml_data/test_relabeled.json")
    args = parser.parse_args()

    samples = json.loads(Path(args.input).read_text())
    relabeled, counters = relabel(samples)

    print(f"Loaded {len(samples)} samples from {args.input}")
    for key, desc in _PASS_DESCRIPTIONS.items():
        counter = counters[key]
        print(f"\n{key.title()} ({desc}): {sum(counter.values())} relabels")
        for orig, n in counter.most_common():
            print(f"  {str(orig):<25s} → relabeled  ({n})")

    Path(args.output).write_text(json.dumps(relabeled, indent=2))
    print(f"\nWrote {len(relabeled)} samples to {args.output}")


if __name__ == "__main__":
    main()
