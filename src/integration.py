"""
Integration layer for Schema.org structured data.

Provides multiple output formats (JSON-LD, microdata, RDFa),
API endpoints, and bulk export functionality.
"""

from typing import (
    Any,
    Dict,
    List,
    NotRequired,
    Optional,
    TYPE_CHECKING,
    TypedDict,
    Union,
    cast,
)
from enum import Enum
from html import escape
import json

from .schema_types import SchemaMapping

if TYPE_CHECKING:
    from .base import SchemaOrgBase


class OutputFormat(Enum):
    """Supported output formats."""
    JSON_LD = "json-ld"
    MICRODATA = "microdata"
    RDFA = "rdfa"
    JSON = "json"


class ApiResponse(TypedDict):
    """API envelope for one schema or the full collection.

    ``count`` is present only on collection responses.
    """
    success: bool
    data: Union[SchemaMapping, List[SchemaMapping]]
    format: str
    count: NotRequired[int]


class RegistryEntry(TypedDict):
    """One registered schema with its metadata."""
    schema: SchemaMapping
    metadata: Dict[str, Any]
    registered_at: str


class RegistryStatistics(TypedDict):
    """Aggregate counts for a SchemaRegistry."""
    total_schemas: int
    types: Dict[str, int]


class SchemaIntegration:
    """
    Integration layer for Schema.org structured data.

    Handles conversion between formats, HTML embedding,
    and provides API-ready output.
    """

    def __init__(self) -> None:
        """Initialize integration layer."""
        self.schemas: List[SchemaMapping] = []

    def add_schema(self, schema: Union[SchemaMapping, 'SchemaOrgBase']) -> 'SchemaIntegration':
        """
        Add schema to collection.

        Args:
            schema: Schema dictionary or SchemaOrgBase instance

        Returns:
            Self for method chaining
        """
        if hasattr(schema, 'to_dict'):
            # mypy can't intersect Mapping with a to_dict protocol; the
            # duck-typed branch is only reachable for SchemaOrgBase-likes.
            schema = cast('SchemaOrgBase', schema).to_dict()
        self.schemas.append(schema)
        return self

    def to_json_ld(self, schema: Optional[SchemaMapping] = None,
                   indent: int = 2) -> str:
        """
        Convert to JSON-LD format.

        Args:
            schema: Specific schema to convert (or use all schemas)
            indent: JSON indentation

        Returns:
            JSON-LD string
        """
        if schema is None:
            if len(self.schemas) == 1:
                data = self.schemas[0]
            else:
                data = {"@graph": self.schemas}
        else:
            data = schema

        return json.dumps(data, indent=indent, ensure_ascii=False)

    def to_json_ld_script(self, schema: Optional[SchemaMapping] = None,
                         indent: int = 2) -> str:
        """
        Convert to JSON-LD script tag for HTML.

        Args:
            schema: Specific schema to convert
            indent: JSON indentation

        Returns:
            HTML script tag with JSON-LD
        """
        json_ld = self.to_json_ld(schema, indent)
        return f'<script type="application/ld+json">\n{json_ld}\n</script>'

    def to_microdata(self, schema: SchemaMapping,
                     tag: str = "div") -> str:
        """
        Convert to HTML5 microdata format.

        Args:
            schema: Schema dictionary
            tag: HTML tag to use

        Returns:
            HTML with microdata attributes
        """
        schema_type = schema.get("@type", "Thing")
        html_parts = [f'<{tag} itemscope itemtype="https://schema.org/{schema_type}">']

        for key, value in schema.items():
            if key.startswith("@"):
                continue

            if isinstance(value, dict) and "@type" in value:
                # Nested schema
                html_parts.append(self.to_microdata(value, tag="div"))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and "@type" in item:
                        html_parts.append(self.to_microdata(item, tag="div"))
                    else:
                        html_parts.append(
                            f'  <meta itemprop="{key}" content="{escape(str(item))}">'
                        )
            else:
                # Simple property
                if key in ["url", "contentUrl", "thumbnailUrl"]:
                    html_parts.append(
                        f'  <link itemprop="{key}" href="{escape(str(value))}">'
                    )
                elif key in ["image", "logo"]:
                    if isinstance(value, str):
                        html_parts.append(
                            f'  <link itemprop="{key}" href="{escape(value)}">'
                        )
                else:
                    html_parts.append(
                        f'  <meta itemprop="{key}" content="{escape(str(value))}">'
                    )

        html_parts.append(f'</{tag}>')
        return '\n'.join(html_parts)

    def to_rdfa(self, schema: SchemaMapping,
                tag: str = "div") -> str:
        """
        Convert to RDFa format.

        Args:
            schema: Schema dictionary
            tag: HTML tag to use

        Returns:
            HTML with RDFa attributes
        """
        schema_type = schema.get("@type", "Thing")
        html_parts = [
            f'<{tag} vocab="https://schema.org/" typeof="{schema_type}">'
        ]

        for key, value in schema.items():
            if key.startswith("@"):
                continue

            if isinstance(value, dict) and "@type" in value:
                # Nested schema
                nested_html = self.to_rdfa(value, tag="div")
                html_parts.append(f'  <div property="{key}">')
                html_parts.append(f'    {nested_html}')
                html_parts.append('  </div>')
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and "@type" in item:
                        nested_html = self.to_rdfa(item, tag="div")
                        html_parts.append(f'  <div property="{key}">')
                        html_parts.append(f'    {nested_html}')
                        html_parts.append('  </div>')
                    else:
                        html_parts.append(
                            f'  <meta property="{key}" content="{escape(str(item))}">'
                        )
            else:
                # Simple property
                if key in ["url", "contentUrl", "thumbnailUrl"]:
                    html_parts.append(
                        f'  <link property="{key}" href="{escape(str(value))}">'
                    )
                else:
                    html_parts.append(
                        f'  <meta property="{key}" content="{escape(str(value))}">'
                    )

        html_parts.append(f'</{tag}>')
        return '\n'.join(html_parts)

    def export_format(self, format: OutputFormat,
                     schema: Optional[SchemaMapping] = None) -> str:
        """
        Export in specified format.

        Args:
            format: Output format
            schema: Specific schema (or use all)

        Returns:
            Formatted string
        """
        if schema is None and len(self.schemas) > 0:
            schema = self.schemas[0]

        if format == OutputFormat.JSON_LD:
            return self.to_json_ld(schema)
        if format == OutputFormat.JSON:
            return json.dumps(schema, indent=2)

        if schema is None:
            raise ValueError("No schema available to export")

        if format == OutputFormat.MICRODATA:
            return self.to_microdata(schema)
        if format == OutputFormat.RDFA:
            return self.to_rdfa(schema)

        raise ValueError(f"Unsupported format: {format}")

    def export_all(self, format: OutputFormat) -> List[str]:
        """
        Export all schemas in specified format.

        Args:
            format: Output format

        Returns:
            List of formatted strings
        """
        return [self.export_format(format, schema) for schema in self.schemas]

    def create_html_page(self, title: str,
                        content: str,
                        format: OutputFormat = OutputFormat.JSON_LD) -> str:
        """
        Create complete HTML page with embedded structured data.

        Args:
            title: Page title
            content: Page content HTML
            format: Structured data format to use

        Returns:
            Complete HTML page
        """
        structured_data = ""
        if format == OutputFormat.JSON_LD:
            structured_data = self.to_json_ld_script()
        elif format == OutputFormat.MICRODATA:
            # Microdata is embedded in content
            structured_data = "<!-- Microdata embedded in content -->"
        elif format == OutputFormat.RDFA:
            # RDFa is embedded in content
            structured_data = "<!-- RDFa embedded in content -->"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape(title)}</title>
    {structured_data}
</head>
<body>
    {content}
</body>
</html>"""
        return html

    def get_api_response(self, schema_id: Optional[str] = None) -> ApiResponse:
        """
        Get API-ready response.

        Args:
            schema_id: Specific schema ID (or return all)

        Returns:
            API response dictionary
        """
        if schema_id is not None:
            # In real implementation, look up by ID
            schema: SchemaMapping = self.schemas[0] if self.schemas else {}
            return {
                "success": True,
                "data": schema,
                "format": "application/ld+json"
            }
        else:
            return {
                "success": True,
                "data": self.schemas,
                "count": len(self.schemas),
                "format": "application/ld+json"
            }

    def export_bulk(self, format: OutputFormat,
                   file_path: str) -> None:
        """
        Export all schemas to file.

        Args:
            format: Output format
            file_path: Output file path
        """
        if format == OutputFormat.JSON_LD or format == OutputFormat.JSON:
            data = {"@graph": self.schemas} if len(self.schemas) > 1 else self.schemas[0]
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        else:
            # For HTML formats, create one file per schema
            base_path = file_path.rsplit('.', 1)[0]
            for i, schema in enumerate(self.schemas):
                output = self.export_format(format, schema)
                with open(f"{base_path}_{i}.html", 'w', encoding='utf-8') as f:
                    f.write(output)

    def clear(self) -> None:
        """Clear all schemas."""
        self.schemas = []


class SchemaRegistry:
    """
    Registry for managing multiple schemas with metadata.

    Provides indexing, search, and retrieval capabilities.
    """

    def __init__(self) -> None:
        """Initialize registry."""
        self.registry: Dict[str, RegistryEntry] = {}

    def register(self, schema_id: str, schema: SchemaMapping,
                metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Register a schema.

        Args:
            schema_id: Unique schema identifier
            schema: Schema dictionary
            metadata: Additional metadata
        """
        self.registry[schema_id] = {
            "schema": schema,
            "metadata": metadata or {},
            "registered_at": str(json.dumps({"timestamp": "now"}))
        }

    def get(self, schema_id: str) -> Optional[SchemaMapping]:
        """Get schema by ID."""
        entry = self.registry.get(schema_id)
        return entry["schema"] if entry else None

    def get_by_type(self, schema_type: str) -> List[SchemaMapping]:
        """Get all schemas of specific type."""
        results = []
        for entry in self.registry.values():
            schema = entry["schema"]
            if schema.get("@type") == schema_type:
                results.append(schema)
        return results

    def search(self, query: str) -> List[SchemaMapping]:
        """
        Search schemas by text.

        Args:
            query: Search query

        Returns:
            List of matching schemas
        """
        results = []
        query_lower = query.lower()
        for entry in self.registry.values():
            schema = entry["schema"]
            # Search in name and description
            if (query_lower in str(schema.get("name", "")).lower() or
                query_lower in str(schema.get("description", "")).lower()):
                results.append(schema)
        return results

    def list_all(self) -> List[str]:
        """List all schema IDs."""
        return list(self.registry.keys())

    def count(self) -> int:
        """Get total count of schemas."""
        return len(self.registry)

    def remove(self, schema_id: str) -> bool:
        """
        Remove schema by ID.

        Args:
            schema_id: Schema ID to remove

        Returns:
            True if removed, False if not found
        """
        if schema_id in self.registry:
            del self.registry[schema_id]
            return True
        return False

    def export_all(self) -> List[SchemaMapping]:
        """Export all schemas."""
        return [entry["schema"] for entry in self.registry.values()]

    def get_statistics(self) -> RegistryStatistics:
        """Get registry statistics."""
        type_counts: Dict[str, int] = {}
        for entry in self.registry.values():
            schema_type = str(entry["schema"].get("@type", "Unknown"))
            type_counts[schema_type] = type_counts.get(schema_type, 0) + 1

        return {
            "total_schemas": len(self.registry),
            "types": type_counts
        }
