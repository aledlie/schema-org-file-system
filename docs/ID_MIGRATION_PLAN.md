# ID Generation Migration Plan

**Date**: 2025-12-10
**Version**: 1.0
**Status**: In Progress

## Executive Summary

This plan addresses critical ID generation issues identified in the schema-org-file-system codebase:
1. Missing `@id` fields in Schema.org JSON-LD output (invalid JSON-LD)
2. Auto-increment integer IDs in entity tables (anti-pattern)
3. No merge event tracking for deduplication

## Migration Phases

### Phase 1: Core Infrastructure (Week 1)
**Goal**: Add foundational ID utilities and update base classes

| Task | File | Priority | Status |
|------|------|----------|--------|
| Create `uri_utils.py` | `src/uri_utils.py` | Critical | Pending |
| Add `@id` to SchemaOrgBase | `src/base.py` | Critical | Pending |
| Update generators | `src/generators.py` | Critical | Pending |
| Fix identifier in enrichment | `src/enrichment.py` | High | Pending |

### Phase 2: Database Schema Updates (Week 2)
**Goal**: Add UUID fields to entity models while preserving backward compatibility

| Task | File | Priority | Status |
|------|------|----------|--------|
| Add UUID to Category | `src/storage/models.py` | Critical | Pending |
| Add UUID to Company | `src/storage/models.py` | Critical | Pending |
| Add UUID to Person | `src/storage/models.py` | Critical | Pending |
| Add UUID to Location | `src/storage/models.py` | Critical | Pending |
| Add canonical_id to File | `src/storage/models.py` | High | Pending |
| Create MergeEvent model | `src/storage/models.py` | High | Pending |

### Phase 3: Data Migration (Week 3)
**Goal**: Backfill UUIDs for existing records

| Task | File | Priority | Status |
|------|------|----------|--------|
| Create migration script | `scripts/migrate_ids.py` | Critical | Pending |
| Backfill Category UUIDs | - | Critical | Pending |
| Backfill Company UUIDs | - | Critical | Pending |
| Backfill Person UUIDs | - | Critical | Pending |
| Backfill Location UUIDs | - | Critical | Pending |
| Backfill File canonical_ids | - | High | Pending |

### Phase 4: Integration & Testing (Week 4)
**Goal**: Update all code paths to use new ID system

| Task | File | Priority | Status |
|------|------|----------|--------|
| Update graph_store.py | `src/storage/graph_store.py` | High | Pending |
| Add unit tests | `tests/test_id_generation.py` | High | Pending |
| Update Schema.org output | All generators | High | Pending |

---

## Detailed Implementation

### 1. URI Utilities (`src/uri_utils.py`)

Create new file with:
- Namespace UUIDs for deterministic ID generation
- `generate_file_iri(file_path)` - SHA-256 based URN
- `generate_canonical_iri(entity_type, natural_key)` - UUID v5
- `generate_entity_url(entity_type, entity_id)` - HTTPS URL

```python
NAMESPACES = {
    'file': uuid.UUID('f4e8a9c0-file-file-file-000000000000'),
    'category': uuid.UUID('c4e8a9c0-cate-gory-cate-000000000000'),
    'company': uuid.UUID('c0e1a2b3-comp-pany-comp-000000000000'),
    'person': uuid.UUID('d1e2a3b4-pers-pers-pers-000000000000'),
    'location': uuid.UUID('e2e3a4b5-loca-tion-loca-000000000000'),
}
```

### 2. SchemaOrgBase Updates (`src/base.py`)

Update `__init__` to:
- Accept optional `entity_id` parameter
- Generate UUID v4 if not provided
- Store as `@id` in data dict

```python
def __init__(self, schema_type: str, entity_id: Optional[str] = None):
    if entity_id is None:
        entity_id = f"urn:uuid:{uuid.uuid4()}"
    elif not entity_id.startswith(('http://', 'https://', 'urn:')):
        entity_id = f"urn:uuid:{entity_id}"

    self.data = {
        "@context": SchemaContext.SCHEMA_ORG,
        "@type": schema_type,
        "@id": entity_id  # NEW
    }
```

### 3. Database Model Updates (`src/storage/models.py`)

#### Category, Company, Person, Location

Add to each:
```python
# Keep existing auto-increment as internal ID
id = Column(Integer, primary_key=True, autoincrement=True)

# Add canonical UUID (deterministic from name)
canonical_id = Column(String(36), unique=True, index=True)

# Historical IDs for merge tracking
source_ids = Column(JSON, default=list)

# Merge tracking
merged_into_id = Column(Integer, ForeignKey('categories.id'))

@staticmethod
def generate_canonical_id(name: str) -> str:
    """Generate deterministic UUID v5 from name."""
    return str(uuid.uuid5(NAMESPACES['category'], name.lower().strip()))
```

#### File Model

Add:
```python
# Public canonical ID for Schema.org @id
canonical_id = Column(String(100), unique=True, index=True)

# Historical IDs
source_ids = Column(JSON, default=list)

def get_schema_id(self) -> str:
    """Get the Schema.org @id for this file."""
    return self.canonical_id or f"urn:sha256:{self.id}"
```

#### New MergeEvent Model

```python
class MergeEvent(Base):
    __tablename__ = 'merge_events'

    id = Column(String(36), primary_key=True)  # UUID
    target_entity_type = Column(String(50), nullable=False)
    target_entity_id = Column(Integer, nullable=False)
    source_entity_ids = Column(JSON, nullable=False)
    merge_reason = Column(Text)
    confidence = Column(Float, default=1.0)
    performed_by = Column(String(100))
    performed_at = Column(DateTime, default=datetime.utcnow)
    jsonld = Column(JSON)  # owl:sameAs representation
```

### 4. Enrichment Fix (`src/enrichment.py`)

Line 121: Remove incorrect `identifier` usage:

```python
def enrich_from_file_stats(self, file_path: str) -> Dict[str, Any]:
    path = Path(file_path)
    if not path.exists():
        return {}

    stats = path.stat()
    file_hash = hashlib.sha256(str(path.absolute()).encode()).hexdigest()

    return {
        '@id': f"urn:sha256:{file_hash}",  # ADD
        'name': path.name,
        'url': f'file://{path.absolute()}',
        'encodingFormat': self.get_encoding_format(file_path),
        'contentSize': stats.st_size,
        'dateCreated': datetime.fromtimestamp(stats.st_ctime),
        'dateModified': datetime.fromtimestamp(stats.st_mtime),
        # REMOVED: 'identifier': path.stem,
    }
```

---

## Migration Script Strategy

### Approach: Shadow Columns

1. **Add new columns** alongside existing (no breaking changes)
2. **Backfill new columns** with generated UUIDs
3. **Update application code** to use new columns
4. **Deprecate old patterns** after verification

### Migration SQL (SQLite)

```sql
-- Phase 2: Add new columns
ALTER TABLE categories ADD COLUMN canonical_id VARCHAR(36) UNIQUE;
ALTER TABLE categories ADD COLUMN source_ids JSON DEFAULT '[]';
ALTER TABLE categories ADD COLUMN merged_into_id INTEGER REFERENCES categories(id);

ALTER TABLE companies ADD COLUMN canonical_id VARCHAR(36) UNIQUE;
ALTER TABLE companies ADD COLUMN source_ids JSON DEFAULT '[]';
ALTER TABLE companies ADD COLUMN merged_into_id INTEGER REFERENCES companies(id);

-- Similar for people, locations, files

-- Phase 3: Backfill (done via Python script)
-- UPDATE categories SET canonical_id = ? WHERE id = ?;
```

---

## Rollback Plan

1. **Phase 1 Rollback**: Revert code changes only
2. **Phase 2 Rollback**: New columns are additive, no data loss
3. **Phase 3 Rollback**: Clear new column values, revert code

---

## Success Criteria

### JSON-LD Validation
- [ ] All Schema.org output includes valid `@id` field
- [ ] `@id` values are valid IRIs (urn:uuid: or https://)
- [ ] Google Rich Results Test passes for generated JSON-LD

### Database Integrity
- [ ] All entities have canonical_id populated
- [ ] Canonical IDs are deterministic (same name = same ID)
- [ ] No duplicate canonical_ids within entity type

### Merge Tracking
- [ ] MergeEvent records created for all deduplication
- [ ] `owl:sameAs` relationships properly stored
- [ ] Historical IDs preserved in source_ids

---

## Testing Requirements

```python
# Test: Schema.org @id present
def test_schema_org_has_id():
    from src.generators import DocumentGenerator
    doc = DocumentGenerator()
    doc.set_basic_info("Test", "application/pdf", "https://example.com/test.pdf")
    data = doc.to_dict()
    assert '@id' in data
    assert data['@id'].startswith(('http://', 'https://', 'urn:uuid:'))

# Test: Canonical IDs are deterministic
def test_canonical_id_deterministic():
    from src.storage.models import Category
    id1 = Category.generate_canonical_id("Legal Documents")
    id2 = Category.generate_canonical_id("Legal Documents")
    id3 = Category.generate_canonical_id("legal documents")  # Case insensitive
    assert id1 == id2 == id3

# Test: File @id uses hash
def test_file_schema_id():
    from src.uri_utils import generate_file_iri
    iri = generate_file_iri("/path/to/file.pdf")
    assert iri.startswith("urn:sha256:")
    assert len(iri) == 75  # urn:sha256: + 64 char hash
```

---

## References

- [JSON-LD Specification](https://www.w3.org/TR/json-ld11/)
- [Schema.org Best Practices](https://schema.org/docs/gs.html)
- [RFC 4122 - UUID URN](https://tools.ietf.org/html/rfc4122)
- [RFC 9562 - UUID v7](https://www.rfc-editor.org/rfc/rfc9562.html)
