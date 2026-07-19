"""EventContentSignal tests — title/date-range structure detection."""

from pathlib import Path

import pytest

from src.scoring.context import FileContext
from src.scoring.signals.event_content import (
    EVENT_CONFIDENCE,
    EVENT_MIN_TEXT_CHARS,
    EVENT_SCHEMA_TYPE,
    EVENT_SIGNAL_NAME,
    EVENTS_CATEGORY,
    EVENTS_DEFAULT_SUBCATEGORY,
    EventContentSignal,
    extract_event_title,
)
from src.scoring.types import EVIDENCE_EVENT_NAME, EVIDENCE_SCHEMA_TYPE

# PDF text layers keep line structure; the title line sits directly above the
# venue/date line (the Burning Flipside placement-map shape).
MULTILINE_FLYER = (
    "Strange Bird Ln.\n"
    "Bananahard Blvd.\n"
    "Burning Flipside\n"
    "City of Pyropolis · April 23 - April 27\n"
    "One Of Us\n"
)

# Single-line OCR of the same map: reading order keeps the title first, the
# range separator is lost ("April 23 April 27"), noise tokens follow.
SINGLE_LINE_OCR = (
    "Burning Flipside 5201'9Go3 ZoFerO5 Mles of Pyropolis "
    "April 23 April 27 One Of Us Rd Roa Monkev Business Camping"
)


def make_ctx(text: str, path: str = "/docs/flyer.pdf") -> FileContext:
    return FileContext(
        path=Path(path),
        schema_type="DigitalDocument",
        text_provider=lambda _p: text,
    )


class TestExtractEventTitle:
    def test_multiline_title_above_date_range(self):
        assert extract_event_title(MULTILINE_FLYER) == "Burning Flipside"

    def test_single_line_ocr_leading_title_run(self):
        assert extract_event_title(SINGLE_LINE_OCR) == "Burning Flipside"

    @pytest.mark.parametrize(
        "date_line",
        [
            "April 23 - April 27",
            "April 23-27",
            "April 23 – 27",
            "April 23 to 27",
            "April 23 April 27",
        ],
    )
    def test_date_range_separator_variants(self, date_line: str):
        text = f"Festival of Lights\n{date_line}\n"
        assert extract_event_title(text) == "Festival of Lights"

    def test_connector_words_allowed_lowercase(self):
        assert extract_event_title("Weekend at the Lake\nJune 5 - June 8\n") == (
            "Weekend at the Lake"
        )

    def test_single_date_is_not_a_range(self):
        # Hearing-style single dates must not fire (letters, court notices).
        assert extract_event_title("Burning Flipside\nApril 23, 2026\n") is None

    def test_bare_year_is_not_a_range(self):
        assert extract_event_title("Annual Report\nMay 2026 Billing Statement\n") is None

    def test_non_title_line_above_range_rejected(self):
        # Adjacency is the evidence: a digit-bearing line directly above the
        # range (cause numbers, addresses) yields nothing — lines further up
        # are never consulted.
        text = "Burning Flipside\nCAUSE NO 12345\nApril 23 - April 27\n"
        assert extract_event_title(text) is None

    def test_date_range_without_any_title_rejected(self):
        assert extract_event_title("scheduled from April 23 - April 27 inclusive") is None


class TestEventContentSignal:
    def test_applies_only_with_enough_text(self):
        signal = EventContentSignal()
        assert signal.applies_to(make_ctx("x" * (EVENT_MIN_TEXT_CHARS - 1))) is False
        assert signal.applies_to(make_ctx("x" * EVENT_MIN_TEXT_CHARS)) is True

    def test_emits_events_vote_with_name_and_schema_type(self):
        scores = EventContentSignal().run(make_ctx(MULTILINE_FLYER))
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == (
            EVENTS_CATEGORY,
            EVENTS_DEFAULT_SUBCATEGORY,
        )
        assert score.confidence == EVENT_CONFIDENCE
        assert score.signal_name == EVENT_SIGNAL_NAME
        assert score.evidence[EVIDENCE_EVENT_NAME] == "Burning Flipside"
        assert score.evidence[EVIDENCE_SCHEMA_TYPE] == EVENT_SCHEMA_TYPE

    def test_no_structure_emits_nothing(self):
        text = "Quarterly revenue grew steadily across all regions this year."
        assert EventContentSignal().run(make_ctx(text)) == []
