# Unified scoring — weight calibration report (2026-07-26, FINAL)

**Status:** FINAL — this is the non-provisional re-tune the 2026-07-17
provisional report ([`scoring-calibration-20260717.md`](scoring-calibration-20260717.md))
deferred. **Decision: the shipped weights are adopted unchanged.** Every
blocker the provisional report listed is now cleared:

| Provisional blocker | State 2026-07-26 |
|---|---|
| Items #4/#5 not merged (stale scorer) | Merged 2026-07-17 (`274fc0e`, `c862cde`) |
| `results/file_organization.db` absent | Populated: 484 File rows, 356 replayable with stored decisions |
| Legacy chain coexisting | Removed (Phase 5, `2702210`) — unified is the only engine |
| Golden corpus 28 fixtures | Grown to **43** fixtures, 43/43 at shipped weights |

## 1. Measurement surfaces

All runs on this checkout (`main` @ Phase-5 removal), venv Python 3.14.

1. **DB replay baseline** — `scripts/backtest_scoring.py` over all 484 rows:
   356 replayed with stored decisions, agreement **152/356 (42.7%)** overall,
   **84/131 (64.1%)** on the non-media slice. The overall number is dominated
   by a replay-fidelity artifact, not weight quality: stored media decisions
   (interiors/exteriors/graphics/chatgpt) were made with live CLIP + scene-probe
   votes and include manual corrections, while the replay serves CLIP only from
   the embedding cache (scene voted on just 2 rows). The top disagreement rows
   (`media/interiors_other → media/photos_chatgpt` ×66, etc.) are all this
   artifact. The **non-media slice is the meaningful oracle**.
2. **Undirected sensitivity** — `backtest_scoring.py --weights-sensitivity`
   (±20%, all 19 priors): flips concentrate in `W_FILENAME` (−20%: 132),
   `W_MIME` (−20%: 41 / +20%: 101), `W_MEDIA` (+20%: 37), `W_TEXT` (−20%: 30),
   `W_UI` (+20%: 12), `W_ORG` (+20%: 8). Ten priors show 0 flips in both
   directions.
3. **Directional grid** — `scripts/weight_grid_search.py` (new, permanent
   harness): every prior at ×{0.8, 0.9, 1.1, 1.2}, one at a time (76 replay
   runs), each flip classified **fix** (now matches stored) / **break** (no
   longer matches) / **neutral** (both wrong).
4. **Golden corpus** — `tests/integration/test_unified_scoring_golden.py`:
   **43/43 at shipped weights** (the correctness gate any candidate must hold).

## 2. Directional grid results

Baseline: 152/356 overall, 84/131 non-media. Every candidate that changed
anything (sorted by overall delta):

| Candidate | Weight | ΔAgree | ΔNonMedia | fix | break | neutral |
|---|---|---|---|---|---|---|
| W_MIME ×1.2 | 0.48 | **+5** | **−1** | 9 | 4 | 88 |
| W_MIME ×1.1 | 0.44 | +1 | −1 | 2 | 1 | 3 |
| W_TEXT ×0.8 | 0.64 | 0 | −3 | 3 | 3 | 9 |
| W_EVENT ×0.8/0.9, W_MEDIA ×1.1, W_ORG ×0.8, W_PERSON ×0.8/1.2 | — | 0 | 0 | 0 | 0 | 1 each |
| W_ID ×0.8/0.9 | 0.80/0.90 | −1 | −1 | 0 | 1 | 1 |
| W_PATH ×0.8/0.9 | 0.48/0.54 | −1 | −1 | 0 | 1 | 0 |
| W_TEXT ×1.1/1.2 | 0.88/0.96 | −1 | −1 | 0 | 1 | 1–3 |
| W_ORG ×1.1/1.2 | 1.10/1.20 | −3 | −3 | 0 | 3 | 2–3 |
| W_TEXT ×0.9 | 0.72 | −3 | −3 | 0 | 3 | 4 |
| W_MIME ×0.8 | 0.32 | −8 | 0 | 0 | 8 | 28 |
| W_FILENAME ×0.9 | 0.99 | −29 | −32 | 6 | 35 | 88 |
| W_FILENAME ×0.8 | 0.88 | −32 | −34 | 6 | 38 | 88 |
| W_MEDIA ×1.2 | 0.78 | −32 | −32 | 0 | 32 | 5 |

All other candidates (the majority): zero flips.

## 3. Analysis — why no weight moves

- **The only positive-delta candidate, `W_MIME ×1.2` (0.48), is rejected on
  three grounds:** (a) it violates the hard commit-gap invariant
  `W_MIME < MIN_DECISION_CONFIDENCE + MIN_DECISION_MARGIN = 0.45` (locked by
  `tests/unit/scoring/test_mime_commit_gap.py`, calibration item #1) — a
  mime-only vote must never commit alone; (b) its +5 overall comes entirely
  from the media artifact slice while the trustworthy non-media slice *drops*
  (−1); (c) 88 neutral flips = mass churn between wrong answers. `W_MIME ×1.1`
  (0.44) squeaks under the invariant but shows the same profile in miniature
  (+1 overall, −1 non-media). Keep **0.40**.
- **`W_FILENAME` down is catastrophic** (−32 non-media at ×0.8, break:fix
  38:6): filename_pattern wins 246/356 replayed rows and its dominance is
  overwhelmingly correct. Its 1.10 prior is confirmed load-bearing from above —
  do not lower.
- **`W_MEDIA` up is the same cliff from the other side** (+20% → 32 breaks,
  0 fixes): at 0.78 the media heuristic starts overtaking filename/text
  decisions it should lose. 0.65 is comfortably below the cliff.
- **`W_ORG` up breaks 3 / fixes 0** — consistent with the provisional finding
  that `W_ORG` (1.00) sits directly on the organization-vs-personal/legal
  boundary with no upward headroom. The invariant
  `W_ORG (1.0) > W_PERSON (0.9) > W_LEGAL (0.85)` holds and still matters.
- **`W_TEXT` is pinned from both sides** (0.72 → 3 breaks; 0.88 → 1 break;
  0.64 → 3:3 wash with −3 non-media). 0.80 is a genuine local optimum.
- **`W_PERSON`, `W_LEGAL`, `W_SCENE`, `W_GAME`, `W_CLIP`, `W_UI`†,
  `W_RENAMED`, `W_KIE`, `W_ARCHIVE`, `W_GRAPHIC`, `W_PEOPLE_PHOTO`**: zero
  directional signal at ±20% — dominated or wide-margin on this corpus.
  († `W_UI` +20% showed 12 undirected flips in surface 2's 500-row config but
  no fix/break signal in the directional grid — churn, not direction.)

**Conclusion: `src/scoring/weights.py` is unchanged.** The shipped priors are
at a local optimum under the only available oracles (stored production
decisions, non-media slice, golden corpus). This closes the final open item of
`UNIFIED_SCORING_PLAN.md` — the plan is fully complete.

## 3.1 Decision-threshold sweeps (addendum, same day)

`weight_grid_search.py` gained `--sweep-confidence` / `--sweep-margin`
(threshold overrides threaded through `build_replay_scorer`; weights shipped).

- **`MIN_DECISION_CONFIDENCE` {0.30, 0.32, 0.38, 0.40}: zero flips at every
  candidate.** Root cause: all 16 low_confidence fallback rows have aggregate
  confidence **0.000** — no signal fired at all (text-less, cache-miss images).
  No threshold value can rescue a row with no votes; the confidence gate is
  not a live lever on this corpus.
- **`MIN_DECISION_MARGIN` {0.04, 0.06, 0.08, 0.12}: the live gate.** Every
  scored fallback row is margin-gated (conf 0.40–0.92, margins 0.00–0.076
  vs the 0.10 gate). Results: 0.12 → −3 (3 breaks); 0.08 → no change;
  **0.06 and 0.04 → +2 (2 fixes, 0 breaks, 2 neutral)**. The fixes are two
  dashboard screenshots correctly scored `media/graphics_other` that the gate
  had pushed to `uncategorized/other`; the neutral flips land on rows whose
  *stored* labels are themselves wrong (e.g. the Texas license-back photo
  stored as `game_assets/sprites`).
- **Decision: keep `MIN_DECISION_MARGIN = 0.10`.** The evidence for 0.06 is
  +2/0 on a 4-row flip set — directionally positive but too small to move a
  safety gate whose purpose is refusing ambiguous ties. Revisit when the DB
  oracle grows (the invariant `W_MIME < MIN_DECISION_CONFIDENCE +
  MIN_DECISION_MARGIN` would still hold at 0.06: 0.40 < 0.41 — no slack, a
  further reason to hold at 0.10).

## 4. Caveats & when to re-run

- The stored-decision oracle is biased: it contains manual corrections and
  pre-unified placements. It measures "does the replay reproduce production",
  not absolute truth. The golden corpus carries the absolute-truth burden.
- The media slice is unmeasurable until the replay can serve scene-probe and
  live CLIP votes (embedding cache coverage). `W_SCENE`'s own backtest
  (2026-07-18: −20% flips 4 / +20% flips 0) remains the reference for that
  prior.
- Re-run after: (a) the scene-probe corpus retrain lands, (b) any new signal
  registers, or (c) the DB grows past ~1k replayable rows. Command:

```bash
PYTHONPATH=src:scripts:. python scripts/backtest_scoring.py --weights-sensitivity
PYTHONPATH=src:scripts:. python scripts/weight_grid_search.py --output results/weight_grid.json
python -m pytest tests/integration/test_unified_scoring_golden.py -q
```
