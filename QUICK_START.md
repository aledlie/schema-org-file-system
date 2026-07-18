# Quick Start

AI-powered file organization using CLIP vision, OCR, Schema.org metadata, and entity detection.

## 1. Setup (first time)

```bash
# Python 3.12 or 3.13 (3.14 broken on macOS 26 — see CLAUDE.md Troubleshooting)
python3.13 -m venv venv && source venv/bin/activate
pip install -e ".[all]"
brew install tesseract poppler
```

Verify the install:

```bash
organize-files health        # should report 9/9 features
```

## 2. Daily use

Activate the venv first in every new shell:

```bash
source venv/bin/activate
```

### Organize files (AI content pipeline)

Always preview with `--dry-run` before moving anything:

```bash
# Preview: classify 100 Downloads files, move nothing
organize-files content --source ~/Downloads --dry-run --limit 100

# Apply: actually move the files
organize-files content --source ~/Downloads --limit 100

# Multiple sources, custom target
organize-files content --source ~/Desktop ~/Downloads --target ~/Documents

# Save a JSON report of what was done
organize-files content --source ~/Downloads --limit 500 --report results/run_report.json

# Sensitive sources: OCR text is stored verbatim in files.extracted_text.
# Use --no-db for health, genomics, or any source with personal data
# (VINs, medical records, genomic reports) to skip all DB writes.
organize-files content --source ~/Downloads --dry-run --no-db --no-sentry --no-cost-tracking
```

Defaults: sources `~/Desktop ~/Downloads`, target `~/Documents`, database `results/file_organization.db`.

The content pipeline uses the **unified** weighted-signal scorer by default. Pass `--scorer legacy` for the original 10-tier priority chain, or `--scorer shadow` to compare them without changing placement (see below).

### Shadow test (compare unified scorer vs legacy chain)

`--scorer shadow` runs both engines: the legacy 10-tier chain controls placement while the
unified weighted scorer's decision is logged to `results/scoring_shadow.jsonl` for
disagreement analysis. Placement is unaffected, so pair it with `--dry-run`.

```bash
# Reset the log, run a shadow pass (dry-run — nothing moves), then report disagreements
: > results/scoring_shadow.jsonl
organize-files content --source ~/Downloads --dry-run --limit 40 --scorer shadow
python scripts/analyze_scoring_disagreement.py \
    --log results/scoring_shadow.jsonl \
    --json results/scoring_disagreement.json \
    --top 15
```

The report prints the legacy↔unified agreement rate, unified decision-state counts
(committed / low_confidence / low_margin), and the top (legacy → unified) disagreement
pairs with example paths.

### Organize files (no AI)

```bash
# Filename/path pattern rules only — fast, no model loading
organize-files name --source ~/Downloads --target ~/Documents --dry-run --limit 50

# Extension-based only (simplest)
organize-files type --source ~/Desktop --dry-run
```

## 3. Where files go

```
~/Documents/
├── Organization/{CompanyName}/   # detected vendor/partner documents
├── Personal/{Contacts,Employment,Events,Legal,...}/
├── Financial/{Invoices,Statements,Tax,Other}/
├── Legal/{Contracts,RealEstate,...}/
├── Research/Papers/{SSRN,arXiv,...}/
├── Technical/  Media/  GameAssets/  Creative/
└── Person/{Name}/                # derived symlink view — never file here directly
```

## 4. Person graph maintenance

All commands are dry-run by default; add `--apply` to execute.

```bash
organize-files migrate-person                  # move legacy Person/ files → Personal/{subcat}/
organize-files migrate-person --apply          # (supports --rollback via manifest)
organize-files index-people --apply            # attach person→file graph edges, no moves
organize-files person-view --apply             # regenerate Person/{Name}/ symlink view
organize-files person-view --apply --prune-missing  # also drop dead-path edges + stale view dirs
organize-files prune-person "Bad Name" --apply # delete false-positive people (backs up DB)
```

Typical hygiene pass: `prune-person` the false positives first, then
`person-view --apply` to regenerate the symlink view without them.

## 5. APIs and dashboard

```bash
# REST API (Schema.org JSON-LD over the graph)
uvicorn src.api.schema_org_api:app --reload
# then: curl http://localhost:8000/health
#       curl http://localhost:8000/api/schema-org/export

# Dashboard / visualization data
organize-files update-site     # refresh _site dashboard data
organize-files timeline        # generate timeline_data.json
```

The timeline groups by `organization_sessions`, which only a **live (non-dry-run)
content pass** records. Populate it before regenerating:

```bash
# Records an organization_sessions row + files.session_id; then rebuild the timeline
organize-files content --source ~/Downloads          # NOT --dry-run
organize-files timeline
```

`organize-files type` and `organize-files name` are DB-free by design and never
record sessions, so their runs do not appear on the timeline.

## 6. ML workflow

```bash
organize-files preprocess --input results/run_report.json --output results/training_data
organize-files evaluate --test-data results/test_set.json --classifier baseline
organize-files evaluate --test-data results/test_set.json --classifier content
```

## 7. Development checks

```bash
pytest tests/unit/                                          # ~1,070 unit tests
pytest tests/integration/                                   # schema.org export pipeline
pytest tests/performance/ --benchmark-only -m "not slow"    # benchmarks
black src/ scripts/ && flake8 src/ scripts/ && mypy src/ scripts/

# Profile the classification hot path (OCR-bound): wall, grouped hotspots,
# OCR-invocation + gate-skip counts. Use for before/after of scoring changes.
PYTHONPATH=src:scripts:. python scripts/profile_pipeline.py --source ~/Documents/Media/Photos --limit 50
PYTHONPATH=src:scripts:. python scripts/profile_pipeline.py --source DIR --ocr-clip-topk 3   # gate on
# Evaluate the CLIP OCR gate on a folder-labeled corpus (recall vs OCR-skip):
PYTHONPATH=src:scripts:. python scripts/eval_ocr_gate.py
```

## Tips

- **Sensitive/private sources:** OCR text and extracted metadata are stored verbatim in `results/file_organization.db` (`files.extracted_text`, `files.schema_data`). Pass `--no-db` to skip all DB writes when running on health records, genomics reports (SNPedia, Promethease), documents containing VINs, or any source with personal data. Alternatively, run `scripts/redact_pii.py` on files first to redact PII before organizing.
- Start every real run with `--dry-run --limit N` and read the classification output before applying.
- `organize-files <command> --help` shows all flags for a subcommand.
- Scripts in `scripts/` must run from the project root so `from shared.x import y` resolves; the `organize-files` CLI handles this automatically.
- See `CLAUDE.md` for the full classification priority order, gotchas, and troubleshooting.
