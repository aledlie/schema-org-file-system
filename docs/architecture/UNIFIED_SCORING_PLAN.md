# Unified Scoring Plan — File Classification Refactor

> Status: Draft v2 · Owner: TBD · Last updated: 2026-07-16
> Mode: Coexist behind `--scorer={legacy,unified}` flag · Default flips after shadow window proves parity
> Code references are as of 2026-07-16 (`main` @ `feeccdc`), post thin-wrapper refactor.
> Status: unimplemented — `src/scoring/` does not exist yet; all line refs below are current-state anchors for the extraction, not existing scorer code.

### Changes from v1 (2026-05-16)

The 2026-07 thin-wrapper refactor moved the entire classification layer out of
`scripts/file_organizer_content_based.py` (now a 502-line CLI shim) into
`src/organizers/content_organizer.py` / `src/classifiers/`. v1's current-state
analysis, line references, and migration mechanics targeted the old monolithic
script and are superseded. Substantive deltas:

- **Extraction target is now `src/`** — signals extract from `ContentOrganizer`,
  `ContentClassifier`, and `shared/filename_classifier.py`, not the script.
- **v1 Open Question #2 (mirror fate) is resolved** — `src` won; there is no
  mirror. v1 Risk 7 (mirror drift) is retired with it.
- **Person taxonomy Option C landed** (2.1.0): `person` is a graph relationship,
  not a category. Person-flavored signals emit `personal/{subcat}` for filing
  plus `people_names` for `GraphStore.add_file_to_person` edges.
- **A proto-unified scorer already ships** in the image path
  (`_merge_clip_text_scores`, §2.3) — this plan generalizes it from
  2 signals × images to N signals × all files.
- **SSRN/arXiv/DOI misrouting is fixed at the filename tier**
  (`_detect_research_publisher`); the residual gap is content-only detection
  (papers without a publisher-prefixed filename).
- v1's `EcommerceSignal` is folded into `TextContentSignal` — the current chain
  has no dedicated e-commerce logic to extract (it lives in
  `ContentClassifier` business/financial keyword patterns).
- No alembic in this repo — the `signal_evidence` column ships via the
  established hand-rolled migration pattern (`src/storage/migration.py`,
  `organize-files migrate-*`).

---

## 1. Goals & Non-Goals

### Goals
- Replace the **first-match-wins 10-tier priority chain** in
  `ContentOrganizer.detect_file_category` (`src/organizers/content_organizer.py:1080`)
  with a **single weighted scorer** that runs all relevant signals per file and
  picks the highest-scoring `(category, subcategory)` tuple.
- Fix the remaining audit failure modes (status updated for v2):
  - **Format drift** — same content (PDF vs PNG) lands in different folders.
    *Partially mitigated:* `_merge_clip_text_scores` unifies CLIP+OCR for
    images, but documents never merge signals; the chain overall is still
    first-match-wins.
  - **Person/Org confusion** — brand names ("Morning Train") triggering person
    classification. *Gates improved* (`_has_human_name_signal`, legal-document
    veto, per-type hit thresholds) but the structural issue — one tier deciding
    alone — remains.
  - **Academic PDFs** misclassified as Technical/Documentation. *Fixed for
    publisher-prefixed filenames* (ssrn-/arxiv-/doi- → `Research/{Publisher}`,
    `ScholarlyArticle`); still broken for papers detectable only from content.
  - **Misleading extensions** — `.zip` named "Photos" routed by extension.
    *Still present:* filepath/extension tiers run before content tiers.
- Make every signal **independently testable**, **swappable**, and
  **observable** (per-signal score logged per file).
- Replace the hidden per-file instance state (`_last_file_*`,
  `_clip_enhance_cache`, reset at `content_organizer.py:1113`) with an explicit
  memoizing `FileContext` — removes ordering coupling between tiers and makes
  per-file scoring parallel-safe.
- Enable **backtest-driven weight calibration** against
  `results/file_organization.db`.
- Preserve current CLI surface (`organize-files content`) — zero behavioral
  change when `--scorer=legacy`.

### Non-Goals
- Replacing CLIP, OCR, or KIE pipelines.
- Redesigning the Schema.org export layer (`src/storage/schema_org_*`,
  `build_*_jsonld` builders).
- Changing folder taxonomy / category vocabulary. Option C is settled ground:
  signals emit `personal/{subcat}` + graph edges; `Person/{Name}/` remains a
  derived symlink view, never a filing target.
- Auto-learning weights from labels (v1 ships hand-tuned priors + offline grid
  search).
- Removing the legacy chain in v1 of the rollout — it stays behind the flag for
  ≥1 release cycle.

---

## 2. Current-State Analysis (post-refactor)

### 2.1 The live chain — `ContentOrganizer.detect_file_category`

Single orchestrator method at `src/organizers/content_organizer.py:1080-1310`;
tiers are methods on the same class (extracted from the old script during the
refactor, logic unchanged). First match wins; confidence is implicit (a tier
returns a tuple or `None`); thresholds are named module constants
(`content_organizer.py:108-174`) — the magic numbers of v1 now have names, but
they gate rather than weigh.

| Tier | Method | Line | Returns | Confidence model |
|---|---|---|---|---|
| 0a renamed screenshot | inline block | 1141 | tuple | substring match on renamed stem |
| 0b filename patterns | `classify_by_filename_patterns` → `shared/filename_classifier.py:87` | 805 | `(cat, sub, company, people)` | ~40 ordered rule groups (research-publisher, legal, financial-doc, event-date, entity, …); first match wins |
| 1a organization | `classify_by_organization` | 583 | `(cat, sub, org)` | ≥2 keyword hits per org type + `extract_company_names` |
| 1b person | `classify_by_person` | 658 | `('personal', sub, people)` | ≥2 hits (≥3 for contacts) + `_has_human_name_signal` gate + legal-document veto (`_LEGAL_DOCUMENT_SIGNALS` ≥2 → defer) |
| 3a game assets | `classify_game_asset` | 522 | `(cat, sub)` | extension + keyword/regex; `_ocr_document_override` (call site L1207) can flip ambiguous textures to document categories |
| 3b filepath | `classify_by_filepath` | 429 | path string | exact filename/extension lookup + project-name extraction |
| 3.5 ID document | `_classify_identification_document` | 1311 | `('personal', 'identification', …, people)` | OCR keywords + MRZ regex; gated on OCR conf ≥ `_OCR_CONFIDENCE_THRESHOLD` (0.3); stores OCR/KIE state for later tiers |
| 4 media file | `classify_media_file` | 727 | `(cat, media_type, sub)` | extension + stem keywords + EXIF GPS/datetime |
| 4.5 screenshot OCR/CLIP | `_classify_screenshot_ocr` | 1412 | tuple | `classify_by_ocr` keyword-ratio ≥ `_SCREENSHOT_OCR_KEYWORD_THRESHOLD` (0.10), then CLIP fallback |
| 5 photo composition | `_classify_photo_composition` | 1501 | tuple | single CLIP pass → people / home-interior flags |
| 6 text + KIE | `_classify_by_content_and_kie` | 1545 | tuple (terminal) | `classify_with_kie` (field conf ≥0.5) else `classify_content` keyword argmax; images then `_cross_check_with_clip` |

Support: `_has_human_name_signal` moved to
`src/classifiers/entity_detector.py:39`. Keyword/category scoring lives in
`ContentClassifier` (`src/classifiers/content_classifier.py`) — note
`score_all_categories` (L285) already returns `{category: confidence}` for all
keyword categories; `classify_content` (L302) argmaxes it. Non-English OCR text
short-circuits to `uncategorized` (L328).

### 2.2 Entry points & pipeline wiring

- `scripts/file_organizer_content_based.py` — `ContentBasedFileOrganizer(ContentOrganizer)`
  (L128) adds only pipeline concerns (schema generation, graph persistence,
  renaming, moves) and delegates them to `src/pipeline`.
- `src/pipeline/file_processor.py:481` — the single call site of
  `detect_file_category` in the production flow.
- `src/cli.py` — `cmd_content` (L45) builds a typed `ContentInputs.from_namespace(args)`
  and calls the script's `run()` (L338); argparse defined in `add_content_arguments`
  (L259). The old `_args_to_argv` argv re-serialization is **gone** (replaced by the
  `ContentInputs` dataclass), so Phase 0 plumbs `--scorer` through
  `ContentInputs`/`add_content_arguments`, not an argv string.
- The v1 "script vs mirror" split no longer exists; `src` is the single source
  of truth. The scorer lands in `src/scoring/` and is wired into
  `ContentOrganizer` directly.

### 2.3 Proto-unified scoring already in production

The image path already contains a two-signal weighted scorer
(`content_organizer.py:907-1044`):

- `_run_clip_signal` (L967) — 20-prompt CLIP pass → `(candidate, score)`,
  gated on `CLIP_ENHANCE_THRESHOLD`, cached per file.
- `_merge_clip_text_scores` (L907) — per-`(cat, sub)` weighted sum: CLIP score
  as-is; OCR text contributes `_TEXT_SIGNAL_PRIOR (0.80) × min(1, chars/200)`;
  `+_SIGNAL_AGREEMENT_BOOST (0.15)` when both agree; argmax wins.
- Consumed by `enhance_weak_image_classification` (L1006, "Point A/B/C"
  enhancement hooks) and `_cross_check_with_clip` (L938).

This validates the aggregation design on real traffic but only fires for
images at specific chain positions. The unified scorer generalizes exactly this
mechanism: `_TEXT_SIGNAL_PRIOR` ≙ `W_TEXT`, the agreement boost ≙ multi-evidence
aggregation, the Point A/B/C hooks dissolve (all signals always compete).

### 2.4 Supporting infrastructure

| File | Role |
|---|---|
| `shared/filename_classifier.py` (1,644 lines) | single-homed filename rule set; `_detect_research_publisher` (L68) side-channels provenance via `last_file_state` |
| `shared/clip_classification.py` | `CLIPResult` NamedTuple, `classify_with_ocr_fallback` — the model for a Signal's output shape |
| `shared/clip_utils.py` / `shared/clip_cache.py` | CLIP singleton + embedding cache (`.cache/clip_embeddings_v2/`) |
| `shared/ocr_classifier.py` | `extract_ocr_with_confidence` (text/conf/lang), `classify_by_ocr` → `(category, confidence, scores, text)` |
| `shared/ocr_easyocr.py` | easyocr screenshot-text backend (CPU-only on Apple Silicon) |
| `shared/confidence_gate.py` | `ConfidenceGateResult` + `check_confidence` — reusable gating primitive |
| `shared/kie_utils.py` | `extract_kie_fields`; result currently stashed in `_last_file_state["kie_result"]` by tier 3.5 for tier 6 |
| `shared/constants.py` | `CLIP_CATEGORY_PROMPTS`, `CLIP_LABEL_TO_ORGANIZER`, `CLIP_ENHANCE_THRESHOLD` |
| `src/organizers/category_config.py` | `CONTENT_CATEGORY_PATHS` — destination taxonomy |
| `src/storage/models.py:96-102` | `file_categories` join table already carries `confidence` (L101); `File.ocr_confidence` at L183 |

---

## 3. Target Architecture

*(Substantively unchanged from v1 — this is the strategic core.)*

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

### 3.2 Core interfaces (Python 3.12+ dataclasses + Protocols)

```python
# src/scoring/types.py
class Signal(Protocol):
    name: str
    weight: float                       # prior, from weights module
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
- Runs signals in **cost-tier waves**: cheap → mid → heavy. Heavy signals
  (CLIP, KIE, OCR-driven) are skipped if the cheap/mid aggregate already
  exceeds `EARLY_EXIT_CONFIDENCE` (default 0.95 *aggregated*, not per-signal —
  preserves multi-evidence wins).
- **Aggregation:** `score(cat,sub) = Σ over signals (signal.weight × s.confidence)`
  for matching `(cat,sub)`. Same-signal duplicate entries deduped by max.
  (Generalizes the shipped `_merge_clip_text_scores` — its agreement boost is
  subsumed by summation across signals.)
- **Tie-breaking** (deterministic):
  1. Higher aggregated score.
  2. More distinct contributing signals (multi-evidence wins).
  3. Higher `cost_tier` priority among contributors (heavy > mid > cheap —
     heavy signals are content-aware).
  4. Stable signal-name order from registry.
- **Confidence thresholds:**
  - `MIN_DECISION_CONFIDENCE` (e.g. 0.35 aggregated) — below this returns
    `("uncategorized","other")`.
  - `MIN_DECISION_MARGIN` (e.g. 0.10) over runner-up — required to commit;
    otherwise route to `review/` (new low-confidence bucket) and log.
- **Chain behaviors that must emerge from calibration, not special cases**
  (goldens in §8 enforce each):
  - Legal-vs-person veto → `LegalContentSignal` outscores `PersonalDocSignal`
    on court documents (the hard veto at `content_organizer.py:709` is
    replaced by competition).
  - `_ocr_document_override` (bloodwork/"blood" collision) → high-confidence
    `TextContentSignal` outscores keyword-only `GameAssetSignal`.
  - Non-English OCR → `TextContentSignal.applies_to` returns False when
    `ctx.ocr_language not in (None, "en")`.

### 3.4 Microservice-friendliness

- Each Signal is a pure function over `FileContext`. No I/O outside its
  constructor's injected clients (CLIP model, OCR backend). Allows future
  relocation to RPC services without API change.
- Signals registered via list in `src/scoring/registry.py` — adding/removing is
  one line, no orchestrator edits.

---

## 4. Per-Signal Mapping

Weights are **priors** (relative magnitude matters, not the sum). All weight
constants live in `src/scoring/weights.py` — no magic numbers. Where the chain
already ships a tuned constant, the prior inherits it (noted below). Line
references: `src/organizers/content_organizer.py` unless stated.

| # | Legacy source | New Signal | Output vocabulary | Prior | Cost | Notes / edge cases |
|---|---|---|---|---|---|---|
| 1 | inline tier 0a (L1141) | `RenamedScreenshotSignal` | `media/photos_screenshots_*` | `W_RENAMED = 1.2` | cheap | only when `display_path != file_path`; very high precision |
| 2 | `classify_by_filename_patterns` → `shared/filename_classifier.py:87` | `FilenamePatternSignal` | full vocabulary + `skip/duplicate` | `W_FILENAME = 1.1` | cheap | wraps the whole 1,644-line rule module as ONE signal in v2 (decomposition is OQ #5); research-publisher provenance moves from `last_file_state` side-channel into `evidence` |
| 3 | `ContentClassifier.classify_with_kie` (`content_classifier.py:241`) | `KieStructuredSignal` | `financial/invoices` (+vendor) | `W_KIE = 1.1` | heavy | field conf ≥ 0.5 retained inside the signal |
| 4 | `_classify_identification_document` (L1311) | `IdentityDocumentSignal` | `personal/identification` + people | `W_ID = 1.0` | heavy | MRZ regex high-precision; OCR conf ≥ 0.3 gate retained; emits people for graph edges |
| 5 | `classify_by_organization` (L583) | `OrganizationKeywordSignal` | `organization/{government,healthcare,financial,educational,nonprofit,employers,vendors,clients}` | `W_ORG = 1.0` | mid | needs ≥2 indicators + extractable org name; brand-as-person collisions resolved by competition with #6 |
| 6 | `classify_by_person` (L658) | `PersonalDocSignal` | `personal/{contacts,employment,events,journal,other}` + people | `W_PERSON = 0.9` | mid | Option C: filing subcat via `_PERSON_SUBCAT_TO_PERSONAL_SUBCAT`; people_names → graph edges regardless of winner; graduated confidence (gated 0.9 / ungated-name-present 0.4) replaces the binary `_has_human_name_signal` gate |
| 7 | `_LEGAL_DOCUMENT_SIGNALS` (L163) + `ContentClassifier` legal patterns | `LegalContentSignal` | `legal/{contracts,real_estate,corporate,other}`, `personal/legal` | `W_LEGAL = 0.85` | mid | replaces the hard person-tier veto; SSRN false-positives ("agreement") suppressed by #2 research rules + co-occurrence with org/person evidence |
| 8 | `classify_game_asset` (L522) | `GameAssetSignal` | `game_assets/{sprites,textures,music,audio,fonts}`, `fonts/*` | `W_GAME = 0.8` | cheap | regex-numbered sprites → high conf; bare keyword → lower conf so document OCR can outscore (subsumes `_ocr_document_override`) |
| 9 | `ContentClassifier.score_all_categories`/`classify_content` (L285/302) | `TextContentSignal` | full keyword vocabulary | `W_TEXT = 0.8` (= shipped `_TEXT_SIGNAL_PRIOR`) | heavy | confidence scaled by extraction length (`min(1, chars/200)`, as shipped); skips non-English OCR; also emits company/people entities |
| 10 | `_classify_screenshot_ocr` step 1 / `classify_by_ocr` | `ScreenshotOcrSignal` | `media/photos_screenshots_*` + cross-category reclass | `W_UI = 0.75` | mid | keyword-ratio threshold 0.10 retained (calibrated to hits/len(keywords) scale — do not raise without eval) |
| 11 | `_run_clip_signal` (L967) | `ClipVisionSignal` | `CLIP_LABEL_TO_ORGANIZER` vocabulary | `W_CLIP = 0.7` | heavy | embedding cache reused; GPS→travel upgrade from `_map_clip_label` kept; `CLIP_ENHANCE_THRESHOLD` becomes a soft floor |
| 12 | `classify_media_file` (L727) | `MediaHeuristicSignal` | `media/{videos,audio,photos}_*` | `W_MEDIA = 0.65` | cheap | EXIF GPS/datetime aware; PNG ambiguity falls to other signals instead of returning None |
| 13 | `_classify_photo_composition` (L1501) | `PhotoCompositionSignal` | `media/photos_social`, `property_management/other` | `W_PEOPLE_PHOTO = 0.65` | heavy | single CLIP pass yields both flags; stock-photo people in marketing remain the known weakness |
| 14 | `classify_by_filepath` (L429) | `FilepathSignal` | path-mapped categories (+project name) | `W_PATH = 0.6` | cheap | brittle on `~/Downloads`; `.zip` named "Photos" now loses to content signals by weight |
| 15 | MIME/extension fallback | `MimeFallbackSignal` | broad category by `schema_type`/ext | `W_MIME = 0.3` | cheap | always fires; deliberately too weak to override anything |

**Format-drift fix:** every signal contributes to a shared `(cat, sub)` score,
so a PDF and a PNG of the same content both accumulate
`TextContentSignal + OrganizationKeywordSignal` weight regardless of which
extension-keyed signal would have fired first. `MimeFallbackSignal` (0.3)
cannot override.

**Entity side-channel:** signals 4, 6, and 9 emit `company_name`/`people_names`
in `evidence`; the decision assembler merges them (org precedence rules as
today in `classify_content`) so graph attribution is unchanged.

---

## 5. Data Contracts

### 5.1 `FileContext` (built once, passed to all signals)

Replaces the per-file instance state on `ContentOrganizer`
(`_last_file_ocr_text/_confidence/_detected_language`,
`_last_file_state["kie_result"]`, `_clip_enhance_cache` — reset at L1113).
Lazy fields are computed by memoizing `ensure_*()` methods so signals declare
what they need; nothing observes mutation order.

| Field | Type | Source | Populated |
|---|---|---|---|
| `path` | `Path` | input | always |
| `display_path` | `Path \| None` | renamer dry-run flow (`FileProcessor._maybe_rename_image`) | when renamed |
| `mime_type` | `str \| None` | `enricher.detect_mime_type` | always |
| `schema_type` | `Literal["ImageObject","DigitalDocument","VideoObject","AudioObject"]` | derived (as L1119-1135) | always |
| `extracted_text` | `str \| None` | `TextExtractor` via `ensure_text()` | lazy |
| `text_length` | `int` | derived | with text |
| `ocr_text` / `ocr_confidence` / `ocr_language` | via `extract_ocr_with_confidence` | `ensure_ocr()` | images, lazy |
| `clip_scores` | `dict[str, float]` | `ensure_clip()` (cache-backed) | images, lazy |
| `image_metadata` | `dict` | `ImageMetadataParser` | images, lazy |
| `kie_result` | `KIEResult \| None` | `extract_kie_fields` when `ocr_confidence ≥ 0.3` | `ensure_kie()` |

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
    winning_signals: list[str]
    all_scores: list[CategoryScore]  # for telemetry
    company_name: str | None         # → Organization/{Name} + graph edge
    people_names: list[str]          # → GraphStore.add_file_to_person edges (Option C)
```

Adapter: `detect_file_category`'s 7-tuple return is preserved under both
scorers (the unified path derives it from `ClassificationDecision`), so
`FileProcessor.organize_file` (`file_processor.py:416`, call site L481) is untouched in
Phases 0–4.

### 5.4 DB columns (reuse + one addition)

`src/storage/models.py:96-102` — `file_categories` already has `confidence` (L101).
Add **one nullable column** `signal_evidence JSON` to persist `all_scores` for
backtesting. No alembic in this repo: ship a migration in the established
pattern (`src/storage/migration.py`, surfaced as an `organize-files migrate-*`
subcommand). Downstream readers unaffected (nullable, additive).

---

## 6. Migration Strategy

### Phase 0 — Plumbing (1 PR)
1. Create `src/scoring/` package skeleton (types, weights, context, scorer,
   registry, signals/).
2. Add `--scorer {legacy,unified,shadow}` to `organize-files content`
   (`src/cli.py` `add_content_arguments` L259 + the `ContentInputs` dataclass —
   note `_args_to_argv` no longer exists; args flow via `ContentInputs.from_namespace`
   → the script's `run()` L338); plumb into `ContentBasedFileOrganizer.__init__`
   → `ContentOrganizer`.
3. Wire `Scorer.classify()` inside `ContentOrganizer.detect_file_category`
   behind the flag. Default `legacy`.

### Phase 1 — Signal extraction (one PR per signal, ~15 PRs)
For each row in §4, extract the legacy method into a Signal class under
`src/scoring/signals/`. The legacy method stays and delegates to the Signal
(so the legacy chain still works bit-for-bit). Unit tests land with each PR.
Suggested order: cheap/pure first (2, 8, 12, 14, 15, 1), then mid (5, 6, 7,
10), then heavy (9, 11, 13, 4, 3).

### Phase 2 — Shadow mode (1–2 weeks of dogfood)
- `--scorer=shadow` runs **both** scorers per file. Legacy controls placement.
  Unified decision + per-signal scores logged to
  `results/scoring_shadow.jsonl` and persisted with `source='shadow_unified'`.
- Diff report generator: `scripts/analyze_scoring_disagreement.py` — counts
  disagreements by category pair, surfaces top regressions.

### Phase 3 — Calibration
- Replay stored runs from `results/file_organization.db` (exists; ~748 KB as of
  2026-07-15). Labeled ground truth: `results/ml_data_labeled_*` refreshed via
  `scripts/relabel_test_set.py`. Grid-search weights to minimize disagreement
  on known-correct cases.
- Surface as `organize-files evaluate --classifier unified` alongside the
  existing `{baseline,content}` options (OQ #6), plus a standalone
  `scripts/backtest_scoring.py` for weight-sensitivity reports.
- Update `src/scoring/weights.py` constants. No code change.

### Phase 4 — Flip default
- Default flips to `unified`. `legacy` flag retained for one release; add
  deprecation warning to the legacy path. Update CLAUDE.md §"Classification
  Priority" → §"Unified Scoring".

### Phase 5 — Removal (future)
- Delete the tier orchestration in `detect_file_category` (L1137-1310); the
  `classify_*` methods become thin shims over their Signals (kept while
  `tests/unit/test_content_organizer.py` exercises them directly).
- ~~Decide fate of the `content_organizer.py` mirror~~ — resolved by the
  2026-07 refactor; nothing to do.

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

Persisted to `results/scoring_telemetry.jsonl` (rotated daily) and the new
`file_categories.signal_evidence` column. OCR confidence/language continue to
persist via the existing `File.ocr_confidence`/`detected_language` columns.

### 7.2 Backtest harness
- `scripts/backtest_scoring.py` reads `results/file_organization.db`, replays
  `FileContext` from stored `extracted_text` + `mime_type` (CLIP scores served
  from `.cache/clip_embeddings_v2/`).
- Outputs accuracy delta vs labeled set, per-category confusion matrix,
  weight-sensitivity report (`∂accuracy/∂weight`).
- Calibration target: ≥98% agreement with legacy on **currently-correct** cases
  (sample audited manually), ≥80% fix rate on the residual audit-failure set
  (§1 items still marked *present*).

### 7.3 Dashboards
- Reuse `_site/` dashboard. Add panel "Signal contribution distribution"
  (per-signal % of wins) — surfaces dead signals (zero contribution =
  candidate for removal).

---

## 8. Testing Strategy

### 8.1 Unit tests — `tests/unit/scoring/`
- One file per signal; each test builds a synthetic `FileContext` with only the
  fields the signal reads (no disk I/O, no CLIP model). ≥90% line coverage per
  signal module.
- The existing `tests/unit/test_content_organizer.py` suite stays green
  untouched — it pins legacy-chain behavior (including the threshold
  calibrations documented in code comments) throughout Phases 0–4.

### 8.2 Scorer aggregation tests — `tests/unit/scoring/test_scorer.py`
- Empty inputs, single signal, conflicting signals, tie-break orderings,
  early-exit threshold, low-confidence rejection, margin routing.

### 8.3 Golden integration tests — `tests/integration/test_unified_scoring_golden.py`
~30 labeled fixtures under `tests/fixtures/scoring/` covering:

| Fixture group | Count | Targets |
|---|---|---|
| Org-named PDFs ("Morning Train" etc.) | 5 | person/org confusion |
| Same content PDF + PNG pairs | 4 | format drift |
| Academic PDFs **without** publisher-prefix filenames | 3 | content-only research detection (prefix case fixed at tier 0b — include 1 prefixed control) |
| Court notices with clerk contact blocks | 2 | legal-outscores-personal (replaces hard veto) |
| Document images with game-keyword collisions ("bloodwork") | 2 | text-outscores-game (replaces `_ocr_document_override`) |
| Misnamed archives (`Photos.zip`) | 3 | MIME/filepath over-trigger |
| Renamed game assets | 3 | naming-pattern brittleness |
| Screenshots (dashboard/terminal/browser) | 4 | OCR/CLIP routing at 0.10 keyword threshold |
| Resumes/CVs | 2 | `personal/contacts` + people edges (Option C) |
| Invoices (KIE) | 3 | structured extraction |
| Generic media | 3 | media routing |

Harness asserts **chosen category**, **minimum margin** (detects "right
answer, fragile reasons"), and for person-bearing fixtures the emitted
`people_names` (graph-edge parity).

### 8.4 Shadow-mode regression test
CI job replays `results/scoring_shadow.jsonl` from main nightly, fails on >2%
new disagreements.

---

## 9. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | **Latency regression** — running all signals vs early exit | High | Medium | Cost-tier waves + `EARLY_EXIT_CONFIDENCE`; benchmark in CI (target ≤1.2× legacy median); CLIP/OCR/KIE caches unchanged; `FileContext` memoization means no extraction runs twice |
| 2 | **Weight-tuning brittleness** — ~15 hand-picked priors yield fragile decisions | High | High | Grid-search calibration in Phase 3; commit weights with backtest report; treat `weights.py` as versioned data |
| 3 | **Regression on currently-correct cases** | Medium | High | Shadow mode + ≥98% legacy-agreement gate before flip; rollback flag retained ≥1 release |
| 4 | **Schema.org export coupling** — exporter consumes category strings; new `review/` bucket may leak | Medium | Medium | Add `review` to the Schema.org mapping or filter `confidence < MIN_DECISION_CONFIDENCE` at export (config flag). Exports are streaming Core-query now — change the `build_*_jsonld` builders in `models.py`, not `to_schema_org()` |
| 5 | **DB schema impact** — `signal_evidence` column | Low | Medium | Nullable, additive; hand-rolled migration per repo convention; dashboard reads via `getattr` |
| 6 | **Signal-explosion debugging** — explaining a decision with 8 contributors | Medium | Medium | Always log `all_scores`; CLI `organize-files explain <file>` reruns + pretty-prints evidence |
| 7 | **Person-signal recall** — graduated confidence may under- or over-fire vs today's binary `_has_human_name_signal` gate | Medium | Medium | Gated 0.9 / ungated 0.4 split; Option C limits blast radius (worst case is filing subcat, graph edges still attach); person fixtures in §8.3 |
| 8 | **Hidden-state parity** — legacy tiers communicate via `_last_file_*` mutation order (tier 3.5 feeds tier 6's KIE); `FileContext` must reproduce exactly | Medium | High | Shadow mode diffs catch drift; `ensure_kie()` encodes the OCR-conf ≥ 0.3 dependency explicitly; unit tests pin the gating |
| 9 | **Stdout parity** — tier prints are load-bearing for tests/UX (`✓ Screenshot OCR sub-class: …`) | Low | Low | Legacy prints untouched under `--scorer=legacy`; unified path emits structured log lines; parity not promised across scorers |

---

## 10. File-level Change List

### New files
| Path | Purpose |
|---|---|
| `src/scoring/__init__.py` | Package marker, named exports |
| `src/scoring/types.py` | `Signal` Protocol, `CategoryScore`, `ClassificationDecision` |
| `src/scoring/weights.py` | All weight + threshold constants (single source of truth) |
| `src/scoring/context.py` | `FileContext` with lazy `ensure_*` memoization |
| `src/scoring/scorer.py` | `Scorer` orchestrator: cost-tier waves + aggregator |
| `src/scoring/registry.py` | Ordered list of registered Signals |
| `src/scoring/signals/renamed_screenshot.py` | ← inline tier 0a |
| `src/scoring/signals/filename_pattern.py` | ← wraps `shared/filename_classifier` |
| `src/scoring/signals/kie_structured.py` | ← `ContentClassifier.classify_with_kie` |
| `src/scoring/signals/identity_document.py` | ← `_classify_identification_document` (incl. MRZ parser) |
| `src/scoring/signals/organization.py` | ← `classify_by_organization` |
| `src/scoring/signals/personal_doc.py` | ← `classify_by_person` + graduated name gate |
| `src/scoring/signals/legal_content.py` | ← `_LEGAL_DOCUMENT_SIGNALS` + legal keyword patterns |
| `src/scoring/signals/game_asset.py` | ← `classify_game_asset` |
| `src/scoring/signals/text_content.py` | ← `score_all_categories`/`classify_content` |
| `src/scoring/signals/screenshot_ocr.py` | ← `_classify_screenshot_ocr` / `classify_by_ocr` |
| `src/scoring/signals/clip_vision.py` | ← `_run_clip_signal` + `_map_clip_label` |
| `src/scoring/signals/media_heuristic.py` | ← `classify_media_file` |
| `src/scoring/signals/photo_composition.py` | ← `_classify_photo_composition` |
| `src/scoring/signals/filepath.py` | ← `classify_by_filepath` |
| `src/scoring/signals/mime_fallback.py` | Extension/MIME default |
| `tests/unit/scoring/test_*.py` | Per-signal + scorer unit tests |
| `tests/integration/test_unified_scoring_golden.py` | ~30-fixture integration test |
| `tests/fixtures/scoring/*` | Labeled fixtures (scrubbed via `scripts/redact_pii.py` before commit) + manifest YAML |
| `scripts/backtest_scoring.py` | DB-driven weight backtest CLI |
| `scripts/analyze_scoring_disagreement.py` | Shadow-mode diff reporter |
| `src/storage/` migration script | Add `file_categories.signal_evidence JSON` (repo migration pattern) |

### Modified files
| Path | Rationale |
|---|---|
| `src/organizers/content_organizer.py` | `--scorer` switch inside `detect_file_category`; each `classify_*` method delegates to its Signal during transition; `_last_file_*` state superseded by `FileContext` in the unified path |
| `src/cli.py` | Register `--scorer` on the `content` subcommand; extend `evaluate --classifier` |
| `scripts/file_organizer_content_based.py` | argparse passthrough for `--scorer` |
| `src/classifiers/content_classifier.py` | Expose subcategory-aware scoring for `TextContentSignal` (today only `classify_content` resolves subcats) |
| `src/pipeline/file_processor.py` | Persist `signal_evidence` + shadow-mode source tag |
| `src/storage/models.py` | Nullable `signal_evidence` column on `file_categories` |
| `CLAUDE.md` | Replace §"Classification Priority" with §"Unified Scoring" once default flips |
| `docs/SCHEMA_ORG_ARCHITECTURE.md` | Document `review` category (if OQ #1 resolves to add it) |

---

## 11. Open Questions

1. **Low-confidence bucket placement** — should files with
   `confidence < MIN_DECISION_CONFIDENCE` route to a new `~/Documents/Review/`
   folder, stay in source location, or use today's `uncategorized/other`?
   Affects Schema.org export semantics (see Risk 4).
2. ~~**`src/organizers/content_organizer.py` fate**~~ — **Resolved 2026-07**:
   the thin-wrapper refactor made `src` the single source of truth; the scorer
   integrates there and no mirror exists.
3. **Weight calibration source of truth** — hand-tuned priors checked into
   `weights.py`, or generated artifact committed alongside? Recommend committed
   priors + backtest report in
   `docs/architecture/scoring-calibration-YYYYMMDD.md` per re-tune.
4. **Early-exit aggressiveness** — should `EARLY_EXIT_CONFIDENCE` (skip heavy
   signals) be tunable per cost budget (CI vs interactive), or a global
   constant?
5. **`FilenamePatternSignal` decomposition** — v2 wraps the 1,644-line rule
   module as one signal (matching how the code is actually structured). Split
   into per-domain signals (legal, financial, research, entity, …) later so
   their weights calibrate independently, or keep monolithic while precision
   stays high?
6. **Backtest surface** — standalone `scripts/backtest_scoring.py` only, or
   also `organize-files evaluate --classifier unified` so the existing eval
   harness (and its labeled test sets) exercises the scorer?
7. **KIE as Signal vs preprocessor** — KIE both extracts structured fields
   *and* classifies; today tier 3.5 stashes the result for tier 6. Standalone
   `KieStructuredSignal` (weight 1.1) keeps evidence transparent — recommended —
   with `FileContext.ensure_kie()` serving both it and any future enrichment
   consumers.
