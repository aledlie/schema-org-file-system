#!/usr/bin/env python3
"""Regenerate the bundled Census given-name / surname gazetteers.

Public-domain sources:
- Surnames: US Census 2010 surname file (names.zip → Names_2010Census.csv).
  Trimmed to surnames with total count >= SURNAME_MIN_COUNT.
- Given names: US Census 1990 first-name distributions (female + male),
  union of the top GIVEN_NAME_TOP_N by frequency rank.

Outputs one lowercase name per line to
``src/classifiers/data/census_names/{given_names,surnames}.txt``.

``given_names.txt`` is committed; ``surnames.txt`` is gitignored for size
(untracked 2026-07-18), so fresh clones must run this script once during
setup (see QUICK_START.md §1) before person/entity detection has the
surname gazetteer:

    python scripts/download_census_names.py
"""

from __future__ import annotations

import csv
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

SURNAME_ZIP_URL = "https://www2.census.gov/topics/genealogy/2010surnames/names.zip"
SURNAME_CSV_MEMBER = "Names_2010Census.csv"
GIVEN_NAME_URLS = (
    "https://www2.census.gov/topics/genealogy/1990surnames/dist.female.first",
    "https://www2.census.gov/topics/genealogy/1990surnames/dist.male.first",
)

SURNAME_MIN_COUNT = 200  # 162,254 rows → 92,357 surnames (verified 2026-07-25)
GIVEN_NAME_TOP_N = 5000  # per-file rank cutoff; union across female+male

DATA_DIR = Path(__file__).resolve().parents[1] / "src/classifiers/data/census_names"
_TIMEOUT = 60


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "schema-org-file-system/2.1 (name-gazetteer)"}
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data: bytes = resp.read()
        return data


def build_surnames() -> list[str]:
    raw = _fetch(SURNAME_ZIP_URL)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        member = next(n for n in zf.namelist() if n.lower().endswith(SURNAME_CSV_MEMBER.lower()))
        text = zf.read(member).decode("latin-1")
    names: list[str] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        name = (row.get("name") or "").strip()
        count = row.get("count") or "0"
        if not name or name == "ALL OTHER NAMES":
            continue
        try:
            if int(count) < SURNAME_MIN_COUNT:
                continue
        except ValueError:
            continue
        names.append(name.lower())
    return sorted(set(names))


def build_given_names() -> list[str]:
    names: set[str] = set()
    for url in GIVEN_NAME_URLS:
        text = _fetch(url).decode("latin-1")
        for line in text.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            name, _freq, _cum, rank = parts[0], parts[1], parts[2], parts[3]
            try:
                if int(rank) > GIVEN_NAME_TOP_N:
                    continue
            except ValueError:
                continue
            names.add(name.strip().lower())
    return sorted(names)


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("Downloading surnames (Census 2010)…", flush=True)
    surnames = build_surnames()
    (DATA_DIR / "surnames.txt").write_text("\n".join(surnames) + "\n")
    print(f"  wrote {len(surnames)} surnames")

    print("Downloading given names (Census 1990)…", flush=True)
    given = build_given_names()
    (DATA_DIR / "given_names.txt").write_text("\n".join(given) + "\n")
    print(f"  wrote {len(given)} given names")
    return 0


if __name__ == "__main__":
    sys.exit(main())
