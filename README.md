# Schema.org File Organization System

AI-powered file organization using CLIP vision, OCR, Schema.org metadata, and entity detection.

**Version:** 2.0.0 | **Python:** 3.13 (3.14 blocked by macOS 26 libexpat ABI) | **Files Processed:** 265,000+

## Quick Start

```bash
# Setup
git clone https://github.com/aledlie/schema-org-file-system.git
cd schema-org-file-system
python3.13 -m venv venv && source venv/bin/activate
pip install -e ".[all]"
brew install tesseract poppler

# Run
organize-files content --source ~/Downloads --dry-run --limit 100
organize-files health  # Should report 9/9 features operational
```

> **macOS 26 note:** Homebrew's `python@3.13` and `python@3.14` bottles link `pyexpat` against a newer `libexpat` than macOS 26 ships, which breaks `pip` on fresh installs. If you see `Symbol not found: _XML_SetAllocTrackerActivationThreshold`, see [Troubleshooting](#troubleshooting).

## CLI Commands

| Command | Description |
|---------|-------------|
| `organize-files content` | AI-powered organization (CLIP, OCR) |
| `organize-files name` | Filename pattern organization |
| `organize-files type` | Extension-based organization |
| `organize-files health` | Check system dependencies |
| `organize-files migrate-ids` | Run database migration |
| `organize-files update-site` | Update dashboard data |
| `organize-files timeline` | Generate timeline visualization data |
| `organize-files preprocess` | Data preprocessing pipeline for ML model training (`--input`, `--output`) |
| `organize-files evaluate` | Run evaluation metrics on test dataset (`--test-data`, `--model`) |

## Architecture

```mermaid
flowchart LR
    A[Source Files] -->|scan| B[organize-files CLI]
    B --> C{Organizer<br/>Strategy}

    C -->|vision| D[CLIP Vision]
    C -->|text| E[docTR OCR]
    C -->|metadata| F[Entity Detection]

    D --> G[Category Assignment]
    E --> G
    F --> G

    G -->|persist| H[GraphStore]
    H --> I[(SQLite DB)]
    H --> J[Schema.org<br/>JSON-LD]

    I --> K[Web Dashboard]
    J --> K
```

## Classification Priority

1. **Organization** - client, vendor, invoice, company names
2. **Person** - resume, contact, signatures (OCR-enhanced)
3. **Legal/Contract** - contracts, agreements, terms
4. **E-commerce** - product listings, shopping carts
5. **Software UI** - app interfaces, dashboards
6. **Game Assets** - 200+ patterns, sprites, textures, audio
7. **Filepath** - directory structure patterns
8. **Content Analysis** - OCR text + CLIP vision
9. **MIME Type** - file extension fallback

## Project Structure

```
├── src/
│   ├── cli.py                       # CLI entry point
│   ├── generators.py                # Schema.org generators
│   ├── api/
│   │   ├── schema_org_api.py        # FastAPI JSON-LD REST endpoints
│   │   ├── schema_org_models.py     # Pydantic models
│   │   └── timeline_api.py          # Timeline data endpoints
│   └── storage/
│       ├── graph_store.py           # GraphStore + canonical IDs
│       ├── models.py                # ORM models with to_schema_org()
│       ├── migration.py             # ID generation migration
│       ├── kv_store.py              # Key-value storage layer
│       ├── schema_org_exporter.py   # Bulk export (JSON / NDJSON / @graph)
│       ├── schema_org_context.py    # JSON-LD @context generation
│       ├── schema_org_variants.py   # Typed representation variants
│       └── schema_org_base.py       # Shared base types
├── scripts/                         # Organizer scripts
├── tests/
│   ├── unit/                        # 755 unit tests
│   ├── integration/                 # Export pipeline integration tests
│   ├── performance/                 # pytest-benchmark suite
│   └── e2e/                         # Playwright + OpenTelemetry
├── _site/                           # Web dashboard
└── results/                         # Database & reports
```

## Output Folders

```
~/Documents/
├── Organization/{Company}/    # Vendor/partner files
├── Person/{Name}/             # Person-related files
├── GameAssets/                # Sprites, textures, models
├── Financial/                 # Invoices, receipts
├── Technical/                 # Code, configs
└── Media/                     # Photos, videos, audio
```

## Key Features

- **Entity Detection** - Prioritizes Organization and Person identification
- **Canonical IDs** - UUID v5 + SHA256 for persistent identification
- **Schema.org JSON-LD** - Full JSON-LD generation with validated spec URLs on every emitted property
- **REST API** - FastAPI endpoints returning `{"@context":…,"@graph":[…]}` for all entity types
- **Bulk Export** - JSON, NDJSON, and `@graph` formats via `SchemaOrgExporter`
- **Cost Tracking** - ROI calculation with manual time savings
- **E2E Testing** - Playwright with OpenTelemetry instrumentation

## Tech Stack

| Layer | Technology |
|-------|------------|
| AI/ML | PyTorch, open-clip-torch, OpenCV |
| OCR | docTR (PyTorch) |
| Database | SQLite + SQLAlchemy |
| API | FastAPI |
| Monitoring | Sentry SDK |
| Testing | pytest, pytest-benchmark, Playwright |

## Documentation

- [CHANGELOG (v2.0.0)](docs/changelog/2.0.0/CHANGELOG.md) - Version history
- [ARCHITECTURE_REFACTOR](docs/ARCHITECTURE_REFACTOR.md) - Design decisions
- [SCHEMA_ORG_ARCHITECTURE](docs/SCHEMA_ORG_ARCHITECTURE.md) - Schema.org type mappings, IRI patterns, JSON-LD context, and implementation reference

## Changelog

### v2.0.0 (2026-03-28)

**Schema.org Integration**
- `SchemaOrgExporter` — bulk export in JSON, NDJSON, and `@graph` formats
- `schema_org_context.py` — standalone JSON-LD `@context` document with `schema:` and `ml:` prefixes
- `schema_org_variants.py` — `CategoryVariants`, `PersonVariants`, `FileVariants`
- All five `to_schema_org()` methods annotated with validated `# https://schema.org/` spec URLs

**REST API**
- FastAPI app at `src/api/schema_org_api.py`
- Bulk endpoints return proper `{"@context":…,"@graph":[…]}` JSON-LD documents
- `/api/schema-org/export`, `/api/schema-org/graph`, `/schema/context` endpoints

**Testing**
- 26 integration tests, performance benchmarks (100 / 1k / 10k entities)
- Per-entity `to_schema_org()` benchmarks and relationship-overhead baseline

### v1.4.0 (2026-03-19)

**Features**
- Typed subdirectories for screenshot categories
- Enhanced weak image classification with full CLIP + OCR fallback
- Shared utilities module consolidating 576 lines of duplication

**See full history:** `git log --oneline`

## Environment Variables

| Variable | Description |
|----------|-------------|
| `FILE_SYSTEM_SENTRY_DSN` | Sentry error tracking (Doppler) |
| `FILE_ORGANIZE_MODE` | `in-place` (default for image renamer) or `folder` (default for screenshot renamer) |
| `--sentry-dsn` | CLI override |

## Troubleshooting

| Issue | Solution |
|-------|----------|
| HEIC fails | `pip install pillow-heif` |
| No OCR | `pip install 'python-doctr[torch]'` |
| No AI | `pip install torch transformers` |
| Check deps | `organize-files health` |
| `pyexpat` / `_XML_SetAllocTrackerActivationThreshold` on macOS 26 | `brew install expat`, then repoint and re-sign the broken module: `install_name_tool -change /usr/lib/libexpat.1.dylib /opt/homebrew/opt/expat/lib/libexpat.1.dylib $(python3.13 -c 'import pyexpat,os;print(pyexpat.__file__)')` and `codesign --force --sign - $(python3.13 -c 'import pyexpat;print(pyexpat.__file__)')` |

## Visual Architecture

### System Overview

```mermaid
flowchart TB
    subgraph Input["1 - Input"]
        U[User]
        F[Source Files]
    end

    subgraph Processing["2 - Processing Pipeline"]
        CLI[organize-files CLI]
        CO{Organizer<br/>Type}
        AI[AI Organizer]
        NM[Name Organizer]
        TY[Type Organizer]

        subgraph Classifiers["Classifiers"]
            CLIP[CLIP Vision]
            OCR[docTR OCR]
            ED[Entity Detection]
            GAD[Game Asset]
            LCD[Legal / Contract]
            ECD[E-commerce]
            SUI[Software UI]
        end
    end

    subgraph Storage["3 - Storage"]
        GS[GraphStore]
        DB[(SQLite)]
        JSON[Schema.org JSON-LD]
    end

    subgraph Output["4 - Output"]
        DASH[Web Dashboard]
        RPT[Reports]
    end

    subgraph Monitoring["Cross-Cutting"]
        SENTRY[Sentry]
        COST[Cost Tracker]
    end

    subgraph External["External Services"]
        HF[open-clip-torch]
        NOM[Nominatim Geocoder]
    end

    U --> CLI
    F --> CLI
    CLI --> CO
    CO -->|content| AI
    CO -->|name| NM
    CO -->|type| TY

    AI --> CLIP
    AI --> OCR
    AI --> ED
    AI --> GAD
    AI --> LCD
    AI --> ECD
    AI --> SUI

    CLIP --> GS
    OCR --> GS
    ED --> GS
    GAD --> GS
    LCD --> GS
    ECD --> GS
    SUI --> GS

    GS --> DB
    GS --> JSON
    DB --> DASH
    JSON --> DASH
    DB --> RPT

    AI -.->|errors| SENTRY
    AI -.->|usage| COST
    CLIP -.->|model| HF
    ED -.->|geo lookup| NOM
```

### Database Schema

```mermaid
erDiagram
    File ||--o{ FileCategory : has
    File ||--o{ FileCompany : has
    File ||--o{ FilePerson : has
    File ||--o{ FileLocation : has
    File ||--o{ FileRelationship : source
    File ||--o{ FileRelationship : target
    File }o--|| OrganizationSession : belongs_to

    File {
        string id PK "SHA-256"
        string canonical_id "UUID v5"
        string filename
        string original_path
        string current_path
        enum status
        string schema_type
        string content_hash
    }

    Category {
        int id PK
        string canonical_id
        string name
        int parent_id FK
        string full_path
    }

    Company {
        int id PK
        string canonical_id
        string name
        string normalized_name
        string domain
    }

    Person {
        int id PK
        string canonical_id
        string name
        string email
        string role
    }

    Location {
        int id PK
        string canonical_id
        string city
        string state
        float lat
        float lng
    }

    OrganizationSession {
        uuid id PK
        datetime started_at
        int total_files
        float total_cost
    }

    CostRecord {
        int id PK
        uuid session_id FK
        string file_id FK
        string feature_name
        float processing_time
        float cost
    }
```

### Module Dependencies

```mermaid
graph TB
    subgraph CLI["CLI Layer"]
        cli[src/cli.py]
    end

    subgraph API["API Layer"]
        soa[schema_org_api.py]
        som[schema_org_models.py]
    end

    subgraph Scripts["Organizer Scripts"]
        foc[file_organizer_content_based.py]
        icr[image_content_renamer.py]
        ica[image_content_analyzer.py]
    end

    subgraph Core["Core Library"]
        gen[generators.py]
        err[error_tracking.py]
        cost[cost_roi_calculator.py]
    end

    subgraph Storage["Storage Layer"]
        gs[graph_store.py]
        models[models.py]
        exp[schema_org_exporter.py]
        ctx[schema_org_context.py]
        var[schema_org_variants.py]
    end

    subgraph External["External Dependencies"]
        torch[PyTorch / open-clip]
        doctr[docTR]
        sentry[Sentry SDK]
        sa[SQLAlchemy]
        fa[FastAPI]
    end

    cli --> foc

    foc --> gen
    foc --> err
    foc --> cost
    foc --> gs
    foc --> torch
    foc --> doctr

    icr --> torch
    ica --> torch

    soa --> exp
    soa --> ctx
    soa --> models
    soa --> som
    soa --> fa

    exp --> models
    var --> models
    gs --> models
    models --> sa
    err --> sentry
```
