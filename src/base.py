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
    """

    def __init__(self, schema_type: str):
        """
        Initialize the Schema.org generator.

        Args:
            schema_type: The Schema.org type (e.g., 'DigitalDocument', 'ImageObject')
        """
        self.schema_type = schema_type
        self.data: Dict[str, Any] = {
            "@context": SchemaContext.SCHEMA_ORG,
            "@type": schema_type
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

    def add_person(self, property_name: str, name: str,
                   email: Optional[str] = None,
                   url: Optional[str] = None,
                   affiliation: Optional[str] = None) -> 'SchemaOrgBase':
        """
        Add a Person schema.

        Args:
            property_name: Property name (e.g., 'author', 'creator')
            name: Person's name
            email: Person's email
            url: Person's URL/homepage
            affiliation: Organization affiliation

        Returns:
            Self for method chaining
        """
        person = {
            "@type": "Person",
            "name": name
        }
        if email:
            person["email"] = email
        if url:
            person["url"] = url
        if affiliation:
            person["affiliation"] = {
                "@type": "Organization",
                "name": affiliation
            }
        self.data[property_name] = person
        return self

    def add_organization(self, property_name: str, name: str,
                        url: Optional[str] = None,
                        logo: Optional[str] = None) -> 'SchemaOrgBase':
        """
        Add an Organization schema.

        Args:
            property_name: Property name (e.g., 'publisher', 'provider')
            name: Organization name
            url: Organization URL
            logo: Organization logo URL

        Returns:
            Self for method chaining
        """
        org = {
            "@type": "Organization",
            "name": name
        }
        if url:
            org["url"] = url
        if logo:
            org["logo"] = {
                "@type": "ImageObject",
                "url": logo
            }
        self.data[property_name] = org
        return self

    def add_place(self, property_name: str, name: str,
                  address: Optional[str] = None,
                  geo: Optional[Dict[str, float]] = None) -> 'SchemaOrgBase':
        """
        Add a Place schema.

        Args:
            property_name: Property name (e.g., 'contentLocation', 'locationCreated')
            name: Place name
            address: Address string
            geo: Geographic coordinates {"latitude": float, "longitude": float}

        Returns:
            Self for method chaining
        """
        place = {
            "@type": "Place",
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
