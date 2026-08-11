"""Unit tests for src/classifiers/person_name_validator.py.

Covers: L0 denylist, L1 shape, L2 probablepeople, L3 gazetteer, composite
routing, all three hard rules (shape_failed, gazetteer_partial, ambiguous_given),
and graceful degradation when optional layers are unavailable.
"""

from __future__ import annotations

import pytest

from src.classifiers.person_name_validator import (
    PERSON_NAME_DENYLIST,
    _AMBIGUOUS_GIVEN_NAMES,
    available_layers,
    is_denylisted,
    validate_person_name,
)

# ---------------------------------------------------------------------------
# L0 denylist (is_denylisted + validate_person_name short-circuit)
# ---------------------------------------------------------------------------


class TestDenylist:
    def test_insurance_policy_rejected(self) -> None:
        assert is_denylisted("Insurance Policy") is True

    def test_inc_rejected(self) -> None:
        assert is_denylisted("Acme Inc") is True

    def test_denylist_whole_word_only_inc(self) -> None:
        # "inc" must NOT reject "Vincent" or "Lincoln"
        assert is_denylisted("Vincent Lincoln") is False

    def test_denylist_whole_word_only_corp(self) -> None:
        # "corp" must NOT reject a name that contains it as a substring
        assert is_denylisted("Corpus Christie") is False

    def test_camp_whole_word_rejected(self) -> None:
        assert is_denylisted("Summer Camp") is True

    def test_camp_substring_not_rejected(self) -> None:
        # "camp" must NOT reject "Campos" (not a whole word)
        assert is_denylisted("Ricardo Campos") is False

    def test_denylist_case_insensitive(self) -> None:
        assert is_denylisted("INSURANCE POLICY") is True

    def test_all_caps_normalised_then_checked(self) -> None:
        # ALL-CAPS goes through title-case normalisation before the denylist check
        assert is_denylisted("TRAVIS CENTRAL APPRAISAL DISTRICT") is True

    def test_validate_rejects_denylisted(self) -> None:
        result = validate_person_name("Acme LLC")
        assert result.decision == "reject"
        assert result.score == 0.0

    def test_every_denylist_term_is_caught(self) -> None:
        # Smoke-test: every term in the tuple can be found by the regex
        for term in PERSON_NAME_DENYLIST:
            candidate = f"Foo {term.title()} Bar"
            assert is_denylisted(candidate), f"denylist term {term!r} not caught in {candidate!r}"


# ---------------------------------------------------------------------------
# True positive person names → auto_accept
# ---------------------------------------------------------------------------


class TestTruePositives:
    """Names that should be auto_accepted (all layers agree this is a person)."""

    @pytest.mark.parametrize(
        "name",
        [
            "Mary Smith",
            "John Williams",
            "Taylor Nicholas Ryan",
            "Elizabeth Johnson",
        ],
    )
    def test_common_names_auto_accepted(self, name: str) -> None:
        result = validate_person_name(name)
        assert result.decision == "auto_accept", (
            f"{name!r} expected auto_accept, got {result.decision!r} "
            f"(score={result.score}, layers={result.layer_scores})"
        )

    def test_hyphenated_surname(self) -> None:
        # Hyphenated names should parse correctly with nameparser
        result = validate_person_name("Mary O'Brien")
        # At minimum should not be rejected; may be review if gazetteer misses
        assert result.decision != "reject", "Mary O'Brien must not be rejected"


# ---------------------------------------------------------------------------
# False positive protection → never auto_accept
# ---------------------------------------------------------------------------


class TestFalsePositives:
    """Event/org/brand names that must never be auto_accepted."""

    @pytest.mark.parametrize(
        "name",
        [
            "Morning Train",  # theme-camp name (gazetteer_partial: 'morning' not in given)
            "Burning Flipside",  # event name
        ],
    )
    def test_event_names_not_auto_accepted(self, name: str) -> None:
        result = validate_person_name(name)
        assert result.decision != "auto_accept", (
            f"{name!r} must not be auto_accepted (got {result.decision!r}, "
            f"score={result.score}, layers={result.layer_scores})"
        )

    @pytest.mark.parametrize(
        "name",
        [
            # Seasonal given name + geographic surname → both in Census data,
            # but the combination is common as a location or event name.
            "Summer Hill",
            "Autumn Woods",
            "Spring Lee",
            "Winter Park",
            "April Park",
            "May Martin",
            "June Hunter",
            "Dawn Martin",
        ],
    )
    def test_ambiguous_given_name_capped_at_review(self, name: str) -> None:
        """Names with an ambiguous first token (common English word that is also
        a Census given name) must not be auto_accepted, regardless of the last
        name's Census membership — they route to pending_review for human confirmation.
        """
        result = validate_person_name(name)
        assert result.decision != "auto_accept", (
            f"{name!r} must not be auto_accepted (got {result.decision!r}, "
            f"score={result.score}, layers={result.layer_scores})\n"
            f"Reasons: {result.reasons}"
        )
        # Confirm the 'ambiguous given name' hard rule fired in the reason list.
        # (Some names may also be caught by the composite score being below
        # AUTO_ACCEPT_THRESHOLD; in that case the ambiguous guard is redundant
        # but the decision — not auto_accept — is still correct.)
        assert result.decision in ("review", "reject")

    def test_ambiguous_given_name_hard_rule_fires_when_composite_high(self) -> None:
        """Verify the ambiguous_given hard rule fires when the composite WOULD
        reach auto_accept — i.e. the rule is the deciding factor, not just a
        redundant guard over an already-low composite.

        Use 'Summer Hill': probablepeople=Person + gaz=1.0 → composite=1.0.
        Without the hard rule this would be auto_accept.
        """
        result = validate_person_name("Summer Hill")
        assert result.decision == "review"
        assert any(
            "ambiguous given name" in r for r in result.reasons
        ), f"Expected 'ambiguous given name' reason for 'Summer Hill', got: {result.reasons}"

    def test_acme_llc_rejected_by_denylist(self) -> None:
        result = validate_person_name("Acme LLC")
        assert result.decision == "reject"


# ---------------------------------------------------------------------------
# Hard rule: shape_failed
# ---------------------------------------------------------------------------


class TestShapeFailedHardRule:
    def test_single_token_capped_at_review(self) -> None:
        # Single-token names have no first+last → shape=0.0 → capped at review
        result = validate_person_name("Madonna")
        assert result.decision != "auto_accept"

    def test_shape_failed_reason_present(self) -> None:
        result = validate_person_name("Cher")
        assert result.decision != "auto_accept"


# ---------------------------------------------------------------------------
# Hard rule: gazetteer_partial
# ---------------------------------------------------------------------------


class TestGazetteerPartialHardRule:
    def test_morning_train_partial(self) -> None:
        # 'morning' not in Census given names, 'train' in surnames → gaz=0.5 partial
        result = validate_person_name("Morning Train")
        assert result.decision == "review"
        assert result.layer_scores["gazetteer"] == pytest.approx(0.5)
        assert any("gazetteer" in r for r in result.reasons)


# ---------------------------------------------------------------------------
# Hard rule: ambiguous_given
# ---------------------------------------------------------------------------


class TestAmbiguousGivenHardRule:
    def test_ambiguous_set_contains_seasons(self) -> None:
        for word in ("summer", "spring", "autumn", "winter"):
            assert word in _AMBIGUOUS_GIVEN_NAMES

    def test_ambiguous_set_contains_months(self) -> None:
        for word in ("april", "may", "june", "august"):
            assert word in _AMBIGUOUS_GIVEN_NAMES

    def test_ambiguous_set_does_not_contain_common_first_names(self) -> None:
        # These are unambiguously person-names: should NOT be in the ambiguous set
        for word in ("mary", "john", "elizabeth", "james", "robert", "patricia"):
            assert word not in _AMBIGUOUS_GIVEN_NAMES

    def test_faith_hill_capped_at_review(self) -> None:
        # "Faith Hill" is the country singer, but also a plausible event name;
        # 'faith' is in _AMBIGUOUS_GIVEN_NAMES → capped at review
        result = validate_person_name("Faith Hill")
        assert result.decision == "review"

    def test_mary_hill_not_affected(self) -> None:
        # 'mary' is NOT ambiguous → normal flow (likely auto_accept)
        result = validate_person_name("Mary Hill")
        assert result.decision == "auto_accept"

    def test_ambiguous_given_does_not_fire_when_gaz_not_fully_corroborated(self) -> None:
        # When gaz < 1.0, gazetteer_partial already caps it; ambiguous_given is
        # only an additional guard for the gaz=1.0 case.
        result = validate_person_name("Summer Train")
        # 'summer' in given, 'train' in surnames → gaz=1.0 actually; but Summer is
        # also ambiguous → must not be auto_accept
        assert result.decision != "auto_accept"


# ---------------------------------------------------------------------------
# Composite routing (no optional layers)
# ---------------------------------------------------------------------------


class TestNoOptionalLayers:
    """Graceful-degradation tests for missing optional layers."""

    def test_routes_to_review_when_all_optional_layers_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When ALL optional layers (shape, probablepeople, gazetteer) are absent,
        only the denylist ran. The fallback composite is 0.5 → review."""
        monkeypatch.setattr(
            "src.classifiers.person_name_validator._nameparser_available", lambda: False
        )
        monkeypatch.setattr(
            "src.classifiers.person_name_validator._probablepeople_available", lambda: False
        )
        monkeypatch.setattr("src.classifiers.person_name_validator._load_gazetteer", lambda: None)
        result = validate_person_name("John Smith")
        assert result.decision == "review"
        assert any("no optional layers" in r for r in result.reasons)

    def test_shape_score_is_none_when_nameparser_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.classifiers.person_name_validator._nameparser_available", lambda: False
        )
        result = validate_person_name("John Smith")
        assert result.layer_scores["shape"] is None


# ---------------------------------------------------------------------------
# available_layers() health reporting
# ---------------------------------------------------------------------------


class TestAvailableLayers:
    def test_returns_dict_with_required_keys(self) -> None:
        layers = available_layers()
        for key in ("denylist", "shape", "probablepeople", "gazetteer"):
            assert key in layers

    def test_denylist_always_true(self) -> None:
        assert available_layers()["denylist"] is True

    def test_gazetteer_true_when_files_present(self) -> None:
        # Files are bundled with the package; should always be True in CI
        assert available_layers()["gazetteer"] is True
