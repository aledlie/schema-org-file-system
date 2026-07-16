# Schema.org Architecture Reference

**Scope:** Core model types in `src/storage/models.py` and `src/storage/schema_org_base.py`

---

## Type Mappings

| Codebase Type | Schema.org Type | Inheritance Chain |
|---|---|---|
| File | DigitalDocument | CreativeWork → Thing |
| File | ImageObject | MediaObject → CreativeWork → Thing |
| File | VideoObject | MediaObject → CreativeWork → Thing |
| File | AudioObject | MediaObject → CreativeWork → Thing |
| File | WebPage | CreativeWork → Thing |
| Category | DefinedTerm | Intangible → Thing |
| Company | Organization | Thing |
| Company | Corporation | Organization → Thing |
| Person | Person | Thing |
| Location | Place | Thing |
| Location | City | Place → Thing |

---

## Entity Details

### File → DigitalDocument / MediaObject

**Type selection algorithm:**
```
if mime_type starts with 'image/' → ImageObject
if mime_type starts with 'video/' → VideoObject
if mime_type starts with 'audio/' → AudioObject
if mime_type == 'text/html'       → WebPage
if schema_type set explicitly     → use that
else                              → DigitalDocument
```

| Codebase Property | Schema.org Property | Notes |
|---|---|---|
| `filename` | `name` | Primary title |
| `mime_type` | `encodingFormat` | MIME type string |
| `file_size` | `contentSize` | Bytes as string |
| `created_at` | `dateCreated` | ISO 8601 |
| `modified_at` | `dateModified` | ISO 8601 |
| `original_path` | `url` | File path/URI |
| `extracted_text` | `text` | Truncated to 2000 chars |
| `image_width` | `width` | ImageObject only |
| `image_height` | `height` | ImageObject only |
| `exif_datetime` | `datePublished` | ImageObject only |
| `gps_latitude/longitude` | `contentLocation.geo` | ImageObject only |

**IRI:** `urn:sha256:{sha256_hash}`

---

### Category → DefinedTerm

| Codebase Property | Schema.org Property | Notes |
|---|---|---|
| `name` | `name` | Category name |
| `full_path` | `identifier` | Hierarchical path |
| `description` | `definition` | Fallback: `"Category: {name}"` |
| `parent_id` | `broader` | Link to parent DefinedTerm |
| `subcategories` | `narrower` | Links to child DefinedTerms |
| — | `inDefinedTermSet` | Fixed: `urn:uuid:categories-taxonomy` |
| `level` | `hierarchyLevel` | custom |
| `file_count` | `fileCount` | custom |
| `icon` | `icon` | custom |
| `color` | `color` | custom |

**IRI:** `urn:uuid:{uuid_v5(category_ns, normalized_name)}`
`category_ns = UUID('c4e8a9c0-2345-6789-abcd-ef0123456789')`

---

### Company → Organization

| Codebase Property | Schema.org Property | Notes |
|---|---|---|
| `name` | `name` | Organization name |
| `domain` | `url` | Normalized to `https://` prefix |
| `industry` | `knowsAbout` | Industry/sector string |
| `first_seen` | `dateCreated` | ISO 8601 |
| `last_seen` | `dateModified` | ISO 8601 |
| `domain` | `sameAs` | External reference array |
| `file_count` | `mentionCount` | custom |

**IRI:** `urn:uuid:{uuid_v5(company_ns, normalized_name)}`
`company_ns = UUID('c0e1a2b3-4567-89ab-cdef-012345678901')`

---

### Person → Person

| Codebase Property | Schema.org Property | Notes |
|---|---|---|
| `name` | `name` | Full name |
| `email` | `email` | Email address |
| `role` | `jobTitle` | Job role/position |
| `first_seen` | `dateCreated` | ISO 8601 |
| `last_seen` | `dateModified` | ISO 8601 |
| `file_count` | `mentionCount` | custom |
| — | `worksFor` | Organization @id ref (optional) |
| — | `workLocation` | Place @id ref (optional) |

**IRI:** `urn:uuid:{uuid_v5(person_ns, normalized_name)}`
`person_ns = UUID('d1e2a3b4-5678-9abc-def0-123456789012')`

---

### Location → Place

**Type selection:** `Place` (full address) → `City` (city present) → `Country` (country only)

| Codebase Property | Schema.org Property | Notes |
|---|---|---|
| `name` | `name` | Location name |
| `city` | `address.addressLocality` | Nested PostalAddress |
| `state` | `address.addressRegion` | Nested PostalAddress |
| `country` | `address.addressCountry` | 2-char ISO code |
| `latitude` | `geo.latitude` | Nested GeoCoordinates |
| `longitude` | `geo.longitude` | Nested GeoCoordinates |
| `geohash` | `geoHash` | custom |
| `file_count` | `mentionCount` | custom |

**IRI:** `urn:uuid:{uuid_v5(location_ns, normalized_name)}`
`location_ns = UUID('e2e3a4b5-6789-abcd-ef01-234567890123')`

---

## Relationships

All relationships use `@id` references only — no inline embedding.

| Relationship | Property | Notes |
|---|---|---|
| File → Category | `mainEntityOfPage` + `about` | Primary category → `mainEntityOfPage` (single ref); remaining → `about` (array) |
| File → Company | `mentions` | Array of Organization refs |
| File → Person | `mentions` | Array of Person refs |
| File → Location | `spatialCoverage` | Place ref (scalar or array) |
| Person → Company | `worksFor` | Organization ref |
| Person → Location | `workLocation` | Place ref |
| Category → parent | `broader` | DefinedTerm ref |
| Category → children | `narrower` | Array of DefinedTerm refs |

---

## JSON-LD Context

**Minimal:**
```json
{ "@context": "https://schema.org" }
```

**Extended (with custom properties):**
```json
{
  "@context": [
    "https://schema.org",
    {
      "fileCount":      "https://example.com/vocab/fileCount",
      "mentionCount":   "https://example.com/vocab/mentionCount",
      "mentionSources": "https://example.com/vocab/mentionSources",
      "hierarchyLevel": "https://example.com/vocab/hierarchyLevel",
      "geoHash":        "https://example.com/vocab/geoHash",
      "icon":           "https://example.com/vocab/icon",
      "color":          "https://example.com/vocab/color"
    }
  ]
}
```

Context document served at `GET /schema/context` via `src/storage/schema_org_context.py`.

---

## Implementation

Serialization lives in **pure builder functions** in `src/storage/models.py`
(`build_file_jsonld`, `build_category_jsonld`, `build_company_jsonld`,
`build_person_jsonld`, `build_location_jsonld`, plus the shared
`build_file_relationships` and the `file_iri` IRI helper). These are the single
source of truth for JSON-LD output.

Each entity's `to_schema_org()` is a **thin delegator** to its builder:

```python
# src/storage/models.py — Location example (all five entities follow this shape)
def to_schema_org(self) -> Dict[str, Any]:
    """Convert Location to schema.org JSON-LD (delegates to build_location_jsonld)."""
    return build_location_jsonld(self)
```

Builders take column values (and, for `File`, sequences of related entities)
rather than an ORM instance, so they run identically over:

- an **ORM instance** — the `to_schema_org()` path, and
- a **lightweight Core-query row** — `SchemaOrgExporter(use_core=True)`, the
  streaming bulk-export path (the default).

Both paths produce byte-identical output; parity is locked by
`tests/integration/test_core_export_parity.py`.

> **When changing serialization, edit the builder — not `to_schema_org()`.**
> The methods only delegate; editing them (or reintroducing inline
> serialization) breaks the ORM ↔ Core-export parity the tests enforce.

### File builder (representative)

`build_file_jsonld(f, categories, companies, people, locations)` maps columns to
schema.org properties (`@type` from `schema_type` or the MIME fallback, `@id`
from `file_iri()`, `dateCreated`/`dateModified`, `encodingFormat`, `contentSize`,
`url`, truncated `text`, `inLanguage`, and `ImageObject` `width`/`height`/`geo`),
then merges the relationship block from `build_file_relationships()`:

```python
# build_file_relationships — the canonical relationship shape
# Primary category  -> mainEntityOfPage (single DefinedTerm ref)
# Remaining categories -> about (list of DefinedTerm refs)
# Companies + people   -> mentions (Organization / Person refs)
# Locations            -> spatialCoverage (single ref, or list when >1)
```

All relationships are emitted as `@id` references (`get_iri()` + `name`), never
inline-embedded entities. See the builder source for the exact per-property
conditionals; the other four builders follow the same column-to-property pattern
described in the **Entity Details** section above.

---

## Validation Checklist

- [ ] `get_iri()` returns correct IRI pattern for the entity type
- [ ] `to_schema_org()` includes `@context`, `@type`, `@id`, `name`
- [ ] Dates serialized as ISO 8601 strings
- [ ] Relationships use `@id` refs only (no inline embedding)
- [ ] NULL / missing fields omitted (not serialized as `None`)
- [ ] Custom properties namespaced under `https://example.com/vocab/`
- [ ] Output passes [validator.schema.org](https://validator.schema.org/)

---

## Resources

- [Schema.org Type Hierarchy](https://schema.org/docs/schemas.html)
- [JSON-LD Playground](https://json-ld.org/playground/)
- [Schema.org Validator](https://validator.schema.org/)
