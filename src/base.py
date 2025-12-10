"""
Base classes for Schema.org generation system.

Provides core functionality for all Schema.org generators including
context management, property validation, and nested schema support.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
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

    def set_property(self, name: str, value: Any, property_type: Optional[PropertyType] = None) -> 'SchemaOrgBase':
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

    def add_nested_schema(self, property_name: str, nested_schema: 'SchemaOrgBase') -> 'SchemaOrgBase':
        """
        Add a nested Schema.org object.

        Args:
            property_name: Property name for the nested schema
            nested_schema: Nested SchemaOrgBase instance

        Returns:
            Self for method chaining
        """
        self.data[property_name] = nested_schema.to_dict()
        return self

    def set_id(self, entity_id: str) -> 'SchemaOrgBase':
        """
        Set or update the @id for this schema.

        Args:
            entity_id: Entity ID (UUID string, URN, or HTTPS URL)

        Returns:
            Self for method chaining
        """
        if entity_id.startswith(('http://', 'https://', 'urn:')):
            self.data["@id"] = entity_id
        else:
            self.data["@id"] = f"urn:uuid:{entity_id}"
        return self

    def get_id(self) -> str:
        """
        Get the @id for this schema.

        Returns:
            The @id IRI string
        """
        return self.data.get("@id", "")

    def add_person(self, property_name: str, name: str,
                   email: Optional[str] = None,
                   url: Optional[str] = None,
                   affiliation: Optional[str] = None,
                   person_id: Optional[str] = None) -> 'SchemaOrgBase':
        """
        Add a Person schema.

        Args:
            property_name: Property name (e.g., 'author', 'creator')
            name: Person's name
            email: Person's email
            url: Person's URL/homepage
            affiliation: Organization affiliation
            person_id: Optional @id for the person (for linking)

        Returns:
            Self for method chaining
        """
        # Generate deterministic @id from name if not provided
        if person_id is None:
            person_uuid = uuid.uuid5(
                uuid.UUID('d1e2a3b4-5678-9abc-def0-123456789012'),  # Person namespace
                name.lower().strip()
            )
            person_id = f"urn:uuid:{person_uuid}"
        elif not person_id.startswith(('http://', 'https://', 'urn:')):
            person_id = f"urn:uuid:{person_id}"

        person = {
            "@type": "Person",
            "@id": person_id,
            "name": name
        }
        if email:
            person["email"] = email
        if url:
            person["url"] = url
        if affiliation:
            # Generate deterministic @id for affiliation org
            org_uuid = uuid.uuid5(
                uuid.UUID('c0e1a2b3-4567-89ab-cdef-012345678901'),  # Company namespace
                affiliation.lower().strip()
            )
            person["affiliation"] = {
                "@type": "Organization",
                "@id": f"urn:uuid:{org_uuid}",
                "name": affiliation
            }
        self.data[property_name] = person
        return self

    def add_organization(self, property_name: str, name: str,
                        url: Optional[str] = None,
                        logo: Optional[str] = None,
                        org_id: Optional[str] = None) -> 'SchemaOrgBase':
        """
        Add an Organization schema.

        Args:
            property_name: Property name (e.g., 'publisher', 'provider')
            name: Organization name
            url: Organization URL
            logo: Organization logo URL
            org_id: Optional @id for the organization (for linking)

        Returns:
            Self for method chaining
        """
        # Generate deterministic @id from name if not provided
        if org_id is None:
            org_uuid = uuid.uuid5(
                uuid.UUID('c0e1a2b3-4567-89ab-cdef-012345678901'),  # Company namespace
                name.lower().strip()
            )
            org_id = f"urn:uuid:{org_uuid}"
        elif not org_id.startswith(('http://', 'https://', 'urn:')):
            org_id = f"urn:uuid:{org_id}"

        org = {
            "@type": "Organization",
            "@id": org_id,
            "name": name
        }
        if url:
            org["url"] = url
        if logo:
            logo_uuid = uuid.uuid5(
                uuid.UUID('f4e8a9c0-1234-5678-9abc-def012345678'),  # File namespace
                logo.lower().strip()
            )
            org["logo"] = {
                "@type": "ImageObject",
                "@id": f"urn:uuid:{logo_uuid}",
                "url": logo
            }
        self.data[property_name] = org
        return self

    def add_place(self, property_name: str, name: str,
                  address: Optional[str] = None,
                  geo: Optional[Dict[str, float]] = None,
                  place_id: Optional[str] = None) -> 'SchemaOrgBase':
        """
        Add a Place schema.

        Args:
            property_name: Property name (e.g., 'contentLocation', 'locationCreated')
            name: Place name
            address: Address string
            geo: Geographic coordinates {"latitude": float, "longitude": float}
            place_id: Optional @id for the place (for linking)

        Returns:
            Self for method chaining
        """
        # Generate deterministic @id from name if not provided
        if place_id is None:
            place_uuid = uuid.uuid5(
                uuid.UUID('e2e3a4b5-6789-abcd-ef01-234567890123'),  # Location namespace
                name.lower().strip()
            )
            place_id = f"urn:uuid:{place_uuid}"
        elif not place_id.startswith(('http://', 'https://', 'urn:')):
            place_id = f"urn:uuid:{place_id}"

        place = {
            "@type": "Place",
            "@id": place_id,
            "name": name
        }
        if address:
            place["address"] = address
        if geo:
            place["geo"] = {
                "@type": "GeoCoordinates",
                "latitude": geo.get("latitude"),
                "longitude": geo.get("longitude")
            }
        self.data[property_name] = place
        return self

    def set_identifier(self, identifier: str,
                      property_id: Optional[str] = None) -> 'SchemaOrgBase':
        """
        Set identifier for the resource.

        Args:
            identifier: Identifier value
            property_id: PropertyValue identifier type

        Returns:
            Self for method chaining
        """
        if property_id:
            self.data["identifier"] = {
                "@type": "PropertyValue",
                "propertyID": property_id,
                "value": identifier
            }
        else:
            self.data["identifier"] = identifier
        return self

    def add_keywords(self, keywords: Union[str, List[str]]) -> 'SchemaOrgBase':
        """
        Add keywords/tags.

        Args:
            keywords: Single keyword string or list of keywords

        Returns:
            Self for method chaining
        """
        if isinstance(keywords, str):
            self.data["keywords"] = keywords
        else:
            self.data["keywords"] = ", ".join(keywords)
        return self

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

    def add_relationship(self, property_name: str,
                        related_item: Union[str, 'SchemaOrgBase']) -> 'SchemaOrgBase':
        """
        Add a relationship to another resource.

        Args:
            property_name: Relationship property (e.g., 'isPartOf', 'hasPart', 'mentions')
            related_item: URL string or SchemaOrgBase instance

        Returns:
            Self for method chaining
        """
        if isinstance(related_item, str):
            self.data[property_name] = related_item
        else:
            self.data[property_name] = related_item.to_dict()
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
