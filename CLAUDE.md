# Schema.org File Organization System

AI-powered file organization using CLIP vision, OCR, and Schema.org metadata.

## Quick Start

```bash
source venv/bin/activate

# With Sentry error tracking (recommended)
./scripts/run_with_sentry.sh --dry-run --limit 100 --sources ~/Downloads

# Direct usage
python3 file_organizer_content_based.py --base-path ~/Documents --sources ~/Documents/Media --limit 1000

# Check dependencies
python3 file_organizer_content_based.py --check-deps
```

## Status

| Metric | Value |
|--------|-------|
| Files processed | 30,133 |
| Success rate | 98.6% |
| Top category | GameAssets (84.8%) |
| Database | `results/file_organization.db` |

## Project Structure

```
├── file_organizer_content_based.py  # Main AI organizer
├── scripts/run_with_sentry.sh       # Run with error tracking
├── src/
│   ├── health_check.py              # Dependency validation
│   ├── error_tracking.py            # Sentry integration
│   ├── cost_roi_calculator.py       # Cost tracking
│   └── storage/                     # SQLAlchemy graph store
├── _site/                           # Dashboard UI
├── results/                         # Reports & database
└── docs/DEPENDENCIES.md             # Install guide
```

## Configuration

### Doppler Secrets

| Project | Key | Description |
|---------|-----|-------------|
| `integrity-studio` | `FILE_SYSTEM_SENTRY_DSN` | Sentry error tracking DSN |

### Environment Variables

| Variable | Priority | Description |
|----------|----------|-------------|
| `--sentry-dsn` | 1 | CLI argument |
| `FILE_SYSTEM_SENTRY_DSN` | 2 | Doppler/env |
| `SENTRY_DSN` | 3 | Fallback |

## Dependencies

```bash
pip install -r requirements.txt && brew install tesseract poppler
```

**Core:** Pillow, pillow-heif, pytesseract, geopy, SQLAlchemy, sentry-sdk
**AI/ML:** torch, transformers, opencv-python

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Check deps | `--check-deps` |
| HEIC fails | `pip install pillow-heif` |
| No OCR | `brew install tesseract` |
| No AI | `pip install torch transformers` |
| No Sentry | Check `FILE_SYSTEM_SENTRY_DSN` in Doppler |

---
**Python:** 3.14 | **Version:** 1.2.0 | **Updated:** 2025-12-10
