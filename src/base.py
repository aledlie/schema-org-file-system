"""
Base classes for Schema.org generation system.

Provides core functionality for all Schema.org generators including
context management, property validation, and nested schema support.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum
import json
import uuid


class SchemaContext:
    """Manages Schema.org context and namespace."""

    SCHEMA_ORG = "https://schema.org"
    DEFAULT_CONTEXT = {
        "@context": "https://schema.org",
        "@vocab": "https://schema.org/"
    }

    @classmethod
    def get_context(cls, additional_contexts: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Get Schema.org context with optional additional contexts.

        Args:
            additional_contexts: Additional context mappings to include

        Returns:
            Complete context dictionary
        """
        context = cls.DEFAULT_CONTEXT.copy()
        if additional_contexts:
            context.update(additional_contexts)
        return context


class PropertyType(Enum):
    """Schema.org property types."""
    TEXT = "Text"
    URL = "URL"
    DATE = "Date"
    DATETIME = "DateTime"
    NUMBER = "Number"
    INTEGER = "Integer"
    BOOLEAN = "Boolean"
    OBJECT = "Object"
    ARRAY = "Array"


class SchemaOrgBase(ABC):
    """
    Base class for all Schema.org generators.

    Provides common functionality for creating, validating, and managing
    Schema.org structured data across different file types.

    All generated Schema.org objects include a valid @id field for JSON-LD
    compliance. The @id can be:
    - Auto-generated UUID v4 (default)
    - Deterministic UUID v5 from a natural key
    - Custom IRI (HTTPS URL or URN)
    """

    def __init__(self, schema_type: str, entity_id: Optional[str] = None):
        """
        Initialize the Schema.org generator.

        Args:
            schema_type: The Schema.org type (e.g., 'DigitalDocument', 'ImageObject')
            entity_id: Optional entity ID. If not provided, generates UUID v4.
                      Can be a UUID string, URN, or HTTPS URL.

        Examples:
            # Auto-generated ID
            doc = DocumentGenerator()

            # Custom UUID
            doc = DocumentGenerator(entity_id='550e8400-e29b-41d4-a716-446655440000')

            # URN format
            doc = DocumentGenerator(entity_id='urn:sha256:abc123...')

            # HTTPS URL
            doc = DocumentGenerator(entity_id='https://example.com/docs/123')
        """
        self.schema_type = schema_type

        # Generate or normalize the @id
        if entity_id is None:
            # Generate random UUID v4
            normalized_id = f"urn:uuid:{uuid.uuid4()}"
        elif entity_id.startswith(('http://', 'https://', 'urn:')):
            # Already a valid IRI
            normalized_id = entity_id
        else:
            # Assume it's a UUID string, wrap in URN
            normalized_id = f"urn:uuid:{entity_id}"

        self.data: Dict[str, Any] = {
            "@context": SchemaContext.SCHEMA_ORG,
            "@type": schema_type,
            "@id": normalized_id
        }
        self._required_properties: List[str] = []
        self._recommended_properties: List[str] = []

    @abstractmethod
    def get_required_properties(self) -> List[str]:
        """
        Get list of required properties for this schema type.

        Returns:
            List of required property names
        """
        pass

    @abstractmethod
    def get_recommended_properties(self) -> List[str]:
        """
        Get list of recommended properties for this schema type.

        Returns:
            List of recommended property names
        """
        pass

    def set_property(self, name: str, value: Any,
                     property_type: Optional[PropertyType] = None) -> 'SchemaOrgBase':
        """
        Set a property value with optional type validation.

        Args:
            name: Property name
            value: Property value
            property_type: Expected property type for validation

        Returns:
            Self for method chaining
        """
        if value is None:
            return self

        # Validate and convert value based on type
        if property_type:
            value = self._validate_and_convert(value, property_type)

        self.data[name] = value
        return self

    def _validate_and_convert(self, value: Any, property_type: PropertyType) -> Any:
        """
        Validate and convert value to appropriate type.

        Args:
            value: Value to validate
            property_type: Expected property type

        Returns:
            Converted value

        Raises:
            ValueError: If value cannot be converted to expected type
        """
        if property_type == PropertyType.TEXT:
            return str(value)
        elif property_type == PropertyType.URL:
            url_str = str(value)
            if not (url_str.startswith('http://') or url_str.startswith('https://')):
                raise ValueError(f"Invalid URL: {url_str}")
            return url_str
        elif property_type == PropertyType.DATE:
            if isinstance(value, datetime):
                return value.date().isoformat()
            elif isinstance(value, str):
                return value  # Assume already in ISO format
            return str(value)
        elif property_type == PropertyType.DATETIME:
            if isinstance(value, datetime):
                return value.isoformat()
            elif isinstance(value, str):
                return value  # Assume already in ISO format
            return str(value)
        elif property_type == PropertyType.NUMBER:
            return float(value)
        elif property_type == PropertyType.INTEGER:
            return int(value)
        elif property_type == PropertyType.BOOLEAN:
            return bool(value)
        elif property_type == PropertyType.OBJECT:
            if not isinstance(value, dict):
                raise ValueError(f"Expected object, got {type(value)}")
            return value
        elif property_type == PropertyType.ARRAY:
            if not isinstance(value, list):
                return [value]
            return value
        return value

    def get_id(self) -> str:
        """
        Get the @id for this schema.

        Returns:
            The @id IRI string
        """
        return self.data.get("@id", "")

    def set_dates(self, created: Optional[datetime] = None,
                  modified: Optional[datetime] = None,
                  published: Optional[datetime] = None) -> 'SchemaOrgBase':
        """
        Set date properties.

        Args:
            created: Date created
            modified: Date modified
            published: Date published

        Returns:
            Self for method chaining
        """
        if created:
            self.set_property("dateCreated", created, PropertyType.DATETIME)
        if modified:
            self.set_property("dateModified", modified, PropertyType.DATETIME)
        if published:
            self.set_property("datePublished", published, PropertyType.DATETIME)
        return self

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary representation.

        Returns:
            Dictionary representation of the schema
        """
        return self.data.copy()

    def to_json_ld(self, indent: int = 2) -> str:
        """
        Convert to JSON-LD string.

        Args:
            indent: JSON indentation level

        Returns:
            JSON-LD string
        """
        return json.dumps(self.data, indent=indent, ensure_ascii=False)

    def to_json_ld_script(self, indent: int = 2) -> str:
        """
        Convert to JSON-LD script tag for HTML embedding.

        Args:
            indent: JSON indentation level

        Returns:
            HTML script tag with JSON-LD
        """
        json_ld = self.to_json_ld(indent=indent)
        return f'<script type="application/ld+json">\n{json_ld}\n</script>'

    def validate_required_properties(self) -> List[str]:
        """
        Validate that all required properties are present.

        Returns:
            List of missing required properties
        """
        required = self.get_required_properties()
        missing = []
        for prop in required:
            if prop not in self.data:
                missing.append(prop)
        return missing

    def get_completion_score(self) -> float:
        """
        Calculate completion score based on required and recommended properties.

        Returns:
            Completion score (0.0 to 1.0)
        """
        required = self.get_required_properties()
        recommended = self.get_recommended_properties()
        total = len(required) + len(recommended)

        if total == 0:
            return 1.0

        present = 0
        for prop in required:
            if prop in self.data:
                present += 1
        for prop in recommended:
            if prop in self.data:
                present += 0.5  # Recommended properties count as half

        return min(present / len(required) if required else 1.0, 1.0)

    def __str__(self) -> str:
        """String representation."""
        return self.to_json_ld()

    def __repr__(self) -> str:
        """Representation."""
        return f"<{self.__class__.__name__}(type={self.schema_type})>"
