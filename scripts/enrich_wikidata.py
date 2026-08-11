#!/usr/bin/env python3
"""Nightly Wikidata entity-type enrichment for the companies table.

Validates detected company names against Wikidata's organization class
(Q43229) using the W3C Reconciliation API.  Results are cached indefinitely
in the local SQLite KeyValueStore (CC0 data, no TTL) and, when ``--apply``
is passed, the confirmed Wikidata QID is written back to the company row
so JSON-LD ``sameAs`` output includes the real Wikidata URL.

Running without ``--apply`` is a safe investigation pass: it shows what
would be matched without writing any changes.

Usage:
    # Dry-run (investigation / hit-rate sizing):
    python scripts/enrich_wikidata.py
    python scripts/enrich_wikidata.py --limit 50

    # Apply (write QIDs back to company rows):
    python scripts/enrich_wikidata.py --apply

    # Also check the event class (strong negative signal for person detection):
    python scripts/enrich_wikidata.py --events

    # Custom DB path:
    python scripts/enrich_wikidata.py --db-path results/file_organization.db
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# Make sure src/ is on sys.path when run as a script.
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from constants import DEFAULT_DB_PATH
from storage.wikidata_enricher import (
    QID_EVENT,
    QID_ORGANIZATION,
    WikidataEnricher,
    WikidataMatch,
    _KV_NAMESPACE,
)

# Seconds to sleep between API calls (sequential batching; Wikidata ToS).
_BETWEEN_CALL_SLEEP_SEC = 0.2


def _get_all_companies(db_path: str) -> List[Dict]:
    """Return id + normalized_name + name for every company row."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT id, name, normalized_name, wikidata_qid FROM companies ORDER BY id"
        )
        rows = cursor.fetchall()
    except sqlite3.OperationalError as exc:
        msg = str(exc)
        if "wikidata_qid" in msg or "no such column" in msg.lower():
            print(
                "ERROR: companies.wikidata_qid column missing.\n"
                "Run: organize-files migrate-wikidata --db-path " + db_path,
                file=sys.stderr,
            )
        else:
            print(f"ERROR: database error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()
    return [{"id": r[0], "name": r[1], "normalized_name": r[2], "wikidata_qid": r[3]} for r in rows]


def _write_qid_to_db(db_path: str, company_id: int, qid: str) -> None:
    """Persist a confirmed Wikidata QID to the companies row."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE companies SET wikidata_qid = ? WHERE id = ?",
            (qid, company_id),
        )
        conn.commit()
    finally:
        conn.close()


def run(
    db_path: str = DEFAULT_DB_PATH,
    limit: Optional[int] = None,
    apply: bool = False,
    check_events: bool = False,
) -> None:
    """Run the Wikidata enrichment pass over the companies table.

    Args:
        db_path: SQLite database path.
        limit: Maximum number of companies to process (None = all).
        apply: If True, write confirmed QIDs back to company rows.
        check_events: Also query the event class (Q1656682) for each name;
            a positive event match is logged as a negative org signal.
    """
    enricher = WikidataEnricher(db_path)
    all_companies = _get_all_companies(db_path)

    # Pre-filter already-enriched rows so --limit caps *queried* companies,
    # not total fetched.  A database where the first N rows are already enriched
    # would otherwise make "--limit N" a no-op.
    to_query = [c for c in all_companies if not c["wikidata_qid"]]
    already_enriched = len(all_companies) - len(to_query)

    if limit is not None:
        to_query = to_query[:limit]

    label = "APPLIED" if apply else "DRY RUN"
    print(f"[{label}] Wikidata enrichment — {len(to_query)} companies\n")
    if already_enriched:
        print(f"  INFO  {already_enriched} companies already enriched (skipped)\n")

    matched = 0
    no_match = 0
    event_collisions: List[str] = []

    for company in to_query:
        name: str = company["name"]

        org_key = enricher._cache_key(name, QID_ORGANIZATION)
        org_cached = enricher._kv.exists(org_key, namespace=_KV_NAMESPACE)
        match: Optional[WikidataMatch] = enricher.reconcile_organization(name)
        if not org_cached:
            time.sleep(_BETWEEN_CALL_SLEEP_SEC)

        if match:
            matched += 1
            print(
                f"  MATCH {name!r} → {match.qid} {match.label!r} "
                f"(score={match.score:.0f}) {match.wikidata_url}"
            )
            if apply:
                _write_qid_to_db(db_path, company["id"], match.qid)
        else:
            no_match += 1
            print(f"  MISS  {name!r}")

            if check_events:
                evt_key = enricher._cache_key(name, QID_EVENT)
                evt_cached = enricher._kv.exists(evt_key, namespace=_KV_NAMESPACE)
                event_match = enricher.reconcile_event(name)
                if not evt_cached:
                    time.sleep(_BETWEEN_CALL_SLEEP_SEC)
                if event_match:
                    event_collisions.append(name)
                    print(
                        f"        EVENT SIGNAL: {name!r} → {event_match.qid} "
                        f"{event_match.label!r} (score={event_match.score:.0f})"
                        " — not an org; strong negative signal for person detection"
                    )

    queried = len(to_query)
    hit_rate = matched / queried * 100 if queried else 0.0
    print(f"\n--- Summary ---")
    print(f"  Skipped    : {already_enriched} (already enriched)")
    print(f"  Queried    : {queried}")
    print(f"  Matched    : {matched}  ({hit_rate:.1f}% hit rate on queried)")
    print(f"  No match   : {no_match}")
    if check_events:
        print(f"  Event collisions: {len(event_collisions)}")
        for n in event_collisions:
            print(f"    - {n!r}")

    if not apply and matched > 0:
        print(f"\n[{label}] Pass --apply to write {matched} QID(s) to the database.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Nightly Wikidata enrichment for the companies table"
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N companies (default: all)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write confirmed QIDs to company rows (default: dry-run)",
    )
    parser.add_argument(
        "--events",
        action="store_true",
        help="Also query the event class for each name; logs event-class "
        "matches as negative signals for person/org detection",
    )
    args = parser.parse_args()
    run(
        db_path=args.db_path,
        limit=args.limit,
        apply=args.apply,
        check_events=args.events,
    )


if __name__ == "__main__":
    main()
