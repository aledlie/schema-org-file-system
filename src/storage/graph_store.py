#!/usr/bin/env python3
"""
Graph-based storage operations for file organization data.

Provides high-level operations for managing files, categories, and their
relationships using a graph-like structure built on SQLAlchemy.
"""

import uuid
from datetime import datetime
from ._time import utcnow
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

from sqlalchemy import create_engine, event, func, and_, or_
from sqlalchemy.orm import Session, sessionmaker, joinedload, selectinload
from sqlalchemy.exc import IntegrityError

from .models import (
    Base, File, Category, Company, Person, Location,
    OrganizationSession, FileRelationship, CostRecord,
    FileStatus, RelationshipType, file_categories
)
try:
    from ..constants import (
        COORDINATE_TOLERANCE_DEG,
        DEFAULT_SEARCH_LIMIT,
        KM_PER_DEGREE_LATITUDE,
        TOP_EXTENSIONS_LIMIT,
    )
except ImportError:
    from constants import (
        COORDINATE_TOLERANCE_DEG,
        DEFAULT_SEARCH_LIMIT,
        KM_PER_DEGREE_LATITUDE,
        TOP_EXTENSIONS_LIMIT,
    )


# Substrings (case-insensitive) that mark a `Person.name` as an obvious
# non-person false positive (organization/meeting names misdetected as
# people). Used by `get_all_people_with_files` to filter results.
_PERSON_NAME_DENYLIST = (
    "studio",
    "meeting",
    "member id",
    "inc",
    "llc",
    "corp",
    "company",
)


class GraphStore:
    """
    High-level interface for graph-based file storage.

    Provides methods for:
    - File CRUD operations
    - Category management with hierarchy
    - Relationship traversal (graph queries)
    - Statistics and aggregations
    """

    def __init__(self, db_path: str = 'results/file_organization.db'):
        """
        Initialize the graph store.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path
        self.engine = create_engine(f'sqlite:///{db_path}', echo=False)

        # Enable SQLite optimizations
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
            cursor.close()

        # Create tables
        Base.metadata.create_all(self.engine)

        # Session factory
        self.SessionLocal = sessionmaker(bind=self.engine)

    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()

    # =========================================================================
    # File Operations
    # =========================================================================

    def add_file(
        self,
        original_path: str,
        filename: str,
        session: Session = None,
        **kwargs
    ) -> File:
        """
        Add a new file to the store.

        Args:
            original_path: Original file path
            filename: File name
            session: Optional existing session
            **kwargs: Additional file properties

        Returns:
            Created File object
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            file_id = File.generate_id(original_path)

            # Check if file already exists
            existing = session.query(File).filter(File.id == file_id).first()
            if existing:
                # Update existing file
                for key, value in kwargs.items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
                session.commit()
                return existing

            # Create new file with canonical ID
            file = File(
                id=file_id,
                canonical_id=File.generate_canonical_id(original_path),
                original_path=original_path,
                filename=filename,
                file_extension=Path(filename).suffix.lower() if filename else None,
                **kwargs
            )
            session.add(file)
            session.commit()
            return file

        except Exception as e:
            session.rollback()
            raise e
        finally:
            if close_session:
                session.close()

    def get_file(self, file_id: str = None, path: str = None, session: Session = None) -> Optional[File]:
        """
        Get a file by ID or path.

        Args:
            file_id: File ID (hash)
            path: Original file path
            session: Optional existing session

        Returns:
            File object or None
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            if file_id:
                return session.query(File).filter(File.id == file_id).first()
            elif path:
                file_id = File.generate_id(path)
                return session.query(File).filter(File.id == file_id).first()
            return None
        finally:
            if close_session:
                session.close()

    def get_files(
        self,
        status: FileStatus = None,
        category: str = None,
        company: str = None,
        extension: str = None,
        limit: int = 100,
        offset: int = 0,
        session: Session = None
    ) -> List[File]:
        """
        Query files with filters.

        Args:
            status: Filter by status
            category: Filter by category name
            company: Filter by company name
            extension: Filter by file extension
            limit: Maximum results
            offset: Skip first N results
            session: Optional existing session

        Returns:
            List of File objects
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            query = session.query(File).options(
                joinedload(File.categories),
                joinedload(File.companies)
            )

            if status:
                query = query.filter(File.status == status)
            if extension:
                query = query.filter(File.file_extension == extension.lower())
            if category:
                query = query.join(File.categories).filter(Category.name == category)
            if company:
                query = query.join(File.companies).filter(Company.name == company)

            return query.order_by(File.organized_at.desc()).offset(offset).limit(limit).all()

        finally:
            if close_session:
                session.close()

    def update_file_status(
        self,
        file_id: str,
        status: FileStatus,
        destination: str = None,
        reason: str = None,
        session: Session = None
    ) -> bool:
        """
        Update file organization status.

        Args:
            file_id: File ID
            status: New status
            destination: New file path after organization
            reason: Reason for status
            session: Optional existing session

        Returns:
            True if updated successfully
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            file = session.query(File).filter(File.id == file_id).first()
            if not file:
                return False

            file.status = status
            file.current_path = destination
            file.organization_reason = reason
            if status == FileStatus.ORGANIZED:
                file.organized_at = utcnow()

            session.commit()
            return True

        except Exception as e:
            session.rollback()
            raise e
        finally:
            if close_session:
                session.close()

    # =========================================================================
    # Category Operations
    # =========================================================================

    def get_or_create_category(
        self,
        name: str,
        parent_name: str = None,
        session: Session = None
    ) -> Optional[Category]:
        """
        Get or create a category.

        Args:
            name: Category name
            parent_name: Parent category name (for hierarchy)
            session: Optional existing session

        Returns:
            Category object or None if creation fails
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            # Build full path
            if parent_name:
                full_path = f"{parent_name}/{name}"
            else:
                full_path = name

            # Check if exists
            category = session.query(Category).filter(Category.full_path == full_path).first()
            if category:
                return category

            # Get parent if specified
            parent = None
            level = 0
            if parent_name:
                parent = session.query(Category).filter(Category.name == parent_name).first()
                if parent:
                    level = parent.level + 1

            # Create new category with canonical ID
            category = Category(
                name=name,
                canonical_id=Category.generate_canonical_id(full_path),
                parent_id=parent.id if parent else None,
                level=level,
                full_path=full_path
            )
            session.add(category)
            # Only commit if we own the session
            if close_session:
                session.commit()
            else:
                session.flush()  # Ensure ID is generated but don't commit
            return category

        except IntegrityError:
            session.rollback()
            # Race condition - return existing
            return session.query(Category).filter(Category.full_path == full_path).first()
        finally:
            if close_session:
                session.close()

    def add_file_to_category(
        self,
        file_id: str,
        category_name: str,
        subcategory_name: str = None,
        confidence: float = 1.0,
        session: Session = None
    ) -> bool:
        """
        Associate a file with a category.

        Args:
            file_id: File ID
            category_name: Main category
            subcategory_name: Optional subcategory
            confidence: Classification confidence
            session: Optional existing session

        Returns:
            True if successful
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            file = session.query(File).filter(File.id == file_id).first()
            if not file:
                return False

            # Get or create category
            if subcategory_name:
                # Create parent first
                parent = self.get_or_create_category(category_name, session=session)
                category = self.get_or_create_category(subcategory_name, category_name, session=session)
            else:
                category = self.get_or_create_category(category_name, session=session)

            # Guard against None category
            if category is None:
                return False

            # Add relationship if not exists
            if category not in file.categories:
                file.categories.append(category)
                category.file_count += 1
                # Only commit if we own the session
                if close_session:
                    session.commit()

            return True

        except Exception as e:
            session.rollback()
            raise e
        finally:
            if close_session:
                session.close()

    def get_category_tree(self, session: Session = None) -> List[Dict[str, Any]]:
        """
        Get the full category hierarchy as a tree.

        Returns:
            List of root categories with nested subcategories
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            categories = session.query(Category).options(
                selectinload(Category.subcategories).selectinload(Category.subcategories)
            ).order_by(Category.level, Category.name).all()

            # Build tree structure
            tree = []
            for category in categories:
                if category.parent_id is None:
                    tree.append(self._build_category_node(category))

            return tree

        finally:
            if close_session:
                session.close()

    def _build_category_node(self, category: Category) -> Dict[str, Any]:
        """Build a category tree node recursively."""
        node = category.to_dict()
        node['subcategories'] = [self._build_category_node(sub) for sub in category.subcategories]
        return node

    # =========================================================================
    # Company Operations
    # =========================================================================

    def get_or_create_company(self, name: str, session: Session = None) -> Optional[Company]:
        """Get or create a company by name."""
        close_session = session is None
        session = session or self.get_session()

        try:
            normalized = Company.normalize_name(name)
            company = session.query(Company).filter(Company.normalized_name == normalized).first()

            if not company:
                company = Company(
                    name=name,
                    normalized_name=normalized,
                    canonical_id=Company.generate_canonical_id(name)
                )
                session.add(company)
                # Only commit if we own the session
                if close_session:
                    session.commit()
                else:
                    session.flush()

            return company

        except IntegrityError:
            session.rollback()
            return session.query(Company).filter(Company.normalized_name == normalized).first()
        finally:
            if close_session:
                session.close()

    def add_file_to_company(
        self,
        file_id: str,
        company_name: str,
        confidence: float = 1.0,
        context: str = None,
        session: Session = None
    ) -> bool:
        """Associate a file with a company."""
        close_session = session is None
        session = session or self.get_session()

        try:
            file = session.query(File).filter(File.id == file_id).first()
            if not file:
                return False

            company = self.get_or_create_company(company_name, session=session)

            # Guard against None company
            if company is None:
                return False

            if company not in file.companies:
                file.companies.append(company)
                company.file_count += 1
                company.last_seen = utcnow()
                # Only commit if we own the session
                if close_session:
                    session.commit()

            return True

        except Exception as e:
            session.rollback()
            raise e
        finally:
            if close_session:
                session.close()

    # =========================================================================
    # Person Operations
    # =========================================================================

    def get_or_create_person(
        self,
        name: str,
        email: str = None,
        role: str = None,
        session: Session = None
    ) -> Optional[Person]:
        """Get or create a person by name."""
        close_session = session is None
        session = session or self.get_session()

        try:
            normalized = Person.normalize_name(name)
            person = session.query(Person).filter(Person.normalized_name == normalized).first()

            if not person:
                person = Person(
                    name=name,
                    normalized_name=normalized,
                    canonical_id=Person.generate_canonical_id(name),
                    email=email,
                    role=role
                )
                session.add(person)
                if close_session:
                    session.commit()
                else:
                    session.flush()

            return person

        except IntegrityError:
            session.rollback()
            return session.query(Person).filter(Person.normalized_name == normalized).first()
        finally:
            if close_session:
                session.close()

    def add_file_to_person(
        self,
        file_id: str,
        person_name: str,
        role: str = None,
        confidence: float = 1.0,
        session: Session = None
    ) -> bool:
        """Associate a file with a person."""
        close_session = session is None
        session = session or self.get_session()

        try:
            file = session.query(File).filter(File.id == file_id).first()
            if not file:
                return False

            person = self.get_or_create_person(person_name, role=role, session=session)

            if person is None:
                return False

            if person not in file.people:
                file.people.append(person)
                person.file_count += 1
                person.last_seen = utcnow()
                if close_session:
                    session.commit()

            return True

        except Exception as e:
            session.rollback()
            raise e
        finally:
            if close_session:
                session.close()

    def get_all_people_with_files(
        self,
        session: Session = None,
        min_files: int = 1
    ) -> List[Tuple[str, List[str]]]:
        """
        Get all people who have at least `min_files` organized files.

        Filters out obvious non-person false positives (organization or
        meeting names accidentally detected as people) using
        `_PERSON_NAME_DENYLIST`, and excludes files that haven't been
        organized yet (current_path is None).

        Args:
            session: Optional existing session
            min_files: Minimum number of valid (organized) files a person
                must have to be included in the results

        Returns:
            List of (display_name, [file.current_path, ...]) tuples
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            results = []
            people = session.query(Person).options(selectinload(Person.files)).all()

            for person in people:
                name_lower = person.name.lower()
                if any(term in name_lower for term in _PERSON_NAME_DENYLIST):
                    continue

                paths = [f.current_path for f in person.files if f.current_path]

                if len(paths) >= min_files:
                    results.append((person.name, paths))

            return results
        finally:
            if close_session:
                session.close()

    def get_files_by_person(
        self,
        person_id_or_name,
        session: Session = None
    ) -> List[str]:
        """
        Get the current file paths associated with a single person.

        Args:
            person_id_or_name: Person primary key (int), or name (str,
                matched via Person.normalize_name, same lookup style as
                get_or_create_person)
            session: Optional existing session

        Returns:
            List of file.current_path values (None paths excluded); empty
            list if the person isn't found
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            if isinstance(person_id_or_name, int):
                person = session.query(Person).filter(Person.id == person_id_or_name).first()
            else:
                normalized = Person.normalize_name(person_id_or_name)
                person = session.query(Person).filter(
                    Person.normalized_name == normalized
                ).first()

            if not person:
                return []

            return [f.current_path for f in person.files if f.current_path]
        finally:
            if close_session:
                session.close()

    def _find_person(self, person_id_or_name, session: Session) -> Optional[Person]:
        """Look up a person by primary key (int) or name (str, normalized)."""
        if isinstance(person_id_or_name, int):
            return session.query(Person).filter(Person.id == person_id_or_name).first()
        normalized = Person.normalize_name(person_id_or_name)
        return session.query(Person).filter(Person.normalized_name == normalized).first()

    def remove_person_edge(
        self,
        file_id: str,
        person_id_or_name,
        session: Session = None
    ) -> bool:
        """
        Remove a single file->person edge, keeping both rows.

        Args:
            file_id: File primary key (SHA-256 hex)
            person_id_or_name: Person primary key (int), or name (str,
                matched via Person.normalize_name)
            session: Optional existing session

        Returns:
            True if an edge existed and was removed, False otherwise
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            file = session.query(File).filter(File.id == file_id).first()
            person = self._find_person(person_id_or_name, session)
            if not file or not person or person not in file.people:
                return False

            file.people.remove(person)
            person.file_count = max((person.file_count or 0) - 1, 0)
            if close_session:
                session.commit()
            return True

        except Exception as e:
            session.rollback()
            raise e
        finally:
            if close_session:
                session.close()

    def prune_person(
        self,
        person_id_or_name,
        dry_run: bool = False,
        session: Session = None
    ) -> Optional[Dict[str, Any]]:
        """
        Delete a person and all of its file->person edges.

        Intended for false-positive "people" (org/event names misdetected as
        people) and stale entries. Files are never touched on disk. Any other
        person merged into this one has its merge pointer cleared.

        Args:
            person_id_or_name: Person primary key (int), or name (str,
                matched via Person.normalize_name)
            dry_run: When True, report what would be removed without changes
            session: Optional existing session

        Returns:
            Summary dict with name/person_id/edges_removed/paths, or None if
            the person isn't found
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            person = self._find_person(person_id_or_name, session)
            if not person:
                return None

            summary = {
                'name': person.name,
                'person_id': person.id,
                'edges_removed': len(person.files),
                'paths': [f.current_path or f.original_path for f in person.files],
            }
            if dry_run:
                return summary

            person.files.clear()
            session.query(Person).filter(
                Person.merged_into_id == person.id
            ).update({Person.merged_into_id: None})
            session.delete(person)
            if close_session:
                session.commit()
            return summary

        except Exception as e:
            session.rollback()
            raise e
        finally:
            if close_session:
                session.close()

    def prune_missing_person_edges(
        self,
        dry_run: bool = False,
        session: Session = None
    ) -> Dict[str, Any]:
        """
        Drop file->person edges whose file no longer exists on disk.

        A file's presence is checked at its current_path (falling back to
        original_path when it was never organized). File and Person rows are
        kept — only the edges are removed; use prune_person to delete a
        person outright.

        Args:
            dry_run: When True, report what would be removed without changes
            session: Optional existing session

        Returns:
            {'edges_removed': N,
             'edges': [{'person': name, 'file_id': id, 'path': path}, ...]}
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            removed: List[Dict[str, Any]] = []
            people = session.query(Person).options(selectinload(Person.files)).all()

            for person in people:
                for file in list(person.files):
                    path = file.current_path or file.original_path
                    if not path or Path(path).exists():
                        continue
                    removed.append({
                        'person': person.name,
                        'file_id': file.id,
                        'path': path,
                    })
                    if not dry_run:
                        person.files.remove(file)
                        person.file_count = max((person.file_count or 0) - 1, 0)

            if not dry_run and close_session:
                session.commit()
            return {'edges_removed': len(removed), 'edges': removed}

        except Exception as e:
            session.rollback()
            raise e
        finally:
            if close_session:
                session.close()

    # =========================================================================
    # Location Operations
    # =========================================================================

    def get_or_create_location(
        self,
        name: str,
        latitude: float = None,
        longitude: float = None,
        city: str = None,
        state: str = None,
        country: str = None,
        session: Session = None
    ) -> Optional[Location]:
        """Get or create a location."""
        close_session = session is None
        session = session or self.get_session()

        try:
            # Try to find by coordinates first
            if latitude and longitude:
                location = session.query(Location).filter(
                    and_(
                        func.abs(Location.latitude - latitude) < COORDINATE_TOLERANCE_DEG,
                        func.abs(Location.longitude - longitude) < COORDINATE_TOLERANCE_DEG
                    )
                ).first()
                if location:
                    return location

            # Try to find by name
            location = session.query(Location).filter(Location.name == name).first()
            if location:
                return location

            # Create new location with canonical ID
            location = Location(
                name=name,
                canonical_id=Location.generate_canonical_id(name),
                latitude=latitude,
                longitude=longitude,
                city=city,
                state=state,
                country=country
            )
            session.add(location)
            # Only commit if we own the session
            if close_session:
                session.commit()
            else:
                session.flush()  # Ensure ID is generated but don't commit
            return location

        except IntegrityError:
            session.rollback()
            return session.query(Location).filter(Location.name == name).first()
        finally:
            if close_session:
                session.close()

    def add_file_to_location(
        self,
        file_id: str,
        location_name: str,
        location_type: str = None,
        latitude: float = None,
        longitude: float = None,
        city: str = None,
        state: str = None,
        country: str = None,
        confidence: float = 1.0,
        session: Session = None
    ) -> bool:
        """Associate a file with a location."""
        close_session = session is None
        session = session or self.get_session()

        try:
            file = session.query(File).filter(File.id == file_id).first()
            if not file:
                return False

            location = self.get_or_create_location(
                name=location_name,
                latitude=latitude,
                longitude=longitude,
                city=city,
                state=state,
                country=country,
                session=session
            )

            if location is None:
                return False

            if location not in file.locations:
                file.locations.append(location)
                location.file_count += 1
                if close_session:
                    session.commit()

            return True

        except Exception as e:
            session.rollback()
            raise e
        finally:
            if close_session:
                session.close()

    # =========================================================================
    # Relationship Operations (Graph Edges)
    # =========================================================================

    def add_relationship(
        self,
        source_file_id: str,
        target_file_id: str,
        relationship_type: RelationshipType,
        confidence: float = 1.0,
        metadata: Dict = None,
        session: Session = None
    ) -> FileRelationship:
        """
        Add a relationship between two files.

        Args:
            source_file_id: Source file ID
            target_file_id: Target file ID
            relationship_type: Type of relationship
            confidence: Relationship confidence
            metadata: Additional metadata

        Returns:
            Created relationship
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            # Check if relationship already exists
            existing = session.query(FileRelationship).filter(
                and_(
                    FileRelationship.source_file_id == source_file_id,
                    FileRelationship.target_file_id == target_file_id,
                    FileRelationship.relationship_type == relationship_type
                )
            ).first()

            if existing:
                existing.confidence = confidence
                existing.metadata = metadata
                session.commit()
                return existing

            relationship = FileRelationship(
                source_file_id=source_file_id,
                target_file_id=target_file_id,
                relationship_type=relationship_type,
                confidence=confidence,
                metadata=metadata
            )
            session.add(relationship)
            session.commit()
            return relationship

        except Exception as e:
            session.rollback()
            raise e
        finally:
            if close_session:
                session.close()

    def find_related_files(
        self,
        file_id: str,
        relationship_type: RelationshipType = None,
        depth: int = 1,
        session: Session = None
    ) -> List[Tuple[File, RelationshipType, float]]:
        """
        Find files related to a given file (graph traversal).

        Args:
            file_id: Starting file ID
            relationship_type: Filter by relationship type
            depth: How many hops to traverse (1 = direct relationships only)
            session: Optional existing session

        Returns:
            List of (file, relationship_type, confidence) tuples
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            results = []
            visited = {file_id}

            # BFS traversal
            current_level = [file_id]

            for _ in range(depth):
                next_level = []
                pending: list[tuple[int, str, float]] = []

                for current_id in current_level:
                    # Get outgoing relationships
                    query = session.query(FileRelationship).filter(
                        FileRelationship.source_file_id == current_id
                    )
                    if relationship_type:
                        query = query.filter(FileRelationship.relationship_type == relationship_type)

                    for rel in query.all():
                        if rel.target_file_id not in visited:
                            visited.add(rel.target_file_id)
                            next_level.append(rel.target_file_id)
                            pending.append((rel.target_file_id, rel.relationship_type, rel.confidence))

                    # Get incoming relationships
                    query = session.query(FileRelationship).filter(
                        FileRelationship.target_file_id == current_id
                    )
                    if relationship_type:
                        query = query.filter(FileRelationship.relationship_type == relationship_type)

                    for rel in query.all():
                        if rel.source_file_id not in visited:
                            visited.add(rel.source_file_id)
                            next_level.append(rel.source_file_id)
                            pending.append((rel.source_file_id, rel.relationship_type, rel.confidence))

                if pending:
                    pending_ids = [fid for fid, _, _ in pending]
                    file_map = {
                        f.id: f
                        for f in session.query(File).filter(File.id.in_(pending_ids)).all()
                    }
                    for fid, rel_type, confidence in pending:
                        file = file_map.get(fid)
                        if file:
                            results.append((file, rel_type, confidence))

                current_level = next_level

            return results

        finally:
            if close_session:
                session.close()

    def find_duplicates(self, content_hash: str = None, session: Session = None) -> List[List[File]]:
        """
        Find groups of duplicate files by content hash.

        Args:
            content_hash: Specific hash to look for (or all if None)
            session: Optional existing session

        Returns:
            List of file groups (files with same content)
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            if content_hash:
                files = session.query(File).filter(File.content_hash == content_hash).all()
                return [files] if len(files) > 1 else []

            # Find all hashes with more than one file
            duplicates = session.query(File.content_hash, func.count(File.id).label('count'))\
                .filter(File.content_hash.isnot(None))\
                .group_by(File.content_hash)\
                .having(func.count(File.id) > 1)\
                .all()

            duplicate_hashes = [h for h, _ in duplicates]
            all_files = session.query(File).filter(File.content_hash.in_(duplicate_hashes)).all()
            groups: defaultdict = defaultdict(list)
            for f in all_files:
                groups[f.content_hash].append(f)

            return list(groups.values())

        finally:
            if close_session:
                session.close()

    # =========================================================================
    # Session Operations
    # =========================================================================

    def create_session(
        self,
        source_directories: List[str],
        base_path: str,
        dry_run: bool = False,
        file_limit: int = None,
        session: Session = None
    ) -> OrganizationSession:
        """
        Create a new organization session.

        Args:
            source_directories: List of source paths
            base_path: Base path for organization
            dry_run: Whether this is a dry run
            file_limit: Optional file limit
            session: Optional existing session

        Returns:
            Created OrganizationSession
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            org_session = OrganizationSession(
                id=str(uuid.uuid4()),
                source_directories=source_directories,
                base_path=base_path,
                dry_run=dry_run,
                file_limit=file_limit
            )
            session.add(org_session)
            session.commit()
            return org_session

        except Exception as e:
            session.rollback()
            raise e
        finally:
            if close_session:
                session.close()

    def complete_session(
        self,
        session_id: str,
        stats: Dict[str, int],
        db_session: Session = None
    ) -> bool:
        """
        Mark a session as completed with statistics.

        Args:
            session_id: Session ID
            stats: Dictionary with total_files, organized_count, etc.
            db_session: Optional existing session

        Returns:
            True if successful
        """
        close_session = db_session is None
        db_session = db_session or self.get_session()

        try:
            org_session = db_session.query(OrganizationSession)\
                .filter(OrganizationSession.id == session_id).first()

            if not org_session:
                return False

            org_session.completed_at = utcnow()
            org_session.total_files = stats.get('total_files', 0)
            org_session.organized_count = stats.get('organized', 0)
            org_session.skipped_count = stats.get('skipped', 0)
            org_session.error_count = stats.get('errors', 0)
            org_session.total_cost = stats.get('total_cost', 0.0)
            org_session.total_processing_time_sec = stats.get('processing_time', 0.0)

            db_session.commit()
            return True

        except Exception as e:
            db_session.rollback()
            raise e
        finally:
            if close_session:
                db_session.close()

    # =========================================================================
    # Statistics and Aggregations
    # =========================================================================

    def get_statistics(self, session: Session = None) -> Dict[str, Any]:
        """
        Get overall statistics.

        Returns:
            Dictionary with counts and aggregations
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            stats = {
                'total_files': session.query(func.count(File.id)).scalar(),
                'organized_files': session.query(func.count(File.id))\
                    .filter(File.status == FileStatus.ORGANIZED).scalar(),
                'total_categories': session.query(func.count(Category.id)).scalar(),
                'total_companies': session.query(func.count(Company.id)).scalar(),
                'total_locations': session.query(func.count(Location.id)).scalar(),
                'total_relationships': session.query(func.count(FileRelationship.id)).scalar(),
                'total_sessions': session.query(func.count(OrganizationSession.id)).scalar(),
            }

            # Category breakdown
            category_counts = session.query(
                Category.name,
                func.count(file_categories.c.file_id)
            ).join(file_categories).group_by(Category.name).all()

            stats['categories'] = {name: count for name, count in category_counts}

            # Extension breakdown
            extension_counts = session.query(
                File.file_extension,
                func.count(File.id)
            ).group_by(File.file_extension).order_by(func.count(File.id).desc()).limit(TOP_EXTENSIONS_LIMIT).all()

            stats['extensions'] = {ext or 'none': count for ext, count in extension_counts}

            return stats

        finally:
            if close_session:
                session.close()

    def get_cost_statistics(
        self,
        session_id: str = None,
        feature_name: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
        session: Session = None
    ) -> Dict[str, Any]:
        """
        Get cost statistics with optional filters.

        Args:
            session_id: Filter by session
            feature_name: Filter by feature
            start_date: Start of date range
            end_date: End of date range
            session: Optional existing session

        Returns:
            Cost statistics dictionary
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            query = session.query(CostRecord)

            if session_id:
                query = query.filter(CostRecord.session_id == session_id)
            if feature_name:
                query = query.filter(CostRecord.feature_name == feature_name)
            if start_date:
                query = query.filter(CostRecord.created_at >= start_date)
            if end_date:
                query = query.filter(CostRecord.created_at <= end_date)

            records = query.all()

            # Aggregate by feature
            feature_stats = defaultdict(lambda: {
                'invocations': 0,
                'total_cost': 0.0,
                'total_time': 0.0,
                'success_count': 0,
                'error_count': 0
            })

            for record in records:
                stats = feature_stats[record.feature_name]
                stats['invocations'] += 1
                stats['total_cost'] += record.cost
                stats['total_time'] += record.processing_time_sec
                if record.success:
                    stats['success_count'] += 1
                else:
                    stats['error_count'] += 1

            return {
                'total_records': len(records),
                'total_cost': sum(r.cost for r in records),
                'total_time': sum(r.processing_time_sec for r in records),
                'by_feature': dict(feature_stats)
            }

        finally:
            if close_session:
                session.close()

    # =========================================================================
    # Search Operations
    # =========================================================================

    def search_files(
        self,
        query: str,
        search_content: bool = True,
        search_filename: bool = True,
        limit: int = DEFAULT_SEARCH_LIMIT,
        session: Session = None
    ) -> List[File]:
        """
        Search files by text content or filename.

        Args:
            query: Search query
            search_content: Search in extracted text
            search_filename: Search in filename
            limit: Maximum results
            session: Optional existing session

        Returns:
            List of matching files
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            filters = []

            if search_filename:
                filters.append(File.filename.ilike(f'%{query}%'))
            if search_content:
                filters.append(File.extracted_text.ilike(f'%{query}%'))

            if not filters:
                return []

            return session.query(File)\
                .filter(or_(*filters))\
                .limit(limit)\
                .all()

        finally:
            if close_session:
                session.close()

    def search_by_location(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 10,
        limit: int = DEFAULT_SEARCH_LIMIT,
        session: Session = None
    ) -> List[File]:
        """
        Find files near a geographic location.

        Uses a simple bounding box approximation for SQLite compatibility.

        Args:
            latitude: Center latitude
            longitude: Center longitude
            radius_km: Search radius in kilometers
            limit: Maximum results
            session: Optional existing session

        Returns:
            List of files with GPS data near the location
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            # Approximate degrees per km (varies by latitude)
            lat_delta = radius_km / KM_PER_DEGREE_LATITUDE
            lon_delta = radius_km / (KM_PER_DEGREE_LATITUDE * abs(latitude) if latitude else KM_PER_DEGREE_LATITUDE)

            return session.query(File)\
                .filter(
                    and_(
                        File.gps_latitude.isnot(None),
                        File.gps_latitude.between(latitude - lat_delta, latitude + lat_delta),
                        File.gps_longitude.between(longitude - lon_delta, longitude + lon_delta)
                    )
                )\
                .limit(limit)\
                .all()

        finally:
            if close_session:
                session.close()
