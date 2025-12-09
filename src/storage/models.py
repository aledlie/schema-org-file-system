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

from datetime import datetime
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
    Column('file_id', String(64), ForeignKey('files.id'), primary_key=True),
    Column('category_id', Integer, ForeignKey('categories.id'), primary_key=True),
    Column('confidence', Float, default=1.0),
    Column('created_at', DateTime, default=datetime.utcnow)
)

file_companies = Table(
    'file_companies',
    Base.metadata,
    Column('file_id', String(64), ForeignKey('files.id'), primary_key=True),
    Column('company_id', Integer, ForeignKey('companies.id'), primary_key=True),
    Column('confidence', Float, default=1.0),
    Column('context', String(255)),  # How the company was detected
    Column('created_at', DateTime, default=datetime.utcnow)
)

file_people = Table(
    'file_people',
    Base.metadata,
    Column('file_id', String(64), ForeignKey('files.id'), primary_key=True),
    Column('person_id', Integer, ForeignKey('people.id'), primary_key=True),
    Column('role', String(50)),  # author, subject, mentioned, etc.
    Column('confidence', Float, default=1.0),
    Column('created_at', DateTime, default=datetime.utcnow)
)

file_locations = Table(
    'file_locations',
    Base.metadata,
    Column('file_id', String(64), ForeignKey('files.id'), primary_key=True),
    Column('location_id', Integer, ForeignKey('locations.id'), primary_key=True),
    Column('location_type', String(50)),  # captured_at, mentioned, subject
    Column('confidence', Float, default=1.0),
    Column('created_at', DateTime, default=datetime.utcnow)
)


class File(Base):
    """
    Central node representing a file in the system.

    The file ID is a SHA-256 hash of the original path for deduplication.
    """
    __tablename__ = 'files'

    # Primary key is hash of original path
    id = Column(String(64), primary_key=True)

    # File identification
    filename = Column(String(255), nullable=False, index=True)
    original_path = Column(Text, nullable=False)
    current_path = Column(Text)  # Where it is now (after organization)
    file_extension = Column(String(20), index=True)
    mime_type = Column(String(100))

    # File properties
    file_size = Column(Integer)
    content_hash = Column(String(64), index=True)  # SHA-256 of content
    created_at = Column(DateTime)
    modified_at = Column(DateTime)
    organized_at = Column(DateTime)

    # Organization status
    status = Column(SQLEnum(FileStatus), default=FileStatus.PENDING, index=True)
    organization_reason = Column(Text)

    # Extracted content
    extracted_text = Column(Text)
    extracted_text_length = Column(Integer, default=0)

    # Schema.org metadata (stored as JSON)
    schema_type = Column(String(50))  # ImageObject, Document, etc.
    schema_data = Column(JSON)

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
    session_id = Column(String(64), ForeignKey('organization_sessions.id'))

    # Timestamps
    db_created_at = Column(DateTime, default=datetime.utcnow)
    db_updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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

    @hybrid_property
    def is_organized(self) -> bool:
        return self.status == FileStatus.ORGANIZED

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
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


class Category(Base):
    """
    Category node for file classification.

    Supports hierarchical categories (e.g., Legal/Contracts, Media/Photos).
    """
    __tablename__ = 'categories'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    parent_id = Column(Integer, ForeignKey('categories.id'))
    description = Column(Text)
    icon = Column(String(50))  # Emoji or icon name
    color = Column(String(20))  # Hex color

    # Hierarchy
    level = Column(Integer, default=0)  # 0 = root, 1 = subcategory, etc.
    full_path = Column(String(255), index=True)  # e.g., "Legal/Contracts"

    # Statistics
    file_count = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    files = relationship('File', secondary=file_categories, back_populates='categories')
    parent = relationship('Category', remote_side=[id], backref='subcategories')

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'full_path': self.full_path,
            'level': self.level,
            'file_count': self.file_count,
        }


class Company(Base):
    """
    Company node for organization affiliation.

    Represents companies detected in documents.
    """
    __tablename__ = 'companies'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    normalized_name = Column(String(255), unique=True, index=True)  # Lowercase, trimmed
    domain = Column(String(255))  # Company website domain
    industry = Column(String(100))

    # Statistics
    file_count = Column(Integer, default=0)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)

    # Relationships
    files = relationship('File', secondary=file_companies, back_populates='companies')

    __table_args__ = (
        Index('ix_companies_normalized', 'normalized_name'),
    )

    @staticmethod
    def normalize_name(name: str) -> str:
        """Normalize company name for deduplication."""
        return name.lower().strip()

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'domain': self.domain,
            'file_count': self.file_count,
        }


class Person(Base):
    """
    Person node for people detected in files.

    Could be authors, subjects, or mentioned individuals.
    """
    __tablename__ = 'people'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    normalized_name = Column(String(255), unique=True, index=True)
    email = Column(String(255))
    role = Column(String(100))  # Default role

    # Statistics
    file_count = Column(Integer, default=0)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)

    # Relationships
    files = relationship('File', secondary=file_people, back_populates='people')

    @staticmethod
    def normalize_name(name: str) -> str:
        """Normalize person name for deduplication."""
        return name.lower().strip()

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'file_count': self.file_count,
        }


class Location(Base):
    """
    Location node for geographic data.

    Extracted from EXIF GPS data or document content.
    """
    __tablename__ = 'locations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    city = Column(String(100))
    state = Column(String(100))
    country = Column(String(100))
    latitude = Column(Float)
    longitude = Column(Float)

    # Geohash for efficient spatial queries
    geohash = Column(String(12), index=True)

    # Statistics
    file_count = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    files = relationship('File', secondary=file_locations, back_populates='locations')

    __table_args__ = (
        Index('ix_locations_geo', 'latitude', 'longitude'),
        Index('ix_locations_city_state', 'city', 'state'),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'city': self.city,
            'state': self.state,
            'country': self.country,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'file_count': self.file_count,
        }


class FileRelationship(Base):
    """
    Edge table for file-to-file relationships.

    Enables graph traversal between related files.
    """
    __tablename__ = 'file_relationships'

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_file_id = Column(String(64), ForeignKey('files.id'), nullable=False, index=True)
    target_file_id = Column(String(64), ForeignKey('files.id'), nullable=False, index=True)
    relationship_type = Column(SQLEnum(RelationshipType), nullable=False, index=True)

    # Relationship metadata
    confidence = Column(Float, default=1.0)
    extra_data = Column(JSON)  # Additional relationship-specific data

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    source_file = relationship('File', foreign_keys=[source_file_id], back_populates='related_to')
    target_file = relationship('File', foreign_keys=[target_file_id], back_populates='related_from')

    __table_args__ = (
        UniqueConstraint('source_file_id', 'target_file_id', 'relationship_type',
                        name='uq_file_relationship'),
        Index('ix_file_rel_type', 'relationship_type'),
    )


class OrganizationSession(Base):
    """
    Represents a single organization run.

    Groups files processed together for tracking and rollback.
    """
    __tablename__ = 'organization_sessions'

    id = Column(String(64), primary_key=True)  # UUID
    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime)
    dry_run = Column(Boolean, default=False)

    # Session parameters
    source_directories = Column(JSON)  # List of source paths
    base_path = Column(String(500))
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
    session_id = Column(String(64), ForeignKey('organization_sessions.id'), index=True)
    file_id = Column(String(64), ForeignKey('files.id'), index=True)

    feature_name = Column(String(50), nullable=False, index=True)
    processing_time_sec = Column(Float, nullable=False)
    cost = Column(Float, default=0.0)
    success = Column(Boolean, default=True)
    error_message = Column(Text)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

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
    file_id = Column(String(64), ForeignKey('files.id'), unique=True, index=True)

    # Schema.org properties
    schema_type = Column(String(50), index=True)  # @type
    schema_context = Column(String(255), default='https://schema.org')
    schema_json = Column(JSON, nullable=False)  # Full JSON-LD

    # Validation
    is_valid = Column(Boolean, default=True)
    validation_errors = Column(JSON)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    namespace = Column(String(50), nullable=False, index=True)  # e.g., 'config', 'cache', 'temp'
    key = Column(String(255), nullable=False)
    value = Column(JSON)
    value_type = Column(String(20))  # 'string', 'int', 'float', 'json', 'binary'

    # Optional association with a file
    file_id = Column(String(64), ForeignKey('files.id'), index=True)

    # TTL support
    expires_at = Column(DateTime)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('namespace', 'key', name='uq_namespace_key'),
        Index('ix_kv_namespace_key', 'namespace', 'key'),
        Index('ix_kv_expires', 'expires_at'),
    )


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
    def set_sqlite_pragma(dbapi_connection, connection_record):
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
