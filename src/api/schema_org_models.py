#!/usr/bin/env python3
"""
Pydantic models for schema.org API request/response types.

Defines types for JSON-LD entities, builder results, and API operations.
"""

from typing import Optional, List, Union
from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl

# ============================================================================
# Schema.org JSON-LD Base Types
# ============================================================================


class PostalAddressSchema(BaseModel):
    """PostalAddress schema.org type."""

    type: str = Field("PostalAddress", alias="@type")
    address_locality: Optional[str] = Field(None, alias="addressLocality")
    address_region: Optional[str] = Field(None, alias="addressRegion")
    address_country: Optional[str] = Field(None, alias="addressCountry")

    class Config:
        populate_by_name = True


class GeoCoordinatesSchema(BaseModel):
    """GeoCoordinates schema.org type."""

    type: str = Field("GeoCoordinates", alias="@type")
    latitude: float
    longitude: float

    class Config:
        populate_by_name = True


class PlaceSchema(BaseModel):
    """Place schema.org type (for relationships)."""

    type: str = Field("Place", alias="@type")
    id: Optional[str] = Field(None, alias="@id")
    name: str
    address: Optional[PostalAddressSchema] = None
    geo: Optional[GeoCoordinatesSchema] = None
    geo_hash: Optional[str] = Field(None, alias="geoHash")
    mention_count: Optional[int] = Field(None, alias="mentionCount")
    date_created: Optional[datetime] = Field(None, alias="dateCreated")

    class Config:
        populate_by_name = True


class OrganizationSchema(BaseModel):
    """Organization schema.org type (for relationships)."""

    type: str = Field("Organization", alias="@type")
    id: Optional[str] = Field(None, alias="@id")
    name: str
    url: Optional[HttpUrl] = None
    knows_about: Optional[str] = Field(None, alias="knowsAbout")
    mention_count: Optional[int] = Field(None, alias="mentionCount")

    class Config:
        populate_by_name = True


class PersonSchema(BaseModel):
    """Person schema.org type (for relationships)."""

    type: str = Field("Person", alias="@type")
    id: Optional[str] = Field(None, alias="@id")
    name: str
    email: Optional[str] = None
    job_title: Optional[str] = Field(None, alias="jobTitle")
    mention_count: Optional[int] = Field(None, alias="mentionCount")

    class Config:
        populate_by_name = True


class DefinedTermSchema(BaseModel):
    """DefinedTerm schema.org type (for categories)."""

    type: str = Field("DefinedTerm", alias="@type")
    id: Optional[str] = Field(None, alias="@id")
    name: str
    identifier: Optional[str] = None
    definition: Optional[str] = None

    class Config:
        populate_by_name = True


class DefinedTermSetSchema(BaseModel):
    """DefinedTermSet schema.org type (category taxonomy container)."""

    type: str = Field("DefinedTermSet", alias="@type")
    id: Optional[str] = Field(None, alias="@id")
    name: str

    class Config:
        populate_by_name = True


# ============================================================================
# File Entity Response
# ============================================================================


class FileSchemaOrg(BaseModel):
    """File entity as schema.org JSON-LD."""

    context: str = Field("https://schema.org", alias="@context")
    type: str = Field(alias="@type")
    id: str = Field(alias="@id")
    name: str
    encoding_format: Optional[str] = Field(None, alias="encodingFormat")
    content_size: Optional[str] = Field(None, alias="contentSize")
    url: Optional[str] = None
    text: Optional[str] = None
    date_created: Optional[datetime] = Field(None, alias="dateCreated")
    date_modified: Optional[datetime] = Field(None, alias="dateModified")
    # Image properties
    width: Optional[int] = None
    height: Optional[int] = None
    has_faces: Optional[bool] = Field(None, alias="hasFaces")
    date_published: Optional[datetime] = Field(None, alias="datePublished")
    content_location: Optional[PlaceSchema] = Field(None, alias="contentLocation")
    # Relationships
    about: Optional[List[DefinedTermSchema]] = None
    mentions: Optional[List["EntityReference"]] = None
    spatial_coverage: Optional[Union[PlaceSchema, List[PlaceSchema]]] = Field(
        None, alias="spatialCoverage"
    )

    class Config:
        populate_by_name = True


# ============================================================================
# Category Entity Response
# ============================================================================


class CategorySchemaOrg(BaseModel):
    """Category entity as schema.org DefinedTerm."""

    context: str = Field("https://schema.org", alias="@context")
    type: str = Field("DefinedTerm", alias="@type")
    id: str = Field(alias="@id")
    name: str
    identifier: Optional[str] = None
    definition: Optional[str] = None
    in_defined_term_set: DefinedTermSetSchema = Field(alias="inDefinedTermSet")
    broader: Optional[DefinedTermSchema] = None
    narrower: Optional[List[DefinedTermSchema]] = None
    file_count: int = Field(alias="fileCount")
    hierarchy_level: int = Field(alias="hierarchyLevel")
    icon: Optional[str] = None
    color: Optional[str] = None

    class Config:
        populate_by_name = True


# ============================================================================
# Company Entity Response
# ============================================================================


class CompanySchemaOrg(BaseModel):
    """Company entity as schema.org Organization."""

    context: str = Field("https://schema.org", alias="@context")
    type: str = Field("Organization", alias="@type")
    id: str = Field(alias="@id")
    name: str
    url: Optional[HttpUrl] = None
    knows_about: Optional[str] = Field(None, alias="knowsAbout")
    date_founded: Optional[str] = Field(None, alias="dateFounded")
    date_created: Optional[datetime] = Field(None, alias="dateCreated")
    date_modified: Optional[datetime] = Field(None, alias="dateModified")
    same_as: Optional[List[str]] = Field(None, alias="sameAs")
    mention_count: int = Field(alias="mentionCount")

    class Config:
        populate_by_name = True


# ============================================================================
# Person Entity Response
# ============================================================================


class PersonSchemaOrg(BaseModel):
    """Person entity as schema.org Person."""

    context: str = Field("https://schema.org", alias="@context")
    type: str = Field("Person", alias="@type")
    id: str = Field(alias="@id")
    name: str
    email: Optional[str] = None
    job_title: Optional[str] = Field(None, alias="jobTitle")
    date_created: Optional[datetime] = Field(None, alias="dateCreated")
    date_modified: Optional[datetime] = Field(None, alias="dateModified")
    mention_count: int = Field(alias="mentionCount")
    # Optional relationships (from to_schema_org_with_relationships)
    works_for: Optional[OrganizationSchema] = Field(None, alias="worksFor")
    work_location: Optional[PlaceSchema] = Field(None, alias="workLocation")

    class Config:
        populate_by_name = True


# ============================================================================
# Location Entity Response
# ============================================================================


class LocationSchemaOrg(BaseModel):
    """Location entity as schema.org Place/City/Country."""

    context: str = Field("https://schema.org", alias="@context")
    type: str = Field(alias="@type")  # Place, City, or Country
    id: str = Field(alias="@id")
    name: str
    address: Optional[PostalAddressSchema] = None
    geo: Optional[GeoCoordinatesSchema] = None
    geo_hash: Optional[str] = Field(None, alias="geoHash")
    date_created: Optional[datetime] = Field(None, alias="dateCreated")
    mention_count: int = Field(alias="mentionCount")

    class Config:
        populate_by_name = True


# ============================================================================
# Bulk Export Response
# ============================================================================


class BulkExportResponse(BaseModel):
    """Bulk export response containing all entity types."""

    files: Optional[List[FileSchemaOrg]] = None
    categories: Optional[List[CategorySchemaOrg]] = None
    companies: Optional[List[CompanySchemaOrg]] = None
    people: Optional[List[PersonSchemaOrg]] = None
    locations: Optional[List[LocationSchemaOrg]] = None


# ============================================================================
# Query Parameters
# ============================================================================


class PaginationParams(BaseModel):
    """Standard pagination parameters."""

    skip: int = Field(0, ge=0, description="Number of records to skip")
    limit: int = Field(100, ge=1, le=1000, description="Max records per page")


class FileFilterParams(PaginationParams):
    """File query parameters."""

    mime_type: Optional[str] = Field(None, description="Filter by MIME type")


class CategoryFilterParams(PaginationParams):
    """Category query parameters."""

    level: Optional[int] = Field(None, description="Filter by hierarchy level")


class CompanyFilterParams(PaginationParams):
    """Company query parameters."""

    industry: Optional[str] = Field(None, description="Filter by industry")


class PersonFilterParams(PaginationParams):
    """Person query parameters."""

    role: Optional[str] = Field(None, description="Filter by job role")


class LocationFilterParams(PaginationParams):
    """Location query parameters."""

    country: Optional[str] = Field(None, description="Filter by country")


class BulkExportParams(BaseModel):
    """Bulk export query parameters."""

    entity_types: str = Field(
        "all",
        description="Comma-separated entity types: file, category, company, person, location, or 'all'",
    )


# ============================================================================
# Error Response
# ============================================================================


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str = Field(description="Error message")
    status_code: Optional[int] = Field(None, description="HTTP status code")


# ============================================================================
# Builder Function Return Types
# ============================================================================


class EntityReference(BaseModel):
    """Generic entity reference in schema.org."""

    type: str = Field(alias="@type")
    id: str = Field(alias="@id")
    name: str

    class Config:
        populate_by_name = True


class MentionsList(BaseModel):
    """List of entity mentions."""

    items: List[EntityReference] = Field(description="List of mentioned entities")


class SpatialCoverage(BaseModel):
    """Spatial coverage (location relationship)."""

    items: List[PlaceSchema] = Field(description="Covered locations")


# ============================================================================
# Helper Types
# ============================================================================


class SchemaContext(BaseModel):
    """Schema.org context definition."""

    vocab: str = Field("https://schema.org/", alias="@vocab")
    ml: str = Field("https://example.org/ml-properties/", description="ML namespace")

    class Config:
        populate_by_name = True


class MimeTypeMapping(BaseModel):
    """MIME type to schema.org type mapping."""

    mime_type: str = Field(description="MIME type")
    schema_type: str = Field(description="schema.org type")


class MimeTypeMappingsResponse(BaseModel):
    """Complete MIME type mapping reference."""

    mappings: List[MimeTypeMapping]
    default_type: str = Field("DigitalDocument", description="Default type for unmapped MIME types")
