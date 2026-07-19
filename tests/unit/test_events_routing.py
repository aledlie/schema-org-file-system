"""Events/{EventName}/ routing — destination path + decision-evidence stash.

Kept separate from test_content_organizer.py: these tests cover only the
events category wiring (category_config entry, get_destination_path branch,
and the _stash_decision_state event_name capture).
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.organizers.content_organizer import ContentOrganizer
from src.scoring.signals.event_content import (
    EVENT_SIGNAL_NAME,
    EVENTS_CATEGORY,
    EVENTS_DEFAULT_SUBCATEGORY,
)
from src.scoring.types import (
    EVIDENCE_EVENT_NAME,
    SCORER_LEGACY,
    CategoryScore,
    ClassificationDecision,
)


@pytest.fixture()
def organizer(tmp_path: Path) -> ContentOrganizer:
    clf = MagicMock()
    clf.extract_company_names.return_value = []
    clf.extract_people_names.return_value = []
    clf.sanitize_company_name.side_effect = lambda name: name
    return ContentOrganizer(base_path=tmp_path, content_classifier=clf, scorer=SCORER_LEGACY)


def make_events_decision(
    winning_signals: list[str],
    all_scores: list[CategoryScore],
    category: str = EVENTS_CATEGORY,
) -> ClassificationDecision:
    return ClassificationDecision(
        category=category,
        subcategory=EVENTS_DEFAULT_SUBCATEGORY,
        schema_type="Event",
        confidence=0.95,
        margin=0.5,
        winning_signals=winning_signals,
        all_scores=all_scores,
        company_name=None,
        people_names=[],
    )


def event_score(name: str) -> CategoryScore:
    return CategoryScore(
        category=EVENTS_CATEGORY,
        subcategory=EVENTS_DEFAULT_SUBCATEGORY,
        confidence=0.95,
        signal_name=EVENT_SIGNAL_NAME,
        evidence={EVIDENCE_EVENT_NAME: name},
    )


class TestEventsDestinationPath:
    def test_event_name_creates_named_subfolder(
        self, organizer: ContentOrganizer, tmp_path: Path
    ) -> None:
        organizer._last_file_state[EVIDENCE_EVENT_NAME] = "Burning Flipside"
        dest = organizer.get_destination_path(
            Path("/downloads/PlacementMap.pdf"), EVENTS_CATEGORY, EVENTS_DEFAULT_SUBCATEGORY
        )
        assert dest == tmp_path / "Events" / "Burning Flipside" / "PlacementMap.pdf"

    def test_without_event_name_files_stay_in_events_root(
        self, organizer: ContentOrganizer, tmp_path: Path
    ) -> None:
        dest = organizer.get_destination_path(
            Path("/downloads/PlacementMap.pdf"), EVENTS_CATEGORY, EVENTS_DEFAULT_SUBCATEGORY
        )
        assert dest == tmp_path / "Events" / "PlacementMap.pdf"

    def test_folder_unsafe_characters_stripped(
        self, organizer: ContentOrganizer, tmp_path: Path
    ) -> None:
        organizer._last_file_state[EVIDENCE_EVENT_NAME] = "Burn: The/Event?"
        dest = organizer.get_destination_path(
            Path("/downloads/flyer.pdf"), EVENTS_CATEGORY, EVENTS_DEFAULT_SUBCATEGORY
        )
        assert dest == tmp_path / "Events" / "Burn TheEvent" / "flyer.pdf"


class TestEventNameStash:
    def test_winning_event_signal_stashes_name(self, organizer: ContentOrganizer) -> None:
        decision = make_events_decision(
            winning_signals=[EVENT_SIGNAL_NAME],
            all_scores=[event_score("Burning Flipside")],
        )
        organizer._stash_decision_state(decision, scorer_label="unified")
        assert organizer._last_file_state[EVIDENCE_EVENT_NAME] == "Burning Flipside"

    def test_non_events_winner_does_not_stash(self, organizer: ContentOrganizer) -> None:
        decision = make_events_decision(
            winning_signals=[EVENT_SIGNAL_NAME],
            all_scores=[event_score("Burning Flipside")],
            category="legal",
        )
        organizer._stash_decision_state(decision, scorer_label="unified")
        assert EVIDENCE_EVENT_NAME not in organizer._last_file_state

    def test_event_signal_not_winning_does_not_stash(self, organizer: ContentOrganizer) -> None:
        decision = make_events_decision(
            winning_signals=["filename_pattern"],
            all_scores=[event_score("Burning Flipside")],
        )
        organizer._stash_decision_state(decision, scorer_label="unified")
        assert EVIDENCE_EVENT_NAME not in organizer._last_file_state
