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

## Current State (2025-11-26)

### Files Organized
- **Total processed:** 1,600 / 14,302 (11.2%)
- **Success rate:** 100% (0 errors)

### Category Breakdown
- GameAssets: 1,132 files
  - Audio: 76 files
  - Music: 33 files
  - Sprites: 674 files
  - Textures: 343 files
- Technical: 4,501 files
- Data: 2,651 files
- Legal: 2,314 files
- Creative: 402 files
- Property_Management: 19 files
- Uncategorized: 766 files

### Recent Enhancements

**GameAssets Category (New!):**
- Added Priority 0 detection (highest priority)
- 4 subdirectories: Audio, Music, Sprites, Textures
- 200+ keywords for classification
- Successfully categorized 1,132 game files

**Image Renamer:**
- New script: `image_renamer_metadata.py`
- Tested on 12,634 images
- Successfully renamed 115 files with EXIF metadata
- 483 files need HEIC support or have no metadata

## Project Structure

```
schema-org-file-system/
├── file_organizer_content_based.py  # AI-powered organizer
├── file_organizer_by_type.py        # Type-based organizer
├── image_renamer_metadata.py        # Image metadata renamer (NEW)
├── src/
│   ├── base.py                      # Schema.org base classes
│   ├── generators.py                # Specialized generators
│   ├── validator.py                 # Validation system
│   ├── integration.py               # Output formats
│   └── enrichment.py                # Metadata enrichment
├── docs/
│   ├── README.md                    # Full documentation
│   ├── BEST_PRACTICES.md            # Best practices
│   ├── IMPLEMENTATION_SUMMARY.md    # Implementation details
│   └── SESSION_NOTES.md             # Session work log (NEW)
├── tests/
│   ├── test_generators.py
│   └── test_validator.py
├── examples/
│   └── example_usage.py
├── results/                          # Organization reports
│   └── content_organization_report_*.json
└── venv/                             # Python virtual environment
```

## Dependencies

**Python Libraries:**
```bash
# Core
pip install Pillow pytesseract piexif geopy

# AI Vision
pip install transformers torch torchvision opencv-python

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

**Files to process:** ~12,702 files remaining in ~/Documents/Media

**Recommended next steps:**
1. Continue processing in batches of 1,000-2,000
2. Run image renamer on specific directories
3. Review uncategorized files for new patterns
4. Add HEIC support to renamer
5. Consider additional game asset subcategories

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

**Latest session:** 2025-11-26
- Added GameAssets category with subdirectories
- Processed 1,600 files (100% success)
- Created image metadata renamer
- Tested on 12,634 images

---

**Project Status:** Active development
**Last Updated:** 2025-11-26
**Python Version:** 3.14 (venv)
**Working Directory:** `/Users/alyshialedlie/schema-org-file-system`
