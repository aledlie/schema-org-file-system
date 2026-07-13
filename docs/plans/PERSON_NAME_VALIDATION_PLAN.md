# Person-Name Validation Gate — Implementation Plan

**Date:** 2026-07-13
**Scope:** Replace the leaky `_PERSON_NAME_DENYLIST` with a layered, local-only person-name confidence gate at write time, plus a review-queue CLI and schema.org-aligned uncertainty storage.
**Backlog ref:** [`docs/BACKLOG.md` → Person-graph edge hygiene, gap 2](../BACKLOG.md#person-graph-edge-hygiene)
**Status:** Not started

## Background

1. OCR/regex person detection (`src/classifiers/entity_detector.py:200`, `extract_people_names`) creates false-positive `schema:Person` nodes — e.g. `Morning Train`, a theme-camp name from `Burning_Flipside_Map.pdf`.
2. The only guard today is a 7-substring denylist (`_PERSON_NAME_DENYLIST`, `src/storage/graph_store.py:44`) applied at **read** time in `get_all_people_with_files` (`graph_store.py:619`), not at write time. A denylist can only enumerate known-bad strings; it structurally cannot generalize to novel event/camp/product names.
3. Web research (2026-07-13) surveyed person-vs-org validation libraries, gazetteers, and production entity-resolution patterns (dedupe.io, Senzing, OpenRefine). Consensus architecture: composite scoring from multiple weak signals, three-way threshold routing (auto-accept / review queue / auto-reject), per-signal explanations stored with queued items.
4. External knowledge-base validation (Wikidata SPARQL `P31`/`Q5`, Google KG) was **rejected** for this feature: personal documents are dominated by non-notable people that no KB can confirm, and most false positives (local camps, small vendors) are equally non-notable, so even the negative veto is weak. See the separate backlog item on Wikidata for non-person entity typing.
5. Schema.org has no native uncertainty construct (GitHub issue #2986 closed "not planned"); the adopted community pattern (RO-Crate style) is an `additionalProperty` PropertyValue sidecar carrying detection confidence and review status.

## Architecture

```
name → L0 denylist            (fast-path reject; absorbs _PERSON_NAME_DENYLIST)
     → L1 nameparser shape    (require non-empty first AND last)
     → L2 probablepeople      (CRF tag type must be 'Person')
     → L3 Census gazetteer    (given-name + surname list membership)
     → weighted composite     → auto_accept (≥ 0.75) | review | reject (≤ 0.30)
```

- **Single write choke point:** all Person rows are born in `GraphStore.get_or_create_person` (`src/storage/graph_store.py:513`). `add_file_to_person` (`:551`) calls it at `:568` and already returns `False` when it receives `None` — so a rejecting gate requires **zero changes at the two edge-creation call sites**:
  - `src/pipeline/file_processor.py:284` (OCR-sourced; both the CLI pipeline and the thin `scripts/file_organizer_content_based.py` wrapper route through it since the 2026-07-13 refactor)
  - `src/storage/person_migration.py:556` (manifest/directory-name-sourced → passes `validate=False`)
- **Known limitation, by design:** `Morning Train` passes L1 (two capitalized tokens parse as first+last). It is caught by L2/L3 — the layers exist because no single signal suffices.
- **Precision over recall:** a false `Person/{Name}/` folder is worse than a missed person. Hard rules below bias ambiguity toward the review queue, never toward auto-accept.

## Phase 1 — Validator module + `names` extra (no DB changes)

**Files:** `src/classifiers/person_name_validator.py` (new), `src/classifiers/data/census_names/{given_names,surnames}.txt` (new), `scripts/download_census_names.py` (new), `tests/unit/test_person_name_validator.py` (new), `pyproject.toml`

**Why:** pure library code, independently shippable; nothing calls it yet.

**Changes:**

```python
# src/classifiers/person_name_validator.py
RouteDecision = Literal["auto_accept", "review", "reject"]

@dataclass(frozen=True)
class PersonNameValidation:
    name: str
    decision: RouteDecision
    score: float                            # composite, 0.0-1.0
    layer_scores: dict[str, float | None]   # {"denylist","shape","probablepeople","gazetteer"}; None = layer unavailable
    reasons: list[str]                      # human-readable, mirrors ConfidenceGateResult.reason style

def validate_person_name(name: str) -> PersonNameValidation: ...
def available_layers() -> dict[str, bool]: ...   # for `organize-files health`
```

Mirrors the `ConfidenceGateResult` pattern (`scripts/shared/confidence_gate.py`) but lives in `src/` — src must not import from scripts/.

Scoring rules (module-top constants, tunable):

- **L0 denylist** hit → immediate `reject` (score 0.0, short-circuit). Absorbs `_PERSON_NAME_DENYLIST` from graph_store (re-export kept there until Phase 3).
- **L1 nameparser:** first AND last non-empty → 1.0 else 0.0. Weight 0.2. Hard rule: L1 failure caps routing at `review` (never auto-accept single tokens) but never alone rejects.
- **L2 probablepeople:** tag type `Person` → 1.0; `Corporation`/`Household` → 0.0; `RepeatedLabelError` → 0.5. Weight 0.4.
- **L3 gazetteer:** first in given-name list AND last in surname list → 1.0; one of two → 0.5; neither → 0.0. Weight 0.4. Hard rule: gazetteer 0.0 alone never forces reject when L1+L2 both pass (non-Anglo name bias) — route to review instead.
- Composite = weighted mean over **available** layers (renormalize weights). `>= 0.75` auto_accept, `<= 0.30` reject, else review.
- **Graceful degradation:** each optional import wrapped in try/except ImportError (existing repo pattern); unavailable layer scores `None`. With zero optional layers installed, everything not denylisted routes to `review` — never auto-accept on shape alone.

Dependencies (`pyproject.toml`): new extra `names = ["nameparser>=1.1.3", "probablepeople>=0.5.5"]`, added to `all`.

Gazetteer data: US Census 2010 surname file + Census 1990 given-name distributions (public domain). Bundle trimmed lists (surnames with count ≥ 200 ≈ 25k rows; top ~5k given names; lowercase, one per line, ~300 KB total) so offline capability holds without the download script. `scripts/download_census_names.py` documents source URLs + trim thresholds and regenerates the bundled files.

**Testing:** parametrized true positives ("Mary O'Brien", hyphenated names) → auto_accept; false positives ("Morning Train", "Burning Flipside", "Acme LLC") → never auto_accept; per-layer ImportError degradation (monkeypatch imports; assert `None` score + renormalized composite); denylist short-circuit; ALL-CAPS/whitespace normalization consistent with `extract_people_names` title-casing.

## Phase 2 — Schema migration + write-time gate

**Files:** `src/storage/models.py`, `src/storage/migration.py`, `src/storage/graph_store.py`, `src/storage/person_migration.py`, tests

**Why:** wires the validator into the single choke point; adds the columns that make routing persistent and explainable.

**Changes:**

- `Person` model (`models.py:530`, after `source_ids` at `:549`):

  ```python
  review_status = Column(String(20), default='auto_accepted', index=True)
  # 'auto_accepted' | 'pending_review' | 'confirmed' | 'rejected'
  detection_confidence = Column(Float)              # nullable; composite score
  validation_scores = Column(JSON, default=dict)    # per-layer breakdown; {} = never validated
  validated_at = Column(DateTime)                   # tz-naive; from ._time import utcnow
  ```

- `run_migration` (`migration.py:552`): new section using the existing `column_exists` PRAGMA guard + `ALTER TABLE people ADD COLUMN ...` idiom (mirror `source_ids` at `:643`):
  `review_status VARCHAR(20) DEFAULT 'auto_accepted'`, `detection_confidence FLOAT`, `validation_scores JSON DEFAULT '{}'`, `validated_at DATETIME`; backfill `UPDATE people SET review_status='auto_accepted' WHERE review_status IS NULL`. Legacy rows keep `validation_scores={}` as the "never validated" marker the Phase 3 sweep targets. Honors `dry_run`; idempotent. `organize-files migrate-ids` already wires it — no new CLI.

- `get_or_create_person(name, email=None, role=None, session=None, *, validate=True)`:
  - Existing row: `review_status == 'rejected'` → return `None` (tombstone blocks silent recreation); else return as today.
  - New row, `validate=True`: `reject` → return `None`, no row (deterministic re-rejection on re-detection); `review` → `review_status='pending_review'`; `auto_accept` → `'auto_accepted'`. Always persist `detection_confidence`, `validation_scores`, `validated_at=utcnow()`.
  - New row, `validate=False`: `review_status='confirmed'` (trusted source), `validation_scores={}`.
  - Validator imported lazily / try-except so `src/storage` works without the `names` extra.
- `add_file_to_person(..., validate=True)` — pass-through to `get_or_create_person`; its existing `if person is None: return False` silently drops the edge on rejection.
- `person_migration.apply_person_index` (`:556`) passes `validate=False` — directory names are human-curated.
- `get_all_people_with_files` (`:619`): add `review_status NOT IN ('rejected', 'pending_review')` filter. **Keep the denylist substring check in this phase only** — legacy false positives were just backfilled to `auto_accepted` and aren't cleaned until the Phase 3 sweep.

**Testing:** legacy-DB migration (raw sqlite3 without new columns → run → PRAGMA-assert columns + backfill + idempotent rerun + dry_run untouched); routing per decision; rejected name → `None`/no row; rejected tombstone blocks recreation without violating the `normalized_name` unique constraint; `validate=False` → `confirmed`; `add_file_to_person` on rejected name → `False`, no edge; read-filter inclusion/exclusion per status; no-extras environment creates people (routes to review) without ImportError escapes.

## Phase 3 — Review-queue CLI + legacy revalidation sweep

**Files:** `src/cli.py`, `src/storage/graph_store.py`, tests, `docs/BACKLOG.md`

**Why:** the middle routing band needs a human workflow, and legacy rows need re-scoring before the denylist can be removed.

**Changes:**

```
organize-files review-people                       # list pending_review (default; read-only)
organize-files review-people --status rejected     # list by any status
organize-files review-people --accept "Name" ...   # pending → confirmed
organize-files review-people --reject "Name" ...   # any → rejected (tombstone kept; prune-person still deletes)
organize-files review-people --revalidate          # re-run validator over legacy rows
                                                   #   (auto_accepted with validation_scores == {}) and pending_review
organize-files review-people --db-path PATH        # default results/file_organization.db
organize-files review-people --apply               # dry-run by default; --apply backs up DB first (mirror prune-person)
```

- `--revalidate` never touches human-set `confirmed`/`rejected`; prints per-name old → new routing with the layer breakdown (the explainability payoff of `validation_scores`).
- New `GraphStore` methods: `list_people_by_status(status)`, `set_person_review_status(person_id_or_name, status)` (reuse the int/name lookup style of `get_files_by_person`), `revalidate_people(apply=False) -> List[dict]`.
- Remove the denylist loop from `get_all_people_with_files`; denylist now lives only inside the validator as L0. Drop the graph_store re-export.
- `organize-files health`: report `names` extra availability via `available_layers()`.

**Testing:** Namespace-driven CLI tests (pattern: `tests/unit/test_graph_store_prune.py`); dry-run makes no writes; `--apply` backs up then mutates; revalidate flips a seeded legacy `Morning Train` to pending/rejected while `confirmed` rows stay untouched; denylist-removal regression (formerly read-filtered names now excluded by status).

## Phase 4 — JSON-LD `additionalProperty` sidecar

**File:** `src/storage/models.py` (`build_person_jsonld`, `:909-928`) — the shared builder, **not** `to_schema_org` (project rule: edit the builders, not the thin delegator methods).

**Why:** schema.org alignment — a Person node must carry machine-detection provenance until confirmed, without inventing non-schema.org properties at the top level.

**Changes:**

```python
props = []
if getattr(f, "review_status", None):
    props.append({"@type": "PropertyValue", "propertyID": "ml:reviewStatus", "value": f.review_status})
if getattr(f, "detection_confidence", None) is not None:
    props.append({"@type": "PropertyValue", "propertyID": "ml:detectionConfidence", "value": f.detection_confidence})
if getattr(f, "validation_scores", None):
    props.append({"@type": "PropertyValue", "propertyID": "ml:validationScores", "value": json.dumps(f.validation_scores)})
if props:
    result["additionalProperty"] = props
```

`getattr` guards keep pre-migration rows serializable; the `ml:` prefix matches the existing `mentionCount` custom-extension convention (`:927`). Consumers filter on `reviewStatus` instead of trusting every `Person` node.

**Testing:** sidecar present/absent per field; legacy row emits no `additionalProperty`; JSON round-trips; core-export parity suite (`tests/integration/test_core_export_parity.py`) stays green.

## Phase 5 (deferred) — GLiNER tiebreaker

Separate heavy extra `names-ml = ["gliner>=0.2"]` (pulls torch). `gliner_tiebreak(name) -> float | None` with labels `["person name", "event name", "organization name", "product name"]`, invoked only from `review-people --revalidate --tiebreak` on pending candidates — never in the hot write path. Ship only if the Phase 3 review queue proves noisy in practice (GLiNER ~48 zero-shot F1 is too weak for first-line gating).

## Files changed

| Phase | Files |
|---|---|
| 1 | `src/classifiers/person_name_validator.py` (new), `src/classifiers/data/census_names/*` (new), `scripts/download_census_names.py` (new), `pyproject.toml`, `tests/unit/test_person_name_validator.py` (new) |
| 2 | `src/storage/models.py`, `src/storage/migration.py`, `src/storage/graph_store.py`, `src/storage/person_migration.py`, tests |
| 3 | `src/cli.py`, `src/storage/graph_store.py`, tests, `docs/BACKLOG.md` |
| 4 | `src/storage/models.py`, serialization tests |

## Testing

```bash
# Unit (per phase)
pytest tests/unit/test_person_name_validator.py
pytest tests/unit/  # full suite, ~831+

# Smoke (after Phase 3, against a copy of the real DB)
organize-files migrate-ids --db-path results/file_organization.db
organize-files review-people --revalidate            # dry-run: inspect old → new routing
organize-files review-people                         # inspect pending queue
organize-files person-view                           # dry-run: confirm no spurious Person/{Name}/ dirs

# Integration (after Phase 4)
pytest tests/integration/
```

## What this does NOT change

- No file moves and no deletion of existing Person rows — `prune-person` remains the deletion tool; `--reject` only sets a tombstone status.
- No external network calls anywhere in the pipeline (KB validation explicitly rejected — see backlog item on Wikidata for non-person types).
- No changes to person-edge call-site signatures; `person-view`/`index-people`/`prune-person` behavior unchanged (they benefit indirectly via the read filter).
- `entity_detector.extract_people_names` regexes unchanged — the gate sits downstream at node creation, so all detection sources (OCR, filenames, future detectors) pass through it.

## Risks

1. **probablepeople on Python 3.13 / macOS arm64** — depends on `python-crfsuite` (C extension); verify cp313 arm64 wheel installs in the venv before committing Phase 1. Mitigation is built in: per-layer ImportError degradation keeps the gate functional (more conservatively) without it.
2. **Gazetteer bias** — Census lists under-cover non-US/non-Anglo names; the "gazetteer alone never rejects when L1+L2 pass" hard rule routes those to review instead of rejecting.
3. **Backfill masks legacy false positives** — mitigated by keeping the read-time denylist through Phase 2 and removing it only after the Phase 3 `--revalidate` sweep exists.
4. **Rejected tombstones vs `normalized_name` uniqueness** — a rejected row occupies the name; `get_or_create_person` must return `None` for it rather than resurrecting it or violating uniqueness (Phase 2 test).
5. **Threshold tuning** — 0.75/0.30 are informed guesses; module constants, validated against the real DB via `--revalidate` dry-run output before any `--apply`.

## Open decisions

- Exact gazetteer trim thresholds (proposal: surname count ≥ 200, top ~5k given names).
- Whether `person-view`/`index-people` summaries should surface pending-review counts (nice-to-have, Phase 3).
- Whether `--reject` should also drop the person's file edges (proposal: no — status filter hides them; `prune-person` remains the deletion tool).
