"""FilenamePatternSignal tests (UNIFIED_SCORING_PLAN §4 row 2)."""

from pathlib import Path

from shared.constants import GAME_SPRITE_KEYWORDS

from src.scoring.signals.filename_pattern import (
    FILENAME_MATCH_CONFIDENCE,
    FilenamePatternSignal,
)
from src.scoring.context import FileContext
from src.scoring.weights import W_FILENAME


def make_ctx(path, display_path=None, schema_type="DigitalDocument"):
    return FileContext(
        path=Path(path),
        schema_type=schema_type,
        display_path=Path(display_path) if display_path else None,
    )


def make_signal(keywords=None):
    return FilenamePatternSignal(GAME_SPRITE_KEYWORDS if keywords is None else keywords)


class TestAppliesTo:
    def test_always_applies(self):
        assert make_signal().applies_to(make_ctx("/tmp/anything.bin")) is True


class TestRun:
    def test_no_pattern_emits_nothing(self):
        ctx = make_ctx("/random/xyzxyz_unique_file.pdf")
        assert make_signal().run(ctx) == []

    def test_log_file_routes_to_technical(self):
        scores = make_signal().run(make_ctx("/logs/error.log"))
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("technical", "logs")
        assert score.confidence == FILENAME_MATCH_CONFIDENCE
        assert score.signal_name == "filename_pattern"
        assert "company_name" not in score.evidence
        assert "people_names" not in score.evidence

    def test_duplicate_passes_through_as_skip_score(self):
        scores = make_signal().run(make_ctx("/photos/photo_20250101_123456.png"))
        assert len(scores) == 1
        assert (scores[0].category, scores[0].subcategory) == ("skip", "duplicate")

    def test_people_names_land_in_evidence(self):
        scores = make_signal().run(make_ctx("/docs/Alyshia_Ledlie_Resume.pdf"))
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("personal", "contacts")
        assert score.evidence["people_names"]

    def test_display_path_preferred_over_physical(self):
        ctx = make_ctx("/tmp/blob.bin", display_path="/tmp/error.log")
        scores = make_signal().run(ctx)
        assert len(scores) == 1
        assert (scores[0].category, scores[0].subcategory) == ("technical", "logs")


class TestResearchEvidence:
    def test_research_pdf_carries_schema_type_and_provenance(self):
        scores = make_signal().run(make_ctx("/papers/arxiv-2401.12345.pdf"))
        assert len(scores) == 1
        score = scores[0]
        assert (score.category, score.subcategory) == ("research", "arxiv")
        assert score.evidence["schema_type"] == "ScholarlyArticle"
        assert score.evidence["company_name"] == "arXiv"
        assert score.evidence["research"] == (
            "arxiv",
            "2401.12345",
            "arXiv",
            "https://arxiv.org/abs/2401.12345",
        )

    def test_non_research_has_no_schema_type_override(self):
        scores = make_signal().run(make_ctx("/docs/nda_2024.pdf"))
        assert len(scores) == 1
        assert (scores[0].category, scores[0].subcategory) == ("legal", "contracts")
        assert "schema_type" not in scores[0].evidence
        assert "research" not in scores[0].evidence


class TestGameSpriteKeywordGating:
    def test_keyword_enables_named_game_asset_rule(self):
        signal = FilenamePatternSignal(["salamander"])
        scores = signal.run(make_ctx("/tmp/salamander_walk.png"))
        assert len(scores) == 1
        assert (scores[0].category, scores[0].subcategory) == ("game_assets", "sprites")

    def test_without_keyword_named_rule_does_not_fire(self):
        signal = FilenamePatternSignal([])
        scores = signal.run(make_ctx("/tmp/salamander_walk.png"))
        assert not any(
            (score.category, score.subcategory) == ("game_assets", "sprites") for score in scores
        )


class TestSignalMetadata:
    def test_signal_metadata(self):
        signal = make_signal()
        assert signal.name == "filename_pattern"
        assert signal.weight == W_FILENAME
        assert signal.cost_tier == "cheap"
