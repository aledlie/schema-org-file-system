"""PII redaction for persisted extracted text (medical and identity files).

``organize-files content`` stores extracted/OCR text verbatim in
``files.extracted_text`` (and a 5,000-char ``text`` property inside
``schema_data``) — the documented PII hazard for sensitive sources. For files
whose classification maps onto a sensitive category or subcategory, the
pipeline redacts PII from the text before persistence instead of storing it
raw; see ``FileProcessor._persist_to_graph_store``.

Redaction is triggered by:
- Any file in a top-level ``TEXT_REDACTION_CATEGORIES`` category (e.g.
  ``medical`` → BloodTest/PathologyTest family).
- Files whose ``(category, subcategory)`` pair is in
  ``TEXT_REDACTION_SUBCATEGORY_PAIRS`` (``personal/identification`` for
  driver's licenses and passports, ``personal/records`` for general personal
  records), which are sensitive in their own right even though ``personal`` as
  a whole is not redacted.

Note what this deliberately does **not** cover: a sensitive document the scorer
files as ``personal/contacts`` or ``uncategorized`` is still stored raw. That is
not hypothetical — during the 2026-07-26 medical ingestion the scorer wanted
``personal/contacts`` for 5 of 11 lab documents, and only a folder-truth
category override kept them inside the gate. Closing that needs a
content-based trigger (medical vocabulary / KIE field classes), not more pairs.

Text analog of ``scripts/redact_pii.py``'s raster token policy (digits,
emails, detected person names). Masks preserve token length with a block
character so document structure stays legible for debugging/search-shape
purposes while values are destroyed. Like the raster redactor, this is
best-effort hardening, not a guarantee — alphabetic PII outside the detected
names (conditions, third-party names) survives.

Known limits (BACKLOG §Persisted-text PII redaction):
- The gate is still category-based, not content-based; a sensitive document
  classified elsewhere (e.g. medical filing as ``uncategorized``) is not
  redacted unless it lands in one of the pairs below.
- Only numeric/email/known-name PII is masked; alphabetic PII (conditions,
  medications, third-party names the entity detector missed) survives verbatim.
"""

from __future__ import annotations

import re
from typing import FrozenSet, Iterable, Tuple

# Top-level categories whose files must not store raw PII text.
# Any file classified under these categories triggers redaction regardless
# of subcategory (e.g. "medical" catches bloodtest, pathologytest, etc.).
TEXT_REDACTION_CATEGORIES: FrozenSet[str] = frozenset({"medical"})

# (category, subcategory) pairs that trigger redaction in addition to
# TEXT_REDACTION_CATEGORIES.  Used for sensitive subcategories that exist
# within categories not otherwise redacted (e.g. personal/identification).
TEXT_REDACTION_SUBCATEGORY_PAIRS: FrozenSet[Tuple[str, str]] = frozenset(
    {
        ("personal", "identification"),  # driver's licenses, passports — DOB, ID numbers
        ("personal", "records"),  # personal records — may contain health/legal data
    }
)

# Backward-compatible alias — callers that imported MEDICAL_TEXT_REDACTION_CATEGORIES
# continue to work; new code should use TEXT_REDACTION_CATEGORIES.
MEDICAL_TEXT_REDACTION_CATEGORIES = TEXT_REDACTION_CATEGORIES


def should_redact_text(category: str, subcategory: str) -> bool:
    """Return True when extracted text must be redacted before DB persistence.

    Covers both category-level triggers (``TEXT_REDACTION_CATEGORIES``) and
    specific (category, subcategory) pairs (``TEXT_REDACTION_SUBCATEGORY_PAIRS``).
    """
    return (
        category in TEXT_REDACTION_CATEGORIES
        or (
            category,
            subcategory,
        )
        in TEXT_REDACTION_SUBCATEGORY_PAIRS
    )


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
