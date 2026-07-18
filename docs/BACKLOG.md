# Backlog

Derived from session work, uncommitted changes, and codebase state.
Last updated: 2026-07-18 (added verified multi-agent review findings from the Wikidata enrichment implementation + pre-existing GPS falsy-zero guard).

## Open Items

### Wikidata SPARQL for non-person entity typing

**Status:** Done — 2026-07-18. Implemented `src/storage/wikidata_enricher.py` (W3C Reconciliation API v0.2 client with SQLite KV cache), `scripts/enrich_wikidata.py` (nightly batch script), `src/storage/wikidata_migration.py` (adds `companies.wikidata_qid` physical column), and `organize-files migrate-wikidata` / `organize-files enrich-wikidata` CLI commands. Company.generate_wikidata_url(qid) fixed (was returning a broken name-derived URL). 22 unit tests added. Core pipeline unchanged — enrichment is opt-in nightly-only. Phase 2 remaining: wire QID into JSON-LD sameAs output (requires surfacing KV cache data through build_company_jsonld or adding an ORM migration path).
**Priority:** P3
**Source:** gap-2 web research session, 2026-07-13

### `PHOTO_PROPERTY_CONFIDENCE` re-tune for `Media/Interiors` commit margin

`PhotoCompositionSignal`'s home-interior flag routes to `media/interiors_other` (folder `Media/Interiors`, schema.org `Room`) but scores `PHOTO_PROPERTY_CONFIDENCE(0.7) × W_PEOPLE_PHOTO(0.65) = 0.455` — only 0.055 over an image's `mime_fallback` vote (`0.4`). That lead is below `MIN_DECISION_MARGIN(0.10)`, so an interior photo whose only signals are composition + mime routes to `LOW_CONFIDENCE_FALLBACK` instead of committing to `Media/Interiors`. The `Room` schema override is wired but effectively unreachable for the common two-signal case.

**Status:** Open — not committed work; calibration change with eval impact.
**Priority:** P3
**Source:** `Media/Interiors` / schema.org `Room` folder addition, 2026-07-17

- **Do not eyeball the bump.** Per the Phase-3 calibration process (`src/scoring/weights.py` header — "treat this module as versioned data and commit each re-tune with its backtest report"), any change to `PHOTO_PROPERTY_CONFIDENCE` (or `W_PEOPLE_PHOTO`) must be backed by a `results/file_organization.db` backtest, committed with the report.
- **Target invariant:** `PHOTO_PROPERTY_CONFIDENCE × W_PEOPLE_PHOTO − (MIME_MATCH_CONFIDENCE × W_MIME) ≥ MIN_DECISION_MARGIN`, i.e. `conf ≥ (0.4 + 0.10) / 0.65 ≈ 0.77`, so interiors commit over the mime-only floor.
- **Regression guard:** measure false positives — staged/real-estate listing photos and any non-interior images the analyzer flags `is_property_mgmt` — before raising, since a higher confidence also strengthens every interior vote against genuine content winners.
- **Legacy parity note:** the legacy `_classify_photo_composition` still routes interiors to `property_management/other`; a unified re-tune widens the shadow legacy-vs-unified disagreement for interior photos until the legacy chain is retired (Phase 5).

### Content pipeline is OCR-bound (gate OCR on text-likelihood)

Profiling `organize-files content` (unified scorer, dry-run) on 2026-07-17 showed the workflow is **~85% OCR-bound** (`torch.conv2d` in the easyocr CRAFT + docTR detection CNNs ≈ 67% of self-time; CLIP is negligible). This session shipped P2/P3/P5 (docTR-fallback gate, screenshot double-OCR dedup, CLIP text-embedding memoization) — conv2d call count dropped 1189→528 (−56%). Two items remain.

**Status:** Open — P1 shipped 2026-07-18 (gate on by default at K=3); P2 gate shipped (recall tradeoff to monitor).
**Priority:** P3
**Source:** content-classification profiling + P2/P3/P5 optimization session, 2026-07-17

1. **Gate OCR on text-likelihood (P1) — Done.** `OCR_CLIP_GATE_TOPK = 3` constant added to `src/scoring/weights.py`; gate enabled by default at K=3 in `ContentOrganizer`, `ContentBasedFileOrganizer`, and the CLI. Opt out with `--ocr-clip-topk 0` (or `ocr_clip_topk=None`); `FileContext._skip_ocr_by_clip_gate` treats `K=0`/`None` as disabled. Eval: K=3 → 100% text recall, ~35% of photos skip OCR. Gate fails open when CLIP is unavailable. 15 unit tests added to `tests/unit/scoring/test_context.py::TestClipOcrGate`. Reusable tooling: `scripts/profile_pipeline.py` (hot-path profiler) + `scripts/eval_ocr_gate.py` (folder-labeled gate eval).

2. **P2 docTR-fallback gate — recall tradeoff to monitor.** The shipped gate (`extract_ocr_with_confidence`: skip the docTR fallback when easyocr cleanly finds no text) was eval'd over 7 text images at varying difficulty: **1/7 recall loss — very-low-contrast text** (easyocr's detector found nothing; docTR would have caught it). Clean, dark-mode, and rotated text were all gate-safe. So P2 trades a rare miss on near-invisible text for eliminating the docTR fallback. For a screenshot/photo-dominated 265k-file library this is very likely a net win, but it is a real behavior change — put it behind a config flag or revert if faint-text recall matters.


### Content organizer misclassifies diverse/screenshot sources (review-gate + robustness gaps)

A live `organize-files content --source ~/Desktop --limit 10` (unified scorer) on mixed real-world desktop content committed most files to wrong folders and surfaced several distinct gaps. Items 2–5 shipped; item 1 remains open.

**Status:** Open — item 1 gates safe use on real user directories.
**Priority:** P2 (item 1)
**Source:** `~/Desktop` content-run audit + full rollback, 2026-07-17

1. **The review gate keys on decision-confidence, which `InteriorSignal` inflates.** UI screenshots of real-estate listings committed to `Media/Interiors` (`Room`) because the interior probe votes ~0.99 (decision confidence ~0.85, margin ~0.81) even when the OCR/label confidence is 1–12%. The `low_confidence`/`low_margin` review bucket exists and *does* fire (confirmed in a `--scorer shadow` pass — one opaque PDF routed to `uncategorized/other`), but cannot catch these because the probe supplies genuine high decision-confidence to wrong content. Options: a per-signal reliability cap, or require corroboration for `InteriorSignal` on screenshot-detected inputs. Distinct from the `PHOTO_PROPERTY_CONFIDENCE` item above (that is the `PhotoCompositionSignal` property flag *under*-committing; this is the `InteriorSignal` probe *over*-committing). The scene-model swap in [`docs/plans/MEDIA_EXTERIORS_PLAN.md`](plans/MEDIA_EXTERIORS_PLAN.md) also intersects here.

### Wikidata enrichment — verified review findings (multi-agent review of the 2026-07-18 implementation)

A five-angle multi-agent review of the Wikidata enrichment commits (`ae1ad07`…`901204d`) produced ~30 candidates; these three survived verification against the current tree (stale/refuted findings were discarded — e.g. the ORM-column crash and hit-rate denominator were already fixed pre-merge).

**Status:** Open — small correctness fixes, no design work needed.
**Priority:** P3
**Source:** multi-agent review of Wikidata enrichment implementation, 2026-07-18

1. **`--limit` is applied before skipping already-enriched rows** (`scripts/enrich_wikidata.py` — `companies = companies[:limit]` runs before the `existing_qid` skip). On a database whose first N rows are already enriched, `--limit N` makes zero API calls. The limit should cap *queried* companies (filter enriched rows first, or skip them in SQL).
2. **API-response parsing sits outside the error guard** (`src/storage/wikidata_enricher.py::_query_api`). The `try/except` ends after `json.loads`; a JSON array body raises `AttributeError` on `body.get("q0")`, and a non-numeric `score` raises `ValueError` from `float()`. Both crash a batch run, violating the module's documented "returns None on any error" contract. Extend the guard (or catch `ValueError`/`AttributeError`/`TypeError`) around the post-parse block.
3. **Dry-run migration reports work it didn't do** (`src/storage/wikidata_migration.py::run_wikidata_migration`). `stats["columns_added"] += 1` also increments under `dry_run=True`, so the summary prints "Columns added: 1" directly above "[DRY RUN] No changes were made", and the return dict claims a change. Count only on the actual `ALTER TABLE` branch (or rename to `columns_pending` in dry-run).

Minor cleanups noted in the same review (batch `_write_qid_to_db` into one connection; dedupe `_column_exists`/`_table_exists` across `scoring_migration.py`/`wikidata_migration.py`; unhardcode `"2.1.0"` in `RECONC_USER_AGENT`) can ride along with these fixes.

### GPS falsy-zero guard drops equator/prime-meridian coordinates in `build_file_jsonld`

`build_file_jsonld` guards the `contentLocation` block with `if f.gps_latitude and f.gps_longitude:` (`src/storage/models.py`), so a valid coordinate of exactly `0.0` (equator or prime meridian) silently drops GPS data from JSON-LD output. Should be `is not None` checks on both.

**Status:** Open — pre-existing bug (not introduced by the Wikidata work), surfaced during the 2026-07-18 review.
**Priority:** P3
**Source:** multi-agent review (line-by-line diff scan angle), 2026-07-18

- One-line fix but touches the core-export path: `build_file_jsonld` is a shared pure builder (see the core-query export gotcha in `CLAUDE.md` — edit the builder, not `to_schema_org()`), and parity is locked by `tests/integration/test_core_export_parity.py`.
- Add a regression test with `gps_latitude=0.0` asserting `contentLocation` is emitted.


