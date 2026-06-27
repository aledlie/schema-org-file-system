# Architecture

Current-state reference for the schema-org-file-system. As of 2026-03-28.

---

## Module Map

```
schema-org-file-system/
│
├── src/                              # Core library (~12k LOC)
│   ├── cli.py                        #   283 LOC  Unified CLI entry (organize-files)
│   ├── generators.py                 # 1,788 LOC  Schema.org metadata generation
│   ├── base.py                       #   540 LOC  Base classes
│   ├── constants.py                  #    55 LOC  Shared constants
│   ├── enrichment.py                 #   668 LOC  Metadata enrichment
│   ├── validator.py                  #   475 LOC  Schema validation
│   ├── error_tracking.py             #   394 LOC  Sentry integration
│   ├── health_check.py               #   377 LOC  Dependency checks
│   ├── integration.py                #   414 LOC  External integrations
│   ├── cost_roi_calculator.py        #   866 LOC  Cost tracking
│   ├── cost_integration.py           #   356 LOC  Cost pipeline hooks
│   │
│   ├── storage/                      # Data persistence
│   │   ├── models.py                 # 1,294 LOC  SQLAlchemy ORM models
│   │   ├── graph_store.py            # 1,151 LOC  Graph DB operations
│   │   ├── migration.py              #   849 LOC  DB migrations
│   │   ├── kv_store.py               #   756 LOC  Key-value store
│   │   ├── schema_org_base.py        #    29 LOC  SchemaOrgSerializable ABC + IriMixin + PropertyBuilder
│   │   ├── schema_org_exporter.py    #   208 LOC  Batch JSON-LD export (SchemaOrgExporter)
│   │   └── schema_org_variants.py    #   310 LOC  Alternative representations (CategoryVariants, PersonVariants, FileVariants)
│   │
│   ├── api/                          # REST API
│   │   ├── schema_org_api.py         #   369 LOC  15 FastAPI endpoints (files, categories, companies, people, locations, bulk)
│   │   ├── schema_org_models.py      #   323 LOC  Pydantic response models
│   │   └── timeline_api.py           #   397 LOC  Timeline endpoints
│   │
│   └── tests/                        # Legacy test location
│       └── test_schema_org_serialization.py   # 16 tests (kept for compatibility)
│
├── scripts/                          # Operational scripts (~13k LOC, NOT refactored)
│   ├── file_organizer_content_based.py  # 4,156 LOC  Main AI organizer (god script)
│   ├── file_organizer.py               #   958 LOC
│   ├── file_organizer_by_name.py       #   806 LOC
│   ├── correction_feedback.py          #   620 LOC
│   ├── data_preprocessing.py           #   609 LOC
│   └── shared/                         # Shared utilities
│       ├── clip_utils.py               #   251 LOC  CLIP model wrapper
│       ├── clip_cache.py               # CLIP result cache
│       ├── ocr_classifier.py           # Tesseract OCR + OCR-driven classification
│       ├── db_utils.py                 # DB helpers
│       ├── file_ops.py                 # File operation helpers
│       └── constants.py               # Shared constants
│
└── tests/                            # Test suite (~10k LOC)
    ├── conftest.py                   #   225 LOC  Shared fixtures + seeded in-memory session
    ├── unit/
    │   ├── test_generators.py        # 1,322 LOC
    │   ├── test_file_organizer.py    # 1,023 LOC
    │   ├── test_base.py              #   735 LOC
    │   ├── test_enrichment.py        #   696 LOC
    │   ├── test_cost_calculator.py   #   668 LOC
    │   ├── test_schema_org_variants.py  # 585 LOC  28 tests — CategoryVariants, PersonVariants, FileVariants
    │   ├── test_uri_utils.py         #   445 LOC
    │   ├── test_storage_models.py    #   333 LOC
    │   ├── test_schema_org_exporter.py  # 312 LOC  32 tests — all SchemaOrgExporter methods
    │   └── test_shared.py
    ├── integration/
    │   ├── test_schema_org_export_e2e.py  # 413 LOC  26 tests — full DB→export→JSON-LD pipeline
    │   ├── test_storage_graph.py     #   674 LOC
    │   └── test_storage_migration.py #   618 LOC
    └── performance/
        └── test_export_benchmark.py  #   159 LOC  Benchmarks at 100/1k/10k entities
```

---

## Schema.org Serialization Layer

The schema.org serialization is the primary completed refactoring. All five entity models implement `to_schema_org()` using a shared base.

### IRI Strategy

| Entity   | IRI pattern                          | Schema.org type          |
|----------|--------------------------------------|--------------------------|
| File     | `urn:sha256:{hash}`                  | Derived from MIME type   |
| Category | `urn:uuid:{deterministic-uuid}`      | `DefinedTerm`            |
| Company  | `urn:uuid:{deterministic-uuid}`      | `Organization`           |
| Person   | `urn:uuid:{deterministic-uuid}`      | `Person`                 |
| Location | `urn:uuid:{deterministic-uuid}`      | `Place` / `City` / `Country` |

### MIME → Schema.org type mapping

Implemented inline in `models.py` via `File.get_schema_type_from_mime()`:

| MIME prefix    | Schema.org type        |
|----------------|------------------------|
| `image/*`      | `ImageObject`          |
| `video/*`      | `VideoObject`          |
| `audio/*`      | `AudioObject`          |
| `application/pdf`, `text/*` | `DigitalDocument` |
| `text/html`    | `WebPage`              |
| code MIME types | `SoftwareSourceCode`  |

### Key classes

- **`SchemaOrgSerializable`** (`schema_org_base.py`) — abstract base requiring `get_iri()`, `get_schema_type()`, `to_schema_org()`; `super().to_schema_org()` fills `@context`, `@type`, `@id`
- **`PropertyBuilder`** (`schema_org_base.py`) — `add_if_present()`, `add_iso_datetime()`, `add_numeric_if_present()`
- **`IriMixin`** (`schema_org_base.py`) — URN generation helpers
- **`SchemaOrgExporter`** (`schema_org_exporter.py`) — batch export: `export_to_file()`, `export_to_ndjson()`, `export_with_graph()`, `get_graph_document()`
- **`CategoryVariants`** / **`PersonVariants`** / **`FileVariants`** (`schema_org_variants.py`) — alternative representations for different contexts

> **Note:** `mime_mapping.py` and `schema_org_builders.py` are referenced in `REFACTORING_GUIDE.md` but were never created. Their logic lives in `models.py` and `schema_org_variants.py`.

### REST API (`src/api/schema_org_api.py`)

15 FastAPI endpoints with Pydantic `response_model=` validation:

- `GET /api/files/{id}/schema-org`
- `GET /api/files/schema-org` (paginated)
- `GET /api/categories/{id}/schema-org`
- `GET /api/categories/schema-org`
- `GET /api/companies/{id}/schema-org`, `GET /api/companies/by-name/{name}/schema-org`, bulk
- `GET /api/people/{id}/schema-org`, `GET /api/people/by-name/{name}/schema-org`, bulk
- `GET /api/locations/{id}/schema-org`, `GET /api/locations/by-name/{name}/schema-org`, bulk
- `GET /api/schema-org/export` (full bulk export)
- `GET /health`

---

## Data Flow

```
CLI (organize-files content)
  └─▶ scripts/file_organizer_content_based.py  [4,156 LOC god script]
        ├─▶ scripts/shared/ (CLIP, OCR, DB, file ops)
        ├─▶ src/enrichment.py
        ├─▶ src/generators.py          ← Schema.org generation
        └─▶ src/storage/graph_store.py ← Persistence
              └─▶ src/storage/models.py (SQLAlchemy + to_schema_org())
```

---

## Open Backlog Items

| ID | Item |
|----|------|
| S5 | Add inline schema.org spec URL comments to builder functions and `to_schema_org()` methods |
| S6 | Update REST API endpoints to use `SchemaOrgExporter` for consistent `@graph` responses |
| S7 | JSON-LD validation against schema.org vocabulary (pyshacl or jsonschema) |
| S8 | Standalone JSON-LD `@context` file generation + `/schema/context` endpoint |

Full details in `docs/BACKLOG.md`.

---

## What Was NOT Refactored

The `docs/ARCHITECTURE_REFACTOR.md` plan called for decomposing `scripts/` into modular `src/classifiers/`, `src/analyzers/`, `src/organizers/`, `src/pipeline/`, `src/ml/`, and `src/feedback/` packages. **This was not implemented.** `scripts/file_organizer_content_based.py` grew from 2,691 LOC to 4,156 LOC and remains a monolith.
