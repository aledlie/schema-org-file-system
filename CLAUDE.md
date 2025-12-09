# CLAUDE.md - Schema.org File Organization System

## Project Overview

This project provides an intelligent file organization system using Schema.org structured data, AI-powered content analysis, and metadata extraction to automatically categorize and organize files.

## Key Components

### 1. Content-Based File Organizer (`file_organizer_content_based.py`)

**Purpose:** Advanced file organization using OCR, AI vision, and metadata analysis.

**Features:**
- **AI Vision Classification** - CLIP model for image content detection (home interiors, etc.)
- **OCR Text Extraction** - Tesseract for extracting text from screenshots and documents
- **EXIF Metadata Parsing** - Datetime, GPS location, camera info
- **Game Asset Detection** - Specialized categorization for game files (Priority 0)
- **Filepath-based Classification** - Intelligent project name extraction
- **Schema.org Metadata** - Generates structured data for all files
- **Cost Tracking** - Per-feature cost and ROI calculation (NEW!)

**Categories:**
- Legal (contracts, real estate, corporate)
- Financial (tax, invoices, statements)
- Business (planning, marketing, clients)
- Personal (employment, identification, certificates)
- Medical (records, insurance, prescriptions)
- Technical (documentation, architecture, code)
- Creative (design, branding, photos)
- **GameAssets** (audio, music, sprites, textures) ← New!
- Property_Management (home interior photos without people)

**Usage:**
```bash
source venv/bin/activate
python3 file_organizer_content_based.py --base-path ~/Documents --sources ~/Documents/Media --limit 1000

# With cost tracking (default enabled)
python3 file_organizer_content_based.py --base-path ~/Documents --sources ~/Documents/Media --cost-report

# Disable cost tracking
python3 file_organizer_content_based.py --base-path ~/Documents --sources ~/Documents/Media --no-cost-tracking
```

### 2. Type-Based File Organizer (`file_organizer_by_type.py`)

**Purpose:** Simple file organization based on extensions and naming patterns.

**Features:**
- File extension mapping to categories
- Screenshot detection (startswith 'screenshot')
- Game asset detection (keywords: frame, item, leg, arm, head, etc.)
- Fast processing for large file sets

**Usage:**
```bash
python3 file_organizer_by_type.py --dry-run --base-path ~/Documents --source ~/Documents/Uncategorized
```

### 3. Image Metadata Renamer (`image_renamer_metadata.py`)

**Purpose:** Rename generic camera filenames to human-readable names using EXIF metadata.

**Features:**
- Detects generic patterns: IMG_*, PXL_*, DSC_*, timestamps, hashes
- Extracts EXIF datetime and GPS location
- Geocoding for location names (via Nominatim)
- OCR for screenshot text extraction
- Format: `YYYYMMDD_Location_HHMMSS.jpg`
- Dry-run mode for safe testing

**Usage:**
```bash
python3 image_renamer_metadata.py --dry-run --source ~/Documents/Media --recursive
```

### 4. Schema.org Base Classes (`src/base.py`)

**Purpose:** Base classes for Schema.org structured data generation.

**Classes:**
- `SchemaOrgBase` - Abstract base class with property validation
- `SchemaContext` - Context management
- `PropertyType` - Enum for type validation

**Methods:**
- `set_property()` - Set properties with type validation
- `add_nested_schema()` - Add nested Schema.org objects
- `add_person()`, `add_organization()`, `add_place()` - Helper methods
- `to_json_ld()` - Export as JSON-LD
- `validate_required_properties()` - Validation

### 5. Cost & ROI Calculator (`src/cost_roi_calculator.py`) - NEW

**Purpose:** Calculate per-feature and per-model costs with ROI metrics.

**Features:**
- **Per-Feature Cost Tracking** - Track costs for CLIP, Tesseract, face detection, geocoding
- **ROI Calculation** - Estimate value based on manual time saved
- **Usage Records** - Detailed logging of each operation
- **Cost Summaries** - Aggregate costs by feature

**Tracked Features:**
| Feature | Cost/Unit | Avg Time | Success Rate |
|---------|-----------|----------|--------------|
| CLIP Vision | $0.0001 | 2.5s | 95% |
| Tesseract OCR | $0.00001 | 1.5s | 90% |
| Face Detection | $0.000005 | 0.5s | 85% |
| Nominatim Geocoding | $0 (free) | 1.0s | 75% |
| Keyword Classifier | $0 | 0.001s | 98% |

**Usage:**
```python
from src.cost_roi_calculator import CostROICalculator, CostTracker

calculator = CostROICalculator()

# Track a feature
with CostTracker(calculator, 'clip_vision', files_processed=1):
    result = analyze_image(image)

# Get cost summary
summary = calculator.get_cost_summary('clip_vision')
print(f"Total cost: ${summary.total_cost:.4f}")

# Get ROI metrics
roi = calculator.get_roi_metrics('clip_vision')
print(f"ROI: {roi.roi_percentage:.1f}%")
```

### 6. Cost Integration (`src/cost_integration.py`) - NEW

**Purpose:** Easy integration of cost tracking into existing code.

**Features:**
- **Decorator Support** - `@track_cost('feature_name')` decorator
- **Context Manager** - `with track_feature('feature_name'):` syntax
- **Global Calculator** - Singleton pattern for easy access
- **File Size Tracking** - Automatically track input file sizes

**Usage:**
```python
from src.cost_integration import track_cost, track_feature, get_calculator

# Decorator
@track_cost('tesseract_ocr')
def extract_text(image_path):
    return pytesseract.image_to_string(Image.open(image_path))

# Context manager
with track_feature('clip_vision', file_path=image_path):
    classification = model.predict(image)

# Get reports
calculator = get_calculator()
calculator.print_summary()
```

### 7. Graph-Based Storage (`src/storage/`) - NEW

**Purpose:** Graph-based SQL storage and key-value store for file metadata.

**Components:**

#### GraphStore (`src/storage/graph_store.py`)
High-level interface for graph-based file storage with relationship traversal.

**Features:**
- File CRUD operations with deduplication (SHA-256 hash IDs)
- Category management with hierarchy
- Many-to-many relationships (files ↔ categories, companies, people, locations)
- File relationship tracking (duplicate, similar, version, derived)
- Statistics and aggregations
- SQLite with WAL mode and optimized pragmas

**Models (`src/storage/models.py`):**
- `File` - Central node with metadata, EXIF, Schema.org data
- `Category` - Hierarchical categories with parent/child relationships
- `Company` - Extracted company entities
- `Person` - Extracted person entities
- `Location` - GPS and location data
- `OrganizationSession` - Track organization runs
- `FileRelationship` - Edges between files (duplicate, similar, etc.)
- `CostRecord` - Cost tracking data
- `SchemaMetadata` - Schema.org JSON-LD storage

#### KeyValueStorage (`src/storage/kv_store.py`)
Redis-like key-value storage using SQLite.

**Features:**
- Namespace isolation (cache, config, metadata, stats, session, feature)
- TTL support for automatic expiration
- JSON value serialization
- Atomic increment/decrement operations
- Pattern-based key scanning

**Namespaces:**
- `cache` - Temporary cached data
- `config` - Configuration values
- `metadata` - File metadata overflow
- `stats` - Statistics and counters
- `session` - Session-specific data
- `feature` - Feature flags

**Usage:**
```python
from src.storage import GraphStore, KeyValueStorage

# Graph store
graph = GraphStore('results/file_organization.db')
file = graph.add_file('/path/to/file.jpg', 'file.jpg', file_size=1024)
graph.add_file_category(file.id, 'Creative/Photos')

# Key-value store
kv = KeyValueStorage('results/file_organization.db')
kv.set('last_run', datetime.now().isoformat(), namespace='session')
kv.increment('files_processed', namespace='stats')
```

#### JSONMigrator (`src/storage/migration.py`)
Migrate existing JSON result files to the database.

**Supported Files:**
- Organization reports (`content_organization_report_*.json`)
- Cost reports (`cost_report_*.json`, `cost_roi_report.json`)
- Model evaluation reports (`model_evaluation.json`)

**Usage:**
```python
from src.storage import JSONMigrator

migrator = JSONMigrator('results/file_organization.db', 'results')
stats = migrator.migrate_all(verbose=True)
print(f"Migrated {stats['files_migrated']} files")
```

## Current State (2025-12-09)

### Files Organized
- **Total processed:** 30,133 files
- **Success rate:** 98.6% (0 errors)
- **Already organized:** 430 files

### Category Breakdown
- GameAssets: 25,554 files (84.8%)
  - Sprites: 16,453 files
  - Textures: 8,883 files
  - Audio: 218 files
- Uncategorized: 2,727 files (9.0%)
- Media: 1,570 files (5.2%)
- Property_Management: 243 files (0.8%)
- Financial: 7 files
- Technical: 6 files

### Recent Enhancements

**Dashboard UI Optimization (2025-12-09):**
- Fixed invalid JSON in `cost_report.json` (replaced `Infinity` values)
- Refactored `metadata_viewer.html` from 24MB to 30KB (-99.9%)
- Extracted 30,133 file records to external `metadata.json`
- Added async data loading with progress spinner
- Implemented error handling with retry button
- Added resource usage panel to main dashboard
- Created comprehensive error handling test suite

**Graph-Based Storage (2025-12-09):**
- SQLAlchemy ORM models for files, categories, companies, people, locations
- Graph-like relationship tracking between files
- Key-value store with namespace isolation and TTL support
- JSON migration tool for existing reports
- Database: `results/file_organization.db`

**Cost & ROI Tracking (2025-12-09):**
- Per-feature cost calculation (CLIP, Tesseract, face detection, geocoding)
- ROI metrics based on manual time saved
- Integrated into file organizer with `--cost-report` and `--no-cost-tracking` flags
- Usage: `CostTracker` context manager or `@track_cost` decorator
- Live stats displayed on main dashboard

**GameAssets Category:**
- Added Priority 0 detection (highest priority)
- 4 subdirectories: Audio, Music, Sprites, Textures
- 200+ keywords for classification
- Successfully categorized 25,554 game files

**Image Renamer:**
- New script: `image_renamer_metadata.py`
- Tested on 12,634 images
- Successfully renamed 115 files with EXIF metadata
- 483 files need HEIC support or have no metadata

## Project Structure

```
schema-org-file-system/
├── file_organizer_content_based.py  # AI-powered organizer (with cost tracking)
├── file_organizer_by_type.py        # Type-based organizer
├── image_renamer_metadata.py        # Image metadata renamer
├── copy_to_site.sh                  # Build script for _site directory
├── src/
│   ├── base.py                      # Schema.org base classes
│   ├── generators.py                # Specialized generators
│   ├── validator.py                 # Validation system
│   ├── integration.py               # Output formats
│   ├── enrichment.py                # Metadata enrichment
│   ├── cost_roi_calculator.py       # Cost & ROI calculation
│   ├── cost_integration.py          # Cost tracking integration
│   └── storage/                     # Graph-based storage
│       ├── __init__.py              # Module exports
│       ├── models.py                # SQLAlchemy ORM models
│       ├── graph_store.py           # Graph-based SQL storage
│       ├── kv_store.py              # Key-value storage
│       └── migration.py             # JSON to DB migration
├── _site/                            # Dashboard & web UI
│   ├── index.html                   # Main dashboard (25KB)
│   ├── metadata_viewer.html         # File browser (30KB, loads external data)
│   ├── metadata.json                # File metadata (24MB, async loaded)
│   ├── organization_report.html     # Organization statistics (28KB)
│   ├── cost_report.json             # Live cost/ROI data (15KB)
│   ├── ml_data_explorer.html        # ML data viewer (85KB)
│   └── correction_interface.html    # Feedback UI (27KB)
├── docs/
│   ├── README.md                    # Full documentation
│   ├── BEST_PRACTICES.md            # Best practices
│   ├── IMPLEMENTATION_SUMMARY.md    # Implementation details
│   └── SESSION_NOTES.md             # Session work log
├── tests/
│   ├── test_generators.py           # Generator tests
│   ├── test_validator.py            # Validator tests
│   └── test_metadata_viewer_errors.js  # UI error handling tests
├── examples/
│   └── example_usage.py
├── results/                          # Organization reports & database
│   ├── content_organization_report_*.json
│   ├── file_organization.db         # SQLite database
│   └── metadata.json                # Copy of file metadata
└── venv/                             # Python virtual environment
```

## Dependencies

**Python Libraries:**
```bash
# Core
pip install Pillow pytesseract piexif geopy

# AI Vision
pip install transformers torch torchvision opencv-python

# Storage & Database (NEW)
pip install sqlalchemy

# HEIC Support (optional)
pip install pillow-heif
```

**System:**
```bash
brew install tesseract  # OCR engine
```

## Key Workflows

### 1. Organize Files (Content-Based)

```bash
source venv/bin/activate

# Dry run (preview)
python3 file_organizer_content_based.py --dry-run --base-path ~/Documents --sources ~/Documents/Media --limit 100

# Actual organization
python3 file_organizer_content_based.py --base-path ~/Documents --sources ~/Documents/Media --limit 1000

# With date-based organization
python3 file_organizer_content_based.py --base-path ~/Documents --sources ~/Documents/Media --organize-by-date

# With location-based organization
python3 file_organizer_content_based.py --base-path ~/Documents --sources ~/Documents/Media --organize-by-location
```

### 2. Rename Images

```bash
# Dry run (safe preview)
python3 image_renamer_metadata.py --dry-run --source ~/Documents/Media

# Actual renaming
python3 image_renamer_metadata.py --source ~/Documents/Media

# Recursive
python3 image_renamer_metadata.py --dry-run --source ~/Documents --recursive
```

### 3. Type-Based Organization

```bash
# Simple organization by file type
python3 file_organizer_by_type.py --dry-run --base-path ~/Documents --source ~/Documents/Uncategorized
```

## Game Asset Classification

### Priority System
1. **Priority 0:** Game assets (checked FIRST)
2. Priority 1: Filepath patterns
3. Priority 2: AI vision content
4. Priority 3: OCR text

### Detection Keywords

**Audio (60+ keywords):**
- Combat: bolt, spell, magic, sword, dagger, arrow, attack, damage
- Spells: lightning, fire, ice, acid, poison, heal, summon, dispel
- Environment: door, chest, coin, pickup, unlock, lock
- Instruments: fiddle, lute, mandoline, glockenspiel

**Music (40+ keywords):**
- Locations: battle, boss, dungeon, castle, forest, town, cave, temple
- Moods: victory, defeat, chaos, hope, despair, triumph, mysterious
- Game-specific: drakalor, altar, dwarven, elven, clockwork

**Sprites (100+ keywords):**
- Body parts: frame, leg, arm, head, torso, wing, tail, face, hand
- Environment: wall, floor, door, window, tree, rock, grass
- Items: sword, shield, armor, potion, scroll, coin, gem
- UI: icon, button, menu, cursor, bar, container

**Textures:**
- Identified by sprite keywords + file characteristics
- UI elements, walls, floors, items

### Code Location

**Game asset detection:** `file_organizer_content_based.py:1004-1053`
**Category paths:** `file_organizer_content_based.py:945-951`
**Keyword lists:** `file_organizer_content_based.py:956-999`

## Image Metadata Renamer

### Generic Filename Patterns Detected
- `IMG_####` - Generic camera
- `PXL_####` - Google Pixel
- `DSC_####` - Digital camera
- `DCIM_####` - Camera folder
- `YYYYMMDD_HHMMSS` - Timestamp only
- Pure numbers: `12345.jpg`
- MD5 hashes
- Generic screenshots

### Naming Strategy

**Photos:**
```
Format: YYYYMMDD_Location_HHMMSS.jpg
Example: 20240425_Austin_123456.jpg
Source: EXIF datetime + GPS geocoding
```

**Screenshots:**
```
Format: Screenshot_Description.png
Example: Screenshot_Employment_Document.png
Source: OCR text extraction
Fallback: Screenshot_YYYYMMDD_HHMMSS.png
```

## Important Notes

### HEIC Files
- Many HEIC files fail to load without `pillow-heif`
- Install: `pip install pillow-heif`
- Affects: ~483 files in test batch

### Rate Limiting
- Geocoding API (Nominatim): 1 request/second
- For large batches, process in chunks

### Performance
- ~500 files per batch (optimal)
- 100% success rate on 1,600 files tested
- AI vision adds ~2-3 seconds per image

### Error Handling
- HEIC images: Skip metadata extraction gracefully
- SVG files: Cannot be processed by PIL
- Missing metadata: Falls back to filename/uncategorized

## Remaining Work

**Recommended next steps:**
1. Review uncategorized files (2,727) for new classification patterns
2. Add HEIC support to image renamer
3. Consider additional game asset subcategories
4. Implement server-side filtering for metadata viewer (if dataset grows)
5. Add automated testing for dashboard UI components

## Troubleshooting

### Common Issues

**"Cannot identify image file"**
- HEIC files need pillow-heif: `pip install pillow-heif`
- SVG files cannot be processed by PIL (expected)

**"No text extracted"**
- Normal for videos, audio files
- HEIC screenshots may lack OCR
- Some images genuinely have no extractable text

**Geocoding errors**
- Rate limit exceeded: Add delays between requests
- Network timeout: Check internet connection
- No location: GPS data not in EXIF (expected)

**Game assets in Uncategorized**
- Add keywords to detection lists (lines 956-999)
- Check Priority 0 is enabled (line 1206)
- Verify file extensions are supported

## Session History

See `docs/SESSION_NOTES.md` for detailed session work log.

**Latest session:** 2025-12-09 (Dashboard UI Debug)
- Fixed invalid JSON in cost_report.json (Infinity values)
- Refactored metadata_viewer.html from 24MB to 30KB
- Added async data loading with progress spinner
- Fixed null reference error on retry button
- Added resource usage panel to main dashboard
- Created test suite for UI error handling
- Processed 30,133 files total (98.6% success rate)

**Previous session:** 2025-12-09 (Storage & Cost Tracking)
- Implemented graph-based SQL storage with SQLAlchemy
- Added key-value store with namespace isolation
- Created JSON to database migration tool
- Added cost and ROI calculation system
- Integrated cost tracking into file organizer

**Earlier session:** 2025-11-26
- Added GameAssets category with subdirectories
- Processed 1,600 files (100% success)
- Created image metadata renamer
- Tested on 12,634 images

---

**Project Status:** Active development
**Last Updated:** 2025-12-09
**Python Version:** 3.14 (venv)
**Working Directory:** `/Users/alyshialedlie/schema-org-file-system`

## Git Commit History (Recent)

```
a0ce0bb docs(debug): add comprehensive debugging session summary
bcf18b4 test(ui): add error handling tests for metadata viewer
e3675ae chore(build): update copy_to_site script
3b9adb1 fix(dashboard): add resource usage panel to main dashboard
ca38ec3 refactor(ui): optimize metadata viewer performance
aa852e9 fix(dashboard): fix invalid json in cost_report
031f300 feat(organizer): auto-update _site after file organization
3dad147 feat(ui): create dashboard with visual storyteller design
027f690 docs(project): update documentation with latest features
87f5e10 feat(organizer): add default cost-report path
c139a4f feat(storage): implement graph-based sql and kv storage
b82b185 feat(organizer): integrate cost tracking
bc70300 feat(cost): add cost and roi calculation system
```
