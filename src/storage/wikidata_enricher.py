"""Wikidata entity-type validator for non-person entity typing.

Uses the W3C Reconciliation API v0.2 at wikidata.reconci.link to validate
entity class membership by name for Organizations, Locations, and Events.

Design principles:
- Optional nightly enrichment only; never called from the hot classification
  path.  The core pipeline must remain offline-capable.
- Offline-safe: every network call is wrapped with a 5-second timeout and
  returns None on any error (connection failure, timeout, malformed JSON).
- Results cached indefinitely in the local SQLite KeyValueStore (CC0 data
  needs no TTL).  Negative results cached for 7 days to avoid re-querying.
- Sequential use only; rate limits are ~5 parallel queries/IP per the Wikidata
  ToS.  Designed for nightly batch batches, not concurrent calls.

Usage::

    from src.storage.wikidata_enricher import WikidataEnricher
    enricher = WikidataEnricher("results/file_organization.db")
    match = enricher.reconcile_organization("Travis County Appraisal District")
    if match:
        print(match.wikidata_url)  # https://www.wikidata.org/wiki/Q...
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Optional, Union

try:
    from ..constants import DEFAULT_DB_PATH
    from .kv_store import KeyValueStorage
except ImportError:
    from constants import DEFAULT_DB_PATH  # type: ignore[no-redef]
    from kv_store import KeyValueStorage  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

try:
    _VERSION = _pkg_version("schema-org-file-system")
except PackageNotFoundError:
    _VERSION = "2.1.0"

# W3C Reconciliation API v0.2 endpoint for Wikidata (English labels).
RECONC_API_URL = "https://wikidata.reconci.link/en/api"

# Mandatory User-Agent string per the Wikidata bot policy.
RECONC_USER_AGENT = (
    f"schema-org-file-system/{_VERSION} (entity-type enrichment; "
    "contact: alyshia@integritystudio.ai)"
)

# Minimum reconciliation score (0–100) to accept a match.
RECONC_MIN_SCORE = 80.0

# Number of candidates fetched per query.  Top result only needs one slot;
# fetching three lets callers inspect the full short-list if desired.
RECONC_LIMIT = 3

# Network timeout in seconds; keeps the hot fallback path fast.
RECONC_TIMEOUT_SEC = 5

# Entity-class QIDs for type-filtered reconciliation.
QID_ORGANIZATION = "Q43229"  # organization (and all subclasses)
QID_EVENT = "Q1656682"  # occurrence (general event superclass)
QID_LOCATION = "Q2221906"  # geographic location

# KV store namespace for Wikidata cache entries.
_KV_NAMESPACE = "wikidata"

# Negative-result TTL: 7 days in seconds.
_NEGATIVE_TTL_SEC = 7 * 24 * 3600

# Sentinel stored for cache misses so we can distinguish "not yet queried"
# (None returned by kv.get) from "queried and confirmed no match".
_CACHE_MISS_SENTINEL = "__none__"


@dataclass(frozen=True)
class WikidataMatch:
    """A confirmed Wikidata entity match returned by the reconciliation API."""

    qid: str  # Wikidata item ID, e.g. "Q95"
    label: str  # English label returned by the API, e.g. "Google"
    score: float  # Reconciliation confidence score (0–100)
    entity_class: str  # Class QID used in the query, e.g. "Q43229"

    @property
    def wikidata_url(self) -> str:
        """Canonical Wikidata URL for this entity."""
        return f"https://www.wikidata.org/wiki/{self.qid}"


class WikidataEnricher:
    """Validates detected entity names against Wikidata class membership.

    Designed for optional nightly batch enrichment (see
    ``scripts/enrich_wikidata.py``).  The core classification pipeline never
    imports this module — adding zero latency to the hot path.

    All public methods return ``WikidataMatch | None``:
    - ``WikidataMatch`` — a high-confidence (score ≥ 80) class match.
    - ``None`` — no match found, score too low, or any network/API error.
    """

    def __init__(self, db_path: Union[str, Path] = DEFAULT_DB_PATH) -> None:
        self._kv = KeyValueStorage(db_path)

    # ------------------------------------------------------------------
    # Public reconciliation methods
    # ------------------------------------------------------------------

    def reconcile_organization(self, name: str) -> Optional[WikidataMatch]:
        """Validate *name* as a Wikidata organization (Q43229+subclasses).

        High-confidence matches confirm the name refers to a real, notable
        organization — suitable for creating ``Organization/{Name}/`` folders.
        """
        return self._reconcile(name, QID_ORGANIZATION)

    def reconcile_event(self, name: str) -> Optional[WikidataMatch]:
        """Check whether *name* is a known Wikidata event (Q1656682).

        A positive match is a strong *negative* signal for person/org
        detection: a name that reconciles as an event is not a person (e.g.
        "Morning Train" → confirmed event, not a person, org, or brand).
        """
        return self._reconcile(name, QID_EVENT)

    def reconcile_location(self, name: str) -> Optional[WikidataMatch]:
        """Validate *name* as a Wikidata geographic location (Q2221906).

        Use before creating Location graph nodes from detected place names.
        """
        return self._reconcile(name, QID_LOCATION)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cache_key(self, name: str, class_qid: str) -> str:
        normalized = name.lower().strip()
        return f"{class_qid}:{normalized}"

    def _reconcile(self, name: str, class_qid: str) -> Optional[WikidataMatch]:
        """Check cache first; fall back to the Wikidata API on a cache miss."""
        cache_key = self._cache_key(name, class_qid)

        cached = self._kv.get(cache_key, namespace=_KV_NAMESPACE)
        if cached is not None:
            if cached == _CACHE_MISS_SENTINEL:
                return None
            try:
                return WikidataMatch(**cached)
            except TypeError, KeyError:
                # Stale or corrupt cache entry; re-query.
                logger.debug("Corrupt Wikidata cache entry for %r; re-querying", name)

        match = self._query_api(name, class_qid)

        if match is not None:
            # CC0 data — cache indefinitely.
            self._kv.set(
                cache_key,
                {
                    "qid": match.qid,
                    "label": match.label,
                    "score": match.score,
                    "entity_class": match.entity_class,
                },
                namespace=_KV_NAMESPACE,
            )
        else:
            # Negative result — re-check in 7 days.
            self._kv.set(
                cache_key,
                _CACHE_MISS_SENTINEL,
                namespace=_KV_NAMESPACE,
                ttl_seconds=_NEGATIVE_TTL_SEC,
            )

        return match

    def _query_api(self, name: str, class_qid: str) -> Optional[WikidataMatch]:
        """POST a single reconciliation query to the Wikidata API.

        Returns a WikidataMatch when the top candidate clears RECONC_MIN_SCORE,
        or None for no match, low confidence, or any network/parse error.
        """
        payload = {
            "q0": {
                "query": name,
                "type": class_qid,
                "limit": RECONC_LIMIT,
            }
        }
        form_data = urllib.parse.urlencode({"queries": json.dumps(payload)}).encode()
        req = urllib.request.Request(
            RECONC_API_URL,
            data=form_data,
            headers={
                "User-Agent": RECONC_USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=RECONC_TIMEOUT_SEC) as resp:
                body = json.loads(resp.read().decode())

            # Parse inside the guard: body may be a JSON array (AttributeError on
            # .get), score may be a non-numeric string (ValueError from float()),
            # and candidate fields may be missing (KeyError/TypeError).
            candidates = body.get("q0", {}).get("result", [])
            if not candidates:
                return None

            top = candidates[0]
            score = float(top.get("score", 0))
            if score < RECONC_MIN_SCORE:
                logger.debug(
                    "Wikidata: %r → %s (score %.1f < threshold %.1f)",
                    name,
                    top.get("id"),
                    score,
                    RECONC_MIN_SCORE,
                )
                return None

            qid = top.get("id", "")
            if not qid or not qid.startswith("Q"):
                return None

            return WikidataMatch(
                qid=qid,
                label=top.get("name", name),
                score=score,
                entity_class=class_qid,
            )
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
            AttributeError,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:
            logger.debug("Wikidata API unavailable for %r: %s", name, exc)
            return None
