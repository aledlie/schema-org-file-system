"""Joint weight/threshold search: invariants, split, and search space.

Covers the parts that must hold without a database — the behavioural
constraints an optimiser would otherwise violate, and the train/holdout split
that makes the overfitting check meaningful. The replay itself is exercised by
the calibration harness, not here.
"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import pytest

from scripts.weight_search import (
    _CONFIDENCE_KEY,
    _MARGIN_KEY,
    constraint_violations,
    shipped_candidate,
    split_rows,
)
from src.scoring.signals.mime_fallback import MIME_MATCH_CONFIDENCE
from src.scoring.weights import MIN_DECISION_CONFIDENCE, MIN_DECISION_MARGIN

_REPO_ROOT = Path(__file__).resolve().parents[3]


def rows(count: int):
    return [SimpleNamespace(file_id=index) for index in range(count)]


class TestShippedCandidate:
    def test_covers_every_searchable_knob(self):
        candidate = shipped_candidate()

        # 19 signal priors plus the two decision thresholds.
        assert len(candidate) == 21
        assert candidate[_CONFIDENCE_KEY] == MIN_DECISION_CONFIDENCE
        assert candidate[_MARGIN_KEY] == MIN_DECISION_MARGIN

    def test_shipped_weights_satisfy_their_own_invariants(self):
        """If this fails, weights.py drifted — not the search."""
        assert constraint_violations(shipped_candidate()) == []


class TestConstraintViolations:
    def test_org_must_outrank_person(self):
        candidate = shipped_candidate()
        candidate["organization_keyword"] = candidate["personal_doc"]

        assert any("W_ORG" in violation for violation in constraint_violations(candidate))

    def test_person_must_outrank_legal(self):
        candidate = shipped_candidate()
        candidate["personal_doc"] = candidate["legal_content"] - 0.1

        assert any("W_PERSON" in violation for violation in constraint_violations(candidate))

    def test_mime_must_still_commit_alone(self):
        # Drop mime below the confidence floor: an extension-only file would
        # fall to uncategorized instead of committing.
        candidate = shipped_candidate()
        candidate["mime_fallback"] = (MIN_DECISION_CONFIDENCE / MIME_MATCH_CONFIDENCE) - 0.05

        assert any("must commit" in violation for violation in constraint_violations(candidate))

    def test_mime_must_not_outcommit_content(self):
        # Raise mime past floor+margin: it would override genuine content.
        candidate = shipped_candidate()
        ceiling = (MIN_DECISION_CONFIDENCE + MIN_DECISION_MARGIN) / MIME_MATCH_CONFIDENCE
        candidate["mime_fallback"] = ceiling + 0.05

        assert any("out-commit" in violation for violation in constraint_violations(candidate))

    def test_raising_the_floor_can_break_mime_commit(self):
        """The interaction coordinate search cannot see.

        Weights and thresholds are tuned in separate passes today, so a
        confidence floor above W_MIME*MIME_MATCH_CONFIDENCE is reachable
        without either pass noticing.
        """
        candidate = shipped_candidate()
        candidate[_CONFIDENCE_KEY] = 0.45

        assert constraint_violations(candidate)

    def test_reports_every_violation_not_just_the_first(self):
        # Both ordering invariants inverted: org < person < legal.
        candidate = shipped_candidate()
        candidate["organization_keyword"] = 0.1
        candidate["personal_doc"] = 0.2
        candidate["legal_content"] = 0.3

        assert len(constraint_violations(candidate)) == 2


class TestSplitRows:
    def test_split_is_a_partition(self):
        train, holdout = split_rows(rows(200), 0.3)

        assert len(train) + len(holdout) == 200
        assert not {r.file_id for r in train} & {r.file_id for r in holdout}

    def test_holdout_fraction_is_approximated(self):
        _train, holdout = split_rows(rows(500), 0.3)

        assert 0.2 < len(holdout) / 500 < 0.4

    def test_zero_fraction_disables_holdout(self):
        train, holdout = split_rows(rows(50), 0.0)

        assert len(train) == 50
        assert holdout == []

    def test_membership_is_stable_when_rows_are_added(self):
        """Adding rows must not reshuffle existing membership."""
        _, before = split_rows(rows(100), 0.3)
        _, after = split_rows(rows(200), 0.3)

        assert {r.file_id for r in before} <= {r.file_id for r in after}

    def test_split_is_stable_across_processes(self):
        """Regression: the builtin hash() is randomised per process.

        Using it here silently reshuffled train/holdout on every run, so two
        runs reported different baselines off different row sets and the
        generalisation check compared nothing.
        """
        script = (
            "import sys; sys.path.insert(0, 'scripts');"
            "from types import SimpleNamespace;"
            "from weight_search import split_rows;"
            "rows=[SimpleNamespace(file_id=i) for i in range(300)];"
            "tr,ho=split_rows(rows,0.3);"
            "print(len(tr), [r.file_id for r in ho[:10]])"
        )
        runs = {
            subprocess.run(
                [sys.executable, "-c", script],
                cwd=_REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            for _ in range(3)
        }

        assert len(runs) == 1, f"split differs across processes: {runs}"


class TestSearchSpace:
    def test_constraint_rejects_inadmissible_candidates(self):
        pytest.importorskip("nevergrad")
        from scripts.weight_search import build_parametrization

        parametrization = build_parametrization(search_thresholds=True, seed=0)

        admissible = parametrization.spawn_child()
        admissible.value = shipped_candidate()
        assert admissible.satisfies_constraints()

        violating = parametrization.spawn_child()
        broken = shipped_candidate()
        broken["organization_keyword"] = broken["legal_content"] - 0.1
        violating.value = broken
        assert not violating.satisfies_constraints()

    def test_weights_only_pins_the_thresholds(self):
        pytest.importorskip("nevergrad")
        from scripts.weight_search import build_parametrization

        value = build_parametrization(search_thresholds=False, seed=0).value

        assert value[_CONFIDENCE_KEY] == MIN_DECISION_CONFIDENCE
        assert value[_MARGIN_KEY] == MIN_DECISION_MARGIN

    def test_bounds_are_wide_enough_for_the_mutation_sigma(self):
        """Every searched scalar spans +/-3 sigma.

        nevergrad's default sigma of 1.0 dwarfs these bands (W_MIME spans
        0.24), so nearly every mutation would land outside the bounds and be
        clipped — it warns below 3 sigma. Without this the search wastes its
        budget on the boundary.
        """
        pytest.importorskip("nevergrad")
        from scripts.weight_search import build_parametrization

        parametrization = build_parametrization(search_thresholds=True, seed=0)

        checked = 0
        for key in parametrization.value:
            scalar = parametrization[key]
            bounds = getattr(scalar, "bounds", None)
            if bounds is None or bounds[0] is None:
                continue
            lower, upper = float(bounds[0].item()), float(bounds[1].item())
            sigma = float(np.asarray(scalar.sigma.value).item())
            assert (upper - lower) / sigma == pytest.approx(6.0, rel=1e-6)
            checked += 1

        assert checked == 21

    def test_building_the_space_emits_no_nevergrad_warnings(self):
        """Regression: set_bounds before set_mutation warns spuriously.

        The final sigma is identical either way, so the only symptom is a
        warning that looks like the sigma never took effect.
        """
        pytest.importorskip("nevergrad")
        import warnings

        from scripts.weight_search import build_parametrization

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            build_parametrization(search_thresholds=True, seed=0)

        sigma_warnings = [str(w.message) for w in caught if "sigma" in str(w.message)]
        assert sigma_warnings == []
