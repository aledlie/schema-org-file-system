"""
Unified service for exporting entities to schema.org JSON-LD in various formats.

Supports three output formats:
  - json   : JSON array, pretty-printed by default
  - ndjson : Newline-delimited JSON (one entity per line, streaming-friendly)
  - graph  : JSON-LD @graph structure (recommended for multiple entity types)
"""

import json
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Type,
    Union,
    cast,
)

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, joinedload

from .schema_org_base import SchemaOrgSerializable

try:
    from ..schema_types import GraphDocument, SchemaMapping
except ImportError:  # flat-module import path (src on sys.path)
    from schema_types import GraphDocument, SchemaMapping  # type: ignore[no-redef]

SCHEMA_ORG_CONTEXT = "https://schema.org"

# Row-fetch batch size for streaming File exports (caps peak memory).
_STREAM_BATCH = 2000


class _EntityRef:
    """Minimal relationship stand-in exposing ``get_iri()`` and ``name``.

    Used by the Core-query path so the shared JSON-LD builders (which iterate
    related entities calling ``get_iri()``/``name``) work without hydrating full
    ORM objects. All relationship targets (Category/Company/Person/Location)
    use ``urn:uuid:{canonical_id}`` IRIs, precomputed here.
    """

    __slots__ = ("_iri", "name")

    def __init__(self, iri: str, name: str) -> None:
        self._iri = iri
        self.name = name

    def get_iri(self) -> str:
        return self._iri


class SchemaOrgExporter:
    """Export schema.org JSON-LD for one or more entity types.

    Usage::

        exporter = SchemaOrgExporter(session)
        exporter.export_to_file("out.json", entity_classes=[File, Category])
        exporter.export_to_ndjson("out.ndjson", entity_classes=[File])
        exporter.export_with_graph("out-graph.json")

    Records are collected via Core column queries (default) instead of ORM
    hydration — byte-identical output (both paths share the JSON-LD builders in
    ``models.py``) but ~3x faster for large bulk exports by avoiding per-entity
    ORM object construction. Unknown entity types fall back to ORM automatically.
    Pass ``use_core=False`` to force the ORM path.
    """

    def __init__(self, session: Session, use_core: bool = True) -> None:
        self._session = session
        self._use_core = use_core

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def export_to_file(
        self,
        output_path: Union[str, Path],
        entity_classes: Optional[List[Type[SchemaOrgSerializable]]] = None,
        pretty: bool = True,
    ) -> int:
        """Export entities to a JSON file (array of JSON-LD objects).

        Args:
            output_path: Destination file path.
            entity_classes: List of SQLAlchemy model classes to export.
                Defaults to all registered entity types when None.
            pretty: Whether to pretty-print (indent=2).

        Returns:
            Total number of entities written.
        """
        with open(output_path, "w", encoding="utf-8") as fh:
            return self._stream_array(
                fh, self._iter_records(entity_classes), pretty=pretty, indent_level=1
            )

    def export_to_ndjson(
        self,
        output_path: Union[str, Path],
        entity_classes: Optional[List[Type[SchemaOrgSerializable]]] = None,
    ) -> int:
        """Export entities to a newline-delimited JSON file.

        Each entity is serialized to a single line and written as it is produced,
        so memory stays flat regardless of export size. Suitable for streaming
        and large-scale processing.

        Args:
            output_path: Destination file path.
            entity_classes: List of SQLAlchemy model classes to export.

        Returns:
            Total number of entities written.
        """
        count = 0
        with open(output_path, "w", encoding="utf-8") as fh:
            for rec in self._iter_records(entity_classes):
                fh.write(json.dumps(rec, separators=(",", ":")))
                fh.write("\n")
                count += 1
        return count

    def export_with_graph(
        self,
        output_path: Union[str, Path],
        entity_classes: Optional[List[Type[SchemaOrgSerializable]]] = None,
        pretty: bool = True,
    ) -> int:
        """Export entities as a JSON-LD @graph document.

        The output structure is::

            {
                "@context": "https://schema.org",
                "@graph": [ ... ]
            }

        Each entity in @graph omits its own @context (it is hoisted to the
        document root).

        Args:
            output_path: Destination file path.
            entity_classes: List of SQLAlchemy model classes to export.
            pretty: Whether to pretty-print (indent=2).

        Returns:
            Total number of entities written.
        """
        context = json.dumps(SCHEMA_ORG_CONTEXT)
        with open(output_path, "w", encoding="utf-8") as fh:
            if pretty:
                fh.write('{\n  "@context": ' + context + ',\n  "@graph": ')
                count = self._stream_array(
                    fh,
                    self._iter_records(entity_classes),
                    pretty=True,
                    indent_level=2,
                    strip_context=True,
                )
                fh.write("\n}")
            else:
                fh.write('{"@context":' + context + ',"@graph":')
                count = self._stream_array(
                    fh,
                    self._iter_records(entity_classes),
                    pretty=False,
                    indent_level=2,
                    strip_context=True,
                )
                fh.write("}")
        return count

    def get_graph_document(
        self,
        entity_classes: Optional[List[Type[SchemaOrgSerializable]]] = None,
    ) -> GraphDocument:
        """Return a JSON-LD @graph document as a Python dict (no I/O).

        Useful for in-memory use, REST API responses, etc.

        Args:
            entity_classes: List of SQLAlchemy model classes to export.

        Returns:
            Dict with "@context" and "@graph" keys.
        """
        records = self._collect_records(entity_classes)
        graph_nodes: List[SchemaMapping] = [
            {k: v for k, v in rec.items() if k != "@context"} for rec in records
        ]
        return {
            "@context": SCHEMA_ORG_CONTEXT,
            "@graph": graph_nodes,
        }

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------

    def export_entities_filtered(
        self,
        output_path: Union[str, Path],
        entity_class: Type[SchemaOrgSerializable],
        entity_ids: Sequence[Union[str, int]],
        pretty: bool = True,
    ) -> int:
        """Export a filtered subset of entities by primary key.

        Args:
            output_path: Destination file path.
            entity_class: SQLAlchemy model class to query.
            entity_ids: Primary key values to include.
            pretty: Whether to pretty-print.

        Returns:
            Number of entities written.
        """
        with open(output_path, "w", encoding="utf-8") as fh:
            return self._stream_array(
                fh,
                self._iter_filtered_records(entity_class, entity_ids),
                pretty=pretty,
                indent_level=1,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _stream_array(
        fh,
        records: Iterable[Dict[str, Any]],
        *,
        pretty: bool,
        indent_level: int = 1,
        strip_context: bool = False,
    ) -> int:
        """Write ``records`` to ``fh`` as a JSON array, one record at a time.

        Streams so peak memory stays flat regardless of record count (only one
        record is dumped at a time). Output parses identically to
        ``json.dumps(list(records))``. ``pretty`` indents 2 spaces per level;
        ``indent_level`` is the nesting depth of the array's elements (1 for a
        top-level array, 2 for a nested ``@graph``). ``strip_context`` drops each
        record's ``@context`` key (for ``@graph`` nodes). Returns the count.
        """
        count = 0
        if pretty:
            elem_pad = "  " * indent_level
            fh.write("[")
            for rec in records:
                if strip_context and "@context" in rec:
                    rec = {k: v for k, v in rec.items() if k != "@context"}
                fh.write(",\n" if count else "\n")
                block = json.dumps(rec, indent=2)
                fh.write("\n".join(elem_pad + line for line in block.split("\n")))
                count += 1
            if count:
                fh.write("\n" + "  " * (indent_level - 1))
            fh.write("]")
        else:
            fh.write("[")
            for rec in records:
                if strip_context and "@context" in rec:
                    rec = {k: v for k, v in rec.items() if k != "@context"}
                if count:
                    fh.write(",")
                fh.write(json.dumps(rec, separators=(",", ":")))
                count += 1
            fh.write("]")
        return count

    def _collect_records(
        self,
        entity_classes: Optional[List[Type[SchemaOrgSerializable]]],
    ) -> List[Dict[str, Any]]:
        """Materialize all records into a list (for in-memory callers)."""
        return list(self._iter_records(entity_classes))

    def _iter_records(
        self,
        entity_classes: Optional[List[Type[SchemaOrgSerializable]]],
    ) -> Iterator[Dict[str, Any]]:
        """Lazily yield JSON-LD dicts for each entity class, one at a time.

        The lazy form lets the streaming writers hold at most one record in
        memory. Dispatches to the Core-query path (default) or the ORM path.
        """
        if entity_classes is None:
            entity_classes = self._default_entity_classes()
        if self._use_core:
            yield from self._iter_records_core(entity_classes)
        else:
            yield from self._iter_records_orm(entity_classes)

    def _iter_records_orm(
        self,
        entity_classes: List[Type[SchemaOrgSerializable]],
    ) -> Iterator[Dict[str, Any]]:
        """ORM path: hydrate each entity and call its ``to_schema_org()``."""
        load_options = self._build_load_options()
        for cls in entity_classes:
            opts = load_options.get(cls, [])
            q = self._session.query(cls)
            if opts:
                q = q.options(*opts)
            for row in q.all():
                yield row.to_schema_org()

    # ------------------------------------------------------------------
    # Core-query collection (use_core=True)
    # ------------------------------------------------------------------

    def _iter_records_core(
        self,
        entity_classes: List[Type[SchemaOrgSerializable]],
    ) -> Iterator[Dict[str, Any]]:
        """Core path: build JSON-LD from column queries, skipping ORM hydration.

        Each entity's dict comes from the shared ``build_*_jsonld`` functions in
        ``models.py`` (the same ones ``to_schema_org()`` delegates to), so output
        is identical to the ORM path. Unknown types fall back to ORM.
        """
        from . import models as m

        iterators: Dict[Type[SchemaOrgSerializable], Callable[[], Iterator[Dict[str, Any]]]] = {
            m.File: lambda: self._iter_core_file_records(),
            m.Category: lambda: self._iter_core_category_records(),
            m.Company: lambda: self._iter_core_simple_records(m.Company, m.build_company_jsonld),
            m.Person: lambda: self._iter_core_simple_records(m.Person, m.build_person_jsonld),
            m.Location: lambda: self._iter_core_simple_records(m.Location, m.build_location_jsonld),
        }
        for cls in entity_classes:
            it = iterators.get(cls)
            if it is not None:
                yield from it()
            else:  # unknown type: fall back to ORM serialization
                for row in self._session.query(cls).all():
                    yield row.to_schema_org()

    def _iter_filtered_records(
        self,
        entity_class: Type[SchemaOrgSerializable],
        entity_ids: Sequence[Union[str, int]],
    ) -> Iterator[Dict[str, Any]]:
        """Yield records for a subset of one entity class, by primary key.

        Uses the Core path (relationship refs scoped to the subset — see
        ``_load_file_refs``) for File and the relationship-free entities;
        Category and unknown types use ORM ``to_schema_org()`` (identical output).
        """
        from . import models as m

        if self._use_core and entity_class is m.File:
            yield from self._iter_core_file_records(file_ids=set(entity_ids))
        elif self._use_core and entity_class is m.Company:
            yield from self._iter_core_simple_records(m.Company, m.build_company_jsonld, entity_ids)
        elif self._use_core and entity_class is m.Person:
            yield from self._iter_core_simple_records(m.Person, m.build_person_jsonld, entity_ids)
        elif self._use_core and entity_class is m.Location:
            yield from self._iter_core_simple_records(
                m.Location, m.build_location_jsonld, entity_ids
            )
        else:
            pk = cast(Any, entity_class).__mapper__.primary_key[0]
            for row in self._session.query(entity_class).filter(pk.in_(entity_ids)).all():
                yield row.to_schema_org()

    def _iter_core_simple_records(
        self, cls, build_fn, pk_ids: Optional[Sequence[Union[str, int]]] = None
    ) -> Iterator[Dict[str, Any]]:
        """Yield records for an entity whose serialization reads no relationships.

        ``pk_ids`` optionally scopes the query to those primary keys.
        """
        stmt = select(cls)
        if pk_ids is not None:
            stmt = stmt.where(cls.__mapper__.primary_key[0].in_(pk_ids))
        for row in self._session.execute(stmt).scalars():
            yield build_fn(row)

    def _iter_core_file_records(self, file_ids: Optional[set] = None) -> Iterator[Dict[str, Any]]:
        """Yield File records, streaming rows in batches to keep memory flat.

        Selects only the columns the JSON-LD builder reads (lightweight ``Row``s,
        no ORM File construction) and fetches them with ``yield_per`` so peak
        memory does not scale with file count. Relationship refs are pre-loaded
        into lookup maps (bounded by the number of related entities, not files);
        ``file_ids`` scopes both the file query and the ref loading to a subset.
        """
        from . import models as m

        F = m.File
        columns = (
            F.id,
            F.canonical_id,
            F.filename,
            F.schema_type,
            F.mime_type,
            F.created_at,
            F.modified_at,
            F.file_size,
            F.original_path,
            F.extracted_text,
            F.detected_language,
            F.image_width,
            F.image_height,
            F.has_faces,
            F.exif_datetime,
            F.gps_latitude,
            F.gps_longitude,
            F.schema_data,
        )

        cats = self._load_file_refs(m.file_categories.c.category_id, m.Category, file_ids)
        comps = self._load_file_refs(m.file_companies.c.company_id, m.Company, file_ids)
        ppl = self._load_file_refs(m.file_people.c.person_id, m.Person, file_ids)
        locs = self._load_file_refs(m.file_locations.c.location_id, m.Location, file_ids)

        empty: tuple = ()
        stmt = select(*columns)
        if file_ids is not None:
            stmt = stmt.where(F.id.in_(file_ids))
        stmt = stmt.execution_options(yield_per=_STREAM_BATCH)
        for f in self._session.execute(stmt):
            fid = f.id
            yield m.build_file_jsonld(
                f,
                cats.get(fid, empty),
                comps.get(fid, empty),
                ppl.get(fid, empty),
                locs.get(fid, empty),
            )

    def _iter_core_category_records(self) -> Iterator[Dict[str, Any]]:
        """Yield Category records, resolving parent/subcategory refs in-memory.

        Categories are loaded fully (a first pass is needed to resolve parent and
        subcategory refs); their count is modest relative to files.
        """
        from . import models as m

        rows = list(self._session.execute(select(m.Category).order_by(m.Category.id)).scalars())
        ref = {r.id: _EntityRef(f"urn:uuid:{r.canonical_id}", r.name) for r in rows}

        children: Dict[int, List[_EntityRef]] = {}
        for r in rows:
            if r.parent_id is not None:
                children.setdefault(r.parent_id, []).append(ref[r.id])

        for r in rows:
            parent = ref.get(r.parent_id) if r.parent_id is not None else None
            yield m.build_category_jsonld(r, parent, children.get(r.id, ()))

    def _load_file_refs(
        self, target_id_col, target_cls, file_ids: Optional[set] = None
    ) -> Dict[str, List[_EntityRef]]:
        """Map file_id -> ordered list of _EntityRef for one association table.

        Association rows are read in natural (insertion) order to match the order
        the ORM relationship yields, which the JSON-LD builders depend on (e.g.
        the first category becomes ``mainEntityOfPage``) — do not add ORDER BY.
        Only targets actually referenced are loaded; ``file_ids`` scopes the
        associations to a subset so filtered exports stay cheap.
        """
        assoc = target_id_col.table
        assoc_stmt = select(assoc.c.file_id, target_id_col)
        if file_ids is not None:
            assoc_stmt = assoc_stmt.where(assoc.c.file_id.in_(file_ids))
        pairs = list(self._session.execute(assoc_stmt))
        if not pairs:
            return {}

        ref_stmt = select(target_cls.id, target_cls.canonical_id, target_cls.name)
        if file_ids is not None:
            # Scoped export: load only the referenced targets. (For a full export
            # we load all targets unfiltered — an IN() over every referenced id
            # could exceed SQLite's bound-parameter limit.)
            needed = {target_id for _, target_id in pairs}
            ref_stmt = ref_stmt.where(target_cls.id.in_(needed))
        refs = {
            tid: _EntityRef(f"urn:uuid:{canon}", name)
            for tid, canon, name in self._session.execute(ref_stmt)
        }
        result: Dict[str, List[_EntityRef]] = {}
        for file_id, target_id in pairs:
            result.setdefault(file_id, []).append(refs[target_id])
        return result

    # ------------------------------------------------------------------
    # Context document helpers (S8)
    # ------------------------------------------------------------------

    def get_context_document(self) -> Dict[str, Dict[str, str]]:
        """Return the JSON-LD @context document as a Python dict.

        Delegates to :mod:`storage.schema_org_context`.

        Returns:
            Dict containing the standalone @context document.
        """
        from .schema_org_context import get_context_document

        return get_context_document()

    def export_context(
        self,
        output_path: Union[str, Path],
        pretty: bool = True,
    ) -> None:
        """Save the JSON-LD @context document to a file.

        Args:
            output_path: Destination file path.
            pretty: Whether to pretty-print (indent=2).
        """
        from .schema_org_context import export_context

        export_context(output_path, pretty=pretty)

    @staticmethod
    def _build_load_options() -> Dict[Type, List]:
        """Return per-entity selectinload options to avoid N+1 queries."""
        from .models import File, Category, Company, Person, Location

        return {
            File: [
                selectinload(File.categories),
                selectinload(File.companies),
                selectinload(File.people),
                selectinload(File.locations),
            ],
            Category: [
                selectinload(Category.files),
                joinedload(Category.parent),
                selectinload(Category.subcategories),
            ],
            Company: [selectinload(Company.files)],
            Person: [selectinload(Person.files)],
            Location: [selectinload(Location.files)],
        }

    @staticmethod
    def _default_entity_classes() -> List[Type[SchemaOrgSerializable]]:
        """Return the canonical set of entity classes for full exports."""
        # Import here to avoid circular imports at module load time
        from .models import File, Category, Company, Person, Location

        return [File, Category, Company, Person, Location]
