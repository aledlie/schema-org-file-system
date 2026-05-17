# Unified Scoring Plan — File Classification Refactor

> Status: Draft v1 · Owner: TBD · Last updated: 2026-05-16
> Mode: Coexist behind `--scorer={legacy,unified}` flag · Default flips after shadow window proves parity

---

## 1. Goals & Non-Goals

### Goals
- Replace the **first-match-wins 9-step priority chain** in `scripts/file_organizer_content_based.py` with a **single weighted scorer** that runs all relevant signals per file and picks the highest-scoring `(category, subcategory)` tuple.
- Fix the audit failure modes:
  - **Format drift** — same content (PDF vs PNG) lands in different folders.
  - **Person/Org confusion** — brand names ("Morning Train") triggering person classification.
  - **Academic SSRN PDFs** misclassified as Technical/Documentation.
  - **Misleading extensions** — `.zip` named "Photos" routed by extension.
- Make every signal **independently testable**, **swappable**, and **observable** (per-signal score logged per file).
- Enable **backtest-driven weight calibration** against `results/file_organization.db`.
- Preserve current CLI surface (`organize-files content`) — zero behavioral change when `--scorer=legacy`.

### Non-Goals
- Replacing CLIP, OCR, or KIE pipelines.
- Redesigning the Schema.org export layer (`src/storage/schema_org_*`).
- Changing folder taxonomy / category vocabulary.
- Auto-learning weights from labels (ML weight tuning is future work; v1 ships hand-tuned priors + offline grid search).
- Removing the legacy chain in v1 — it stays behind the flag for ≥1 release cycle.

---

## 2. Current-State Analysis

### 2.1 Live classifier methods in `scripts/file_organizer_content_based.py`

| # | Priority (CLAUDE.md) | Method | Line | Returns | Confidence model |
|---|---|---|---|---|---|
| — | helper | `_has_human_name_signal` | 231 | `bool` | binary gate (titles, contact phrases) |
| 0a | renamed screenshots | inline block | 3331-3346 | tuple | substring match in renamed stem |
| 0b | filename patterns | `classify_by_filename_patterns` | 2050 | `(cat, sub, company, people)` | substring/regex; first match wins |
| 1a | organization | `classify_by_organization` | 1849 | `(cat, sub, org)` | keyword count + indicator lists (line 1869+) |
| 1b | person | `classify_by_person` | 1923 | `(cat, sub, people)` | `matches >= 2` keyword threshold (line 1971) + `_has_human_name_signal` gate |
| 3a | game assets | `classify_game_asset` | 1777 | `(cat, sub)` | extension + keyword/regex match |
| 3b | filepath | `classify_by_filepath` | 1703 | `str` path | exact filename/extension lookup |
| 3.5 | ID document (OCR) | inline block | 3416-3469 | tuple | OCR keyword list + MRZ regex |
| 4 | media file | `classify_media_file` | 1978 | `(cat, media_type, sub)` | extension + stem keywords + EXIF GPS |
| 4.5 | screenshot OCR/CLIP | inline block | 3485-3537 | tuple | OCR confidence threshold then CLIP fallback |
| 5 | people-in-photo | inline block (`has_people_in_photo`, `is_home_interior_no_people`) | 3539-3561, impls at 1245 / 1209 | tuple | CLIP score threshold 0.2-0.3 |
| 6 | text + KIE | inline + `classify_content` | 3563+ / 750 | `(cat, sub, company, people)` | `classify_with_kie` then keyword pattern dict |
| — | image-only CLIP | `classify_image_content` | 1178 | `dict[label] → score` | raw CLIP softmax |

The orchestration `else if`-style chain lives in **one large method spanning lines 3310-3589** (the file's main `_classify_file`-equivalent flow). Confidence values are mostly **implicit** (a method either returns a tuple or `None`); thresholds live as **magic numbers** (`0.2`, `0.3`, `_OCR_CONFIDENCE_THRESHOLD`, `matches >= 2`).

### 2.2 Canonical mirror — `src/organizers/content_organizer.py`
Partial reimplementation tracking the live script. Per project conventions in this audit, **the script is authoritative**; mirror drift is acknowledged. Refactor lands in `src/scoring/` (new module) and `scripts/file_organizer_content_based.py` is wired to consume it via thin adapter. The `src/organizers/content_organizer.py` mirror is updated last (or deleted in a follow-up — see Open Questions).

### 2.3 Supporting infrastructure

| File | Role |
|---|---|
| `scripts/shared/clip_classification.py` | `CLIPResult` NamedTuple, `classify_image`, `classify_with_ocr_fallback` (line 71) — already the right shape for a "Signal" output |
| `scripts/shared/clip_utils.py` | low-level CLIP embedding helpers |
| `scripts/shared/confidence_gate.py` | `ConfidenceGateResult` + `check_confidence` — reusable gating primitive |
| `scripts/shared/ocr_utils.py` | `extract_ocr_with_confidence` returning text/confidence/lang |
| `scripts/shared/ocr_classifier.py` | `classify_by_ocr` returning `(category, confidence, scores, text)` — model for signal output |
| `scripts/shared/kie_utils.py` | `extract_kie_fields` |
| `scripts/shared/constants.py` | candidate home for shared weight constants (see §5) |
| `src/storage/models.py` | `File` model has `extracted_text`, `mime_type`, `content_hash`; join tables (`file_categories`, line 99-103) already carry `confidence` — reusable for persisted scores |

---

## 3. Target Architecture

### 3.1 High-level

```
FileContext (built once per file)
        │
        ▼
   ┌────────────┐
   │  Scorer    │ ── iterates registered Signals (parallel-friendly)
   └─────┬──────┘
         │ collects List[CategoryScore]
         ▼
   Aggregator → per-(cat, sub) weighted sum → arg-max
         │
         ▼
   ClassificationDecision { winner, runner_up, margin, all_scores, evidence }
```

### 3.2 Core interfaces (Python 3.13 dataclasses + Protocols)

```python
# src/scoring/types.py
class Signal(Protocol):
    name: str
    weight: float                       # prior, from constants module
    cost_tier: Literal["cheap","mid","heavy"]
    def applies_to(self, ctx: FileContext) -> bool: ...
    def run(self, ctx: FileContext) -> list[CategoryScore]: ...

@dataclass(frozen=True, slots=True)
class CategoryScore:
    category: str
    subcategory: str
    confidence: float                   # signal-local, [0,1]
    signal_name: str
    evidence: dict[str, object]         # what matched (keywords, regex, CLIP label)
```

### 3.3 Scorer

- `Scorer.classify(ctx) -> ClassificationDecision`
- Runs signals in **cost-tier waves**: cheap → mid → heavy. Heavy signals (CLIP, KIE) are skipped if a cheap-tier signal already exceeds `EARLY_EXIT_CONFIDENCE` (default 0.95 *aggregated*, not per-signal — preserves multi-evidence wins).
- **Aggregation:** `score(cat,sub) = Σ over signals (signal.weight × s.confidence)` for matching `(cat,sub)`. Same-signal duplicate entries deduped by max.
- **Tie-breaking** (deterministic):
  1. Higher aggregated score.
  2. More distinct contributing signals (multi-evidence wins).
  3. Higher `cost_tier` priority among contributors (heavy > mid > cheap — heavy signals are content-aware).
  4. Stable signal-name order from registry.
- **Confidence thresholds:**
  - `MIN_DECISION_CONFIDENCE` (e.g. 0.35 aggregated) — below this returns `("uncategorized","other")`.
  - `MIN_DECISION_MARGIN` (e.g. 0.10) over runner-up — required to commit; otherwise route to `review/` (new low-confidence bucket) and log.

### 3.4 Microservice-friendliness
- Each Signal is a pure function over `FileContext`. No I/O outside its constructor's injected clients (CLIP model, OCR client). Allows future relocation to RPC services without API change.
- Signals registered via list in `src/scoring/registry.py` — adding/removing is one line, no orchestrator edits.

---

## 4. Per-Signal Mapping

Weights are **priors** (sum need not equal 1; relative magnitude matters). All weight constants live in `src/scoring/weights.py` — **no magic numbers**.

| # | Legacy classifier | New Signal | Output vocabulary | Prior weight | Cost | Precision/recall profile | Edge cases |
|---|---|---|---|---|---|---|---|
| 1 | `classify_by_organization` (L1849) | `OrganizationKeywordSignal` | `(government, healthcare, financial, educational, nonprofit, employers, organization/*)` | `W_ORG = 1.0` | mid | high-precision when >2 indicators, low recall | Brand-as-person collisions; gated by `_has_human_name_signal` inversion |
| 2 | `classify_by_person` (L1923) | `PersonKeywordSignal` | `(person/contacts, employees, references, clients)` | `W_PERSON = 0.9` | mid | medium precision; needs `_has_human_name_signal=True` to fire above 0.5 | "Morning Train"; partial resumes |
| 3 | legal patterns in `classify_by_filename_patterns` (L2086-2104) + `legal_patterns` (L2410) | `LegalContractSignal` | `legal/(corporate, contracts)`, `business/legal` | `W_LEGAL = 0.85` | cheap | high precision filename, low recall | SSRN academic PDFs (false-positive on "agreement") — use co-occurrence with org/person evidence to confirm |
| 4 | embedded in `classify_content` + filename patterns | `EcommerceSignal` | `business/ecommerce`, `financial/receipts` | `W_ECOM = 0.7` | mid | needs cart/SKU/price tokens | Receipts vs invoices ambiguity |
| 5 | embedded keyword logic | `SoftwareUiSignal` (OCR-driven) | `media/photos_screenshots_(dashboard,terminal,settings,browser,…)` | `W_UI = 0.75` | mid (OCR) | high recall on text-heavy UI | Marketing screenshots of dashboards |
| 6 | `classify_game_asset` (L1777) | `GameAssetSignal` | `game_assets/(sprites,textures,music,audio,fonts)`, `fonts/*` | `W_GAME = 0.8` | cheap | very high precision on naming patterns, zero on renamed files | Game music `.ogg` vs podcasts |
| 7 | `classify_by_filepath` (L1703) | `FilepathSignal` | path string (mapped to category via existing `filepath_patterns`) | `W_PATH = 0.6` | cheap | high recall, brittle on personal Downloads | `.zip` named "Photos" — under unified scoring, MIME extension contributes only 0.6×conf vs Media CLIP 0.7×0.8 |
| 8a | `classify_image_content` (L1178) CLIP | `ClipVisionSignal` | media subcats, screenshots subcats | `W_CLIP = 0.7` | heavy | medium precision, high recall | EXIF-driven enhancements (`enhance_weak_image_classification`) |
| 8b | KIE + `classify_content` (L750, L3573) | `TextContentSignal` (+ `KieStructuredSignal` sub-signal) | full category vocabulary | `W_TEXT = 0.8`, `W_KIE = 1.1` | heavy | KIE high-precision on invoices/receipts; text classifier medium | `_OCR_CONFIDENCE_THRESHOLD` gate retained |
| 9 | MIME / extension fallback | `MimeFallbackSignal` | broad category by ext (`DigitalDocument`, `ImageObject`, …) | `W_MIME = 0.3` | cheap | low precision, full recall | Always fires; deliberately low weight |
| — | renamed screenshot lookup (L3331) | `RenamedScreenshotSignal` | `media/photos_screenshots_*` | `W_RENAMED = 1.2` | cheap | very high precision when matches | Only when `display_path != file_path` |
| — | ID document OCR (L3416) | `IdentityDocumentSignal` | `person/contacts` | `W_ID = 1.0` | heavy | high precision on MRZ regex | Driver license low OCR confidence |
| — | photos w/ people / interior (L3539) | `PeopleInPhotoSignal`, `HomeInteriorSignal` | `media/photos_social`, `property_management/other` | `W_PEOPLE_PHOTO = 0.65` | heavy | medium | Stock-photo people in marketing |

**Format-drift fix:** because every signal contributes to a shared `(cat, sub)` score, a PDF and a PNG of the same content both accumulate weight from `TextContentSignal` + `OrganizationKeywordSignal` regardless of which extension-keyed signal fires first. The `MimeFallbackSignal` is too weak (0.3) to override.

---

## 5. Data Contracts

### 5.1 `FileContext` (built once, passed to all signals)

| Field | Type | Source | Populated when |
|---|---|---|---|
| `path` | `Path` | input | always |
| `display_path` | `Path \| None` | input | renamed-file flow |
| `mime_type` | `str \| None` | `enricher.detect_mime_type` | always |
| `schema_type` | `Literal["ImageObject","DigitalDocument","VideoObject","AudioObject"]` | derived | always |
| `extracted_text` | `str \| None` | `extract_text(path)` | mid tier, lazy |
| `text_length` | `int` | derived | with text |
| `ocr_text` | `str \| None` | `extract_ocr_with_confidence` | images, lazy |
| `ocr_confidence` | `float \| None` | OCR | with ocr |
| `ocr_language` | `str \| None` | OCR | with ocr |
| `clip_scores` | `dict[str,float]` | `classify_image_content` | images, lazy |
| `image_metadata` | `dict` | metadata parser | images |
| `kie_result` | `KieResult \| None` | `extract_kie_fields` | when OCR conf ≥ threshold |

Lazy fields are computed by methods on `FileContext` (`ensure_text()`, `ensure_clip()`) so signals declare what they need; the context memoizes.

### 5.2 `CategoryScore` — see §3.2.

### 5.3 `ClassificationDecision`

```python
@dataclass(frozen=True, slots=True)
class ClassificationDecision:
    category: str
    subcategory: str
    schema_type: str
    confidence: float          # aggregated, normalized to [0,1]
    margin: float              # over runner-up
    winning_signals: list[str] # which signals contributed
    all_scores: list[CategoryScore]  # for telemetry
    company_name: str | None
    people_names: list[str]
```

### 5.4 DB columns (already exist; reused)
`src/storage/models.py:99-103` `file_categories` join table already has a `confidence` column. We add **one new column** `signal_evidence JSON` (alembic migration) to persist `all_scores` for backtesting. No schema breakage.

---

## 6. Migration Strategy

### Phase 0 — Plumbing (1 PR)
1. Create `src/scoring/` package skeleton (types, weights, scorer, registry, signals/).
2. Add CLI flag `--scorer {legacy,unified,shadow}` to `organize-files content`. Default `legacy`.
3. Wire `Scorer.classify()` callable in `scripts/file_organizer_content_based.py` behind the flag.

### Phase 1 — Signal extraction (one PR per signal, ~12 PRs)
For each row in §4, extract the legacy method into a Signal class. Legacy method stays in place and delegates to the Signal (so legacy chain still works). Unit tests land with each PR.

### Phase 2 — Shadow mode (1-2 weeks of dogfood)
- `--scorer=shadow` runs **both** scorers per file. Legacy controls placement. Unified result + per-signal scores logged to `results/scoring_shadow.jsonl` and `file_categories` (with `source='shadow_unified'`).
- Diff report generator: `scripts/analyze_scoring_disagreement.py` — counts disagreements by category pair, surfaces top regressions.

### Phase 3 — Calibration
- Replay last N runs from `results/file_organization.db`. Grid-search weights to minimize disagreement on **known-correct** cases (human-labeled in `results/ml_data_labeled_*`).
- Update `src/scoring/weights.py` constants. No code change.

### Phase 4 — Flip default
- Default flips to `unified`. `legacy` flag retained for one release.
- Add deprecation warning to legacy path.

### Phase 5 — Removal (future)
- Delete legacy chain orchestration block (lines 3310-3589) and individual `classify_*` methods (they become thin shims around Signals).
- Decide fate of `src/organizers/content_organizer.py` mirror (see Open Questions).

---

## 7. Telemetry & Calibration

### 7.1 Per-classification log record (JSONL)

```
{
  "ts": "...", "file_hash": "...", "scorer": "unified",
  "decision": {"category": "...", "subcategory": "...", "confidence": 0.71, "margin": 0.18},
  "winning_signals": ["TextContentSignal", "OrganizationKeywordSignal"],
  "all_scores": [
    {"signal": "OrganizationKeywordSignal", "cat": "organization", "sub": "vendors", "conf": 0.62, "evidence": {...}},
    ...
  ],
  "legacy_decision": {"category": "...", ...}   // shadow mode only
}
```

Persisted to `results/scoring_telemetry.jsonl` (rotated daily) and the new `file_categories.signal_evidence` JSON column.

### 7.2 Backtest harness
- `scripts/backtest_scoring.py` reads `results/file_organization.db`, replays `FileContext` from stored `extracted_text` + `mime_type` (CLIP scores cached in `clip_cache`).
- Outputs accuracy delta vs labeled set, per-category confusion matrix, weight-sensitivity report (`∂accuracy/∂weight`).
- Calibration target: ≥98% agreement with legacy on **currently-correct** cases (sample audited manually), ≥80% fix rate on the audit-failure set (§9 risk 3 mitigation).

### 7.3 Dashboards
- Reuse `_site/` dashboard. Add panel "Signal contribution distribution" (per-signal % of wins) — surfaces dead signals (zero contribution = candidate for removal).

---

## 8. Testing Strategy

### 8.1 Unit tests — `tests/unit/scoring/`
- One file per signal: `test_organization_signal.py`, etc.
- Each test constructs a synthetic `FileContext` with the minimum fields the signal reads (no disk I/O, no CLIP model).
- Coverage gates: ≥90% line coverage per signal module.

### 8.2 Scorer aggregation tests — `tests/unit/scoring/test_scorer.py`
- Empty inputs, single signal, conflicting signals, tie-break orderings, early-exit threshold, low-confidence rejection.

### 8.3 Golden integration tests — `tests/integration/test_unified_scoring_golden.py`
~30 labeled fixtures under `tests/fixtures/scoring/` covering:

| Fixture group | Count | Targets audit failure |
|---|---|---|
| Org-named PDFs ("Morning Train" etc.) | 5 | person/org confusion |
| Same content PDF + PNG pairs | 4 | format drift |
| SSRN academic PDFs | 3 | misclassified as Technical |
| Misnamed archives (`Photos.zip`) | 3 | MIME-fallback over-trigger |
| Game asset edge cases (renamed) | 3 | naming-pattern brittleness |
| Screenshots (dashboard/terminal/browser) | 4 | OCR/CLIP routing |
| Resumes/CVs | 2 | person recall |
| Invoices (KIE) | 3 | structured extraction |
| Generic media | 3 | media routing |

Test harness asserts both **chosen category** and **minimum margin** to detect "right answer, fragile reasons".

### 8.4 Shadow-mode regression test
CI job replays `results/scoring_shadow.jsonl` from main branch nightly, fails on >2% new disagreements.

---

## 9. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | **Latency regression** — running all signals per file vs early exit | High | Medium | Cost-tier wave execution + `EARLY_EXIT_CONFIDENCE`; benchmark in CI (target ≤1.2× legacy median latency); CLIP/KIE cached as today |
| 2 | **Weight tuning brittleness** — manually picking 12 weights yields fragile decisions | High | High | Grid-search calibration in Phase 3; commit weights with backtest report; treat `weights.py` as data, version it separately |
| 3 | **Regression on currently-correct cases** — unified scorer might worsen cases legacy got right | Medium | High | Shadow mode + ≥98% legacy-agreement gate before default flip; rollback flag retained |
| 4 | **Schema.org export coupling** — `src/storage/schema_org_*` consumes category/subcategory strings; new low-confidence `review/` bucket may break export | Medium | Medium | Add `review` as first-class category in Schema.org mapping or have exporter skip `confidence < MIN_DECISION_CONFIDENCE` records (config flag) |
| 5 | **DB schema impact** — new `signal_evidence` JSON column requires migration; downstream readers may not tolerate | Low | Medium | Nullable column; gated alembic migration; dashboard reads via getattr |
| 6 | **Signal-explosion debugging** — hard to explain a misclassification when 8 signals contributed | Medium | Medium | Always log `all_scores`; CLI command `organize-files explain <file>` rerun + pretty-print evidence |
| 7 | **`content_organizer.py` mirror drift** during multi-PR rollout | High | Low | Freeze mirror at Phase 0; update or delete in Phase 5 only |
| 8 | **Person-gate too strict** — `_has_human_name_signal` requires title/contact phrases, may miss legit person docs without those | Medium | Medium | Person signal returns *graduated* confidence (gated → 0.9, ungated but name present → 0.4); aggregated scorer can still win on multi-signal evidence |

---

## 10. File-level Change List

### New files
| Path | Purpose |
|---|---|
| `src/scoring/__init__.py` | Package marker, named exports |
| `src/scoring/types.py` | `Signal` Protocol, `CategoryScore`, `ClassificationDecision`, `FileContext` |
| `src/scoring/weights.py` | All weight + threshold constants (single source of truth, no magic numbers) |
| `src/scoring/context.py` | `FileContext` builder with lazy `ensure_*` methods |
| `src/scoring/scorer.py` | `Scorer` orchestrator with cost-tier waves + aggregator |
| `src/scoring/registry.py` | Ordered list of registered Signals |
| `src/scoring/signals/organization.py` | Extracted from `classify_by_organization` |
| `src/scoring/signals/person.py` | Extracted from `classify_by_person` + `_has_human_name_signal` |
| `src/scoring/signals/legal.py` | Consolidates legal patterns from filename + content classifiers |
| `src/scoring/signals/ecommerce.py` | New extraction from `classify_content` ecom logic |
| `src/scoring/signals/software_ui.py` | OCR-driven UI screenshot detection |
| `src/scoring/signals/game_asset.py` | Wraps `classify_game_asset` |
| `src/scoring/signals/filepath.py` | Wraps `classify_by_filepath` |
| `src/scoring/signals/clip_vision.py` | Wraps `classify_image_content`, `has_people_in_photo`, `is_home_interior_no_people` |
| `src/scoring/signals/text_content.py` | Wraps `classify_content` + `classify_with_kie` |
| `src/scoring/signals/mime_fallback.py` | Extension/MIME default |
| `src/scoring/signals/renamed_screenshot.py` | Extracted from inline L3331 block |
| `src/scoring/signals/identity_document.py` | Extracted from inline L3416 block (incl. MRZ parser) |
| `tests/unit/scoring/test_*.py` | Per-signal + scorer unit tests |
| `tests/integration/test_unified_scoring_golden.py` | 30-fixture integration test |
| `tests/fixtures/scoring/*` | Labeled fixtures (real files or scrubbed text dumps + manifest YAML) |
| `scripts/backtest_scoring.py` | DB-driven weight backtest CLI |
| `scripts/analyze_scoring_disagreement.py` | Shadow-mode diff reporter |
| `migrations/NNNN_add_signal_evidence.py` | Alembic add `file_categories.signal_evidence JSON` |
| `docs/architecture/UNIFIED_SCORING_PLAN.md` | This document |

### Modified files
| Path | Rationale |
|---|---|
| `scripts/file_organizer_content_based.py` | Add `--scorer` switch in orchestrator (L3310-3589); each `classify_*` method delegates to its Signal during transition |
| `scripts/shared/constants.py` | Re-export selected weight names if other scripts need them |
| `src/organizers/content_organizer.py` | Mirror frozen until Phase 5; thin shim onto `Scorer` after |
| `src/cli.py` | Register `--scorer` argument |
| `CLAUDE.md` | Replace §"Classification Priority" with §"Unified Scoring" once default flips |
| `docs/SCHEMA_ORG_ARCHITECTURE.md` | Document new `review` category (if Open Question #2 resolves to add it) |
| `src/storage/models.py` | Optional `signal_evidence` column on `file_categories` join (line 99-103) |

---

## 11. Open Questions

1. **Low-confidence bucket placement** — should files with `confidence < MIN_DECISION_CONFIDENCE` route to a new `~/Documents/Review/` folder, stay in source location, or use today's `uncategorized/other`? Affects Schema.org export semantics.
2. **`src/organizers/content_organizer.py` fate** — delete in Phase 5 (single source of truth in `src/scoring/`), or keep as adapter for non-CLI callers? No current non-CLI callers found, leaning delete — confirm.
3. **Weight calibration source of truth** — hand-tuned priors checked into `weights.py`, or generated artifact from backtest committed alongside? Recommend committed priors + backtest report in `docs/architecture/scoring-calibration-YYYYMMDD.md` per re-tune.
4. **Early-exit aggressiveness** — should `EARLY_EXIT_CONFIDENCE` (skip heavy signals) be tunable per cost budget (CI vs interactive), or global constant?
5. **KIE as Signal vs preprocessor** — KIE both extracts structured fields *and* classifies. Treat as standalone `KieStructuredSignal` (weight 1.1) or as enrichment that boosts `TextContentSignal` confidence? Recommend separate signal for evidence transparency.
