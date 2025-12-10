# Schema.org File Organization System

Intelligent file organization using AI vision, OCR, and Schema.org metadata.

## Quick Start

```bash
source venv/bin/activate

# Organize files (content-based with AI)
python3 file_organizer_content_based.py --base-path ~/Documents --sources ~/Documents/Media --limit 1000

# Simple type-based organization
python3 file_organizer_by_type.py --dry-run --base-path ~/Documents --source ~/Documents/Uncategorized

# Rename images using EXIF metadata
python3 image_renamer_metadata.py --dry-run --source ~/Documents/Media --recursive
```

## Current State

- **Files processed:** 30,133 (98.6% success)
- **Top category:** GameAssets 25,554 (84.8%)
- **Database:** `results/file_organization.db`

## Project Structure

```
├── file_organizer_content_based.py  # AI organizer (CLIP, OCR, cost tracking)
├── file_organizer_by_type.py        # Simple type-based organizer
├── image_renamer_metadata.py        # EXIF-based image renamer
├── src/
│   ├── base.py, generators.py       # Schema.org classes
│   ├── cost_roi_calculator.py       # Cost & ROI tracking
│   └── storage/                     # SQLAlchemy graph store & KV store
├── _site/                           # Dashboard UI
│   ├── index.html                   # Main dashboard
│   ├── metadata_viewer.html (30KB)  # File browser (async loads metadata.json)
│   └── cost_report.json             # Live stats
├── results/                         # Reports & database
└── tests/                           # Test suites
```

## Key Features

### Classification Priority
1. **Priority 0:** Game assets (audio, music, sprites, textures)
2. **Priority 1:** Filepath patterns
3. **Priority 2:** AI vision (CLIP model)
4. **Priority 3:** OCR text extraction

### Categories
GameAssets, Media, Technical, Legal, Financial, Business, Personal, Medical, Creative, Property_Management

### Cost Tracking
```python
from src.cost_integration import track_cost

@track_cost('clip_vision')
def analyze_image(path):
    # CLIP: $0.0001/image, Tesseract: $0.00001/image
    ...
```

### Storage
```python
from src.storage import GraphStore, KeyValueStorage

graph = GraphStore('results/file_organization.db')
file = graph.add_file('/path/to/file.jpg', 'file.jpg', file_size=1024)
graph.add_file_category(file.id, 'Creative/Photos')
```

## Dependencies

```bash
# Full install
pip install -r requirements.txt
brew install tesseract poppler

# Check all dependencies
python3 file_organizer_content_based.py --check-deps
```

See [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) for detailed guide.

**Core:** Pillow, pillow-heif, pytesseract, geopy, SQLAlchemy
**AI/ML:** torch, transformers, opencv-python
**Docs:** python-docx, pypdf, openpyxl

## Error Tracking (Sentry)

```bash
# Run with Sentry via Doppler
./scripts/run_with_sentry.sh --dry-run --limit 100

# Or set DSN manually
export SENTRY_DSN=$(doppler secrets get FILE_SYSTEM_SENTRY_DSN --project integrity-studio --config prd --plain)
python3 file_organizer_content_based.py --dry-run
```

**Doppler:** `integrity-studio` project, key: `FILE_SYSTEM_SENTRY_DSN`

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Check all deps | `python3 file_organizer_content_based.py --check-deps` |
| HEIC files fail | `pip install pillow-heif` |
| Tesseract missing | `brew install tesseract` |
| AI vision disabled | `pip install torch transformers` |
| Sentry not working | Check `FILE_SYSTEM_SENTRY_DSN` in Doppler |
| Geocoding rate limit | Process in chunks, 1 req/sec |

## Recent Changes (2025-12-10)

- Added Sentry error tracking with Doppler integration
- Added `--check-deps` flag for system health check
- Created requirements.txt with all 40+ packages documented
- Created docs/DEPENDENCIES.md installation guide
- Added src/health_check.py and src/error_tracking.py modules
- Refactored metadata_viewer.html: 24MB → 30KB
- Added graph-based SQL storage & cost tracking

---
**Python:** 3.14 | **Version:** 1.2.0 | **Updated:** 2025-12-10
