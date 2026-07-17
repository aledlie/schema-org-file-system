# Unified scoring — weight calibration report (2026-07-17, PROVISIONAL)

**Status:** PROVISIONAL — do **not** adopt the recommended weights yet.
**Scope:** BACKLOG "Unified scoring — Phase-3 calibration worklist" **item #6**
(grid-search calibration proper; plan §6 Phase 3 / Open Question #3).
**Blocking caveat:** this worktree contains calibration items **#1–#3** but
**not #4/#5** (insurance-vocabulary gap, legacy naming traps), which are being
built in parallel. Any weights tuned now are calibrated against a stale scorer.
This document is a **methodology + baseline + sensitivity report only**; it
changes **no** code in `src/scoring/weights.py`. The final re-tune happens
post-merge and is owned by the orchestrator.

---

## 1. Methodology (rerun loop)

The calibration loop the worklist prescribes has three measurement surfaces.
All commands run from the worktree root with the project venv
(`/Users/alyshialedlie/schema-org-file-system/venv/bin/python`).

1. **Labeled evaluation** — accuracy of each classifier against a labeled set:
   ```
   python -m src.cli evaluate --classifier baseline --test-data <labels.json> --output <out.json>
   python -m src.cli evaluate --classifier content  --test-data <labels.json> --output <out.json>
   python -m src.cli evaluate --classifier unified   --test-data <labels.json> --output <out.json>
   ```
   - `baseline` = filename-heuristic model (`FileCategorizationModel`), no I/O.
   - `content` = production CLIP+OCR organizer; **requires the test files on
     disk** (`ContentClassifierModel` returns a SKIP sentinel for missing
     files, which are excluded from metrics).
   - `unified` = the real 15-signal registry + `Scorer`, replayed from each
     record's fields (`UnifiedScorerModel` in `scripts/evaluate_model.py`), no
     disk access. Records without extracted text classify from filename-driven
     signals alone.

2. **DB replay + sensitivity** — replay stored `File` rows through the scorer:
   ```
   python scripts/backtest_scoring.py --labels <labels.json>
   python scripts/backtest_scoring.py --weights-sensitivity --limit 200
   ```
   `--weights-sensitivity` reruns the replay with each `weights.py` prior scaled
   ±20% (`WEIGHT_DELTA_FRACTION`) and reports per-weight decision-flip counts
   (`∂decisions/∂weight`). This is the **intended production probe**.

3. **Shadow dogfood** — real-corpus agreement vs legacy:
   ```
   organize-files content --scorer shadow --dry-run
   python scripts/analyze_scoring_disagreement.py
   ```

### Data reality on this checkout (verified 2026-07-17)

| Surface | State | Consequence |
|---|---|---|
| `results/file_organization.db` | **absent** (no file) | `backtest_scoring.py` exits `EXIT_NO_DATA` — **the DB-replay and `--weights-sensitivity` paths yield nothing**. Verified: `--weights-sensitivity --limit 200` prints "database not found …" and stops. |
| `results/training_data_desktop/test.json` | 5 records, 5-class ML labels (`business/financial/legal/personal/uncategorized`) | Usable for `baseline`/`unified` (no disk), but the label taxonomy is **incompatible** with the scorer's fine-grained taxonomy — see §2. |
| `results/test_set_augmentation/test_entries.json` | 14 records, `medical/*`, mostly text-less redacted PNGs | Usable for `unified` but measures **filename-only** behavior (no OCR wired in the replay adapter). |
| test files on disk | `test.json` filepaths point at `~/temp_downloads_reorg/*` (**gone**); `test_entries.json` filepaths resolve under `results/test_set_augmentation/redacted/` (**present**) | `content` classifier skips all 5 of `test.json`; the committed `eval_content.json` already carries a `content` run over the medical set. |

Because the DB replay is empty and `test.json`'s labels are taxonomy-mismatched,
the **golden corpus** (`tests/integration/test_unified_scoring_golden.py`,
28 fixtures) is used as the labeled probe for the sensitivity analysis, exactly
as the worklist permits ("using the golden corpus … as the labeled probe if
test.json accuracy for 'unified' is not measurable").

---

## 2. Baseline accuracy table

### 2.1 `results/training_data_desktop/test.json` (5 records)

| Classifier | Category accuracy | Subcat accuracy | Evaluated | Notes |
|---|---|---|---|---|
| baseline | **20.0%** (1/5) | 40.0% | 5/5 | filename heuristic |
| content  | **n/a** | n/a | 0/5 | **all 5 skipped** — files not on disk |
| unified  | **0.0%** (0/5) | 0.0% | 5/5 | see caveat below |

**This table does not measure scorer quality.** The `test.json` labels come
from a 5-class ML training taxonomy that does not map onto the scorer's
categories, and several labels are themselves noisy. Per-record detail:

| filename | test.json label | unified prediction | comment |
|---|---|---|---|
| `Oct 25 Zouk social at the Mansion.docx` | `uncategorized` | `zouk/events` | scorer answer is arguably *better* than the label |
| `Oct 17 Zouk Social at Rhythm House.docx` | `legal` | `zouk/events` | label is wrong; `zouk` is outside the label space |
| `Leora Intro … Notes by Gemini.docx` | `legal` | `organization/healthcare` | label is wrong |
| `Board Report_Nov 2025.pdf` | `personal` | `uncategorized/other` | low-confidence fallback |
| `Sync … Notes by Gemini.docx` | `financial` | `uncategorized/other` | low-confidence fallback |

The `zouk`/`organization` predictions are categories the label set (`{business,
financial, legal, personal, uncategorized}`) cannot even represent, so every
sensible fine-grained decision is scored "wrong". **Conclusion: `test.json` is
not a valid accuracy oracle for the unified scorer.**

### 2.2 `results/test_set_augmentation/test_entries.json` (medical, 13–14 records)

| Classifier | Category accuracy | Source |
|---|---|---|
| content | **23.1%** (3/13) | committed `eval_content.json` (2026-07-01, real CLIP+OCR on the redacted PNGs) |
| unified | **28.6%** (4/14) | this run (`--classifier unified`), filename-only (records carry no extracted text) |

Both are low because (a) `medical` is a sparsely-covered leaf in the taxonomy
and (b) the redacted PNGs carry **no extracted text**, so the unified replay has
only filename + MIME signals to work with — it is measuring degraded
filename-only behavior, not weight calibration. Not a calibration signal.

### 2.3 Golden corpus — the measurable proxy

`tests/integration/test_unified_scoring_golden.py`, run through the real
registry + `Scorer` (synthetic OCR/CLIP/KIE providers, no models):

| Metric | Value |
|---|---|
| Golden fixtures | **28** (24 `GOLDEN_CASES` + 4 `SCREENSHOT_CASES`) |
| Correct at shipped weights | **28/28 (100%)** |

This is the only corpus on this checkout where the unified scorer is at a known,
100%-correct baseline, so it is the basis for the sensitivity analysis below.

### 2.4 Real-corpus shadow agreement (reported, not re-measured)

The worklist records a `~/Downloads` shadow run (49 files): **43/49 (87.8%)**
legacy agreement after items #1+#2 (item #3 was threshold-only, 0 numeric
change). This could not be re-measured here — the source files are not in the
worktree — and is cited from the backlog for context only.

---

## 3. Weight-sensitivity analysis

**Procedure.** For each of the 15 `W_*` priors, the golden corpus was
re-classified with that one signal's weight scaled by ±20%
(`WEIGHT_DELTA_FRACTION`), holding all other weights at their shipped values.
A **flip** is a fixture whose `(category, subcategory)` differs from the
shipped-weight baseline; a **break** is a currently-correct fixture that becomes
wrong. This mirrors `backtest_scoring.weight_sensitivity`, substituting the
golden corpus for the (empty) DB replay. (Probe script kept out of the repo;
it reuses `build_default_signals` with instance-level `signal.weight`
overrides — `weights.py` untouched — exactly as `build_replay_scorer` does.)

### 3.1 Per-weight flip counts (±20%)

| Prior | Signal | Shipped | −20% flips | +20% flips | breaks |
|---|---|---|---|---|---|
| W_RENAMED | renamed_screenshot | 1.20 | 0 | 0 | 0 |
| W_FILENAME | filename_pattern | 1.10 | 0 | 0 | 0 |
| W_KIE | kie_structured | 1.10 | 0 | 0 | 0 |
| W_ID | identity_document | 1.00 | 0 | 0 | 0 |
| **W_ORG** | **organization_keyword** | **1.00** | **2** | 0 | **2** |
| **W_PERSON** | **personal_doc** | **0.90** | 0 | **2** | **2** |
| W_LEGAL | legal_content | 0.85 | 0 | 0 | 0 |
| W_GAME | game_asset | 0.80 | 0 | 0 | 0 |
| W_TEXT | text_content | 0.80 | 0 | 0 | 0 |
| W_UI | screenshot_ocr | 0.75 | 0 | 0 | 0 |
| W_CLIP | clip_vision | 0.70 | 0 | 0 | 0 |
| W_MEDIA | media_heuristic | 0.65 | 0 | 0 | 0 |
| W_PEOPLE_PHOTO | photo_composition | 0.65 | 0 | 0 | 0 |
| W_PATH | filepath | 0.60 | 0 | 0 | 0 |
| W_MIME | mime_fallback | 0.40 | 0 | 0 | 0 |

### 3.2 Load-bearing vs inert (on this corpus)

**Load-bearing: only `W_ORG` and `W_PERSON`.** Both sit on the
organization-vs-personal/legal boundary — the exact confusion the Group-1 and
Group-4 fixtures were built to pin.

- **`W_ORG` (1.00) has downward headroom to ≈0.90.** Sweep: first break at
  factor 0.90 (`W_ORG≈0.90`), second at 0.86. The breaking fixtures are
  `org_government_notice` and `org_employer_offer_letter` — as the org prior
  drops, `organization/*` loses its lead over a cross-category rival and the
  files route to `uncategorized/other` via the **low-margin** gate (not a
  wrong commit — a fallback).
- **`W_PERSON` (0.90) has upward headroom to ≈1.03.** Sweep: no flip through
  factor 1.15 (`W_PERSON≈1.035`); first flip at ≈1.06. Above that,
  `legal_court_notice_clerk_contacts` and `legal_court_motion_clerk_contacts`
  flip `legal/litigation → personal/contacts` (a **committed** wrong answer —
  the clerk/plaintiff contact block makes `personal_doc` overtake
  `legal_content`). This directly regresses the "legal-outscores-personal"
  emergent behavior that replaced the hard person-tier veto (§3.3).

**The ordering `W_ORG (1.0) > W_PERSON (0.9) > W_LEGAL (0.85)` is the invariant
that matters**, not the absolute magnitudes. `W_LEGAL` must stay high enough
that court notices beat `personal_doc`; `W_ORG` must stay above `W_PERSON` so
org-named documents file as `organization/*`.

**Inert on this corpus (0 flips at ±20%): the other 13 priors.** Their golden
fixtures win by margins wider than a ±20% perturbation, because a
higher-priority signal (filename/KIE/renamed) dominates or the content margin is
large. **This is a corpus-coverage statement, not a global one.** In
particular:

- **`W_MIME` reads inert here but is not inert in production.** The golden
  corpus contains no mime-only-at-margin fixture; `W_MIME`'s commit-gap
  behavior (item #1) is locked separately by
  `tests/unit/scoring/test_mime_commit_gap.py`, and the invariant
  `W_MIME < MIN_DECISION_CONFIDENCE + MIN_DECISION_MARGIN (0.45)` must be
  preserved by any re-tune.
- `W_CLIP`, `W_UI`, `W_PEOPLE_PHOTO`, `W_MEDIA` are under-probed: the golden
  corpus has few fixtures where these decide at the margin. The empty DB is why
  their real sensitivity is unmeasured here.

---

## 4. Provisional recommended weights

**Recommendation: keep the shipped weights unchanged for now.** There is no
measurable evidence on this checkout that supports moving any prior — the golden
corpus is already at 28/28, the DB replay is empty, and `test.json` is not a
valid oracle. Changing weights against a scorer that lacks items #4/#5 would be
tuning to a moving target.

| Prior | Shipped | Provisional | Rationale |
|---|---|---|---|
| W_RENAMED | 1.20 | 1.20 | inert; top-priority renamer signal, no evidence to move |
| W_FILENAME | 1.10 | 1.10 | inert |
| W_KIE | 1.10 | 1.10 | inert |
| W_ID | 1.00 | 1.00 | inert |
| W_ORG | 1.00 | 1.00 | load-bearing; keep — must stay > W_PERSON (org-named docs) and has only ≈0.10 downward slack before Group-1 fixtures fall to fallback |
| W_PERSON | 0.90 | 0.90 | load-bearing; keep — raising it past ≈1.03 regresses legal-outscores-personal (court notices flip to personal/contacts) |
| W_LEGAL | 0.85 | 0.85 | keep — the floor that keeps court notices above personal_doc |
| W_GAME | 0.80 | 0.80 | inert |
| W_TEXT | 0.80 | 0.80 | inert |
| W_UI | 0.75 | 0.75 | under-probed; keep |
| W_CLIP | 0.70 | 0.70 | under-probed; keep |
| W_MEDIA | 0.65 | 0.65 | under-probed; keep |
| W_PEOPLE_PHOTO | 0.65 | 0.65 | under-probed; keep |
| W_PATH | 0.60 | 0.60 | inert |
| W_MIME | 0.40 | 0.40 | keep — bounded by item-#1 invariant, not by this corpus |

> **PENDING #4/#5 MERGE — re-run before adopting.** After items #4 (insurance
> vocabulary) and #5 (legacy naming traps) merge, re-run §1's evaluate +
> backtest surfaces against a **populated** `results/file_organization.db` and a
> taxonomy-aligned labeled set, then repeat the §3 sensitivity sweep. Only then
> should any prior move off its shipped value.

### 4.1 Guidance for the post-merge grid search

- **Focus the search grid on `W_ORG` and `W_PERSON`** (and the `W_LEGAL` floor).
  These are the only priors that flip decisions at the boundary on the current
  corpus; the other 13 are either dominated or under-probed and should be held
  fixed until a real corpus exercises them.
- **Populate the DB first.** The sensitivity harness of record
  (`backtest_scoring.py --weights-sensitivity`) needs stored `File` rows; it is
  the `∂decisions/∂weight` measurement the plan §7.2 specifies. The golden
  corpus is a stopgap, not a substitute.
- **Build a taxonomy-aligned labeled set.** `test.json`'s 5-class labels cannot
  score the fine-grained scorer; a valid oracle must label at the
  `(category, subcategory)` granularity the scorer emits.

### 4.2 Phase-4 flip gate (unchanged — restated for the re-tune)

Before the default scorer flips from `legacy` to `unified` (plan §6 Phase 4,
BACKLOG item #6), a candidate weight set must clear:

- **≥98% agreement** with legacy on **currently-correct** cases (manually
  audited sample), and
- **≥80% fix rate** on the §1 residual audit-failure set (the plan §1 items
  still marked *present* — content-only academic-PDF detection, the naming
  traps of item #5, and the insurance-vocabulary gap of item #4).

Neither gate is evaluable on this checkout (empty DB, no aligned labels, items
#4/#5 absent). The re-tune must measure both post-merge.

---

## 5. Reproduction

```
# 1. Labeled evaluation (baseline + unified are disk-free; content needs files)
python -m src.cli evaluate --classifier baseline --test-data results/training_data_desktop/test.json --output /tmp/eval_baseline.json
python -m src.cli evaluate --classifier unified   --test-data results/training_data_desktop/test.json --output /tmp/eval_unified.json
python -m src.cli evaluate --classifier content    --test-data results/training_data_desktop/test.json --output /tmp/eval_content.json  # all skipped here

# 2. DB replay + sensitivity (empty DB on this checkout → EXIT_NO_DATA)
python scripts/backtest_scoring.py --weights-sensitivity --limit 200

# 3. Golden-corpus baseline (the measurable proxy)
python -m pytest tests/integration/test_unified_scoring_golden.py -q
```

The §3 sensitivity numbers were produced with an out-of-tree probe that reuses
`build_default_signals` + per-signal `signal.weight` overrides over the golden
`ALL_CASES` (same instance-level override mechanism as
`backtest_scoring.build_replay_scorer`; `src/scoring/weights.py` is never
mutated).
