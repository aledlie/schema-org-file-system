"""Extract a US postal address from document text (library-driven).

Three libraries do the work; this module only orchestrates:

- ``pyap`` detects full street addresses in free text (the primary path).
- ``usaddress`` (CRF) tags a single line as a fallback so a bare
  ``City ST ZIP`` (no street — e.g. a receipt with only a PO box) is still
  captured.
- ``us`` validates/normalizes the state token (``us.states.lookup`` handles
  "TX"/"Texas"/"texas" → 'TX' and rejects noise like ``#``), so there is no
  hand-rolled state table here.

All three are optional (the ``geo`` extra); when they are not importable this
returns ``None`` and the caller simply creates no location edge.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

_ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")


def _normalize_state(token: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Return (abbr, full_name) for a state token, or (None, None) if invalid."""
    if not token:
        return None, None
    try:
        import us
    except ImportError:
        return None, None
    state = us.states.lookup(token.strip().strip(".,"))
    if state is None:
        return None, None
    return state.abbr, state.name


def _clean_city(city: Optional[str]) -> Optional[str]:
    if not city:
        return None
    city = " ".join(city.split()).strip(".,")
    if not city:
        return None
    return city.title() if city.isupper() else city


def _result(
    city: Optional[str],
    abbr: str,
    state_name: Optional[str],
    zip_code: Optional[str],
    raw: str,
) -> Dict[str, Optional[str]]:
    city = _clean_city(city)
    parts = [p for p in (city, abbr) if p]
    display = ", ".join(parts) if parts else raw.strip()
    if zip_code:
        display = f"{display} {zip_code}".strip()
    return {
        "raw": raw.strip(),
        "display_name": display,
        "city": city,
        "state": abbr,
        "state_name": state_name,
        "zip": zip_code,
    }


def _from_pyap(text: str) -> Optional[Dict[str, Optional[str]]]:
    try:
        import pyap
    except ImportError:
        return None
    try:
        addresses = pyap.parse(text, country="US")
    except Exception:
        return None
    for addr in addresses:
        abbr, state_name = _normalize_state(getattr(addr, "region1", None))
        if not abbr:
            continue
        return _result(
            getattr(addr, "city", None),
            abbr,
            state_name,
            getattr(addr, "postal_code", None),
            str(addr),
        )
    return None


def _from_usaddress(text: str) -> Optional[Dict[str, Optional[str]]]:
    """Line-scan fallback for bare 'City ST ZIP' (no street number)."""
    try:
        import usaddress
    except ImportError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or not _ZIP_RE.search(line):
            continue
        try:
            tagged, _atype = usaddress.tag(line)
        except Exception:
            continue  # RepeatedLabelError etc. — skip the line
        abbr, state_name = _normalize_state(tagged.get("StateName"))
        zip_code = (tagged.get("ZipCode") or "").strip()
        place = tagged.get("PlaceName")
        if abbr and place and _ZIP_RE.fullmatch(zip_code):
            return _result(place, abbr, state_name, zip_code, line)
    return None


def extract_primary_address(text: str) -> Optional[Dict[str, Optional[str]]]:
    """Return the first usable address as a dict, or None.

    Dict keys: ``raw``, ``display_name``, ``city``, ``state`` (2-letter),
    ``state_name``, ``zip``. Tries pyap (full street addresses) first, then a
    usaddress line-scan fallback (bare city/state/zip).
    """
    if not text:
        return None
    return _from_pyap(text) or _from_usaddress(text)
