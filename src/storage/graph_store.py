#!/usr/bin/env python3
"""
Graph-based storage operations for file organization data.

Provides high-level operations for managing files, categories, and their
relationships using a graph-like structure built on SQLAlchemy.
"""

import math
import uuid
from datetime import datetime
from ._time import utcnow
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    TYPE_CHECKING,
    Tuple,
    TypedDict,
    Union,
    cast,
)

if TYPE_CHECKING:
    from sqlalchemy.engine.interfaces import DBAPIConnection
    from sqlalchemy.pool import ConnectionPoolEntry
from collections import defaultdict
from contextlib import contextmanager

from sqlalchemy import create_engine, event, func, and_, or_, inspect as sqla_inspect
from sqlalchemy.orm import Session, sessionmaker, joinedload, selectinload
from sqlalchemy.exc import IntegrityError

from .models import (
    Base,
    File,
    Category,
    Company,
    Person,
    Location,
    OrganizationSession,
    FileRelationship,
    CostRecord,
    FileStatus,
    KeyValueStore,
    RelationshipType,
    file_categories,
)

try:
    from ..constants import (
        COORDINATE_TOLERANCE_DEG,
        DEFAULT_DB_PATH,
        DEFAULT_SEARCH_LIMIT,
        KM_PER_DEGREE_LATITUDE,
        TOP_EXTENSIONS_LIMIT,
    )
except ImportError:
    from constants import (  # type: ignore[no-redef]
        COORDINATE_TOLERANCE_DEG,
        DEFAULT_DB_PATH,
        DEFAULT_SEARCH_LIMIT,
        KM_PER_DEGREE_LATITUDE,
        TOP_EXTENSIONS_LIMIT,
    )


# Valid values for `Person.review_status` — single source of truth lives on the
# model (docs/plans/PERSON_NAME_VALIDATION_PLAN.md); re-exported here for the
# review-queue validation call sites below.
PERSON_REVIEW_STATUSES = Person.REVIEW_STATUSES

# Validator RouteDecision → persisted review_status.
_DECISION_TO_STATUS = {
    "auto_accept": "auto_accepted",
    "review": "pending_review",
    "reject": "rejected",
}

# Subcategory used when an entity-named folder resolves to a parent that the
# taxonomy declares without one (``Events`` → ``("events", None)``).
_ENTITY_FALLBACK_SUBCATEGORY = "other"


def resolve_taxonomy_folder(
    reverse: Mapping[str, tuple], folder: str
) -> Optional[Tuple[str, Optional[str]]]:
    """Map an on-disk folder to a ``(category, subcategory)`` taxonomy pair.

    Exact match wins. Failing that, trailing path segments are stripped one at a
    time: an entity-named folder has no taxonomy entry of its own, so
    ``Events/Burning Flipside`` resolves via ``Events`` and
    ``Media/Interiors/{Property}/{Room}`` via ``Media/Interiors``. The strip
    loops rather than trying a single parent, so arbitrarily deep entity nesting
    still lands.

    A parent reached *by stripping* is standing in for a child the taxonomy does
    not name, so a pair carrying no subcategory is filed under the generic
    ``other`` bucket — ``Events/*`` → ``events/other``, not a bare ``events``.
    The bare category stays reserved for files sitting directly in that folder,
    which an exact match still returns unchanged.

    Args:
        reverse: Destination-path → ``(category, subcategory)`` map from
            ``build_path_to_category_map``
        folder: Folder path relative to the organized root, POSIX-separated

    Returns:
        The resolved pair, or ``None`` when no ancestor is in the taxonomy.
    """
    exact = reverse.get(folder)
    if exact is not None:
        return cast(Tuple[str, Optional[str]], exact)
    while "/" in folder:
        folder = folder.rsplit("/", 1)[0]
        pair = reverse.get(folder)
        if pair is not None:
            category, subcategory = pair
            return (category, subcategory or _ENTITY_FALLBACK_SUBCATEGORY)
    return None


class PersonSummary(TypedDict):
    """``_person_summary()`` row for the review-queue CLI."""

    person_id: int
    name: str
    review_status: Optional[str]
    detection_confidence: Optional[float]
    validation_scores: Dict[str, Optional[float]]
    file_count: int
    paths: List[str]


class ReviewStatusChange(TypedDict):
    """``set_person_review_status()`` result."""

    person_id: int
    name: str
    old_status: Optional[str]
    new_status: str


class RevalidationResult(TypedDict):
    """One ``revalidate_people()`` candidate row."""

    person_id: int
    name: str
    old_status: Optional[str]
    new_status: str
    score: float
    layer_scores: Dict[str, Optional[float]]
    changed: bool


class PrunePersonSummary(TypedDict):
    """``prune_person()`` result."""

    name: str
    person_id: int
    edges_removed: int
    paths: List[str]


class PersonEdgeEntry(TypedDict):
    """One stale file->person edge."""

    person: str
    file_id: str
    path: str


class PruneEdgesResult(TypedDict):
    """``prune_missing_person_edges()`` result."""

    edges_removed: int
    edges: List[PersonEdgeEntry]


class CategoryChange(TypedDict):
    """``set_file_category()`` result."""

    file_id: str
    path: str
    old_categories: List[str]
    new_category: str


class BackfillFileEntry(TypedDict):
    """One orphaned file row from ``backfill_missing_categories()``."""

    file_id: str
    filename: str
    category: Optional[str]


class BackfillResult(TypedDict):
    """``backfill_missing_categories()`` result."""

    orphaned: int
    attached: int
    unresolved: int
    files: List[BackfillFileEntry]


class PrunedFileEntry(TypedDict):
    """One deleted File row from ``prune_missing_files()``."""

    file_id: str
    path: str


class PruneFilesResult(TypedDict):
    """``prune_missing_files()`` result."""

    removed: int
    files: List[PrunedFileEntry]


class SignalEvidenceEntry(TypedDict):
    """One ``file_categories`` row carrying persisted scoring evidence.

    The read side of ``add_file_to_category(signal_evidence=...)``. Until this
    existed the column was write-only: nothing in the codebase read back what
    every content run had been recording since UNIFIED_SCORING_PLAN §5.4.
    """

    file_id: str
    filename: str
    current_path: Optional[str]
    category: Optional[str]
    confidence: Optional[float]
    evidence: Dict[str, Any]


class GraphStatistics(TypedDict):
    """``get_statistics()`` shape."""

    total_files: int
    organized_files: int
    total_categories: int
    total_companies: int
    total_locations: int
    total_relationships: int
    total_sessions: int
    categories: Dict[str, int]
    extensions: Dict[str, int]


class CostStatistics(TypedDict):
    """``get_cost_statistics()`` shape."""

    total_records: int
    total_cost: float
    total_time: float
    by_feature: Dict[str, Dict[str, float]]


class GraphStore:
    """
    High-level interface for graph-based file storage.

    Provides methods for:
    - File CRUD operations
    - Category management with hierarchy
    - Relationship traversal (graph queries)
    - Statistics and aggregations
    """

    def __init__(self, db_path: Union[str, Path] = DEFAULT_DB_PATH):
        """
        Initialize the graph store.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path
        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)

        # Enable SQLite optimizations
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(
            dbapi_connection: "DBAPIConnection",
            connection_record: "ConnectionPoolEntry",
        ) -> None:
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

        # Lazily-resolved support flag for file_categories.signal_evidence
        # (None until first checked; see _supports_signal_evidence).
        self._signal_evidence_supported: Optional[bool] = None

    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()

    @contextmanager
    def _session_scope(self, session: Optional[Session] = None):
        """Own a DB session, or borrow a caller-supplied one.

        Yields ``(session, owned)``. A session created here is rolled back on
        error and closed on exit; a caller-supplied session is left open (the
        caller owns its lifecycle). Commit stays in the method body, gated on
        ``owned`` — this collapses the repeated close_session/try/except/finally
        scaffolding without changing per-method commit semantics.
        """
        owned = session is None
        session = session or self.get_session()
        try:
            yield session, owned
        except Exception:
            session.rollback()
            raise
        finally:
            if owned:
                session.close()

    # =========================================================================
    # File Operations
    # =========================================================================

    def add_file(
        self, original_path: str, filename: str, session: Optional[Session] = None, **kwargs
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
        with self._session_scope(session) as (session, owned):
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
                **kwargs,
            )
            session.add(file)
            session.commit()
            return file

    def get_file(
        self,
        file_id: Optional[str] = None,
        path: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> Optional[File]:
        """
        Get a file by ID or path.

        Args:
            file_id: File ID (hash)
            path: Original file path
            session: Optional existing session

        Returns:
            File object or None
        """
        with self._session_scope(session) as (session, owned):
            if file_id:
                return session.query(File).filter(File.id == file_id).first()
            elif path:
                file_id = File.generate_id(path)
                return session.query(File).filter(File.id == file_id).first()
            return None

    def get_files(
        self,
        status: Optional[FileStatus] = None,
        category: Optional[str] = None,
        company: Optional[str] = None,
        extension: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        session: Optional[Session] = None,
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
        with self._session_scope(session) as (session, owned):
            query = session.query(File).options(
                joinedload(File.categories), joinedload(File.companies)
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

    def update_file_status(
        self,
        file_id: str,
        status: FileStatus,
        destination: Optional[str] = None,
        reason: Optional[str] = None,
        session: Optional[Session] = None,
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
        with self._session_scope(session) as (session, owned):
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

    # =========================================================================
    # Category Operations
    # =========================================================================

    def get_or_create_category(
        self, name: str, parent_name: Optional[str] = None, session: Optional[Session] = None
    ) -> Optional[Category]:
        """
        Get or create a category, keyed on ``full_path`` (the identity).

        Lookups — existing row, parent resolution, and post-``IntegrityError``
        recovery — all go through ``full_path``, never ``name``: leaf names
        repeat across parents, so a name query can return a *different*
        category (``legal/other`` when asked for ``media/other``).

        Args:
            name: Category leaf name
            parent_name: Parent category full path (for hierarchy)
            session: Optional existing session

        Returns:
            Category object, or None only when the row genuinely cannot be
            resolved after a concurrent-insert rollback.

        Raises:
            IntegrityError: when insertion fails for a reason other than the
                row already existing — previously swallowed, which silently
                dropped the caller's category edge.
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            # Build full path
            if parent_name:
                full_path = f"{parent_name}/{name}"
            else:
                full_path = name

            # Check if exists (identity = full_path)
            category = session.query(Category).filter(Category.full_path == full_path).first()
            if category:
                return category

            # Get parent if specified (by full_path: a root parent's path is
            # its name, and a name query could match an unrelated leaf)
            parent = None
            level = 0
            if parent_name:
                parent = session.query(Category).filter(Category.full_path == parent_name).first()
                if parent:
                    level = (parent.level or 0) + 1

            # Create new category with canonical ID
            category = Category(
                name=name,
                canonical_id=Category.generate_canonical_id(full_path),
                parent_id=parent.id if parent else None,
                level=level,
                full_path=full_path,
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
            # Concurrent insert of the same full_path: adopt the winner. Any
            # other integrity failure is a real error and must not be
            # swallowed into a None that silently drops the category edge.
            existing = session.query(Category).filter(Category.full_path == full_path).first()
            if existing is not None:
                return existing
            raise
        finally:
            if close_session:
                session.close()

    def _supports_signal_evidence(self) -> bool:
        """True when file_categories has the signal_evidence column (§5.4).

        Fresh databases get the column via ``Base.metadata.create_all``;
        databases created before it existed need ``organize-files
        migrate-scoring``. Checked once per store instance so unmigrated
        databases keep working (evidence is skipped with a one-time warning)
        instead of poisoning the write transaction.
        """
        if self._signal_evidence_supported is None:
            columns = sqla_inspect(self.engine).get_columns(file_categories.name)
            supported = any(
                column["name"] == file_categories.c.signal_evidence.name for column in columns
            )
            if not supported:
                print(
                    "  ⚠ file_categories.signal_evidence column missing — run "
                    "`organize-files migrate-scoring` to persist scoring evidence"
                )
            self._signal_evidence_supported = supported
        return self._signal_evidence_supported

    def get_signal_evidence(
        self,
        *,
        file_id: Optional[str] = None,
        category_full_path: Optional[str] = None,
        limit: Optional[int] = None,
        session: Optional[Session] = None,
    ) -> List[SignalEvidenceEntry]:
        """Read back persisted ``file_categories.signal_evidence`` rows.

        The counterpart to ``add_file_to_category(signal_evidence=...)``. Rows
        with a NULL column (legacy runs, or runs before the migration) are
        skipped, so an empty result means "nothing recorded", never "no files".

        Args:
            file_id: Restrict to one file's associations.
            category_full_path: Restrict to one category identity. Matches
                ``Category.full_path`` (the identity), not ``name`` — ``name``
                repeats across parents and would collapse unrelated buckets.
            limit: Cap the number of rows returned.
            session: Optional existing session.

        Returns:
            One entry per association row that carries evidence.
        """
        if not self._supports_signal_evidence():
            return []

        with self._session_scope(session) as (session, _owned):
            query = (
                session.query(
                    file_categories.c.file_id,
                    file_categories.c.confidence,
                    file_categories.c.signal_evidence,
                    File.filename,
                    File.current_path,
                    Category.full_path,
                )
                .join(File, File.id == file_categories.c.file_id)
                .join(Category, Category.id == file_categories.c.category_id)
                .filter(file_categories.c.signal_evidence.isnot(None))
            )
            if file_id is not None:
                query = query.filter(file_categories.c.file_id == file_id)
            if category_full_path is not None:
                query = query.filter(Category.full_path == category_full_path)
            if limit is not None:
                query = query.limit(limit)

            return [
                SignalEvidenceEntry(
                    file_id=row[0],
                    filename=row[3],
                    current_path=row[4],
                    category=row[5],
                    confidence=row[1],
                    evidence=row[2] or {},
                )
                for row in query.all()
            ]

    def add_file_to_category(
        self,
        file_id: str,
        category_name: str,
        subcategory_name: Optional[str] = None,
        confidence: float = 1.0,
        session: Optional[Session] = None,
        signal_evidence: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Associate a file with a category.

        Args:
            file_id: File ID
            category_name: Main category
            subcategory_name: Optional subcategory
            confidence: Classification confidence
            session: Optional existing session
            signal_evidence: Optional JSON-serializable scoring evidence
                (UNIFIED_SCORING_PLAN §5.4) stored verbatim on the
                association row; None (legacy runs) leaves the column NULL

        Returns:
            True if successful
        """
        with self._session_scope(session) as (session, owned):
            file = session.query(File).filter(File.id == file_id).first()
            if not file:
                return False

            # Get or create category
            if subcategory_name:
                # Create parent first (ensures the parent category exists before the subcategory)
                self.get_or_create_category(category_name, session=session)
                category = self.get_or_create_category(
                    subcategory_name, category_name, session=session
                )
            else:
                category = self.get_or_create_category(category_name, session=session)

            # Defensive: get_or_create_category now raises rather than
            # returning None for a genuine failure, so this only trips on a
            # lost concurrent-insert race.
            if category is None:
                return False

            # Add relationship if not exists (ORM append event maintains file_count).
            changed = False
            if category not in file.categories:
                file.categories.append(category)
                changed = True

            # Persist scoring evidence on the association row (nullable,
            # additive: absent evidence means a legacy run -> NULL).
            if signal_evidence is not None and self._supports_signal_evidence():
                # Flush so a newly-appended association row exists to update.
                session.flush()
                session.execute(
                    file_categories.update()
                    .where(file_categories.c.file_id == file_id)
                    .where(file_categories.c.category_id == category.id)
                    .values(signal_evidence=signal_evidence)
                )
                changed = True

            # Only commit if we own the session
            if changed and owned:
                session.commit()

            return True

    def get_category_tree(self, session: Optional[Session] = None) -> List[Dict[str, Any]]:
        """
        Get the full category hierarchy as a tree.

        Returns:
            List of root categories with nested subcategories
        """
        with self._session_scope(session) as (session, owned):
            categories = (
                session.query(Category)
                .options(selectinload(Category.subcategories).selectinload(Category.subcategories))
                .order_by(Category.level, Category.name)
                .all()
            )

            # Build tree structure
            tree = []
            for category in categories:
                if category.parent_id is None:
                    tree.append(self._build_category_node(category))

            return tree

    def _build_category_node(self, category: Category) -> Dict[str, Any]:
        """Build a category tree node recursively."""
        node = category.to_dict()
        node["subcategories"] = [self._build_category_node(sub) for sub in category.subcategories]
        return node

    # =========================================================================
    # Company Operations
    # =========================================================================

    def get_or_create_company(
        self, name: str, session: Optional[Session] = None
    ) -> Optional[Company]:
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
                    canonical_id=Company.generate_canonical_id(name),
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
        context: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> bool:
        """Associate a file with a company."""
        with self._session_scope(session) as (session, owned):
            file = session.query(File).filter(File.id == file_id).first()
            if not file:
                return False

            company = self.get_or_create_company(company_name, session=session)

            # Guard against None company
            if company is None:
                return False

            if company not in file.companies:
                file.companies.append(company)
                # ORM append event maintains company.file_count.
                company.last_seen = utcnow()
                # Only commit if we own the session
                if owned:
                    session.commit()

            return True

    # =========================================================================
    # Person Operations
    # =========================================================================

    def get_or_create_person(
        self,
        name: str,
        email: Optional[str] = None,
        role: Optional[str] = None,
        session: Optional[Session] = None,
        *,
        validate: bool = True,
    ) -> Optional[Person]:
        """Get or create a person by name, applying the validation gate.

        The layered person-name gate (PERSON_NAME_VALIDATION_PLAN) runs only
        when creating a NEW row and ``validate=True``:

        - ``reject`` → returns ``None`` and creates no row (deterministic
          re-rejection on re-detection). Callers such as ``add_file_to_person``
          treat ``None`` as "drop the edge".
        - ``review`` → row created with ``review_status='pending_review'``
          (hidden from the person-view read filter until confirmed).
        - ``auto_accept`` → ``review_status='auto_accepted'``.

        ``validate=False`` marks the row ``confirmed`` (trusted source, e.g.
        directory-name migration). An existing ``rejected`` row is a tombstone:
        it returns ``None`` rather than resurrecting the name.
        """
        close_session = session is None
        session = session or self.get_session()

        try:
            normalized = Person.normalize_name(name)
            person = session.query(Person).filter(Person.normalized_name == normalized).first()

            if person:
                if getattr(person, "review_status", None) == "rejected":
                    return None
                return person

            # validate=False marks a trusted source (e.g. curated directory
            # names) as 'confirmed'. When validate=True we must NOT auto-trust:
            # a working validator routes per its decision, and an *unavailable*
            # validator routes to 'pending_review' (never 'confirmed' on
            # nothing — PERSON_NAME_VALIDATION_PLAN).
            review_status = "confirmed"
            detection_confidence = None
            validation_scores: Dict[str, Optional[float]] = {}
            if validate:
                result = self._validate_person_name(name)
                if result is None:
                    review_status = "pending_review"  # validator unavailable
                elif result.decision == "reject":
                    return None
                else:
                    # Single decision→status table (shared with revalidate_people);
                    # 'reject' is handled above (no row), so only 'review'/
                    # 'auto_accept' reach here — both are keys in the map.
                    review_status = _DECISION_TO_STATUS[result.decision]
                    detection_confidence = result.score
                    validation_scores = dict(result.layer_scores)

            person = Person(
                name=name,
                normalized_name=normalized,
                canonical_id=Person.generate_canonical_id(name),
                email=email,
                role=role,
                review_status=review_status,
                detection_confidence=detection_confidence,
                validation_scores=validation_scores,
                validated_at=utcnow(),
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

    @staticmethod
    def _validate_person_name(name: str):
        """Run the person-name validation gate, or None if it's unavailable.

        Imported lazily and guarded so ``src.storage`` works without the
        ``names`` extra (or the classifiers package) installed.
        """
        try:
            from ..classifiers.person_name_validator import validate_person_name
        except ImportError:
            try:
                from classifiers.person_name_validator import (  # type: ignore[no-redef]
                    validate_person_name,
                )
            except ImportError:
                return None
        try:
            return validate_person_name(name)
        except Exception:
            return None

    def add_file_to_person(
        self,
        file_id: str,
        person_name: str,
        role: Optional[str] = None,
        confidence: float = 1.0,
        session: Optional[Session] = None,
        *,
        validate: bool = True,
    ) -> bool:
        """Associate a file with a person.

        Passes ``validate`` through to :meth:`get_or_create_person`; when the
        gate rejects the name, that returns ``None`` and this drops the edge
        (returns ``False``) without creating a Person row.
        """
        with self._session_scope(session) as (session, owned):
            file = session.query(File).filter(File.id == file_id).first()
            if not file:
                return False

            person = self.get_or_create_person(
                person_name, role=role, session=session, validate=validate
            )

            if person is None:
                return False

            if person not in file.people:
                file.people.append(person)
                # ORM append event maintains person.file_count.
                person.last_seen = utcnow()
                if owned:
                    session.commit()

            return True

    def get_all_people_with_files(
        self, session: Optional[Session] = None, min_files: int = 1
    ) -> List[Tuple[str, List[str]]]:
        """
        Get all people who have at least `min_files` organized files.

        Filters out rejected and pending-review persons via the review_status
        gate (false positives are caught at write time by the person_name_validator
        and tombstoned via review_status). Excludes files that haven't been
        organized yet (current_path is None).

        Args:
            session: Optional existing session
            min_files: Minimum number of valid (organized) files a person
                must have to be included in the results

        Returns:
            List of (display_name, [file.current_path, ...]) tuples
        """
        with self._session_scope(session) as (session, owned):
            results = []
            people = session.query(Person).options(selectinload(Person.files)).all()

            for person in people:
                # Validation-gate status filter: hide rejected tombstones and
                # names awaiting human review from the person-view. Legacy rows
                # (NULL/'' status) are treated as visible. False positives are
                # caught at write time by the person_name_validator (L0 denylist
                # + composite score) and tombstoned here via review_status.
                if getattr(person, "review_status", None) in ("rejected", "pending_review"):
                    continue

                paths = [f.current_path for f in person.files if f.current_path]

                if len(paths) >= min_files:
                    results.append((person.name, paths))

            return results

    def get_files_by_person(
        self, person_id_or_name, session: Optional[Session] = None
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
        with self._session_scope(session) as (session, owned):
            if isinstance(person_id_or_name, int):
                person = session.query(Person).filter(Person.id == person_id_or_name).first()
            else:
                normalized = Person.normalize_name(person_id_or_name)
                person = session.query(Person).filter(Person.normalized_name == normalized).first()

            if not person:
                return []

            return [f.current_path for f in person.files if f.current_path]

    def _find_person(self, person_id_or_name, session: Session) -> Optional[Person]:
        """Look up a person by primary key (int) or name (str, normalized)."""
        if isinstance(person_id_or_name, int):
            return session.query(Person).filter(Person.id == person_id_or_name).first()
        normalized = Person.normalize_name(person_id_or_name)
        return session.query(Person).filter(Person.normalized_name == normalized).first()

    @staticmethod
    def _person_summary(person: Person) -> PersonSummary:
        """Compact person record for the review-queue CLI (no lazy loads beyond files)."""
        return {
            "person_id": person.id,
            "name": person.name,
            "review_status": person.review_status,
            "detection_confidence": person.detection_confidence,
            "validation_scores": person.validation_scores or {},
            "file_count": person.file_count,
            "paths": [f.current_path for f in person.files if f.current_path],
        }

    def list_people_by_status(
        self, status: Optional[str] = None, session: Optional[Session] = None
    ) -> List[PersonSummary]:
        """List people filtered by ``review_status`` (the review-queue read side).

        Args:
            status: One of :data:`PERSON_REVIEW_STATUSES`. ``None`` returns all
                people regardless of status. Filtering is an exact column match,
                so legacy rows with a NULL/empty status only appear under
                ``status=None`` (use :meth:`revalidate_people` to re-score them).
            session: Optional existing session.

        Returns:
            List of per-person summary dicts (see :meth:`_person_summary`),
            ordered by name.

        Raises:
            ValueError: if ``status`` is not a recognized review status.
        """
        if status is not None and status not in PERSON_REVIEW_STATUSES:
            raise ValueError(
                f"unknown review_status {status!r}; expected one of {PERSON_REVIEW_STATUSES}"
            )

        with self._session_scope(session) as (session, owned):
            query = session.query(Person).options(selectinload(Person.files))
            if status is not None:
                query = query.filter(Person.review_status == status)
            people = query.order_by(Person.name).all()
            return [self._person_summary(p) for p in people]

    def set_person_review_status(
        self, person_id_or_name, status: str, session: Optional[Session] = None
    ) -> Optional[ReviewStatusChange]:
        """Set a human review decision on a person (accept / reject / requeue).

        This is the write side of the review queue: ``--accept`` sets
        ``confirmed``, ``--reject`` sets ``rejected`` (a tombstone that
        :meth:`get_or_create_person` refuses to resurrect; ``prune_person``
        remains the hard-delete tool). File edges are left intact — the status
        filter in :meth:`get_all_people_with_files` hides them.

        Args:
            person_id_or_name: Person primary key (int), or name (str,
                normalized like :meth:`get_or_create_person`).
            status: One of :data:`PERSON_REVIEW_STATUSES`.
            session: Optional existing session.

        Returns:
            ``{"person_id", "name", "old_status", "new_status"}`` on success, or
            ``None`` if the person isn't found.

        Raises:
            ValueError: if ``status`` is not a recognized review status.
        """
        if status not in PERSON_REVIEW_STATUSES:
            raise ValueError(
                f"unknown review_status {status!r}; expected one of {PERSON_REVIEW_STATUSES}"
            )

        with self._session_scope(session) as (session, owned):
            person = self._find_person(person_id_or_name, session)
            if not person:
                return None

            old_status = person.review_status
            person.review_status = status
            if owned:
                session.commit()

            return {
                "person_id": person.id,
                "name": person.name,
                "old_status": old_status,
                "new_status": status,
            }

    def revalidate_people(
        self, apply: bool = False, session: Optional[Session] = None
    ) -> List[RevalidationResult]:
        """Re-run the person-name gate over legacy and pending rows.

        Targets rows the validator has never scored well:

        - ``pending_review`` (re-score, e.g. after installing the ``names``
          extra a name may now clear the auto-accept bar or fail outright), and
        - ``auto_accepted`` legacy rows whose ``validation_scores`` is empty
          (backfilled by the Phase-2 migration, never actually validated).

        Human decisions (``confirmed`` / ``rejected``) are never touched. Rows
        are skipped when the validator is unavailable (nothing to re-score by).

        Args:
            apply: When ``False`` (default), report the proposed transitions
                without writing. When ``True``, persist the new status plus the
                fresh ``detection_confidence`` / ``validation_scores`` /
                ``validated_at``.
            session: Optional existing session.

        Returns:
            One dict per candidate: ``{person_id, name, old_status, new_status,
            score, layer_scores, changed}`` — the explainability payoff of
            storing per-layer scores.
        """
        with self._session_scope(session) as (session, owned):
            candidates = (
                session.query(Person)
                .filter(Person.review_status.in_(("auto_accepted", "pending_review")))
                .order_by(Person.name)
                .all()
            )

            results: List[RevalidationResult] = []
            for person in candidates:
                # Skip already-validated auto_accepted rows; only legacy ones
                # (empty validation_scores) are re-scored alongside every pending.
                if person.review_status == "auto_accepted" and person.validation_scores:
                    continue

                validation = self._validate_person_name(person.name)
                if validation is None:
                    continue  # validator unavailable — can't re-score

                new_status = _DECISION_TO_STATUS[validation.decision]
                old_status = person.review_status
                layer_scores = dict(validation.layer_scores)

                results.append(
                    {
                        "person_id": person.id,
                        "name": person.name,
                        "old_status": old_status,
                        "new_status": new_status,
                        "score": validation.score,
                        "layer_scores": layer_scores,
                        "changed": old_status != new_status,
                    }
                )

                if apply:
                    person.review_status = new_status
                    person.detection_confidence = validation.score
                    person.validation_scores = layer_scores
                    person.validated_at = utcnow()

            if apply and owned:
                session.commit()

            return results

    def remove_person_edge(
        self, file_id: str, person_id_or_name, session: Optional[Session] = None
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
        with self._session_scope(session) as (session, owned):
            file = session.query(File).filter(File.id == file_id).first()
            person = self._find_person(person_id_or_name, session)
            if not file or not person or person not in file.people:
                return False

            file.people.remove(person)
            # ORM remove event maintains person.file_count.
            if owned:
                session.commit()
            return True

    def prune_person(
        self, person_id_or_name, dry_run: bool = False, session: Optional[Session] = None
    ) -> Optional[PrunePersonSummary]:
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
        with self._session_scope(session) as (session, owned):
            person = self._find_person(person_id_or_name, session)
            if not person:
                return None

            summary: PrunePersonSummary = {
                "name": person.name,
                "person_id": person.id,
                "edges_removed": len(person.files),
                "paths": [f.current_path or f.original_path for f in person.files],
            }
            if dry_run:
                return summary

            person.files.clear()
            session.query(Person).filter(Person.merged_into_id == person.id).update(
                {Person.merged_into_id: None}
            )
            session.delete(person)
            if owned:
                session.commit()
            return summary

    def prune_missing_person_edges(
        self, dry_run: bool = False, session: Optional[Session] = None
    ) -> PruneEdgesResult:
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
        with self._session_scope(session) as (session, owned):
            removed: List[PersonEdgeEntry] = []
            people = session.query(Person).options(selectinload(Person.files)).all()

            for person in people:
                for file in list(person.files):
                    path = file.current_path or file.original_path
                    if not path or Path(path).exists():
                        continue
                    removed.append(
                        {
                            "person": person.name,
                            "file_id": file.id,
                            "path": path,
                        }
                    )
                    if not dry_run:
                        person.files.remove(file)
                        # ORM remove event maintains person.file_count.

            if not dry_run and owned:
                session.commit()
            return {"edges_removed": len(removed), "edges": removed}

    def _find_file(self, file_id_or_path: str, session: Session) -> Optional[File]:
        """Resolve a File by primary-key id, then by current/original path.

        Path lookup matches the stored column value directly (not a
        hash-of-path), so a file that was moved after organization still
        resolves by its new ``current_path``.
        """
        file = session.query(File).filter(File.id == file_id_or_path).first()
        if file:
            return file
        return (
            session.query(File)
            .filter(
                or_(
                    File.current_path == file_id_or_path,
                    File.original_path == file_id_or_path,
                )
            )
            .first()
        )

    def set_file_category(
        self,
        file_id_or_path: str,
        category_name: str,
        subcategory_name: Optional[str] = None,
        dry_run: bool = False,
        session: Optional[Session] = None,
    ) -> Optional[CategoryChange]:
        """
        Replace a file's category edge(s) with a single category/subcategory.

        Resolves the file by primary-key id or by current_path/original_path.
        All existing file->category edges are dropped (decrementing each
        category's file_count) and one new edge is attached. Files on disk are
        never touched. Use when a file was moved to a folder that no longer
        matches its recorded category edge.

        Args:
            file_id_or_path: File primary key (SHA-256 hex) or a path stored
                in current_path/original_path
            category_name: New top-level category (matched/created lowercase)
            subcategory_name: Optional subcategory under category_name
            dry_run: When True, report the change without applying it
            session: Optional existing session

        Returns:
            Summary dict with file_id/path/old_categories/new_category, or
            None if the file isn't found
        """
        with self._session_scope(session) as (session, owned):
            file = self._find_file(file_id_or_path, session)
            if not file:
                return None

            new_path = f"{category_name}/{subcategory_name}" if subcategory_name else category_name
            summary: CategoryChange = {
                "file_id": file.id,
                "path": file.current_path or file.original_path,
                "old_categories": [c.full_path for c in file.categories],
                "new_category": new_path,
            }
            if dry_run:
                return summary

            for category in list(file.categories):
                file.categories.remove(category)
                # ORM remove event maintains category.file_count.

            self.add_file_to_category(file.id, category_name, subcategory_name, session=session)

            if owned:
                session.commit()
            return summary

    def backfill_missing_categories(
        self,
        base_path: Path,
        dry_run: bool = False,
        session: Optional[Session] = None,
    ) -> BackfillResult:
        """Attach a category edge to File rows that have none.

        Repairs edges dropped by the pre-2026-07-26 ``categories.name`` UNIQUE
        bug (see ``category_migration``). The category is *derived*, not
        re-classified: the file's on-disk folder relative to ``base_path`` is
        looked up in the reversed taxonomy (``build_path_to_category_map``), so
        the graph is made to agree with where the file actually sits. Re-running
        ``organize-files content`` cannot do this — a correctly-placed file
        short-circuits at ``already_organized`` before persistence.

        Folder lookup is ``resolve_taxonomy_folder``: exact match first, then
        trailing segments stripped one at a time until an ancestor is in the
        taxonomy.  That resolves entity-named subfolders such as
        ``Events/{EventName}`` (→ ``events/other``),
        ``Media/Interiors/{Property}`` (→ ``media/interiors_other``) and
        ``Organization/Clients/{ClientName}`` (→ ``organization/clients``), at
        any nesting depth.  A parent reached by stripping that declares no
        subcategory is filed under ``other`` rather than the bare category.
        Folders with no taxonomy ancestor at all are reported unresolved and
        left untouched rather than guessed.

        **Duplicate documents split across categories — by design.** Because the
        pair follows the folder and nothing else, two copies of one document
        living in two trees get two different, individually-correct edges::

            Documents/Events/Burning Flipside/PlacementMap.pdf   -> events/other
            Documents/Personal/Events/PlacementMap_300dpi.png    -> personal/events

        A category query therefore returns a subset of the logical document
        family.  That is a filing outcome, not drift, and it must not be
        "repaired" here by inferring which copy is canonical: this method's
        contract is that the graph agrees with the filesystem.  Merge the two by
        moving the file and re-running, or leave them split.  The same reasoning
        makes ``Organization/{Name}`` resolve to ``organization/vendors`` — the
        taxonomy declares that folder the vendor/partner root.

        Args:
            base_path: Organized-files root (e.g. ``~/Documents``)
            dry_run: When True, report what would be attached without writing
            session: Optional existing session

        Returns:
            ``{'orphaned': N, 'attached': N, 'unresolved': N, 'files': [...]}``
            where each file entry carries ``file_id``, ``filename`` and the
            resolved ``category`` (``None`` when unresolved).
        """
        try:
            from ..organizers.category_config import build_path_to_category_map
        except ImportError:  # flat-module import path (scripts/ on sys.path)
            from organizers.category_config import (  # type: ignore[no-redef]
                build_path_to_category_map,
            )

        reverse = build_path_to_category_map()
        entries: List[BackfillFileEntry] = []
        attached = unresolved = 0

        with self._session_scope(session) as (session, owned):
            orphans = (
                session.query(File)
                .filter(~File.categories.any())
                .filter(File.current_path.isnot(None))
                .all()
            )
            for file in orphans:
                if not file.current_path:  # narrows Optional[str] for the type checker
                    continue
                current = Path(file.current_path)
                pair = None
                try:
                    folder = current.parent.relative_to(base_path).as_posix()
                    pair = resolve_taxonomy_folder(reverse, folder)
                except ValueError:
                    pair = None  # outside base_path
                entry: BackfillFileEntry = {
                    "file_id": file.id,
                    "filename": file.filename,
                    "category": None,
                }
                if pair is None:
                    unresolved += 1
                    entries.append(entry)
                    continue
                category_name, subcategory_name = pair
                entry["category"] = (
                    f"{category_name}/{subcategory_name}" if subcategory_name else category_name
                )
                if not dry_run:
                    self.add_file_to_category(
                        file_id=file.id,
                        category_name=category_name,
                        subcategory_name=subcategory_name,
                        session=session,
                    )
                attached += 1
                entries.append(entry)

            if owned and not dry_run:
                session.commit()

        return {
            "orphaned": len(entries),
            "attached": attached,
            "unresolved": unresolved,
            "files": entries,
        }

    def prune_missing_files(
        self,
        dry_run: bool = False,
        session: Optional[Session] = None,
    ) -> PruneFilesResult:
        """
        Delete File rows whose current_path and original_path are both gone.

        A row is stale when neither path exists on disk. Removing it drops the
        file's category/person edges (decrementing the respective file_counts),
        clears company/location edges, and deletes the file's cost_records,
        schema_metadata, and any FileRelationship rows referencing it — all
        required because SQLite foreign-key enforcement is enabled. Files
        present on disk are never affected.

        Args:
            dry_run: When True, report what would be removed without changes
            session: Optional existing session

        Returns:
            {'removed': N, 'files': [{'file_id': id, 'path': path}, ...]}
        """
        with self._session_scope(session) as (session, owned):
            removed: List[PrunedFileEntry] = []
            for file in session.query(File).all():
                current, original = file.current_path, file.original_path
                on_disk = (current and Path(current).exists()) or (
                    original and Path(original).exists()
                )
                if on_disk:
                    continue

                removed.append({"file_id": file.id, "path": current or original})
                if dry_run:
                    continue

                for category in list(file.categories):
                    file.categories.remove(category)
                    # ORM remove event maintains category.file_count.
                for person in list(file.people):
                    file.people.remove(person)
                    # ORM remove event maintains person.file_count.
                file.companies.clear()
                file.locations.clear()

                for child in file.cost_records or []:
                    session.delete(child)
                if file.schema_metadata is not None:
                    session.delete(file.schema_metadata)
                session.query(FileRelationship).filter(
                    or_(
                        FileRelationship.source_file_id == file.id,
                        FileRelationship.target_file_id == file.id,
                    )
                ).delete(synchronize_session=False)
                session.query(KeyValueStore).filter(KeyValueStore.file_id == file.id).delete(
                    synchronize_session=False
                )

                session.delete(file)

            if not dry_run and owned:
                session.commit()
            return {"removed": len(removed), "files": removed}

    # =========================================================================
    # Location Operations
    # =========================================================================

    def get_or_create_location(
        self,
        name: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        country: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> Optional[Location]:
        """Get or create a location."""
        close_session = session is None
        session = session or self.get_session()

        try:
            # Try to find by coordinates first
            if latitude and longitude:
                location = (
                    session.query(Location)
                    .filter(
                        and_(
                            func.abs(Location.latitude - latitude) < COORDINATE_TOLERANCE_DEG,
                            func.abs(Location.longitude - longitude) < COORDINATE_TOLERANCE_DEG,
                        )
                    )
                    .first()
                )
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
                country=country,
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
        location_type: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        country: Optional[str] = None,
        confidence: float = 1.0,
        session: Optional[Session] = None,
    ) -> bool:
        """Associate a file with a location."""
        with self._session_scope(session) as (session, owned):
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
                session=session,
            )

            if location is None:
                return False

            if location not in file.locations:
                file.locations.append(location)
                # ORM append event maintains location.file_count.
                if owned:
                    session.commit()

            return True

    # =========================================================================
    # Relationship Operations (Graph Edges)
    # =========================================================================

    def add_relationship(
        self,
        source_file_id: str,
        target_file_id: str,
        relationship_type: RelationshipType,
        confidence: float = 1.0,
        extra_data: Optional[Dict] = None,
        session: Optional[Session] = None,
    ) -> FileRelationship:
        """
        Add a relationship between two files.

        Args:
            source_file_id: Source file ID
            target_file_id: Target file ID
            relationship_type: Type of relationship
            confidence: Relationship confidence
            extra_data: Additional relationship-specific data (JSON). On an
                existing relationship, only overwritten when provided.

        Returns:
            Created relationship
        """
        with self._session_scope(session) as (session, owned):
            # Check if relationship already exists
            existing = (
                session.query(FileRelationship)
                .filter(
                    and_(
                        FileRelationship.source_file_id == source_file_id,
                        FileRelationship.target_file_id == target_file_id,
                        FileRelationship.relationship_type == relationship_type,
                    )
                )
                .first()
            )

            if existing:
                existing.confidence = confidence
                if extra_data is not None:
                    existing.extra_data = extra_data
                session.commit()
                return existing

            relationship = FileRelationship(
                source_file_id=source_file_id,
                target_file_id=target_file_id,
                relationship_type=relationship_type,
                confidence=confidence,
                extra_data=extra_data,
            )
            session.add(relationship)
            session.commit()
            return relationship

    def find_related_files(
        self,
        file_id: str,
        relationship_type: Optional[RelationshipType] = None,
        depth: int = 1,
        session: Optional[Session] = None,
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
        with self._session_scope(session) as (session, owned):
            results = []
            visited = {file_id}

            # BFS traversal
            current_level = [file_id]

            for _ in range(depth):
                next_level = []
                pending: list[tuple[str, RelationshipType, float]] = []

                for current_id in current_level:
                    # Get outgoing relationships
                    query = session.query(FileRelationship).filter(
                        FileRelationship.source_file_id == current_id
                    )
                    if relationship_type:
                        query = query.filter(
                            FileRelationship.relationship_type == relationship_type
                        )

                    for rel in query.all():
                        if rel.target_file_id not in visited:
                            visited.add(rel.target_file_id)
                            next_level.append(rel.target_file_id)
                            pending.append(
                                (rel.target_file_id, rel.relationship_type, rel.confidence or 0.0)
                            )

                    # Get incoming relationships
                    query = session.query(FileRelationship).filter(
                        FileRelationship.target_file_id == current_id
                    )
                    if relationship_type:
                        query = query.filter(
                            FileRelationship.relationship_type == relationship_type
                        )

                    for rel in query.all():
                        if rel.source_file_id not in visited:
                            visited.add(rel.source_file_id)
                            next_level.append(rel.source_file_id)
                            pending.append(
                                (rel.source_file_id, rel.relationship_type, rel.confidence or 0.0)
                            )

                if pending:
                    pending_ids = [fid for fid, _, _ in pending]
                    file_map = {
                        f.id: f for f in session.query(File).filter(File.id.in_(pending_ids)).all()
                    }
                    for fid, rel_type, confidence in pending:
                        file = file_map.get(fid)
                        if file:
                            results.append((file, rel_type, confidence))

                current_level = next_level

            return results

    def find_duplicates(
        self, content_hash: Optional[str] = None, session: Optional[Session] = None
    ) -> List[List[File]]:
        """
        Find groups of duplicate files by content hash.

        Args:
            content_hash: Specific hash to look for (or all if None)
            session: Optional existing session

        Returns:
            List of file groups (files with same content)
        """
        with self._session_scope(session) as (session, owned):
            if content_hash:
                files = session.query(File).filter(File.content_hash == content_hash).all()
                return [files] if len(files) > 1 else []

            # Find all hashes with more than one file
            duplicates = (
                session.query(File.content_hash, func.count(File.id).label("count"))
                .filter(File.content_hash.isnot(None))
                .group_by(File.content_hash)
                .having(func.count(File.id) > 1)
                .all()
            )

            duplicate_hashes = [h for h, _ in duplicates]
            all_files = session.query(File).filter(File.content_hash.in_(duplicate_hashes)).all()
            groups: defaultdict = defaultdict(list)
            for f in all_files:
                groups[f.content_hash].append(f)

            return list(groups.values())

    # =========================================================================
    # Session Operations
    # =========================================================================

    def create_session(
        self,
        source_directories: List[str],
        base_path: str,
        dry_run: bool = False,
        file_limit: Optional[int] = None,
        session: Optional[Session] = None,
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
        with self._session_scope(session) as (session, owned):
            org_session = OrganizationSession(
                id=str(uuid.uuid4()),
                source_directories=source_directories,
                base_path=base_path,
                dry_run=dry_run,
                file_limit=file_limit,
            )
            session.add(org_session)
            session.commit()
            # When we own the session, ``commit`` expires the instance and the
            # following ``close`` detaches it, so a caller reading ``.id`` (e.g.
            # the batch path) would hit "not bound to a Session". Refresh to load
            # the columns while still bound, then expunge so the values survive
            # detachment.
            if owned:
                session.refresh(org_session)
                session.expunge(org_session)
            return org_session

    def complete_session(
        self, session_id: str, stats: Mapping[str, float], db_session: Optional[Session] = None
    ) -> bool:
        """
        Mark a session as completed with statistics.

        Args:
            session_id: Session ID
            stats: Counts plus the float-valued ``total_cost`` and
                ``processing_time`` (the two Float columns below) — hence
                ``float`` values, which also accept the int counts. A
                ``Mapping`` so an all-int caller dict is still assignable.
            db_session: Optional existing session

        Returns:
            True if successful
        """
        close_session = db_session is None
        db_session = db_session or self.get_session()

        try:
            org_session = (
                db_session.query(OrganizationSession)
                .filter(OrganizationSession.id == session_id)
                .first()
            )

            if not org_session:
                return False

            org_session.completed_at = utcnow()
            # Coerce per column type: the four counts are Integer, the last two
            # are Float. `stats` is Mapping[str, float] so callers may pass
            # either for any key.
            org_session.total_files = int(stats.get("total_files", 0))
            org_session.organized_count = int(stats.get("organized", 0))
            org_session.skipped_count = int(stats.get("skipped", 0))
            org_session.error_count = int(stats.get("errors", 0))
            org_session.total_cost = float(stats.get("total_cost", 0.0))
            org_session.total_processing_time_sec = float(stats.get("processing_time", 0.0))

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

    def get_statistics(self, session: Optional[Session] = None) -> GraphStatistics:
        """
        Get overall statistics.

        Returns:
            Dictionary with counts and aggregations
        """
        with self._session_scope(session) as (session, owned):
            # Category breakdown
            category_counts = (
                session.query(Category.name, func.count(file_categories.c.file_id))
                .join(file_categories)
                .group_by(Category.name)
                .all()
            )

            # Extension breakdown
            extension_counts = (
                session.query(File.file_extension, func.count(File.id))
                .group_by(File.file_extension)
                .order_by(func.count(File.id).desc())
                .limit(TOP_EXTENSIONS_LIMIT)
                .all()
            )

            return {
                "total_files": session.query(func.count(File.id)).scalar(),
                "organized_files": session.query(func.count(File.id))
                .filter(File.status == FileStatus.ORGANIZED)
                .scalar(),
                "total_categories": session.query(func.count(Category.id)).scalar(),
                "total_companies": session.query(func.count(Company.id)).scalar(),
                "total_locations": session.query(func.count(Location.id)).scalar(),
                "total_relationships": session.query(func.count(FileRelationship.id)).scalar(),
                "total_sessions": session.query(func.count(OrganizationSession.id)).scalar(),
                "categories": {name: count for name, count in category_counts},
                "extensions": {ext or "none": count for ext, count in extension_counts},
            }

    def get_cost_statistics(
        self,
        session_id: Optional[str] = None,
        feature_name: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        session: Optional[Session] = None,
    ) -> CostStatistics:
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
        with self._session_scope(session) as (session, owned):
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
            feature_stats: defaultdict[str, dict[str, float]] = defaultdict(
                lambda: {
                    "invocations": 0,
                    "total_cost": 0.0,
                    "total_time": 0.0,
                    "success_count": 0,
                    "error_count": 0,
                }
            )

            for record in records:
                stats = feature_stats[cast(str, record.feature_name)]
                stats["invocations"] += 1
                stats["total_cost"] += record.cost or 0.0
                stats["total_time"] += record.processing_time_sec or 0.0
                if record.success:
                    stats["success_count"] += 1
                else:
                    stats["error_count"] += 1

            return {
                "total_records": len(records),
                "total_cost": sum(r.cost or 0.0 for r in records),
                "total_time": sum(r.processing_time_sec or 0.0 for r in records),
                "by_feature": dict(feature_stats),
            }

    # =========================================================================
    # Search Operations
    # =========================================================================

    def search_files(
        self,
        query: str,
        search_content: bool = True,
        search_filename: bool = True,
        limit: int = DEFAULT_SEARCH_LIMIT,
        session: Optional[Session] = None,
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
        with self._session_scope(session) as (session, owned):
            filters = []

            if search_filename:
                filters.append(File.filename.ilike(f"%{query}%"))
            if search_content:
                filters.append(File.extracted_text.ilike(f"%{query}%"))

            if not filters:
                return []

            return session.query(File).filter(or_(*filters)).limit(limit).all()

    def search_by_location(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 10,
        limit: int = DEFAULT_SEARCH_LIMIT,
        session: Optional[Session] = None,
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
        with self._session_scope(session) as (session, owned):
            # Approximate degrees per km. Longitude degrees shrink by
            # cos(latitude); clamp the scale near the poles where cos
            # approaches zero and the bounding box would blow up.
            lat_delta = radius_km / KM_PER_DEGREE_LATITUDE
            lon_scale = max(math.cos(math.radians(latitude)), 0.01)
            lon_delta = radius_km / (KM_PER_DEGREE_LATITUDE * lon_scale)

            return (
                session.query(File)
                .filter(
                    and_(
                        File.gps_latitude.isnot(None),
                        File.gps_latitude.between(latitude - lat_delta, latitude + lat_delta),
                        File.gps_longitude.between(longitude - lon_delta, longitude + lon_delta),
                    )
                )
                .limit(limit)
                .all()
            )
