"""Model-free ("Phase 0") organization-name extraction.

Composes the fragile regex extractor in
:class:`~src.classifiers.entity_detector.EntityDetector` with cheap,
deterministic layers that fix two documented failure modes *without* adding an
ML model:

1. **Single-token brands with no legal suffix** (real case: ``GeneDx``) are
   missed by the suffix/institutional regexes.  We recover them from an
   email/URL domain-ownership cue (``genedx.com`` -> ``GeneDx``).
2. **Garbled citation fragments** are extracted from References/Bibliography
   sections (a cited standards body, not the document's own org).  We drop the
   reference span *before* extraction.

``extract_organizations`` returns a ranked, de-garbled ``list[str]`` — the
document's OWN organization first, because downstream code keys off
``companies[0]``.  It preserves the ``extract_company_names`` return contract so
it can drop into that seam.

Layers, in order:

* Reference-span exclusion (kills failure mode #2).
* Base regex extraction (delegated to the existing ``EntityDetector``).
* Optional ``known_brands`` gazetteer (recurring single-token brands).
* Email/URL domain-ownership cue (recovers ``GeneDx``; kills failure mode #1).
* Salience ranking (owner first, then header/footer proximity, then frequency).
* Canonicalization via ``cleanco.basename`` (replaces the hand-rolled
  ``_legal_suffix_regexes``).
"""

from __future__ import annotations

import re
from typing import Callable, Iterable, Optional, Union

try:  # cleanco is the intended Phase-0 dependency (MIT, pure-python).
    from cleanco import basename as _cleanco_basename
except ImportError:  # pragma: no cover - keeps the module importable pre-install
    _cleanco_basename = None

# A base extractor is either an ``EntityDetector``-like object exposing
# ``extract_company_names`` or a plain ``Callable[[str], list[str]]``.
BaseExtractor = Union[Callable[[str], list[str]], object]

# Salience windows: an org near the top or bottom of the document is far more
# likely to be the document's OWN org than one buried in the body.
_HEADER_WINDOW = 2000
_FOOTER_WINDOW = 500

# Free-mail / infra domains are never an ownership cue for a document's own org.
_GENERIC_DOMAINS = frozenset(
    {
        "gmail",
        "yahoo",
        "hotmail",
        "outlook",
        "icloud",
        "aol",
        "proton",
        "protonmail",
        "mail",
        "live",
        "msn",
        "me",
        "example",
    }
)

# Second-level labels of common two-part public suffixes (``co.uk`` etc.), so the
# registrable brand label is taken from the correct position.
_MULTI_PART_TLD_HEADS = frozenset({"co", "com", "org", "net", "gov", "edu", "ac"})

# Heading that opens a reference/citation section.  Robust to case and a trailing
# colon; matched at a line start (allowing markdown/quote bullet prefixes) and
# terminated by either a colon or end-of-line so a prose sentence that merely
# starts with "References to ..." is NOT treated as a heading.
_REFERENCE_SPLIT_RE = re.compile(
    r"(?im)^[ \t>*#\-]*"
    r"(?:references|reference list|bibliography|works\s+cited|"
    r"literature\s+cited|citations|sources)"
    r"[ \t]*(?::|$)"
)

# A plausible domain: one or more ``label.`` groups followed by an alpha TLD.
_DOMAIN_RE = re.compile(
    r"\b((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,})\b",
    re.IGNORECASE,
)

# A single capitalized word token (allows internal caps/digits/&) used to find a
# domain's brand token as it actually appears in the body (preserves "GeneDx").
_WORD_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9&]*")

# Minimal fallback suffix strip used only when cleanco is unavailable.
_FALLBACK_SUFFIX_RE = re.compile(
    r"[,\s]+(?:Incorporated|Corporation|Limited|Company|LLC|LLP|Inc|Corp|"
    r"Ltd|Co|PLC|LP|GmbH|AG|SA)\.?$",
    re.IGNORECASE,
)


def _norm_token(value: str) -> str:
    """Reduce a name/label to a comparable token: lowercase alphanumerics only."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _canonicalize(name: str) -> str:
    """Strip legal suffixes for a folder-safe canonical name via ``cleanco``."""
    stripped = name.strip()
    if not stripped:
        return ""
    if _cleanco_basename is not None:
        canon = _cleanco_basename(stripped)
    else:  # pragma: no cover - exercised only when cleanco is absent
        canon = _FALLBACK_SUFFIX_RE.sub("", stripped)
    return " ".join(canon.split())


def _run_base(base_extractor: BaseExtractor, text: str) -> list[str]:
    """Invoke the base extractor, supporting both object and callable forms."""
    method = getattr(base_extractor, "extract_company_names", None)
    if callable(method):
        return list(method(text))
    if callable(base_extractor):
        return list(base_extractor(text))
    raise TypeError("base_extractor must expose extract_company_names(text) or be callable")


def _strip_reference_span(text: str) -> str:
    """Drop everything from the first reference/bibliography heading onward."""
    match = _REFERENCE_SPLIT_RE.search(text)
    if match:
        return text[: match.start()]
    return text


def _domain_brand_token(domain: str) -> Optional[str]:
    """Derive a normalized brand token from a domain (``genedx.com`` -> genedx)."""
    domain = domain.lower().strip().rstrip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    labels = domain.split(".")
    if len(labels) < 2:
        return None
    main = labels[-2]
    # Skip the public second-level label of a two-part TLD (``genedx.co.uk``).
    if main in _MULTI_PART_TLD_HEADS and len(labels) >= 3:
        main = labels[-3]
    if main in _GENERIC_DOMAINS:
        return None
    token = _norm_token(main)
    return token or None


def _extract_domain_tokens(text: str) -> set[str]:
    """Collect ownership-cue brand tokens from every domain mentioned in text."""
    tokens: set[str] = set()
    for match in _DOMAIN_RE.finditer(text):
        token = _domain_brand_token(match.group(1))
        if token:
            tokens.add(token)
    return tokens


def _find_body_brand(text: str, token: str) -> Optional[str]:
    """Find ``token`` as a bare *capitalized* word in the body (preserving case).

    This is how ``GeneDx`` is recovered with no model: the base regex missed it
    (no legal suffix), but its domain says it owns the document, and it appears
    verbatim in the body as a capitalized token.
    """
    for match in _WORD_TOKEN_RE.finditer(text):
        word = match.group()
        if word[:1].isupper() and _norm_token(word) == token:
            return word
    return None


def _brand_in_text(brand: str, text: str) -> bool:
    """Case-insensitive whole-token match for a gazetteer brand string."""
    pattern = re.compile(r"\b" + re.escape(brand.strip()) + r"\b", re.IGNORECASE)
    return bool(pattern.search(text))


def _salience_key(
    name: str, key: str, owner_keys: set[str], body: str
) -> tuple[int, int, int, int]:
    """Build an ascending sort key: owner, then header/footer, then frequency."""
    body_lower = body.lower()
    needle = re.escape(name.lower())
    starts = [m.start() for m in re.finditer(needle, body_lower)]
    freq = len(starts)
    first = starts[0] if starts else len(body)
    last = starts[-1] if starts else -1
    in_header = first < _HEADER_WINDOW
    in_footer = last >= 0 and last >= (len(body) - _FOOTER_WINDOW)
    return (
        0 if key in owner_keys else 1,
        0 if (in_header or in_footer) else 1,
        -freq,
        first,
    )


def extract_organizations(
    text: str,
    *,
    base_extractor: BaseExtractor,
    known_brands: Optional[Iterable[str]] = None,
) -> list[str]:
    """Extract a ranked, de-garbled list of organizations from document text.

    Args:
        text: Raw document text (OCR output, plain text, etc.).
        base_extractor: An ``EntityDetector``-like object exposing
            ``extract_company_names(text)`` or a plain ``Callable[[str],
            list[str]]`` returning raw candidate org names.
        known_brands: Optional caller-supplied set of confirmed brand strings
            (future: seeded from ``src.feedback.correction_tracker``) matched
            case-insensitively — a cheap catch for recurring single-token brands.

    Returns:
        Organization names, canonicalized (legal suffixes stripped) and ranked
        with the document's OWN org first.  Same ``list[str]`` contract as
        ``EntityDetector.extract_company_names``.
    """
    if not text:
        return []

    # Layer 1: drop the reference span so cited orgs never reach the extractor.
    body = _strip_reference_span(text)

    # candidates: normalized-key -> canonical display name (first casing wins).
    candidates: dict[str, str] = {}

    def add(raw_name: str) -> Optional[str]:
        canon = _canonicalize(raw_name)
        if not canon:
            return None
        key = _norm_token(canon)
        if not key:
            return None
        candidates.setdefault(key, canon)
        return key

    # Layer 2: base regex extraction over the reference-free body.
    for raw_name in _run_base(base_extractor, body):
        add(raw_name)

    # Layer 3: optional gazetteer of confirmed brands.
    for brand in known_brands or ():
        if _brand_in_text(brand, body):
            add(brand)

    # Layer 4: email/URL domain-ownership cue.
    domain_tokens = _extract_domain_tokens(body)
    owner_keys: set[str] = {key for key in candidates if key in domain_tokens}
    for token in domain_tokens:
        if token in candidates:
            continue
        # The base regex missed a domain-owning brand — recover it from the body.
        surface = _find_body_brand(body, token)
        if surface:
            key = add(surface)
            if key:
                owner_keys.add(key)

    # Layer 5: salience ranking (owner first, then proximity, then frequency).
    ordered = sorted(
        candidates.items(),
        key=lambda item: _salience_key(item[1], item[0], owner_keys, body),
    )
    return [name for _, name in ordered]
