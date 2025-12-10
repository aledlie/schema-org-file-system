# Dependencies Guide

Complete guide to dependencies for the Schema.org File Organization System.

## Quick Install

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install all Python dependencies
pip install -r requirements.txt

# Install system dependencies (macOS)
brew install tesseract poppler
```

## Dependency Groups

### Core Dependencies (Required)

| Package | Version | Purpose |
|---------|---------|---------|
| `Pillow` | >=12.0.0 | Image loading, EXIF extraction, thumbnails |
| `pillow-heif` | >=1.1.1 | HEIC/HEIF support (iPhone photos) |
| `piexif` | >=1.1.3 | EXIF metadata read/write |
| `pytesseract` | >=0.3.13 | OCR text extraction |
| `geopy` | >=2.4.1 | GPS coordinate to location name lookup |
| `SQLAlchemy` | >=2.0.0 | Database storage for file metadata |

**Without these:** Basic file organization still works, but metadata extraction and smart classification are disabled.

### AI/ML Dependencies (Recommended)

| Package | Version | Purpose |
|---------|---------|---------|
| `torch` | >=2.9.0 | PyTorch deep learning framework |
| `torchvision` | >=0.24.0 | Computer vision utilities |
| `transformers` | >=4.57.0 | Hugging Face CLIP model |
| `huggingface-hub` | >=0.36.0 | Model downloading |
| `opencv-python` | >=4.12.0 | Image processing |

**Without these:** No AI-powered content classification. Falls back to keyword-only detection.

### Document Processing (Optional)

| Package | Version | Purpose |
|---------|---------|---------|
| `python-docx` | >=1.2.0 | Microsoft Word parsing |
| `pypdf` | >=6.3.0 | PDF text extraction |
| `PyPDF2` | >=3.0.1 | PDF utilities (legacy) |
| `pdf2image` | >=1.17.0 | PDF to image conversion |
| `openpyxl` | >=3.1.5 | Excel spreadsheet parsing |
| `lxml` | >=6.0.0 | XML/HTML parsing |

**Without these:** Document metadata extraction limited to filename analysis.

### System Dependencies

#### macOS
```bash
brew install tesseract    # OCR engine (required for pytesseract)
brew install poppler      # PDF rendering (required for pdf2image)
```

#### Linux (Ubuntu/Debian)
```bash
sudo apt-get install tesseract-ocr
sudo apt-get install poppler-utils
```

#### Windows
- Tesseract: Download from [GitHub releases](https://github.com/UB-Mannheim/tesseract/wiki)
- Poppler: Download from [poppler releases](https://github.com/osber/poppler-windows/releases)

## Feature Availability Matrix

| Feature | Required Packages | Fallback Behavior |
|---------|-------------------|-------------------|
| Image metadata | Pillow, piexif | Filename only |
| HEIC photos | pillow-heif | Skip HEIC files |
| OCR text extraction | pytesseract + tesseract | No text from images |
| AI content classification | torch, transformers | Keyword matching only |
| Location from GPS | geopy | No location names |
| Database storage | SQLAlchemy | JSON file storage |
| Word documents | python-docx | Skip .docx files |
| PDF text | pypdf, pdf2image | Skip PDF content |
| Excel files | openpyxl | Skip .xlsx files |

## Health Check

Run the built-in health check to verify all dependencies:

```bash
# Activate virtual environment
source venv/bin/activate

# Check all dependencies
python3 scripts/file_organizer_content_based.py --check-deps

# Or run standalone
python3 src/health_check.py -v
```

Example output:
```
============================================================
SYSTEM HEALTH CHECK
============================================================
  [OK] Python v3.14.0
  [OK] Pillow (Image Processing) v12.0.0
  [OK] HEIC Support v1.1.1
  [OK] OCR (Tesseract) v5.5.1
  [OK] AI Vision (CLIP) vtorch 2.9.1, transformers 4.57.3
  [OK] Database (SQLAlchemy) v2.0.44
  [OK] Geocoding (geopy) v2.4.1
  [OK] Document Processing vdocx, pypdf, openpyxl
------------------------------------------------------------
Features available: 8/8
All features operational!
============================================================
```

## Minimal Installation

For basic file organization without AI features:

```bash
pip install Pillow pillow-heif piexif pytesseract geopy SQLAlchemy
brew install tesseract
```

This gives you:
- Image metadata extraction
- HEIC support
- OCR text extraction
- Location lookup
- Database storage

## Full Installation

For all features including AI classification:

```bash
pip install -r requirements.txt
brew install tesseract poppler
```

## Troubleshooting

### "tesseract not found"
```bash
# macOS
brew install tesseract

# Verify installation
which tesseract
tesseract --version
```

### "No module named 'torch'"
```bash
# Install PyTorch (CPU version for smaller download)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Or full version with CUDA support
pip install torch torchvision
```

### "HEIC files not loading"
```bash
pip install pillow-heif

# Verify in Python
python3 -c "from pillow_heif import register_heif_opener; print('HEIC OK')"
```

### "PDF conversion failed"
```bash
# Install poppler
brew install poppler  # macOS
sudo apt-get install poppler-utils  # Linux

# Verify
which pdftoppm
```

### Checking installed versions
```bash
pip freeze | grep -E "Pillow|torch|transformers|SQLAlchemy"
```

## Upgrade Dependencies

```bash
# Upgrade all packages
pip install --upgrade -r requirements.txt

# Upgrade specific package
pip install --upgrade torch transformers
```

## Development Dependencies

For running tests and code quality tools:

```bash
pip install pytest pytest-cov black flake8 mypy
```

## Storage Requirements

| Component | Disk Space |
|-----------|------------|
| Base packages | ~100 MB |
| PyTorch (CPU) | ~500 MB |
| PyTorch (CUDA) | ~2 GB |
| CLIP model (cached) | ~600 MB |
| Tesseract data | ~30 MB |

**Total (full install):** ~1.2 GB minimum

## Python Version

- **Minimum:** Python 3.8
- **Recommended:** Python 3.11+
- **Tested on:** Python 3.14.0
