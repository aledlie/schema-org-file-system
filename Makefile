# Scoring calibration harness (docs/architecture/scoring-calibration-20260726.md).
# Uses the project venv; run `python3.14 -m venv venv && pip install -e ".[all]"` first.

PYTHON := venv/bin/python
PYTHONPATH := src:scripts:.
RESULTS := results

.PHONY: calibrate clip-backfill backtest weight-grid threshold-sweeps weight-search golden

## Full calibration pass: backfill CLIP scores, replay + sensitivity,
## directional weight grid, threshold sweeps, golden-corpus gate.
calibrate: clip-backfill backtest weight-grid threshold-sweeps golden

## Backfill files.image_classification + the CLIP embedding cache for any
## image rows not yet scored (idempotent; --force via FLAGS=--force).
clip-backfill:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/backfill_clip_scores.py --apply $(FLAGS)

## DB replay with undirected ±20% weight sensitivity.
backtest:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/backtest_scoring.py \
		--weights-sensitivity --output $(RESULTS)/backtest_report.json

## Directional weight grid (fix/break/neutral vs stored decisions).
weight-grid:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/weight_grid_search.py \
		--output $(RESULTS)/weight_grid.json

## MIN_DECISION_CONFIDENCE and MIN_DECISION_MARGIN sweeps.
threshold-sweeps:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/weight_grid_search.py \
		--sweep-confidence --output $(RESULTS)/threshold_confidence.json
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/weight_grid_search.py \
		--sweep-margin --output $(RESULTS)/threshold_margin.json

## Joint weight + threshold search (nevergrad). Deliberately NOT part of
## `calibrate`: it is exploratory and budget-priced, where `calibrate` is the
## reproducible gate. Reports a proposal only — it never writes weights.py.
## BUDGET=250 make weight-search
BUDGET ?= 150
weight-search:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/weight_search.py \
		--budget $(BUDGET) --output $(RESULTS)/weight_search.json

## Golden corpus — the correctness gate any weight change must hold.
golden:
	$(PYTHON) -m pytest tests/integration/test_unified_scoring_golden.py -q
