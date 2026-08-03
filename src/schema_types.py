"""Shared typing aliases for schema.org JSON-LD payloads.

Dependency-free on purpose: importable from the API layer (which cannot
import ``src.integration`` without dragging in the whole ``src`` package
init) as well as from ``src.integration`` itself.

pydantic's ``JsonValue`` supplies the recursive leaf union; the aggregate
is hand-rolled with covariant Mapping/Sequence so schema collections nest
(e.g. ``{"@graph": [...]}``) and narrow caller dicts are accepted without
invariance false-positives. Values extracted back out of ``JsonValue`` are
``dict[str, JsonValue]``, so schema-walking code must accept
``SchemaMapping``, never a concrete ``Dict``.
"""

from typing import List, Mapping, Sequence, TypedDict, Union

from pydantic import JsonValue

SchemaValue = Union[JsonValue, "SchemaMapping", Sequence["SchemaValue"]]
SchemaMapping = Mapping[str, SchemaValue]

# JSON-LD @graph envelope shared by the exporter and the API's bulk/export/
# graph routes (functional syntax: @-prefixed keys are not identifiers).
# @context is SchemaValue because producers emit either the plain
# "https://schema.org" string or the full term-map dict.
GraphDocument = TypedDict(
    "GraphDocument", {"@context": SchemaValue, "@graph": List[SchemaMapping]}
)

__all__ = ["GraphDocument", "SchemaMapping", "SchemaValue"]
