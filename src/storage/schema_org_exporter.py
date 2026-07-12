"""
Unified service for exporting entities to schema.org JSON-LD in various formats.

Supports three output formats:
  - json   : JSON array, pretty-printed by default
  - ndjson : Newline-delimited JSON (one entity per line, streaming-friendly)
  - graph  : JSON-LD @graph structure (recommended for multiple entity types)
"""

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Type, Union

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, joinedload

from .schema_org_base import SchemaOrgSerializable

SCHEMA_ORG_CONTEXT = "https://schema.org"


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
                    fh, self._iter_records(entity_classes),
                    pretty=True, indent_level=2, strip_context=True,
                )
                fh.write("\n}")
            else:
                fh.write('{"@context":' + context + ',"@graph":')
                count = self._stream_array(
                    fh, self._iter_records(entity_classes),
                    pretty=False, indent_level=2, strip_context=True,
                )
                fh.write("}")
        return count

    def get_graph_document(
        self,
        entity_classes: Optional[List[Type[SchemaOrgSerializable]]] = None,
    ) -> Dict[str, Any]:
        """Return a JSON-LD @graph document as a Python dict (no I/O).

        Useful for in-memory use, REST API responses, etc.

        Args:
            entity_classes: List of SQLAlchemy model classes to export.

        Returns:
            Dict with "@context" and "@graph" keys.
        """
        records = self._collect_records(entity_classes)
        graph_nodes = [{k: v for k, v in rec.items() if k != "@context"} for rec in records]
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
        entity_ids: Sequence[Any],
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
                fh, self._iter_filtered_records(entity_class, entity_ids),
                pretty=pretty, indent_level=1,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_records(
        self,
        entity_classes: Optional[List[Type[SchemaOrgSerializable]]],
    ) -> List[Dict[str, Any]]:
        """Query all instances of each entity class and call to_schema_org().

        Args:
            entity_classes: Classes to query; None queries default entity types.

        Returns:
            Flat list of JSON-LD dicts.
        """
        if entity_classes is None:
            entity_classes = self._default_entity_classes()

        if self._use_core:
            return self._collect_records_core(entity_classes)

        load_options = self._build_load_options()
        records: List[Dict[str, Any]] = []
        for cls in entity_classes:
            opts = load_options.get(cls, [])
            q = self._session.query(cls)
            if opts:
                q = q.options(*opts)
            for row in q.all():
                records.append(row.to_schema_org())
        return records

    # ------------------------------------------------------------------
    # Core-query collection (use_core=True)
    # ------------------------------------------------------------------

    def _collect_records_core(
        self,
        entity_classes: List[Type[SchemaOrgSerializable]],
    ) -> List[Dict[str, Any]]:
        """Collect records via Core column queries, skipping ORM hydration.

        Each entity's JSON-LD is built by the shared ``build_*_jsonld`` functions
        in ``models.py`` (the same functions ``to_schema_org()`` delegates to),
        so output is identical to the ORM path. Entity types without a Core
        builder fall back to per-object ORM serialization.
        """
        from . import models as m

        builders = {
            m.File: self._core_file_records,
            m.Category: self._core_category_records,
            m.Company: lambda: self._core_simple_records(m.Company, m.build_company_jsonld),
            m.Person: lambda: self._core_simple_records(m.Person, m.build_person_jsonld),
            m.Location: lambda: self._core_simple_records(m.Location, m.build_location_jsonld),
        }

        records: List[Dict[str, Any]] = []
        for cls in entity_classes:
            builder = builders.get(cls)
            if builder is not None:
                records.extend(builder())
            else:  # unknown type: fall back to ORM serialization
                records.extend(row.to_schema_org() for row in self._session.query(cls).all())
        return records

    def _core_simple_records(self, cls, build_fn) -> List[Dict[str, Any]]:
        """Core records for an entity whose serialization reads no relationships."""
        return [build_fn(row) for row in self._session.execute(select(cls)).scalars()]

    def _core_file_records(self) -> List[Dict[str, Any]]:
        """Core records for File, with relationship refs bulk-loaded per file."""
        from . import models as m

        cats = self._load_file_refs(m.file_categories.c.category_id, m.Category)
        comps = self._load_file_refs(m.file_companies.c.company_id, m.Company)
        ppl = self._load_file_refs(m.file_people.c.person_id, m.Person)
        locs = self._load_file_refs(m.file_locations.c.location_id, m.Location)

        empty: tuple = ()
        records = []
        for f in self._session.execute(select(m.File)).scalars():
            fid = f.id
            records.append(m.build_file_jsonld(
                f,
                cats.get(fid, empty),
                comps.get(fid, empty),
                ppl.get(fid, empty),
                locs.get(fid, empty),
            ))
        return records

    def _core_category_records(self) -> List[Dict[str, Any]]:
        """Core records for Category, resolving parent/subcategory refs in-memory."""
        from . import models as m

        rows = list(self._session.execute(
            select(m.Category).order_by(m.Category.id)
        ).scalars())
        ref = {r.id: _EntityRef(f"urn:uuid:{r.canonical_id}", r.name) for r in rows}

        children: Dict[Any, list] = {}
        for r in rows:
            if r.parent_id is not None:
                children.setdefault(r.parent_id, []).append(ref[r.id])

        records = []
        for r in rows:
            parent = ref.get(r.parent_id) if r.parent_id is not None else None
            records.append(m.build_category_jsonld(r, parent, children.get(r.id, ())))
        return records

    def _load_file_refs(self, target_id_col, target_cls) -> Dict[Any, list]:
        """Map file_id -> ordered list of _EntityRef for one association table.

        Association rows are read in natural (insertion) order to match the
        order the ORM relationship yields, which the JSON-LD builders depend on
        (e.g. the first category becomes ``mainEntityOfPage``).
        """
        refs = {
            tid: _EntityRef(f"urn:uuid:{canon}", name)
            for tid, canon, name in self._session.execute(
                select(target_cls.id, target_cls.canonical_id, target_cls.name)
            )
        }
        assoc = target_id_col.table
        result: Dict[Any, list] = {}
        for file_id, target_id in self._session.execute(
            select(assoc.c.file_id, target_id_col)
        ):
            result.setdefault(file_id, []).append(refs[target_id])
        return result

    # ------------------------------------------------------------------
    # Context document helpers (S8)
    # ------------------------------------------------------------------

    def get_context_document(self) -> Dict[str, Any]:
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
