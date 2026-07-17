# Roadmap

Future enhancements not yet scheduled. Items here are aspirational — no commits reference them.

Source: `REFACTORING_INDEX.md` § Future Enhancements (2026-03-24)

---

## Schema.org Export Pipeline

### Caching
Cache MIME type lookups and builder function results to avoid redundant computation during large batch exports. `MimeTypeMapper` already does O(1) dict lookup; caching builder outputs by input hash would help repeated entity exports.

### Streaming exports — ✅ COMPLETE
Replaced in-memory list accumulation in `SchemaOrgExporter` with a generator pattern (`_stream_array` + lazy `_iter_records`; File path column-select + `yield_per`) so large exports don't blow up RAM. Parity + streaming locked by `tests/integration/test_core_export_parity.py`.

### JSON-LD schema validation on export
Validate exported JSON-LD against the schema.org spec on write (e.g., via `pyld` or `rdflib`). Currently only Pydantic response model validation is in place (`e989a88`).

### Output size optimization
Compress or compact JSON-LD output — deduplicate `@context` blocks, use prefix shortening, or offer a `compact` flag on `SchemaOrgExporter`.

### JSON-LD context file generation — ✅ COMPLETE
Shipped in 2.0.0: `src/storage/schema_org_context.py` generates a standalone `@context` document declaring the `schema:` and `ml:` namespaces (e.g., `ml:hasFaces`), served at `GET /schema/context`. The still-open export-validation item above can resolve custom properties against it.

### Additional serialization formats
Support RDF/XML, N-Triples, and Turtle output formats via `rdflib`. Useful for linked-data consumers that don't accept JSON-LD.
