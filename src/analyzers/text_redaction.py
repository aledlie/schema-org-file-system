"""PII redaction for persisted extracted text (medical files).

``organize-files content`` stores extracted/OCR text verbatim in
``files.extracted_text`` (and a 5,000-char ``text`` property inside
``schema_data``) — the documented PII hazard for sensitive sources. For files
whose classification maps onto the schema.org MedicalTest family
(``BloodTestEntity``/``PathologyTestEntity`` in ``storage.entity_metadata``),
the pipeline redacts PII from the text before persistence instead of storing
it raw; see ``FileProcessor._persist_to_graph_store``.

Text analog of ``scripts/redact_pii.py``'s raster token policy (digits,
emails, detected person names). Masks preserve token length with a block
character so document structure stays legible for debugging/search-shape
purposes while values are destroyed. Like the raster redactor, this is
best-effort hardening, not a guarantee — alphabetic PII outside the detected
names (conditions, third-party names) survives.
"""

from __future__ import annotations

import re
from typing import Iterable

# Classification categories whose files persist as MedicalTest-family
# entities (BloodTest, PathologyTest, ...) and must not store raw PII text.
MEDICAL_TEXT_REDACTION_CATEGORIES = frozenset({"medical"})

# Mask character (mirrors the raster redactor's black boxes).
REDACTION_CHAR = "█"

# Email addresses.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# Digit runs of 2+ (IDs, MRNs, DOBs, phone numbers, lab values), including
# internal separators (12.5, 1993-11-26, 555-0100). Single digits stay —
# negligible re-identification value ("type 2", "D3") and useful context.
_DIGIT_RUN_RE = re.compile(r"\d(?:[\d.,/\-]*\d)+|\d{2,}")


def _mask(match: "re.Match[str]") -> str:
    return REDACTION_CHAR * len(match.group(0))


def redact_pii_text(text: str, people_names: Iterable[str] = ()) -> str:
    """Redact emails, digit runs, and the detected person names from text.

    ``people_names`` is the entity-detection output already attached to the
    file's decision — each name (and its individual word parts, so "Jane Doe"
    also catches a bare "Doe") is masked case-insensitively. Masks preserve
    length with ``REDACTION_CHAR``.
    """
    if not text:
        return text
    redacted = _EMAIL_RE.sub(_mask, text)
    redacted = _DIGIT_RUN_RE.sub(_mask, redacted)
    name_parts = {part for name in people_names for part in (name, *name.split()) if len(part) >= 2}
    for part in sorted(name_parts, key=len, reverse=True):
        redacted = re.sub(
            re.escape(part), REDACTION_CHAR * len(part), redacted, flags=re.IGNORECASE
        )
    return redacted
