"""Unit tests for src/storage/wikidata_enricher.py.

All tests mock the HTTP layer so no real network calls are made.  The KV
cache is backed by a fresh in-memory SQLite database for each test.
"""

from __future__ import annotations

import json
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.storage.wikidata_enricher import (
    QID_EVENT,
    QID_LOCATION,
    QID_ORGANIZATION,
    RECONC_MIN_SCORE,
    WikidataEnricher,
    WikidataMatch,
    _CACHE_MISS_SENTINEL,
    _KV_NAMESPACE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_api_response(
    qid: str = "Q95",
    label: str = "Google",
    score: float = 100.0,
    match: bool = True,
) -> bytes:
    """Return a minimal Reconciliation API response body."""
    payload = {
        "q0": {
            "result": [
                {"id": qid, "name": label, "score": score, "match": match}
            ]
        }
    }
    return json.dumps(payload).encode()


def _make_empty_response() -> bytes:
    return json.dumps({"q0": {"result": []}}).encode()


def _mock_urlopen(body: bytes) -> Any:
    """Patch urllib.request.urlopen to return *body*."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=False)
    ctx.read.return_value = body
    return ctx


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def enricher(tmp_path):
    """WikidataEnricher backed by an in-memory (tmp) SQLite database."""
    db_path = tmp_path / "test_wikidata.db"
    return WikidataEnricher(db_path)


# ---------------------------------------------------------------------------
# WikidataMatch dataclass
# ---------------------------------------------------------------------------


class TestWikidataMatch:
    def test_wikidata_url(self):
        m = WikidataMatch(qid="Q95", label="Google", score=100.0, entity_class=QID_ORGANIZATION)
        assert m.wikidata_url == "https://www.wikidata.org/wiki/Q95"

    def test_frozen(self):
        m = WikidataMatch(qid="Q95", label="Google", score=100.0, entity_class=QID_ORGANIZATION)
        with pytest.raises(Exception):
            m.qid = "Q1"  # type: ignore[misc]

    def test_fields(self):
        m = WikidataMatch(qid="Q42", label="Answer", score=90.0, entity_class=QID_EVENT)
        assert m.qid == "Q42"
        assert m.label == "Answer"
        assert m.score == 90.0
        assert m.entity_class == QID_EVENT


# ---------------------------------------------------------------------------
# reconcile_organization — positive match
# ---------------------------------------------------------------------------


class TestReconcileOrganization:
    def test_match_returned_on_high_score(self, enricher):
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(_make_api_response())):
            result = enricher.reconcile_organization("Google")
        assert isinstance(result, WikidataMatch)
        assert result.qid == "Q95"
        assert result.label == "Google"
        assert result.score == 100.0
        assert result.entity_class == QID_ORGANIZATION

    def test_none_on_empty_results(self, enricher):
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(_make_empty_response())):
            result = enricher.reconcile_organization("XyzNoMatchCo")
        assert result is None

    def test_none_when_score_below_threshold(self, enricher):
        low_score_body = _make_api_response(score=RECONC_MIN_SCORE - 1)
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(low_score_body)):
            result = enricher.reconcile_organization("Some Fuzzy Name")
        assert result is None

    def test_none_on_network_error(self, enricher):
        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            result = enricher.reconcile_organization("Google")
        assert result is None

    def test_none_on_timeout(self, enricher):
        with patch("urllib.request.urlopen", side_effect=TimeoutError()):
            result = enricher.reconcile_organization("Google")
        assert result is None

    def test_none_on_malformed_json(self, enricher):
        ctx = _mock_urlopen(b"not json at all")
        with patch("urllib.request.urlopen", return_value=ctx):
            result = enricher.reconcile_organization("Google")
        assert result is None


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------


class TestCache:
    def test_positive_result_cached_indefinitely(self, enricher):
        body = _make_api_response()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)) as mock:
            enricher.reconcile_organization("Google")
            enricher.reconcile_organization("Google")
        # Second call must not hit the network.
        assert mock.call_count == 1

    def test_negative_result_cached(self, enricher):
        with patch(
            "urllib.request.urlopen", return_value=_mock_urlopen(_make_empty_response())
        ) as mock:
            enricher.reconcile_organization("NonExistentCo")
            enricher.reconcile_organization("NonExistentCo")
        assert mock.call_count == 1

    def test_cache_key_is_class_scoped(self, enricher):
        """Same name under different classes gets separate cache entries."""
        body = _make_api_response()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)) as mock:
            enricher.reconcile_organization("Burning Man")
            enricher.reconcile_event("Burning Man")
        assert mock.call_count == 2

    def test_cache_key_normalizes_case(self, enricher):
        body = _make_api_response()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)) as mock:
            enricher.reconcile_organization("Google")
            enricher.reconcile_organization("GOOGLE")
        assert mock.call_count == 1

    def test_corrupt_cache_entry_re_queries(self, enricher):
        """A stale or corrupt KV value triggers a fresh API call."""
        cache_key = enricher._cache_key("Google", QID_ORGANIZATION)
        enricher._kv.set(cache_key, {"bad": "data"}, namespace=_KV_NAMESPACE)
        body = _make_api_response()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)) as mock:
            result = enricher.reconcile_organization("Google")
        assert mock.call_count == 1
        assert result is not None
        assert result.qid == "Q95"

    def test_network_error_does_not_cache_permanently(self, enricher):
        """Network errors should cache the sentinel for 7 days, not forever."""
        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("down"),
        ):
            enricher.reconcile_organization("Google")

        # The sentinel is in the cache (short TTL); calling again skips network.
        with patch("urllib.request.urlopen") as mock2:
            enricher.reconcile_organization("Google")
        assert mock2.call_count == 0


# ---------------------------------------------------------------------------
# reconcile_event and reconcile_location
# ---------------------------------------------------------------------------


class TestOtherEntityClasses:
    def test_reconcile_event(self, enricher):
        body = _make_api_response(qid="Q2301702", label="Burning Man")
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
            result = enricher.reconcile_event("Burning Man")
        assert result is not None
        assert result.entity_class == QID_EVENT
        assert result.qid == "Q2301702"

    def test_reconcile_location(self, enricher):
        body = _make_api_response(qid="Q956", label="Austin")
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
            result = enricher.reconcile_location("Austin")
        assert result is not None
        assert result.entity_class == QID_LOCATION
        assert result.qid == "Q956"

    def test_event_returns_none_for_no_match(self, enricher):
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(_make_empty_response())):
            result = enricher.reconcile_event("XyzMadeUpEvent2026")
        assert result is None


# ---------------------------------------------------------------------------
# QID format guard — must start with Q
# ---------------------------------------------------------------------------


class TestQidFormatGuard:
    def test_rejects_non_q_id(self, enricher):
        """The API should never return non-Q IDs, but guard defensively."""
        bad_body = json.dumps(
            {"q0": {"result": [{"id": "L123", "name": "Lexeme", "score": 100.0}]}}
        ).encode()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(bad_body)):
            result = enricher.reconcile_organization("Something")
        assert result is None

    def test_rejects_empty_id(self, enricher):
        bad_body = json.dumps(
            {"q0": {"result": [{"id": "", "name": "Empty", "score": 100.0}]}}
        ).encode()
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(bad_body)):
            result = enricher.reconcile_organization("Something")
        assert result is None


# ---------------------------------------------------------------------------
# Threshold boundary
# ---------------------------------------------------------------------------


class TestScoreThreshold:
    def test_exactly_at_threshold_accepted(self, enricher):
        body = _make_api_response(score=RECONC_MIN_SCORE)
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
            result = enricher.reconcile_organization("Threshold Co")
        assert result is not None

    def test_one_below_threshold_rejected(self, enricher):
        body = _make_api_response(score=RECONC_MIN_SCORE - 0.01)
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(body)):
            result = enricher.reconcile_organization("Near Miss Co")
        assert result is None
