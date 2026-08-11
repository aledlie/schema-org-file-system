#!/usr/bin/env python3
"""
Unit tests for src/base.py - Schema.org base classes.

Priority: P1-1 (High - Core Schema.org generation)
Coverage: 90%+ target

Tests base classes for Schema.org generation including:
- SchemaContext
- PropertyType enum
- SchemaOrgBase abstract class
"""

import json
import uuid
from datetime import datetime
from typing import List

import pytest

from src.base import SchemaContext, PropertyType, SchemaOrgBase


class TestSchemaContext:
    """Test SchemaContext class."""

    def test_schema_org_constant(self):
        """Should have Schema.org URL constant."""
        assert SchemaContext.SCHEMA_ORG == "https://schema.org"

    def test_default_context_has_required_keys(self):
        """Default context should have @context and @vocab."""
        assert "@context" in SchemaContext.DEFAULT_CONTEXT
        assert "@vocab" in SchemaContext.DEFAULT_CONTEXT

    def test_get_context_returns_default(self):
        """get_context without args should return default context."""
        context = SchemaContext.get_context()
        assert context["@context"] == "https://schema.org"
        assert context["@vocab"] == "https://schema.org/"

    def test_get_context_with_additional(self):
        """get_context with additional contexts should merge them."""
        additional = {"custom": "http://example.com/custom"}
        context = SchemaContext.get_context(additional)

        assert context["@context"] == "https://schema.org"
        assert context["custom"] == "http://example.com/custom"

    def test_get_context_does_not_modify_default(self):
        """get_context should not modify DEFAULT_CONTEXT."""
        original = SchemaContext.DEFAULT_CONTEXT.copy()
        SchemaContext.get_context({"extra": "value"})
        assert SchemaContext.DEFAULT_CONTEXT == original


class TestPropertyType:
    """Test PropertyType enum."""

    def test_all_property_types_exist(self):
        """Should have all expected property types."""
        expected_types = [
            "TEXT",
            "URL",
            "DATE",
            "DATETIME",
            "NUMBER",
            "INTEGER",
            "BOOLEAN",
            "OBJECT",
            "ARRAY",
        ]
        for type_name in expected_types:
            assert hasattr(PropertyType, type_name)

    def test_property_type_values(self):
        """Property types should have correct string values."""
        assert PropertyType.TEXT.value == "Text"
        assert PropertyType.URL.value == "URL"
        assert PropertyType.DATE.value == "Date"
        assert PropertyType.DATETIME.value == "DateTime"
        assert PropertyType.NUMBER.value == "Number"
        assert PropertyType.INTEGER.value == "Integer"
        assert PropertyType.BOOLEAN.value == "Boolean"
        assert PropertyType.OBJECT.value == "Object"
        assert PropertyType.ARRAY.value == "Array"


class ConcreteSchema(SchemaOrgBase):
    """Concrete implementation of SchemaOrgBase for testing."""

    def get_required_properties(self) -> List[str]:
        return ["name"]

    def get_recommended_properties(self) -> List[str]:
        return ["description", "url"]


class TestSchemaOrgBaseInit:
    """Test SchemaOrgBase initialization."""

    def test_init_sets_schema_type(self):
        """Should set the schema type."""
        schema = ConcreteSchema("Thing")
        assert schema.schema_type == "Thing"
        assert schema.data["@type"] == "Thing"

    def test_init_sets_context(self):
        """Should set Schema.org context."""
        schema = ConcreteSchema("Thing")
        assert schema.data["@context"] == "https://schema.org"

    def test_init_generates_uuid_id_when_none(self):
        """Should generate UUID v4 @id when entity_id is None."""
        schema = ConcreteSchema("Thing")
        assert "@id" in schema.data
        assert schema.data["@id"].startswith("urn:uuid:")
        # Validate the UUID
        uuid_str = schema.data["@id"].replace("urn:uuid:", "")
        uuid.UUID(uuid_str)  # Will raise if invalid

    def test_init_accepts_uuid_string(self):
        """Should wrap plain UUID string in urn:uuid:."""
        uuid_str = "550e8400-e29b-41d4-a716-446655440000"
        schema = ConcreteSchema("Thing", entity_id=uuid_str)
        assert schema.data["@id"] == f"urn:uuid:{uuid_str}"

    def test_init_accepts_urn_uuid(self):
        """Should accept urn:uuid: IRI directly."""
        iri = "urn:uuid:550e8400-e29b-41d4-a716-446655440000"
        schema = ConcreteSchema("Thing", entity_id=iri)
        assert schema.data["@id"] == iri

    def test_init_accepts_urn_sha256(self):
        """Should accept urn:sha256: IRI directly."""
        iri = "urn:sha256:abc123def456"
        schema = ConcreteSchema("Thing", entity_id=iri)
        assert schema.data["@id"] == iri

    def test_init_accepts_https_url(self):
        """Should accept HTTPS URL directly."""
        url = "https://example.com/entity/123"
        schema = ConcreteSchema("Thing", entity_id=url)
        assert schema.data["@id"] == url

    def test_init_accepts_http_url(self):
        """Should accept HTTP URL directly."""
        url = "http://example.com/entity/123"
        schema = ConcreteSchema("Thing", entity_id=url)
        assert schema.data["@id"] == url

    def test_init_creates_empty_required_properties(self):
        """Should initialize required properties list."""
        schema = ConcreteSchema("Thing")
        assert hasattr(schema, "_required_properties")

    def test_init_creates_empty_recommended_properties(self):
        """Should initialize recommended properties list."""
        schema = ConcreteSchema("Thing")
        assert hasattr(schema, "_recommended_properties")


class TestSchemaOrgBaseSetProperty:
    """Test set_property method."""

    def test_set_property_basic(self):
        """Should set a basic property."""
        schema = ConcreteSchema("Thing")
        schema.set_property("name", "Test Name")
        assert schema.data["name"] == "Test Name"

    def test_set_property_returns_self(self):
        """Should return self for method chaining."""
        schema = ConcreteSchema("Thing")
        result = schema.set_property("name", "Test")
        assert result is schema

    def test_set_property_none_value_skipped(self):
        """Should skip setting None values."""
        schema = ConcreteSchema("Thing")
        schema.set_property("name", None)
        assert "name" not in schema.data

    def test_set_property_text_type(self):
        """Should convert to string with TEXT type."""
        schema = ConcreteSchema("Thing")
        schema.set_property("name", 123, PropertyType.TEXT)
        assert schema.data["name"] == "123"

    def test_set_property_url_type_valid(self):
        """Should accept valid URL with URL type."""
        schema = ConcreteSchema("Thing")
        schema.set_property("url", "https://example.com", PropertyType.URL)
        assert schema.data["url"] == "https://example.com"

    def test_set_property_url_type_invalid_raises(self):
        """Should raise ValueError for invalid URL."""
        schema = ConcreteSchema("Thing")
        with pytest.raises(ValueError) as exc_info:
            schema.set_property("url", "not-a-url", PropertyType.URL)
        assert "Invalid URL" in str(exc_info.value)

    def test_set_property_date_type_datetime(self):
        """Should convert datetime to ISO date string."""
        schema = ConcreteSchema("Thing")
        dt = datetime(2024, 6, 15, 10, 30, 0)
        schema.set_property("dateCreated", dt, PropertyType.DATE)
        assert schema.data["dateCreated"] == "2024-06-15"

    def test_set_property_date_type_string(self):
        """Should pass string dates through."""
        schema = ConcreteSchema("Thing")
        schema.set_property("dateCreated", "2024-06-15", PropertyType.DATE)
        assert schema.data["dateCreated"] == "2024-06-15"

    def test_set_property_datetime_type(self):
        """Should convert datetime to ISO datetime string."""
        schema = ConcreteSchema("Thing")
        dt = datetime(2024, 6, 15, 10, 30, 0)
        schema.set_property("dateCreated", dt, PropertyType.DATETIME)
        assert schema.data["dateCreated"] == "2024-06-15T10:30:00"

    def test_set_property_number_type(self):
        """Should convert to float with NUMBER type."""
        schema = ConcreteSchema("Thing")
        schema.set_property("price", "99.99", PropertyType.NUMBER)
        assert schema.data["price"] == 99.99

    def test_set_property_integer_type(self):
        """Should convert to int with INTEGER type."""
        schema = ConcreteSchema("Thing")
        schema.set_property("count", "42", PropertyType.INTEGER)
        assert schema.data["count"] == 42

    def test_set_property_boolean_type(self):
        """Should convert to bool with BOOLEAN type."""
        schema = ConcreteSchema("Thing")
        schema.set_property("active", 1, PropertyType.BOOLEAN)
        assert schema.data["active"] is True

    def test_set_property_object_type_valid(self):
        """Should accept dict with OBJECT type."""
        schema = ConcreteSchema("Thing")
        obj = {"@type": "Person", "name": "John"}
        schema.set_property("author", obj, PropertyType.OBJECT)
        assert schema.data["author"] == obj

    def test_set_property_object_type_invalid_raises(self):
        """Should raise ValueError for non-dict OBJECT type."""
        schema = ConcreteSchema("Thing")
        with pytest.raises(ValueError) as exc_info:
            schema.set_property("author", "not-an-object", PropertyType.OBJECT)
        assert "Expected object" in str(exc_info.value)

    def test_set_property_array_type_list(self):
        """Should pass list through with ARRAY type."""
        schema = ConcreteSchema("Thing")
        arr = ["a", "b", "c"]
        schema.set_property("keywords", arr, PropertyType.ARRAY)
        assert schema.data["keywords"] == arr

    def test_set_property_array_type_single_value(self):
        """Should wrap single value in array with ARRAY type."""
        schema = ConcreteSchema("Thing")
        schema.set_property("keywords", "single", PropertyType.ARRAY)
        assert schema.data["keywords"] == ["single"]


class TestSchemaOrgBaseGetID:
    """Test get_id method."""

    def test_get_id(self):
        """Should return current @id."""
        iri = "urn:uuid:550e8400-e29b-41d4-a716-446655440000"
        schema = ConcreteSchema("Thing", entity_id=iri)
        assert schema.get_id() == iri

    def test_get_id_empty_returns_empty_string(self):
        """Should return empty string if @id not set."""
        schema = ConcreteSchema("Thing")
        del schema.data["@id"]  # Remove the auto-generated ID
        assert schema.get_id() == ""


class TestSchemaOrgBaseDates:
    """Test set_dates method."""

    def test_set_dates_created(self):
        """Should set dateCreated."""
        schema = ConcreteSchema("Thing")
        dt = datetime(2024, 6, 15, 10, 30)
        schema.set_dates(created=dt)
        assert schema.data["dateCreated"] == "2024-06-15T10:30:00"

    def test_set_dates_modified(self):
        """Should set dateModified."""
        schema = ConcreteSchema("Thing")
        dt = datetime(2024, 6, 20, 14, 45)
        schema.set_dates(modified=dt)
        assert schema.data["dateModified"] == "2024-06-20T14:45:00"

    def test_set_dates_published(self):
        """Should set datePublished."""
        schema = ConcreteSchema("Thing")
        dt = datetime(2024, 6, 25)
        schema.set_dates(published=dt)
        assert schema.data["datePublished"] == "2024-06-25T00:00:00"

    def test_set_dates_all(self):
        """Should set all dates when provided."""
        schema = ConcreteSchema("Thing")
        created = datetime(2024, 1, 1)
        modified = datetime(2024, 6, 15)
        published = datetime(2024, 6, 20)

        schema.set_dates(created=created, modified=modified, published=published)

        assert "dateCreated" in schema.data
        assert "dateModified" in schema.data
        assert "datePublished" in schema.data

    def test_set_dates_returns_self(self):
        """Should return self for method chaining."""
        schema = ConcreteSchema("Thing")
        result = schema.set_dates(created=datetime.now())
        assert result is schema


class TestSchemaOrgBaseOutput:
    """Test output methods."""

    def test_to_dict(self):
        """Should return dictionary representation."""
        schema = ConcreteSchema("Thing")
        schema.set_property("name", "Test")

        result = schema.to_dict()

        assert isinstance(result, dict)
        assert result["@type"] == "Thing"
        assert result["name"] == "Test"

    def test_to_dict_returns_copy(self):
        """Should return a copy, not the original."""
        schema = ConcreteSchema("Thing")
        dict1 = schema.to_dict()
        dict1["modified"] = "value"

        dict2 = schema.to_dict()
        assert "modified" not in dict2

    def test_to_json_ld(self):
        """Should return JSON-LD string."""
        schema = ConcreteSchema("Thing")
        schema.set_property("name", "Test")

        json_str = schema.to_json_ld()

        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["@type"] == "Thing"
        assert parsed["name"] == "Test"

    def test_to_json_ld_indent(self):
        """Should respect indent parameter."""
        schema = ConcreteSchema("Thing")

        json_2 = schema.to_json_ld(indent=2)
        json_4 = schema.to_json_ld(indent=4)

        # More indentation = longer string
        assert len(json_4) > len(json_2)

    def test_to_json_ld_script(self):
        """Should return script tag with JSON-LD."""
        schema = ConcreteSchema("Thing")
        script = schema.to_json_ld_script()

        assert script.startswith('<script type="application/ld+json">')
        assert script.endswith("</script>")
        assert '"@type": "Thing"' in script


class TestSchemaOrgBaseValidation:
    """Test validation methods."""

    def test_validate_required_missing(self):
        """Should return list of missing required properties."""
        schema = ConcreteSchema("Thing")
        # Don't set 'name' which is required
        missing = schema.validate_required_properties()
        assert "name" in missing

    def test_validate_required_present(self):
        """Should return empty list when all required present."""
        schema = ConcreteSchema("Thing")
        schema.set_property("name", "Test")
        missing = schema.validate_required_properties()
        assert missing == []


class TestSchemaOrgBaseCompletionScore:
    """Test get_completion_score method."""

    def test_completion_score_all_required(self):
        """Should return 1.0 when all required properties present."""
        schema = ConcreteSchema("Thing")
        schema.set_property("name", "Test")
        score = schema.get_completion_score()
        assert score == 1.0

    def test_completion_score_none_present(self):
        """Should return 0.0 when no required properties present."""
        schema = ConcreteSchema("Thing")
        score = schema.get_completion_score()
        assert score == 0.0

    def test_completion_score_recommended_count_half(self):
        """Recommended properties should count as 0.5."""
        schema = ConcreteSchema("Thing")
        schema.set_property("name", "Test")  # Required
        schema.set_property("description", "A test")  # Recommended

        # Score should be 1.0 (all required) + partial for recommended
        # But capped at 1.0
        score = schema.get_completion_score()
        assert score == 1.0


class TestSchemaOrgBaseStringMethods:
    """Test __str__ and __repr__ methods."""

    def test_str_returns_json_ld(self):
        """__str__ should return JSON-LD string."""
        schema = ConcreteSchema("Thing")
        str_repr = str(schema)
        assert '"@type": "Thing"' in str_repr

    def test_repr_format(self):
        """__repr__ should return class name and type."""
        schema = ConcreteSchema("Thing")
        repr_str = repr(schema)
        assert "ConcreteSchema" in repr_str
        assert "type=Thing" in repr_str


class TestMethodChaining:
    """Test that methods can be chained together."""

    def test_full_method_chain(self):
        """Should support full method chaining."""
        created = datetime.now()
        schema = ConcreteSchema("Article")

        result = (
            schema.set_property("name", "Test Article")
            .set_property("description", "A test article")
            .set_dates(created=created)
        )

        assert result is schema
        assert schema.data["name"] == "Test Article"
        assert schema.data["description"] == "A test article"
        assert "dateCreated" in schema.data
