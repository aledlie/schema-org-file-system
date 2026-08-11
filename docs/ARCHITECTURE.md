# Architecture

Current-state reference for the schema-org-file-system. As of 2026-07-15.

---

## Module Map

The `scripts/` monolith described in earlier revisions has been decomposed into
modular `src/` packages; the old god-script is now a thin CLI wrapper (see
[Refactoring status](#refactoring-status)).

```
schema-org-file-system/
│
├── src/                              # Core library
│   ├── cli.py                        # Unified CLI entry (organize-files)
│   ├── generators.py                 # Schema.org metadata generation
│   ├── enrichment.py                 # Metadata enrichment
│   ├── validator.py                  # Schema validation
│   ├── error_tracking.py             # Sentry integration
│   ├── health_check.py               # Dependency checks
│   │
│   ├── classifiers/                  # content_classifier, entity_detector (company/person)
│   ├── analyzers/                    # image_analyzer, image_metadata (EXIF/GPS), text_extractor
│   ├── organizers/                   # base_organizer, content_organizer, name_organizer,
│   │                                 #   category_config, mime_classifier
│   ├── pipeline/                     # batch_processor, file_processor
│   ├── ml/                           # data_preprocessor, feature_extractor
│   ├── feedback/                     # correction_tracker, feedback_loop
│   ├── utils/                        # tracking + shared helpers
│   │
│   ├── scoring/                      # Unified weighted-signal classifier (the decision engine)
│   │   ├── scorer.py                 # Cost-tier waves + early exit; aggregates signal votes
│   │   ├── registry.py               # Signal registration/ordering
│   │   ├── weights.py                # Signal priors + decision thresholds (calibrated — see below)
│   │   ├── context.py                # FileContext (lazy OCR/KIE/CLIP accessors)
│   │   ├── types.py                  # CategoryScore, ClassificationDecision
│   │   └── signals/                  # 19 signal modules (org, person, legal, kie, scene, clip, mime, …)
│   │
│   ├── similarity/                   # Near-duplicate detection (read-only report)
│   │   ├── descriptors.py            # SSCD copy-detection descriptors + cache (.cache/sscd_descriptors_v1/)
│   │   ├── index.py                  # faiss IndexFlatIP + union-find grouping
│   │   ├── worker.py                 # Runs the faiss stage in a subprocess (faiss/torch libomp clash)
│   │   ├── finder.py                 # Walk -> describe -> group -> report
│   │   ├── types.py                  # SimilarPair, DuplicateGroup (cross the process boundary)
│   │   └── constants.py              # Model URL, preprocessing, thresholds
│   │
│   ├── storage/                      # Data persistence
│   │   ├── models.py                 # SQLAlchemy ORM + build_*_jsonld builders (serialization SoT)
│   │   ├── graph_store.py            # Graph DB operations (canonical IDs, person edges)
│   │   ├── migration.py              # Canonical-ID migration
│   │   ├── person_migration.py       # Person/ → Personal/{subcat} migration (+ rollback)
│   │   ├── person_view_generator.py  # Derived Person/{Name}/ symlink view
│   │   ├── kv_store.py               # Key-value store
│   │   ├── schema_org_base.py        # SchemaOrgSerializable base (get_iri/get_schema_type/to_schema_org)
│   │   ├── schema_org_exporter.py    # Batch/streaming JSON-LD export (SchemaOrgExporter)
│   │   ├── schema_org_context.py     # Standalone JSON-LD @context generation
│   │   └── schema_org_variants.py    # Alternative representations (Category/Person/File variants)
│   │
│   └── api/                          # REST API (FastAPI)
│       ├── schema_org_api.py         # JSON-LD endpoints (see REST API below)
│       ├── schema_org_models.py      # Pydantic response models
│       └── timeline_api.py           # Timeline endpoints
│
├── scripts/                          # Thin CLI wrappers + operational scripts
│   ├── file_organizer_content_based.py  # Thin wrapper over src/{classifiers,analyzers,organizers,pipeline}
│   ├── rename_images.py                 # Unified CLIP renamer (--profile photo|screenshot)
│   ├── redact_pii.py                    # Rasterize + OCR-redact PII before VCS
│   └── shared/                          # Run from project root so `from shared.x import y` resolves
│       ├── clip_classification.py       # Unified CLIP+OCR pipeline (classify_with_ocr_fallback)
│       ├── clip_utils.py                # CLIPClassifier singleton (open-clip ViT-B-32)
│       ├── clip_cache.py                # Embedding cache (.cache/clip_embeddings_v2/)
│       ├── ocr_classifier.py            # OCR fallback logic
│       └── file_organizer.py            # FileOrganizer (mode=in-place|folder)
│
└── tests/                            # unit/ + integration/ + performance/ + e2e/
```

---

## Schema.org Serialization Layer

Serialization is centralized in **pure builder functions** in
`src/storage/models.py` (`build_file_jsonld`, `build_category_jsonld`,
`build_company_jsonld`, `build_person_jsonld`, `build_location_jsonld`, plus
`build_file_relationships` and the `file_iri` helper). Each entity's
`to_schema_org()` is a thin delegator to its builder, so the ORM path and the
`SchemaOrgExporter(use_core=True)` streaming path share one implementation and
produce byte-identical output. See
[`SCHEMA_ORG_ARCHITECTURE.md`](SCHEMA_ORG_ARCHITECTURE.md) for the full contract.

### IRI Strategy

| Entity   | IRI pattern                          | Schema.org type          |
|----------|--------------------------------------|--------------------------|
| File     | `urn:sha256:{hash}`                  | Derived from MIME type   |
| Category | `urn:uuid:{deterministic-uuid}`      | `DefinedTerm`            |
| Company  | `urn:uuid:{deterministic-uuid}`      | `Organization`           |
| Person   | `urn:uuid:{deterministic-uuid}`      | `Person`                 |
| Location | `urn:uuid:{deterministic-uuid}`      | `Place` / `City` / `Country` |

### MIME → Schema.org type mapping

Implemented in `models.py` via `File.get_schema_type_from_mime()`:

| MIME prefix    | Schema.org type        |
|----------------|------------------------|
| `image/*`      | `ImageObject`          |
| `video/*`      | `VideoObject`          |
| `audio/*`      | `AudioObject`          |
| `application/pdf`, `text/*` | `DigitalDocument` |
| `text/html`    | `WebPage`              |
| code MIME types | `SoftwareSourceCode`  |

### Key classes

- **`SchemaOrgSerializable`** (`schema_org_base.py`) — base declaring `get_iri()`, `get_schema_type()`, `to_schema_org()`
- **`build_*_jsonld`** (`models.py`) — single source of truth for JSON-LD serialization (edit these, not the delegating `to_schema_org()` methods)
- **`SchemaOrgExporter`** (`schema_org_exporter.py`) — batch/streaming export: `export_to_file()`, `export_to_ndjson()`, `export_with_graph()`, `get_graph_document()`, `export_entities_filtered()`, `export_context()`. Defaults to `use_core=True` (Core-query streaming path)
- **`CategoryVariants`** / **`PersonVariants`** / **`FileVariants`** (`schema_org_variants.py`) — alternative representations for different contexts

### REST API (`src/api/schema_org_api.py`)

FastAPI endpoints with Pydantic `response_model=` validation:

- `GET /api/{entity}/{id}/schema-org` — single entity as JSON-LD (`files`, `categories`, `companies`, `people`, `locations`)
- `GET /api/{entity}/schema-org/bulk` — filtered list as `{"@context":…,"@graph":[…]}`
- `GET /api/{companies|people|locations}/schema-org/by-name/{name}` — lookup by name
- `GET /api/schema-org/export` — full `@graph` document, filterable by entity type
- `GET /api/schema-org/graph` — full graph, all entity types
- `GET /schema/context` — standalone JSON-LD `@context` document
- `GET /health`

---

## Data Flow

```
CLI (organize-files content)
  └─▶ scripts/file_organizer_content_based.py  [thin wrapper]
        └─▶ src/pipeline/ (batch_processor, file_processor)
              ├─▶ src/classifiers/ (content_classifier, entity_detector)
              ├─▶ src/analyzers/  (image_analyzer, image_metadata, text_extractor)
              ├─▶ scripts/shared/ (CLIP, OCR)
              ├─▶ src/generators.py          ← Schema.org generation
              └─▶ src/storage/graph_store.py ← Persistence
                    └─▶ src/storage/models.py (SQLAlchemy + build_*_jsonld)
```

---

## Refactoring status

The `docs/archive/ARCHITECTURE_REFACTOR.md` plan to decompose `scripts/` into modular
`src/` packages (`classifiers/`, `analyzers/`, `organizers/`, `pipeline/`,
`ml/`, `feedback/`) is **complete**. `scripts/file_organizer_content_based.py`
is now a thin CLI wrapper delegating into those packages rather than the former
4k-LOC monolith.

Open follow-up work is tracked in [`docs/BACKLOG.md`](BACKLOG.md).

---

## Diagrams

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

    subgraph Scripts["CLI Wrappers (scripts/)"]
        foc[file_organizer_content_based.py]
        icr[rename_images.py]
        ica[image_content_analyzer.py]
    end

    subgraph Core["Core Library (src/)"]
        org[organizers/content_organizer.py]
        pipe[pipeline/file_processor + batch_processor]
        clf[classifiers/]
        ana[analyzers/]
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

    foc --> org
    foc --> pipe
    org --> clf
    org --> ana
    org --> torch
    org --> doctr
    pipe --> gen
    pipe --> gs
    pipe --> cost
    foc --> err

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
