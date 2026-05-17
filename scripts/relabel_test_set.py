#!/usr/bin/env python3
"""Relabel the evaluation test set to fix obvious label rot.

The current test labels were produced by a prior production run; files that
the prior run failed to categorize ended up labeled ``uncategorized`` or
``media`` even when their location and filename clearly indicate
``game_assets``. This script applies two corrective passes.

Pass 1 (safe): every file under ``parent_folder == 'Games'`` becomes
``game_assets``.

Pass 2 (heuristic): files under ``parent_folder == 'Other'`` with an image
extension whose filename matches sprite-like patterns (sprite vocabulary +
numeric ID, or very short tokens + numeric ID) become ``game_assets``.

Usage::

    python scripts/relabel_test_set.py \\
        --input results/ml_data/test.json \\
        --output results/ml_data/test_relabeled.json
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

SPRITE_VOCAB = frozenset({
    'level', 'lever', 'blob', 'spine', 'bubble', 'salamander', 'heart',
    'beat', 'map', 'feet', 'hair', 'legs', 'pupils', 'mandible', 'stats',
    'stat', 'water', 'pole', 'arm', 'glow', 'mee', 'gelf',
})

_TOKEN_RE = re.compile(r'[_\-]')
_MAX_SHORT_TOKEN_LEN = 4
_MIN_TOKENS = 2


def _is_sprite_like(filename: str) -> bool:
    name = filename.rsplit('.', 1)[0].lower()
    tokens = _TOKEN_RE.split(name)
    has_digit = any(t.isdigit() for t in tokens)
    if not has_digit:
        return False
    if any(t in SPRITE_VOCAB for t in tokens):
        return True
    return len(tokens) >= _MIN_TOKENS and all(len(t) <= _MAX_SHORT_TOKEN_LEN for t in tokens)


def relabel(samples: list[dict]) -> tuple[list[dict], Counter, Counter]:
    pass1 = Counter()
    pass2 = Counter()
    out = []
    for s in samples:
        s = dict(s)
        parent = s.get('parent_folder', '')
        cat = s.get('category')
        if parent == 'Games' and cat != 'game_assets':
            pass1[cat] += 1
            s['category'] = 'game_assets'
        elif (
            parent == 'Other'
            and s.get('extension_category') == 'image'
            and cat != 'game_assets'
            and _is_sprite_like(s.get('filename', ''))
        ):
            pass2[cat] += 1
            s['category'] = 'game_assets'
        out.append(s)
    return out, pass1, pass2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', '-i', default='results/ml_data/test.json')
    parser.add_argument('--output', '-o', default='results/ml_data/test_relabeled.json')
    args = parser.parse_args()

    samples = json.loads(Path(args.input).read_text())
    relabeled, pass1, pass2 = relabel(samples)

    print(f'Loaded {len(samples)} samples from {args.input}')
    print(f'\nPass 1 (parent_folder=Games → game_assets): {sum(pass1.values())} relabels')
    for orig, n in pass1.most_common():
        print(f'  {orig:<25s} → game_assets  ({n})')
    print(f'\nPass 2 (Other/ sprite-like → game_assets): {sum(pass2.values())} relabels')
    for orig, n in pass2.most_common():
        print(f'  {orig:<25s} → game_assets  ({n})')

    Path(args.output).write_text(json.dumps(relabeled, indent=2))
    print(f'\nWrote {len(relabeled)} samples to {args.output}')


if __name__ == '__main__':
    main()
