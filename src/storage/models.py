#!/usr/bin/env python3
"""
SQLAlchemy models for graph-based storage.

Implements a graph-like structure using relational tables with explicit
relationship tables for flexibility and query performance.

Graph Structure:
    Files (nodes) <---> Categories (nodes)
    Files (nodes) <---> Companies (nodes)
    Files (nodes) <---> People (nodes)
    Files (nodes) <---> Locations (nodes)
    Files (nodes) <---> Files (edges via FileRelationship)

Key-Value Storage:
    Flexible schema-less storage for arbitrary metadata
"""

from ._time import utcnow
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, JSON,
    ForeignKey, Index, UniqueConstraint, Table, Enum as SQLEnum,
    create_engine, event
)
from sqlalchemy.orm import (
    declarative_base, relationship, Session, sessionmaker
)
from sqlalchemy.ext.hybrid import hybrid_property
import enum
import hashlib
import json
import uuid

from .schema_org_base import SchemaOrgSerializable

try:
    from ..constants import (
        SHA256_HEX_LENGTH,
        UUID_STRING_LENGTH,
        MAX_STRING_LENGTH,
        SHORT_STRING_LENGTH,
        SHORT_FIELD_LENGTH,
        GEOHASH_MAX_LENGTH,
        BASE_PATH_MAX_LENGTH,
    )
except ImportError:
    from constants import (
        SHA256_HEX_LENGTH,
        UUID_STRING_LENGTH,
        MAX_STRING_LENGTH,
        SHORT_STRING_LENGTH,
        SHORT_FIELD_LENGTH,
        GEOHASH_MAX_LENGTH,
        BASE_PATH_MAX_LENGTH,
    )


# Namespace UUIDs for deterministic ID generation (UUID v5)
# These match the namespaces in src/uri_utils.py for consistency
NAMESPACES = {
    'file': uuid.UUID('f4e8a9c0-1234-5678-9abc-def012345678'),
    'category': uuid.UUID('c4e8a9c0-2345-6789-abcd-ef0123456789'),
    'company': uuid.UUID('c0e1a2b3-4567-89ab-cdef-012345678901'),
    'person': uuid.UUID('d1e2a3b4-5678-9abc-def0-123456789012'),
    'location': uuid.UUID('e2e3a4b5-6789-abcd-ef01-234567890123'),
    'session': uuid.UUID('f3e4a5b6-789a-bcde-f012-345678901234'),
    'merge_event': uuid.UUID('a1b2c3d4-89ab-cdef-0123-456789abcdef'),
}


Base = declarative_base()


class FileStatus(enum.Enum):
    """Status of file organization."""
    PENDING = "pending"
    ORGANIZED = "organized"
    SKIPPED = "skipped"
    ERROR = "error"
    ALREADY_ORGANIZED = "already_organized"


class RelationshipType(enum.Enum):
    """Types of relationships between files."""
    DUPLICATE = "duplicate"           # Same content hash
    SIMILAR = "similar"               # Similar content
    VERSION = "version"               # Different version of same file
    DERIVED = "derived"               # One file derived from another
    RELATED = "related"               # Semantically related
    PARENT_CHILD = "parent_child"     # Directory relationship
    REFERENCES = "references"         # One file references another


# Association tables for many-to-many relationships
file_categories = Table(
    'file_categories',
    Base.metadata,
    Column('file_id', String(SHA256_HEX_LENGTH), ForeignKey('files.id'), primary_key=True),
    Column('category_id', Integer, ForeignKey('categories.id'), primary_key=True),
    Column('confidence', Float, default=1.0),
    # Per-signal scoring evidence for backtesting (UNIFIED_SCORING_PLAN §5.4).
    # Nullable and additive: legacy runs persist NULL; existing databases gain
    # the column via `organize-files migrate-scoring` (scoring_migration.py).
    Column('signal_evidence', JSON, nullable=True),
    Column('created_at', DateTime, default=utcnow)
)
Index('ix_file_categories_category_id', file_categories.c.category_id)

file_companies = Table(
    'file_companies',
    Base.metadata,
    Column('file_id', String(SHA256_HEX_LENGTH), ForeignKey('files.id'), primary_key=True),
    Column('company_id', Integer, ForeignKey('companies.id'), primary_key=True),
    Column('confidence', Float, default=1.0),
    Column('context', String(MAX_STRING_LENGTH)),  # How the company was detected
    Column('created_at', DateTime, default=utcnow)
)
Index('ix_file_companies_company_id', file_companies.c.company_id)

file_people = Table(
    'file_people',
    Base.metadata,
    Column('file_id', String(SHA256_HEX_LENGTH), ForeignKey('files.id'), primary_key=True),
    Column('person_id', Integer, ForeignKey('people.id'), primary_key=True),
    Column('role', String(SHORT_STRING_LENGTH)),  # author, subject, mentioned, etc.
    Column('confidence', Float, default=1.0),
    Column('created_at', DateTime, default=utcnow)
)
Index('ix_file_people_person_id', file_people.c.person_id)

file_locations = Table(
    'file_locations',
    Base.metadata,
    Column('file_id', String(SHA256_HEX_LENGTH), ForeignKey('files.id'), primary_key=True),
    Column('location_id', Integer, ForeignKey('locations.id'), primary_key=True),
    Column('location_type', String(SHORT_STRING_LENGTH)),  # captured_at, mentioned, subject
    Column('confidence', Float, default=1.0),
    Column('created_at', DateTime, default=utcnow)
)
Index('ix_file_locations_location_id', file_locations.c.location_id)


class File(Base, SchemaOrgSerializable):
    """
    Central node representing a file in the system.

    The file ID is a SHA-256 hash of the original path for deduplication.

    ID Strategy:
    - `id`: SHA-256 hash of original path (internal, deterministic)
    - `canonical_id`: Public IRI for JSON-LD @id (urn:sha256:{hash})
    - `source_ids`: Historical IDs from imports/renames (for deduplication)
    """
    __tablename__ = 'files'

    # Primary key is hash of original path
    id = Column(String(SHA256_HEX_LENGTH), primary_key=True)

    # Public canonical ID for JSON-LD @id (urn:sha256:{hash} format)
    canonical_id = Column(String(100), unique=True, index=True)

    # Historical IDs for deduplication (previous paths, external IDs)
    source_ids = Column(JSON, default=list)

    # File identification
    filename = Column(String(MAX_STRING_LENGTH), nullable=False, index=True)
    original_path = Column(Text, nullable=False)
    current_path = Column(Text)  # Where it is now (after organization)
    file_extension = Column(String(SHORT_FIELD_LENGTH), index=True)
    mime_type = Column(String(100))

    # File properties
    file_size = Column(Integer)
    content_hash = Column(String(SHA256_HEX_LENGTH), index=True)  # SHA-256 of content
    created_at = Column(DateTime)
    modified_at = Column(DateTime)
    organized_at = Column(DateTime)

    # Organization status
    status = Column(SQLEnum(FileStatus), default=FileStatus.PENDING, index=True)
    organization_reason = Column(Text)

    # Extracted content
    extracted_text = Column(Text)
    extracted_text_length = Column(Integer, default=0)
    ocr_confidence = Column(Float)          # average OCR word confidence (0.0–1.0)
    detected_language = Column(String(10))  # ISO 639-1 language code from OCR

    # Schema.org metadata (stored as JSON)
    schema_type = Column(String(SHORT_STRING_LENGTH))  # ImageObject, Document, etc.
    schema_data = Column(JSON)
    kie_fields = Column(JSON)            # KIE-extracted structured fields (raw)

    # Image-specific metadata
    image_width = Column(Integer)
    image_height = Column(Integer)
    has_faces = Column(Boolean)
    face_count = Column(Integer)
    image_classification = Column(JSON)  # CLIP classification scores

    # EXIF metadata
    exif_datetime = Column(DateTime)
    gps_latitude = Column(Float)
    gps_longitude = Column(Float)

    # Processing metadata
    processing_time_sec = Column(Float)
    session_id = Column(String(SHA256_HEX_LENGTH), ForeignKey('organization_sessions.id'), index=True)

    # Timestamps
    db_created_at = Column(DateTime, default=utcnow)
    db_updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    categories = relationship('Category', secondary=file_categories, back_populates='files')
    companies = relationship('Company', secondary=file_companies, back_populates='files')
    people = relationship('Person', secondary=file_people, back_populates='files')
    locations = relationship('Location', secondary=file_locations, back_populates='files')
    session = relationship('OrganizationSession', back_populates='files')
    cost_records = relationship('CostRecord', back_populates='file')
    schema_metadata = relationship('SchemaMetadata', back_populates='file', uselist=False)

    # Self-referential relationships (graph edges)
    related_to = relationship(
        'FileRelationship',
        foreign_keys='FileRelationship.source_file_id',
        back_populates='source_file'
    )
    related_from = relationship(
        'FileRelationship',
        foreign_keys='FileRelationship.target_file_id',
        back_populates='target_file'
    )

    # Additional composite indexes (single-column indexes handled by index=True on columns)
    __table_args__ = (
        Index('ix_files_organized_at', 'organized_at'),
    )

    @staticmethod
    def generate_id(path: str) -> str:
        """Generate a deterministic ID from the file path."""
        return hashlib.sha256(path.encode()).hexdigest()

    @staticmethod
    def generate_canonical_id(path: str) -> str:
        """
        Generate canonical IRI for JSON-LD @id from file path.

        Uses SHA-256 hash of the path in URN format.

        Args:
            path: File path (absolute recommended)

        Returns:
            URN string (urn:sha256:{hash})
        """
        file_hash = hashlib.sha256(path.encode()).hexdigest()
        return f"urn:sha256:{file_hash}"

    def get_iri(self) -> str:
        """Get the JSON-LD @id IRI for this file."""
        return file_iri(self.id, self.canonical_id)

    def get_schema_type(self) -> str:
        """Return the schema.org @type for this file."""
        return self.schema_type or self.get_schema_type_from_mime(self.mime_type)

    @staticmethod
    def get_schema_type_from_mime(mime_type: Optional[str]) -> str:
        """Select appropriate schema.org type based on MIME type."""
        if not mime_type:
            return "DigitalDocument"

        mime_lower = mime_type.lower()

        type_mapping = {
            # Images
            "image/jpeg": "ImageObject",
            "image/png": "ImageObject",
            "image/gif": "ImageObject",
            "image/svg": "ImageObject",
            "image/webp": "ImageObject",
            # Video
            "video/mp4": "VideoObject",
            "video/mpeg": "VideoObject",
            "video/quicktime": "VideoObject",
            "video/webm": "VideoObject",
            # Audio
            "audio/mpeg": "AudioObject",
            "audio/wav": "AudioObject",
            "audio/ogg": "AudioObject",
            "audio/mp4": "AudioObject",
            # Documents
            "application/pdf": "DigitalDocument",
            "application/msword": "DigitalDocument",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DigitalDocument",
            "text/plain": "DigitalDocument",
            "text/markdown": "DigitalDocument",
            "text/html": "WebPage",
            # Code
            "application/json": "SoftwareSourceCode",
            "application/x-python": "SoftwareSourceCode",
            "text/x-python": "SoftwareSourceCode",
            "text/typescript": "SoftwareSourceCode",
        }

        # Try exact match first
        if mime_type in type_mapping:
            return type_mapping[mime_type]

        # Try prefix match
        for mime_prefix, schema_type in type_mapping.items():
            if mime_lower.startswith(mime_prefix.split('/')[0] + '/'):
                return schema_type

        return "DigitalDocument"

    def to_schema_org(self) -> Dict[str, Any]:
        """Convert File to schema.org JSON-LD (delegates to build_file_jsonld)."""
        return build_file_jsonld(
            self, self.categories, self.companies, self.people, self.locations
        )

    def build_schema_relationships(self) -> Dict[str, Any]:
        """Build relationships to other entities (delegates to build_file_relationships)."""
        return build_file_relationships(
            self.categories, self.companies, self.people, self.locations
        )

    @hybrid_property
    def is_organized(self) -> bool:
        return self.status == FileStatus.ORGANIZED

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            '@id': self.get_iri(),
            'canonical_id': self.canonical_id,
            'filename': self.filename,
            'original_path': self.original_path,
            'current_path': self.current_path,
            'file_extension': self.file_extension,
            'mime_type': self.mime_type,
            'file_size': self.file_size,
            'status': self.status.value if self.status else None,
            'categories': [c.name for c in self.categories],
            'companies': [c.name for c in self.companies],
            'people': [p.name for p in self.people],
            'schema_type': self.schema_type,
            'organized_at': self.organized_at.isoformat() if self.organized_at else None,
        }


class Category(Base, SchemaOrgSerializable):
    """
    Category node for file classification.

    Supports hierarchical categories (e.g., Legal/Contracts, Media/Photos).

    ID Strategy:
    - `id`: Auto-increment integer (internal, for DB performance)
    - `canonical_id`: Deterministic UUID v5 from name (public, for JSON-LD @id)
    - `source_ids`: Historical IDs from merges/imports (for deduplication)
    """
    __tablename__ = 'categories'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Canonical UUID for JSON-LD @id (deterministic from name)
    canonical_id = Column(String(UUID_STRING_LENGTH), unique=True, index=True)

    # Historical IDs for merge tracking and deduplication
    source_ids = Column(JSON, default=list)

    # Merge tracking: if this category was merged into another
    merged_into_id = Column(Integer, ForeignKey('categories.id'))

    name = Column(String(100), nullable=False, unique=True, index=True)
    parent_id = Column(Integer, ForeignKey('categories.id'), index=True)
    description = Column(Text)
    icon = Column(String(SHORT_STRING_LENGTH))  # Emoji or icon name
    color = Column(String(SHORT_FIELD_LENGTH))  # Hex color

    # Hierarchy
    level = Column(Integer, default=0)  # 0 = root, 1 = subcategory, etc.
    full_path = Column(String(MAX_STRING_LENGTH), index=True)  # e.g., "Legal/Contracts"

    # Statistics
    file_count = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    files = relationship('File', secondary=file_categories, back_populates='categories')
    parent = relationship('Category', remote_side=[id], backref='subcategories',
                         foreign_keys=[parent_id])
    merged_into = relationship('Category', remote_side=[id],
                              foreign_keys=[merged_into_id])

    @staticmethod
    def generate_canonical_id(name: str) -> str:
        """
        Generate deterministic UUID v5 from category name.

        Same name always produces the same canonical ID, enabling
        deduplication across systems.

        Args:
            name: Category name

        Returns:
            UUID string (without urn:uuid: prefix)
        """
        return str(uuid.uuid5(NAMESPACES['category'], name.lower().strip()))

    def get_schema_type(self) -> str:
        """Return the schema.org @type for this category."""
        return "DefinedTerm"

    def get_iri(self) -> str:
        """Get the JSON-LD @id IRI for this category."""
        return f"urn:uuid:{self.canonical_id}"

    def to_schema_org(self) -> Dict[str, Any]:
        """Convert Category to schema.org JSON-LD (delegates to build_category_jsonld)."""
        return build_category_jsonld(self, self.parent, self.subcategories)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            '@id': self.get_iri() if self.canonical_id else None,
            'canonical_id': self.canonical_id,
            'name': self.name,
            'full_path': self.full_path,
            'level': self.level,
            'file_count': self.file_count,
        }


class Company(Base, SchemaOrgSerializable):
    """
    Company node for organization affiliation.

    Represents companies detected in documents.

    ID Strategy:
    - `id`: Auto-increment integer (internal, for DB performance)
    - `canonical_id`: Deterministic UUID v5 from normalized name (public, for JSON-LD @id)
    - `source_ids`: Historical IDs from merges/imports (for deduplication)
    """
    __tablename__ = 'companies'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Canonical UUID for JSON-LD @id (deterministic from normalized name)
    canonical_id = Column(String(UUID_STRING_LENGTH), unique=True, index=True)

    # Historical IDs for merge tracking and deduplication
    source_ids = Column(JSON, default=list)

    # Merge tracking: if this company was merged into another
    merged_into_id = Column(Integer, ForeignKey('companies.id'))

    name = Column(String(MAX_STRING_LENGTH), nullable=False, index=True)
    normalized_name = Column(String(MAX_STRING_LENGTH), unique=True, index=True)  # Lowercase, trimmed
    domain = Column(String(MAX_STRING_LENGTH))  # Company website domain
    industry = Column(String(100))

    # Statistics
    file_count = Column(Integer, default=0)
    first_seen = Column(DateTime, default=utcnow)
    last_seen = Column(DateTime, default=utcnow)

    # Relationships
    files = relationship('File', secondary=file_companies, back_populates='companies')
    merged_into = relationship('Company', remote_side=[id])

    # ix_companies_normalized_name created by unique=True, index=True on normalized_name column


    @staticmethod
    def normalize_name(name: str) -> str:
        """Normalize company name for deduplication."""
        return name.lower().strip()

    @staticmethod
    def generate_canonical_id(name: str) -> str:
        """
        Generate deterministic UUID v5 from company name.

        Args:
            name: Company name

        Returns:
            UUID string (without urn:uuid: prefix)
        """
        return str(uuid.uuid5(NAMESPACES['company'], name.lower().strip()))

    def get_schema_type(self) -> str:
        """Return the schema.org @type for this company."""
        return "Organization"

    def get_iri(self) -> str:
        """Get the JSON-LD @id IRI for this company."""
        return f"urn:uuid:{self.canonical_id}"

    @staticmethod
    def generate_wikidata_url(company_name: str) -> Optional[str]:
        """Generate potential Wikidata URL for external reference"""
        # This would typically call an external API
        # For now, return a template
        normalized = company_name.lower().replace(' ', '_')
        return f"https://www.wikidata.org/wiki/Q{normalized}"

    def to_schema_org(self) -> Dict[str, Any]:
        """Convert Company to schema.org JSON-LD (delegates to build_company_jsonld)."""
        return build_company_jsonld(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            '@id': self.get_iri() if self.canonical_id else None,
            'canonical_id': self.canonical_id,
            'name': self.name,
            'domain': self.domain,
            'file_count': self.file_count,
        }


class Person(Base, SchemaOrgSerializable):
    """
    Person node for people detected in files.

    Could be authors, subjects, or mentioned individuals.

    ID Strategy:
    - `id`: Auto-increment integer (internal, for DB performance)
    - `canonical_id`: Deterministic UUID v5 from normalized name (public, for JSON-LD @id)
    - `source_ids`: Historical IDs from merges/imports (for deduplication)
    """
    __tablename__ = 'people'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Canonical UUID for JSON-LD @id (deterministic from normalized name)
    canonical_id = Column(String(UUID_STRING_LENGTH), unique=True, index=True)

    # Historical IDs for merge tracking and deduplication
    source_ids = Column(JSON, default=list)

    # Merge tracking: if this person was merged into another
    merged_into_id = Column(Integer, ForeignKey('people.id'))

    name = Column(String(MAX_STRING_LENGTH), nullable=False, index=True)
    normalized_name = Column(String(MAX_STRING_LENGTH), unique=True, index=True)
    email = Column(String(MAX_STRING_LENGTH))
    role = Column(String(100))  # Default role

    # Statistics
    file_count = Column(Integer, default=0)
    first_seen = Column(DateTime, default=utcnow)
    last_seen = Column(DateTime, default=utcnow)

    # Relationships
    files = relationship('File', secondary=file_people, back_populates='people')
    merged_into = relationship('Person', remote_side=[id])

    @staticmethod
    def normalize_name(name: str) -> str:
        """Normalize person name for deduplication."""
        return name.lower().strip()

    @staticmethod
    def generate_canonical_id(name: str) -> str:
        """
        Generate deterministic UUID v5 from person name.

        Args:
            name: Person name

        Returns:
            UUID string (without urn:uuid: prefix)
        """
        return str(uuid.uuid5(NAMESPACES['person'], name.lower().strip()))

    def get_schema_type(self) -> str:
        """Return the schema.org @type for this person."""
        return "Person"

    def get_iri(self) -> str:
        """Get the JSON-LD @id IRI for this person."""
        return f"urn:uuid:{self.canonical_id}"

    def to_schema_org(self) -> Dict[str, Any]:
        """Convert Person to schema.org JSON-LD (delegates to build_person_jsonld)."""
        return build_person_jsonld(self)

    def to_schema_org_with_relationships(self,
                                       company: Optional['Company'] = None,
                                       location: Optional['Location'] = None) -> Dict[str, Any]:
        """Convert Person with optional relationship references"""

        result = self.to_schema_org()

        # Add work relationships
        if company:
            result["worksFor"] = {
                "@type": "Organization",
                "@id": company.get_iri(),
                "name": company.name
            }

        if location:
            result["workLocation"] = {
                "@type": "Place",
                "@id": location.get_iri(),
                "name": location.name
            }

        return result

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            '@id': self.get_iri() if self.canonical_id else None,
            'canonical_id': self.canonical_id,
            'name': self.name,
            'email': self.email,
            'file_count': self.file_count,
        }


class Location(Base, SchemaOrgSerializable):
    """
    Location node for geographic data.

    Extracted from EXIF GPS data or document content.

    ID Strategy:
    - `id`: Auto-increment integer (internal, for DB performance)
    - `canonical_id`: Deterministic UUID v5 from name (public, for JSON-LD @id)
    - `source_ids`: Historical IDs from merges/imports (for deduplication)
    """
    __tablename__ = 'locations'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Canonical UUID for JSON-LD @id (deterministic from name)
    canonical_id = Column(String(UUID_STRING_LENGTH), unique=True, index=True)

    # Historical IDs for merge tracking and deduplication
    source_ids = Column(JSON, default=list)

    # Merge tracking: if this location was merged into another
    merged_into_id = Column(Integer, ForeignKey('locations.id'))

    name = Column(String(MAX_STRING_LENGTH), nullable=False, index=True)
    city = Column(String(100))
    state = Column(String(100))
    country = Column(String(100))
    latitude = Column(Float)
    longitude = Column(Float)

    # Geohash for efficient spatial queries
    geohash = Column(String(GEOHASH_MAX_LENGTH), index=True)

    # Statistics
    file_count = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    files = relationship('File', secondary=file_locations, back_populates='locations')
    merged_into = relationship('Location', remote_side=[id])

    __table_args__ = (
        Index('ix_locations_geo', 'latitude', 'longitude'),
        Index('ix_locations_city_state', 'city', 'state'),
    )

    @staticmethod
    def generate_canonical_id(name: str) -> str:
        """
        Generate deterministic UUID v5 from location name.

        Args:
            name: Location name

        Returns:
            UUID string (without urn:uuid: prefix)
        """
        return str(uuid.uuid5(NAMESPACES['location'], name.lower().strip()))

    def get_iri(self) -> str:
        """Get the JSON-LD @id IRI for this location."""
        return f"urn:uuid:{self.canonical_id}"

    def get_schema_type(self) -> str:
        """Return the schema.org @type for this location (Place, City, or Country)."""
        return location_schema_type(self.city, self.state, self.country)

    def to_schema_org(self) -> Dict[str, Any]:
        """Convert Location to schema.org JSON-LD (delegates to build_location_jsonld)."""
        return build_location_jsonld(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            '@id': self.get_iri() if self.canonical_id else None,
            'canonical_id': self.canonical_id,
            'name': self.name,
            'city': self.city,
            'state': self.state,
            'country': self.country,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'file_count': self.file_count,
        }


# ---------------------------------------------------------------------------
# schema.org JSON-LD builders (single source of truth)
#
# Each ``to_schema_org()`` method delegates to the matching builder below.
# Builders operate on any object exposing the entity's column attributes — an
# ORM instance *or* a lightweight Core-query row — so the ORM path and the
# exporter's Core-query path (SchemaOrgExporter, use_core=True) produce byte-
# identical output with no duplicated serialization logic. Relationship args
# are sequences of objects exposing ``get_iri()`` and ``name`` (ORM entities or
# lightweight refs). Do not inline these back into the methods.
# ---------------------------------------------------------------------------


def file_iri(file_id: str, canonical_id: Optional[str] = None) -> str:
    """Return the canonical JSON-LD ``@id`` IRI for a file record.

    Prefer *canonical_id* when present (it is already in ``urn:sha256:…``
    format); fall back to ``urn:sha256:{file_id}`` so that callers during
    migration backfill (before canonical IDs are assigned) get a stable IRI.

    Single source of truth for the ``urn:sha256:{id}`` fallback expression.
    Any future URN-scheme change only needs to be made here.
    """
    return canonical_id or f"urn:sha256:{file_id}"


def build_file_relationships(categories, companies, people, locations) -> Dict[str, Any]:
    """Build a File's schema.org relationship properties from related entities."""
    relationships: Dict[str, Any] = {}

    # Categories — primary as mainEntityOfPage, remainder as about
    if categories:
        primary = categories[0]
        relationships["mainEntityOfPage"] = {
            "@type": "DefinedTerm",
            "@id": primary.get_iri(),
            "name": primary.name,
        }
        if len(categories) > 1:
            relationships["about"] = [
                {"@type": "DefinedTerm", "@id": cat.get_iri(), "name": cat.name}
                for cat in categories[1:]
            ]

    # Companies + people -> mentions
    mentions = []
    if companies:
        mentions.extend(
            {"@type": "Organization", "@id": comp.get_iri(), "name": comp.name}
            for comp in companies
        )
    if people:
        mentions.extend(
            {"@type": "Person", "@id": person.get_iri(), "name": person.name}
            for person in people
        )
    if mentions:
        relationships["mentions"] = mentions

    # Locations -> spatialCoverage (single object or list)
    if locations:
        if len(locations) == 1:
            relationships["spatialCoverage"] = {
                "@type": "Place",
                "@id": locations[0].get_iri(),
                "name": locations[0].name,
            }
        else:
            relationships["spatialCoverage"] = [
                {"@type": "Place", "@id": loc.get_iri(), "name": loc.name}
                for loc in locations
            ]

    return relationships


def build_file_jsonld(f, categories, companies, people, locations) -> Dict[str, Any]:
    """Build a File's schema.org JSON-LD from column values + related entities."""
    schema_type = f.schema_type or File.get_schema_type_from_mime(f.mime_type)

    result = {
        "@context": "https://schema.org",
        "@type": schema_type,
        "@id": file_iri(f.id, f.canonical_id),
        "name": f.filename,
    }

    # description: classifier-derived, sourced from the persisted generated
    # schema (File has no description column)
    schema_data = f.schema_data
    if isinstance(schema_data, dict) and schema_data.get("description"):
        result["description"] = schema_data["description"]

    if f.created_at:
        result["dateCreated"] = f.created_at.isoformat()
    if f.modified_at:
        result["dateModified"] = f.modified_at.isoformat()
    if f.mime_type:
        result["encodingFormat"] = f.mime_type
    if f.file_size:
        result["contentSize"] = str(f.file_size)
    if f.original_path:
        result["url"] = f.original_path
    if f.extracted_text:
        result["text"] = f.extracted_text[:2000]  # truncate for embedding
    if f.detected_language:
        result["inLanguage"] = f.detected_language

    if schema_type == "ImageObject":
        if f.image_width:
            result["width"] = f.image_width
        if f.image_height:
            result["height"] = f.image_height
        if f.has_faces is not None:
            result["hasFaces"] = f.has_faces  # custom ml: extension
        if f.exif_datetime:
            result["datePublished"] = f.exif_datetime.isoformat()
        if f.gps_latitude and f.gps_longitude:
            result["contentLocation"] = {
                "@type": "Place",
                "geo": {
                    "@type": "GeoCoordinates",
                    "latitude": f.gps_latitude,
                    "longitude": f.gps_longitude,
                },
            }

    result.update(build_file_relationships(categories, companies, people, locations))
    return result


def build_category_jsonld(f, parent, subcategories) -> Dict[str, Any]:
    """Build a Category's schema.org JSON-LD (DefinedTerm) from column values."""
    result = {
        "@context": "https://schema.org",
        "@type": "DefinedTerm",
        "@id": f"urn:uuid:{f.canonical_id}",
        "name": f.name,
    }

    if f.full_path:
        result["identifier"] = f.full_path.lower().replace("/", "-")

    # definition: description if present, else a generated fallback (custom)
    result["definition"] = f.description if f.description else f"Category: {f.name}"

    result["inDefinedTermSet"] = {
        "@type": "DefinedTermSet",
        "@id": "urn:uuid:categories-taxonomy",
        "name": "File Organization Categories",
    }

    if parent:  # SKOS broader
        result["broader"] = {
            "@type": "DefinedTerm",
            "@id": parent.get_iri(),
            "name": parent.name,
        }
    if subcategories:  # SKOS narrower
        result["narrower"] = [
            {"@type": "DefinedTerm", "@id": sub.get_iri(), "name": sub.name}
            for sub in subcategories
        ]

    result["fileCount"] = f.file_count or 0        # custom ml: extension
    result["hierarchyLevel"] = f.level or 0        # custom ml: extension
    if f.icon:
        result["icon"] = f.icon                    # custom extension
    if f.color:
        result["color"] = f.color                  # custom extension

    return result


def build_company_jsonld(f) -> Dict[str, Any]:
    """Build a Company's schema.org JSON-LD (Organization) from column values."""
    result = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "@id": f"urn:uuid:{f.canonical_id}",
        "name": f.name,
    }

    if f.domain:
        result["url"] = (
            f.domain if f.domain.startswith(("http://", "https://")) else f"https://{f.domain}"
        )
    if f.industry:
        result["knowsAbout"] = f.industry
    if f.first_seen:
        result["dateFounded"] = f.first_seen.date().isoformat()  # custom (non-standard)
        result["dateCreated"] = f.first_seen.isoformat()
    if f.last_seen:
        result["dateModified"] = f.last_seen.isoformat()

    same_as = []
    if f.domain:
        same_as.append(f"https://{f.domain.replace('https://', '').replace('http://', '')}")
    same_as.append(Company.generate_wikidata_url(f.name))
    if same_as:
        result["sameAs"] = [url for url in same_as if url]

    result["mentionCount"] = f.file_count or 0     # custom ml: extension
    return result


def build_person_jsonld(f) -> Dict[str, Any]:
    """Build a Person's schema.org JSON-LD from column values."""
    result = {
        "@context": "https://schema.org",
        "@type": "Person",
        "@id": f"urn:uuid:{f.canonical_id}",
        "name": f.name,
    }

    if f.email:
        result["email"] = f.email
    if f.role:
        result["jobTitle"] = f.role
    if f.first_seen:
        result["dateCreated"] = f.first_seen.isoformat()
    if f.last_seen:
        result["dateModified"] = f.last_seen.isoformat()

    result["mentionCount"] = f.file_count or 0     # custom ml: extension
    return result


def location_schema_type(city, state, country) -> str:
    """Return the schema.org @type for a location (Place, City, or Country)."""
    if city and state and country:
        return "Place"  # full address
    elif country and not state and not city:
        return "Country"
    elif city:
        return "City"
    return "Place"  # default


def build_location_jsonld(f) -> Dict[str, Any]:
    """Build a Location's schema.org JSON-LD (Place) from column values."""
    result = {
        "@context": "https://schema.org",
        "@type": location_schema_type(f.city, f.state, f.country),
        "@id": f"urn:uuid:{f.canonical_id}",
        "name": f.name,
    }

    address = {}
    if f.city:
        address["addressLocality"] = f.city
    if f.state:
        address["addressRegion"] = f.state
    if f.country:
        # country code if already 2 chars, else attempt to derive one
        address["addressCountry"] = f.country if len(f.country) == 2 else f.country[:2]
    if address:
        result["address"] = {"@type": "PostalAddress", **address}

    if f.latitude is not None and f.longitude is not None:
        result["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": f.latitude,
            "longitude": f.longitude,
        }
    if f.geohash:
        result["geoHash"] = f.geohash              # custom ml: extension
    if f.created_at:
        result["dateCreated"] = f.created_at.isoformat()

    result["mentionCount"] = f.file_count or 0     # custom ml: extension
    return result


class FileRelationship(Base):
    """
    Edge table for file-to-file relationships.

    Enables graph traversal between related files.
    """
    __tablename__ = 'file_relationships'

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_file_id = Column(String(SHA256_HEX_LENGTH), ForeignKey('files.id'), nullable=False, index=True)
    target_file_id = Column(String(SHA256_HEX_LENGTH), ForeignKey('files.id'), nullable=False, index=True)
    relationship_type = Column(SQLEnum(RelationshipType), nullable=False, index=True)

    # Relationship metadata
    confidence = Column(Float, default=1.0)
    extra_data = Column(JSON)  # Additional relationship-specific data

    # Timestamps
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    source_file = relationship('File', foreign_keys=[source_file_id], back_populates='related_to')
    target_file = relationship('File', foreign_keys=[target_file_id], back_populates='related_from')

    __table_args__ = (
        UniqueConstraint('source_file_id', 'target_file_id', 'relationship_type',
                        name='uq_file_relationship'),
        # ix_file_relationships_* indexes created by index=True on source_file_id, target_file_id, relationship_type
    )


class OrganizationSession(Base):
    """
    Represents a single organization run.

    Groups files processed together for tracking and rollback.
    """
    __tablename__ = 'organization_sessions'

    id = Column(String(SHA256_HEX_LENGTH), primary_key=True)  # UUID
    started_at = Column(DateTime, default=utcnow, index=True)
    completed_at = Column(DateTime)
    dry_run = Column(Boolean, default=False)

    # Session parameters
    source_directories = Column(JSON)  # List of source paths
    base_path = Column(String(BASE_PATH_MAX_LENGTH))
    file_limit = Column(Integer)

    # Statistics
    total_files = Column(Integer, default=0)
    organized_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)

    # Cost tracking
    total_cost = Column(Float, default=0.0)
    total_processing_time_sec = Column(Float, default=0.0)

    # Relationships
    files = relationship('File', back_populates='session')
    cost_records = relationship('CostRecord', back_populates='session')

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'dry_run': self.dry_run,
            'total_files': self.total_files,
            'organized_count': self.organized_count,
            'total_cost': self.total_cost,
        }


class CostRecord(Base):
    """
    Individual cost tracking record for feature usage.

    Links to files and sessions for detailed cost analysis.
    """
    __tablename__ = 'cost_records'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(SHA256_HEX_LENGTH), ForeignKey('organization_sessions.id'), index=True)
    file_id = Column(String(SHA256_HEX_LENGTH), ForeignKey('files.id'), index=True)

    feature_name = Column(String(SHORT_STRING_LENGTH), nullable=False, index=True)
    processing_time_sec = Column(Float, nullable=False)
    cost = Column(Float, default=0.0)
    success = Column(Boolean, default=True)
    error_message = Column(Text)

    # Timestamps
    created_at = Column(DateTime, default=utcnow, index=True)

    # Relationships
    session = relationship('OrganizationSession', back_populates='cost_records')
    file = relationship('File', back_populates='cost_records')

    __table_args__ = (
        Index('ix_cost_feature_date', 'feature_name', 'created_at'),
    )


class SchemaMetadata(Base):
    """
    Schema.org metadata storage.

    Stores the full JSON-LD Schema.org representation.
    """
    __tablename__ = 'schema_metadata'

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(SHA256_HEX_LENGTH), ForeignKey('files.id'), unique=True, index=True)

    # Schema.org properties
    schema_type = Column(String(SHORT_STRING_LENGTH), index=True)  # @type
    schema_context = Column(String(MAX_STRING_LENGTH), default='https://schema.org')
    schema_json = Column(JSON, nullable=False)  # Full JSON-LD

    # Validation
    is_valid = Column(Boolean, default=True)
    validation_errors = Column(JSON)

    # Timestamps
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    file = relationship('File', back_populates='schema_metadata')


class KeyValueStore(Base):
    """
    Flexible key-value storage for arbitrary metadata.

    Designed for schema-less data that doesn't fit the relational model.
    Supports namespacing, TTL, and JSON values.
    """
    __tablename__ = 'key_value_store'

    id = Column(Integer, primary_key=True, autoincrement=True)
    namespace = Column(String(SHORT_STRING_LENGTH), nullable=False, index=True)  # e.g., 'config', 'cache', 'temp'
    key = Column(String(MAX_STRING_LENGTH), nullable=False)
    value = Column(JSON)
    value_type = Column(String(SHORT_FIELD_LENGTH))  # 'string', 'int', 'float', 'json', 'binary'

    # Optional association with a file
    file_id = Column(String(SHA256_HEX_LENGTH), ForeignKey('files.id'), index=True)

    # TTL support
    expires_at = Column(DateTime)

    # Timestamps
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint('namespace', 'key', name='uq_namespace_key'),
        Index('ix_kv_namespace_key', 'namespace', 'key'),
        Index('ix_kv_expires', 'expires_at'),
    )


class MergeEventType(enum.Enum):
    """Types of merge events."""
    CATEGORY = "category"
    COMPANY = "company"
    PERSON = "person"
    LOCATION = "location"
    FILE = "file"


class MergeEvent(Base):
    """
    Track entity merges with owl:sameAs semantics.

    When entities are deduplicated or merged, this table records:
    - Which entities were merged
    - The canonical (surviving) entity
    - The reasoning and confidence
    - JSON-LD representation with owl:sameAs

    This enables:
    - Audit trail of all merges
    - Rollback capability
    - Linked Data compatibility via owl:sameAs
    - Historical ID preservation
    """
    __tablename__ = 'merge_events'

    id = Column(String(UUID_STRING_LENGTH), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Target entity (canonical/surviving)
    target_entity_type = Column(SQLEnum(MergeEventType), nullable=False)  # indexed via ix_merge_entity_type
    target_entity_id = Column(Integer, nullable=False)  # Internal DB ID
    target_canonical_id = Column(String(UUID_STRING_LENGTH))  # UUID for JSON-LD @id

    # Source entities being merged (list of internal IDs)
    source_entity_ids = Column(JSON, nullable=False)

    # Source canonical IDs (for JSON-LD owl:sameAs)
    source_canonical_ids = Column(JSON)

    # Metadata
    merge_reason = Column(Text)  # Why these were merged
    confidence = Column(Float, default=1.0)  # 0.0-1.0
    performed_by = Column(String(100))  # user_id or 'system'
    performed_at = Column(DateTime, default=utcnow)  # indexed via ix_merge_performed_at

    # JSON-LD representation (for export/API)
    jsonld = Column(JSON)

    # Rollback support
    is_rolled_back = Column(Boolean, default=False)
    rolled_back_at = Column(DateTime)
    rolled_back_by = Column(String(100))

    __table_args__ = (
        Index('ix_merge_entity_type', 'target_entity_type'),
        Index('ix_merge_performed_at', 'performed_at'),
    )

    def generate_jsonld(self) -> dict:
        """
        Generate JSON-LD with owl:sameAs for this merge event.

        Returns:
            JSON-LD dict representing the merge
        """
        target_iri = f"urn:uuid:{self.target_canonical_id}" if self.target_canonical_id else None
        source_iris = [f"urn:uuid:{cid}" for cid in (self.source_canonical_ids or [])]

        return {
            "@context": {
                "@vocab": "https://schema.org/",
                "owl": "http://www.w3.org/2002/07/owl#"
            },
            "@type": "MergeAction",
            "@id": f"urn:uuid:{self.id}",
            "targetEntity": {
                "@id": target_iri,
                "owl:sameAs": source_iris if len(source_iris) > 1 else source_iris[0] if source_iris else None
            },
            "description": self.merge_reason,
            "confidence": self.confidence,
            "agent": self.performed_by,
            "startTime": self.performed_at.isoformat() if self.performed_at else None
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'target_entity_type': self.target_entity_type.value if self.target_entity_type else None,
            'target_entity_id': self.target_entity_id,
            'target_canonical_id': self.target_canonical_id,
            'source_entity_ids': self.source_entity_ids,
            'source_canonical_ids': self.source_canonical_ids,
            'merge_reason': self.merge_reason,
            'confidence': self.confidence,
            'performed_by': self.performed_by,
            'performed_at': self.performed_at.isoformat() if self.performed_at else None,
            'is_rolled_back': self.is_rolled_back,
        }


def init_db(db_path: str = 'file_organization.db') -> Session:
    """
    Initialize the database and return a session.

    Args:
        db_path: Path to SQLite database file

    Returns:
        SQLAlchemy Session
    """
    engine = create_engine(f'sqlite:///{db_path}', echo=False)

    # Enable foreign keys for SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")  # Better concurrency
        cursor.close()

    # Create all tables
    Base.metadata.create_all(engine)

    # Create session factory
    SessionLocal = sessionmaker(bind=engine)

    return SessionLocal()


def get_session(db_path: str = 'file_organization.db') -> Session:
    """Get a database session."""
    return init_db(db_path)
