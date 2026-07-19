"""EventContentSignal — event-document detection via title/date-range structure.

Event ephemera (flyers, programs, placement maps, schedules) share a layout
signature that keyword taxonomies misread: a prominent event title adjacent
to a calendar date *range*. Keyword signals see only the token bag — a camp
map whose labels include "Court of Faerie" and "DMV" scores legal/
organization — so this signal detects the structure instead:

- a date-range ("April 23 - April 27", "April 23 to 27", and the OCR-mangled
  "April 23 April 27" where the dash was lost), AND
- a title-like line immediately above it (line-structured text), or a
  title-like leading run when OCR collapsed the page to one line.

Both parts are required; a date range alone (common in letters and legal
notices) emits nothing. The detected title becomes ``event_name`` evidence —
the organizer routes a committed ``events`` winner to ``Events/{EventName}/``
— and ``schema_type`` evidence marks the file's schema.org type ``Event``
(same override mechanism as research → ScholarlyArticle).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from ..context import FileContext

from ..types import EVIDENCE_EVENT_NAME, EVIDENCE_SCHEMA_TYPE, CategoryScore
from ..weights import W_EVENT

EVENT_SIGNAL_NAME = "event_content"
EVENTS_CATEGORY = "events"
EVENTS_DEFAULT_SUBCATEGORY = "other"
EVENT_SCHEMA_TYPE = "Event"

# Structural adjacency (title + date range) is specific evidence, on par with
# the filename rule set: 1.0 × 0.95 outscores a keyword-taxonomy misfire
# (W_TEXT 0.8 × 1.0) by more than MIN_DECISION_MARGIN and reaches the
# early-exit threshold once the co-voting filename rules agree.
EVENT_CONFIDENCE = 0.95

# Minimum extracted-text length (parallel to the other mid-tier text signals).
EVENT_MIN_TEXT_CHARS = 50

# Title shape: short display-line, mostly capitalized words, no digits.
EVENT_TITLE_MIN_WORDS = 2
EVENT_TITLE_MAX_WORDS = 6
EVENT_TITLE_MIN_CHARS = 5
EVENT_TITLE_MAX_CHARS = 50

_MONTH = (
    r"(?:january|february|march|april|may|june|july|august|september|october|"
    r"november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)"
)
_DAY = r"\d{1,2}(?:st|nd|rd|th)?"
_RANGE_SEP = r"(?:[-–—·~]|to\b|thru\b|through\b)"

# "April 23 - April 27" | "April 23-27" | "April 23 to 27" | "April 23 April 27"
# (the last is OCR with the dash lost — a repeated month stands in for the
# separator; a bare "April 23 27" does NOT match).
DATE_RANGE_PATTERN = re.compile(
    rf"\b{_MONTH}\.?\s+{_DAY}"
    rf"(?:\s*{_RANGE_SEP}\s*(?:{_MONTH}\.?\s+)?|\s+{_MONTH}\.?\s+)"
    rf"{_DAY}\b",
    re.IGNORECASE,
)

_TITLE_WORD = re.compile(r"^[A-Z][A-Za-z'’&-]*$")
# Connector words allowed lowercase in a title ("Festival of Lights").
_TITLE_CONNECTORS = frozenset({"of", "the", "and", "at", "in", "on", "de", "la"})


def _validate_title(words: List[str]) -> Optional[str]:
    """The words as one title string when they satisfy the title shape."""
    if not EVENT_TITLE_MIN_WORDS <= len(words) <= EVENT_TITLE_MAX_WORDS:
        return None
    if not _TITLE_WORD.match(words[0]):
        return None
    for word in words[1:]:
        if not (_TITLE_WORD.match(word) or word in _TITLE_CONNECTORS):
            return None
    title = " ".join(words)
    if not EVENT_TITLE_MIN_CHARS <= len(title) <= EVENT_TITLE_MAX_CHARS:
        return None
    return title


def _leading_title_run(line: str) -> Optional[str]:
    """Title formed by the line's leading conforming words (OCR fallback).

    Single-line OCR keeps reading order, so the page title survives as the
    first tokens; collect words while they conform, stop at the first that
    does not (coordinates, OCR noise, the date itself).
    """
    words: List[str] = []
    for word in line.split():
        if len(words) >= EVENT_TITLE_MAX_WORDS:
            break
        if _TITLE_WORD.match(word) or (words and word in _TITLE_CONNECTORS):
            words.append(word)
        else:
            break
    return _validate_title(words)


def extract_event_title(text: str) -> Optional[str]:
    """Event title adjacent to the first date range, or ``None``.

    Line-structured text: the nearest non-empty line above the date-range
    line must itself be the title (adjacency is the evidence — lines further
    up are not considered). When no line precedes the match (single-line OCR,
    title-page first line), fall back to the leading title-run of the match's
    own line.
    """
    match = DATE_RANGE_PATTERN.search(text)
    if not match:
        return None
    line_start = text.rfind("\n", 0, match.start()) + 1
    for previous_line in reversed(text[:line_start].splitlines()):
        stripped = previous_line.strip()
        if stripped:
            return _validate_title(stripped.split())
    line_end = text.find("\n", match.start())
    match_line = text[line_start : line_end if line_end != -1 else len(text)]
    return _leading_title_run(match_line.strip())


class EventContentSignal:
    """Title + date-range structure → ``events/other`` with the event name."""

    name = EVENT_SIGNAL_NAME
    weight = W_EVENT
    cost_tier = "mid"

    def applies_to(self, ctx: FileContext) -> bool:
        return bool(ctx.text_length >= EVENT_MIN_TEXT_CHARS)

    def run(self, ctx: FileContext) -> List[CategoryScore]:
        title = extract_event_title(ctx.ensure_text())
        if title is None:
            return []
        return [
            CategoryScore(
                category=EVENTS_CATEGORY,
                subcategory=EVENTS_DEFAULT_SUBCATEGORY,
                confidence=EVENT_CONFIDENCE,
                signal_name=self.name,
                evidence={
                    EVIDENCE_EVENT_NAME: title,
                    EVIDENCE_SCHEMA_TYPE: EVENT_SCHEMA_TYPE,
                },
            )
        ]
