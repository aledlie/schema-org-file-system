"""
Integration tests for GraphStore.

Tests database operations with real SQLite database.
"""

import pytest
from datetime import datetime
from pathlib import Path

from src.storage.graph_store import GraphStore
from src.storage.models import FileStatus, RelationshipType


class TestGraphStoreInit:
    """Test GraphStore initialization."""

    def test_initialization(self, graph_store):
        """Test GraphStore initializes correctly."""
        assert graph_store is not None
        assert graph_store.db_path is not None

    def test_creates_tables(self, graph_store):
        """Test that all tables are created."""
        from sqlalchemy import inspect
        inspector = inspect(graph_store.engine)
        tables = inspector.get_table_names()

        expected_tables = [
            'files', 'categories', 'companies', 'people', 'locations',
            'file_relationships', 'organization_sessions', 'cost_records',
            'schema_metadata', 'key_value_store', 'file_categories',
            'file_companies', 'file_people', 'file_locations', 'merge_events'
        ]

        for table in expected_tables:
            assert table in tables, f"Table '{table}' not found"


class TestGraphStoreFileOperations:
    """Test file CRUD operations.

    Note: GraphStore closes sessions after each operation, so we need to
    use a session context for reading attributes or use get_file to retrieve
    fresh objects within a session.
    """

    def test_add_file(self, graph_store, sample_file_data):
        """Test adding a file to the store."""
        session = graph_store.get_session()
        try:
            file = graph_store.add_file(**sample_file_data, session=session)

            assert file is not None
            assert file.filename == sample_file_data['filename']
            assert file.mime_type == sample_file_data['mime_type']
            assert file.file_extension == '.jpg'
        finally:
            session.close()

    def test_add_file_generates_id(self, graph_store, sample_file_data):
        """Test that file ID is generated from path."""
        session = graph_store.get_session()
        try:
            file = graph_store.add_file(**sample_file_data, session=session)

            assert file.id is not None
            assert len(file.id) == 64  # SHA-256 hex
        finally:
            session.close()

    def test_add_file_generates_canonical_id(self, graph_store, sample_file_data):
        """Test that canonical ID is generated."""
        session = graph_store.get_session()
        try:
            file = graph_store.add_file(**sample_file_data, session=session)

            assert file.canonical_id is not None
            assert file.canonical_id.startswith('urn:sha256:')
        finally:
            session.close()

    def test_get_file_by_id(self, graph_store, sample_file_data):
        """Test retrieving file by ID."""
        session = graph_store.get_session()
        try:
            created = graph_store.add_file(**sample_file_data, session=session)
            created_id = created.id
            created_filename = created.filename

            retrieved = graph_store.get_file(file_id=created_id, session=session)

            assert retrieved is not None
            assert retrieved.id == created_id
            assert retrieved.filename == created_filename
        finally:
            session.close()

    def test_get_file_by_path(self, graph_store, sample_file_data):
        """Test retrieving file by path."""
        session = graph_store.get_session()
        try:
            created = graph_store.add_file(**sample_file_data, session=session)
            created_id = created.id

            retrieved = graph_store.get_file(path=sample_file_data['original_path'], session=session)

            assert retrieved is not None
            assert retrieved.id == created_id
        finally:
            session.close()

    def test_get_nonexistent_file(self, graph_store):
        """Test retrieving non-existent file returns None."""
        result = graph_store.get_file(file_id='nonexistent')
        assert result is None

    def test_duplicate_file_updates_existing(self, graph_store, sample_file_data):
        """Test adding duplicate file updates existing record."""
        session = graph_store.get_session()
        try:
            file1 = graph_store.add_file(**sample_file_data, session=session)
            file1_id = file1.id

            # Add same file with different data
            updated_data = sample_file_data.copy()
            updated_data['file_size'] = 2048
            file2 = graph_store.add_file(**updated_data, session=session)

            # Should be same record
            assert file1_id == file2.id
            assert file2.file_size == 2048
        finally:
            session.close()

    def test_update_file_status(self, graph_store, sample_file_data):
        """Test updating file status."""
        session = graph_store.get_session()
        try:
            file = graph_store.add_file(**sample_file_data, session=session)
            file_id = file.id

            result = graph_store.update_file_status(
                file_id,
                FileStatus.ORGANIZED,
                destination='/organized/path/sample.jpg',
                session=session
            )

            assert result is True

            # Verify update
            updated = graph_store.get_file(file_id=file_id, session=session)
            assert updated.status == FileStatus.ORGANIZED
            assert updated.current_path == '/organized/path/sample.jpg'
        finally:
            session.close()

    def test_get_files_with_filters(self, graph_store, sample_file_data):
        """Test querying files with filters."""
        session = graph_store.get_session()
        try:
            # Add some files first
            graph_store.add_file(**sample_file_data, session=session)
            files = graph_store.get_files(limit=10, session=session)
            assert len(files) >= 1
        finally:
            session.close()

    def test_get_files_by_extension(self, graph_store):
        """Test filtering files by extension."""
        session = graph_store.get_session()
        try:
            # Add files with different extensions
            graph_store.add_file(
                original_path='/tmp/test.jpg',
                filename='test.jpg',
                session=session
            )
            graph_store.add_file(
                original_path='/tmp/test.png',
                filename='test.png',
                session=session
            )

            jpg_files = graph_store.get_files(extension='.jpg', session=session)
            assert len(jpg_files) >= 1
            assert all(f.file_extension == '.jpg' for f in jpg_files)
        finally:
            session.close()


class TestGraphStoreCategoryOperations:
    """Test category management."""

    def test_get_or_create_category(self, graph_store):
        """Test creating a category."""
        session = graph_store.get_session()
        try:
            category = graph_store.get_or_create_category(name="Documents", session=session)

            assert category is not None
            assert category.name == "Documents"
            assert category.canonical_id is not None
        finally:
            session.close()

    def test_get_existing_category(self, graph_store):
        """Test getting an existing category."""
        session = graph_store.get_session()
        try:
            created = graph_store.get_or_create_category(name="GameAssets", session=session)
            created_id = created.id
            retrieved = graph_store.get_or_create_category(name="GameAssets", session=session)

            assert created_id == retrieved.id
        finally:
            session.close()

    def test_create_subcategory(self, graph_store):
        """Test creating a subcategory."""
        session = graph_store.get_session()
        try:
            parent = graph_store.get_or_create_category(name="Media", session=session)
            parent_id = parent.id
            child = graph_store.get_or_create_category(
                name="Photos",
                parent_name="Media",
                session=session
            )

            assert child is not None
            assert child.parent_id == parent_id
            assert child.level == 1
            assert child.full_path == "Media/Photos"
        finally:
            session.close()

    def test_add_file_to_category(self, graph_store, sample_file_data):
        """Test associating file with category."""
        session = graph_store.get_session()
        try:
            file = graph_store.add_file(**sample_file_data, session=session)
            file_id = file.id

            result = graph_store.add_file_to_category(
                file_id,
                "Documents",
                session=session
            )

            assert result is True

            # Verify association
            updated = graph_store.get_file(file_id=file_id, session=session)
            category_names = [c.name for c in updated.categories]
            assert "Documents" in category_names
        finally:
            session.close()

    def test_add_file_to_subcategory(self, graph_store, sample_file_data):
        """Test associating file with subcategory."""
        session = graph_store.get_session()
        try:
            file = graph_store.add_file(**sample_file_data, session=session)
            file_id = file.id

            result = graph_store.add_file_to_category(
                file_id,
                category_name="Financial",
                subcategory_name="Invoices",
                session=session
            )

            assert result is True
        finally:
            session.close()

    def test_get_category_tree(self, graph_store):
        """Test getting category hierarchy."""
        session = graph_store.get_session()
        try:
            # Create hierarchy
            graph_store.get_or_create_category("Root1", session=session)
            graph_store.get_or_create_category("Child1", parent_name="Root1", session=session)
            graph_store.get_or_create_category("Root2", session=session)

            tree = graph_store.get_category_tree(session=session)

            assert len(tree) >= 2
            root_names = [c['name'] for c in tree]
            assert "Root1" in root_names
            assert "Root2" in root_names
        finally:
            session.close()


class TestGraphStoreCompanyOperations:
    """Test company management."""

    def test_get_or_create_company(self, graph_store):
        """Test creating a company."""
        session = graph_store.get_session()
        try:
            company = graph_store.get_or_create_company("Acme Corp", session=session)

            assert company is not None
            assert company.name == "Acme Corp"
            assert company.normalized_name == "acme corp"
            assert company.canonical_id is not None
        finally:
            session.close()

    def test_company_normalization(self, graph_store):
        """Test company name normalization."""
        session = graph_store.get_session()
        try:
            c1 = graph_store.get_or_create_company("Test Company", session=session)
            c1_id = c1.id
            c2 = graph_store.get_or_create_company("  test company  ", session=session)

            assert c1_id == c2.id
        finally:
            session.close()

    def test_add_file_to_company(self, graph_store, sample_file_data):
        """Test associating file with company."""
        session = graph_store.get_session()
        try:
            file = graph_store.add_file(**sample_file_data, session=session)
            file_id = file.id

            result = graph_store.add_file_to_company(
                file_id,
                "Test Corp",
                session=session
            )

            assert result is True

            # Verify association
            updated = graph_store.get_file(file_id=file_id, session=session)
            company_names = [c.name for c in updated.companies]
            assert "Test Corp" in company_names
        finally:
            session.close()


class TestGraphStorePersonOperations:
    """Test person management."""

    def test_get_or_create_person(self, graph_store):
        """Test creating a person."""
        session = graph_store.get_session()
        try:
            person = graph_store.get_or_create_person("John Doe", session=session)

            assert person is not None
            assert person.name == "John Doe"
            assert person.normalized_name == "john doe"
            assert person.canonical_id is not None
        finally:
            session.close()

    def test_person_with_email(self, graph_store):
        """Test creating person with email."""
        session = graph_store.get_session()
        try:
            person = graph_store.get_or_create_person(
                name="Jane Smith",
                email="jane@example.com",
                role="author",
                session=session
            )

            assert person.email == "jane@example.com"
            assert person.role == "author"
        finally:
            session.close()

    def test_add_file_to_person(self, graph_store, sample_file_data):
        """Test associating file with person."""
        session = graph_store.get_session()
        try:
            file = graph_store.add_file(**sample_file_data, session=session)
            file_id = file.id

            result = graph_store.add_file_to_person(
                file_id,
                "Test Person",
                session=session
            )

            assert result is True
        finally:
            session.close()


class TestGraphStoreLocationOperations:
    """Test location management."""

    def test_get_or_create_location(self, graph_store):
        """Test creating a location."""
        session = graph_store.get_session()
        try:
            location = graph_store.get_or_create_location(
                name="San Francisco",
                city="San Francisco",
                state="CA",
                country="USA",
                latitude=37.7749,
                longitude=-122.4194,
                session=session
            )

            assert location is not None
            assert location.name == "San Francisco"
            assert location.latitude == 37.7749
            assert location.canonical_id is not None
        finally:
            session.close()

    def test_find_location_by_coordinates(self, graph_store):
        """Test finding location by nearby coordinates."""
        session = graph_store.get_session()
        try:
            created = graph_store.get_or_create_location(
                name="NYC",
                latitude=40.7128,
                longitude=-74.0060,
                session=session
            )
            created_id = created.id

            # Find with slightly different coordinates
            found = graph_store.get_or_create_location(
                name="NYC Area",
                latitude=40.7130,
                longitude=-74.0058,
                session=session
            )

            assert created_id == found.id
        finally:
            session.close()

    def test_add_file_to_location(self, graph_store, sample_file_data):
        """Test associating file with location."""
        session = graph_store.get_session()
        try:
            file = graph_store.add_file(**sample_file_data, session=session)
            file_id = file.id

            result = graph_store.add_file_to_location(
                file_id,
                "Test Location",
                latitude=40.0,
                longitude=-74.0,
                session=session
            )

            assert result is True
        finally:
            session.close()


class TestGraphStoreRelationships:
    """Test file-to-file relationships."""

    def test_add_relationship(self, graph_store):
        """Test adding relationship between files."""
        session = graph_store.get_session()
        try:
            file1 = graph_store.add_file(
                original_path='/tmp/file1.jpg',
                filename='file1.jpg',
                session=session
            )
            file1_id = file1.id
            file2 = graph_store.add_file(
                original_path='/tmp/file2.jpg',
                filename='file2.jpg',
                session=session
            )
            file2_id = file2.id

            relationship = graph_store.add_relationship(
                source_file_id=file1_id,
                target_file_id=file2_id,
                relationship_type=RelationshipType.SIMILAR,
                confidence=0.85,
                session=session
            )

            assert relationship is not None
            assert relationship.confidence == 0.85
        finally:
            session.close()

    def test_find_related_files(self, graph_store):
        """Test finding related files."""
        session = graph_store.get_session()
        try:
            file1 = graph_store.add_file(
                original_path='/tmp/source.jpg',
                filename='source.jpg',
                session=session
            )
            file1_id = file1.id
            file2 = graph_store.add_file(
                original_path='/tmp/related.jpg',
                filename='related.jpg',
                session=session
            )
            file2_id = file2.id

            graph_store.add_relationship(
                source_file_id=file1_id,
                target_file_id=file2_id,
                relationship_type=RelationshipType.RELATED,
                session=session
            )

            related = graph_store.find_related_files(file1_id, session=session)

            assert len(related) >= 1
            related_ids = [f.id for f, _, _ in related]
            assert file2_id in related_ids
        finally:
            session.close()

    def test_find_duplicates(self, graph_store):
        """Test finding duplicate files."""
        session = graph_store.get_session()
        try:
            # Add files with same content hash
            file1 = graph_store.add_file(
                original_path='/tmp/dup1.jpg',
                filename='dup1.jpg',
                content_hash='abc123',
                session=session
            )
            file1_id = file1.id
            file2 = graph_store.add_file(
                original_path='/tmp/dup2.jpg',
                filename='dup2.jpg',
                content_hash='abc123',
                session=session
            )
            file2_id = file2.id

            duplicates = graph_store.find_duplicates(session=session)

            assert len(duplicates) >= 1
            dup_group = duplicates[0]
            dup_ids = [f.id for f in dup_group]
            assert file1_id in dup_ids
            assert file2_id in dup_ids
        finally:
            session.close()


class TestGraphStoreSession:
    """Test organization session management."""

    def test_create_session(self, graph_store):
        """Test creating an organization session."""
        db_session = graph_store.get_session()
        try:
            org_session = graph_store.create_session(
                source_directories=['/tmp/source'],
                base_path='/tmp/target',
                dry_run=True,
                session=db_session
            )

            assert org_session is not None
            assert org_session.dry_run is True
            assert org_session.started_at is not None
        finally:
            db_session.close()

    def test_complete_session(self, graph_store):
        """Test completing a session with stats."""
        db_session = graph_store.get_session()
        try:
            org_session = graph_store.create_session(
                source_directories=['/tmp/source'],
                base_path='/tmp/target',
                session=db_session
            )
            session_id = org_session.id

            result = graph_store.complete_session(
                session_id=session_id,
                stats={
                    'total_files': 100,
                    'organized': 95,
                    'skipped': 3,
                    'errors': 2
                },
                db_session=db_session
            )

            assert result is True
        finally:
            db_session.close()


class TestGraphStoreStatistics:
    """Test statistics and aggregations."""

    def test_get_statistics(self, graph_store, sample_file_data):
        """Test getting overall statistics."""
        session = graph_store.get_session()
        try:
            # Add some data first
            graph_store.add_file(**sample_file_data, session=session)
            stats = graph_store.get_statistics(session=session)

            assert 'total_files' in stats
            assert 'total_categories' in stats
            assert 'total_companies' in stats
            assert stats['total_files'] >= 1
        finally:
            session.close()

    def test_get_cost_statistics(self, graph_store):
        """Test getting cost statistics."""
        session = graph_store.get_session()
        try:
            stats = graph_store.get_cost_statistics(session=session)

            assert 'total_records' in stats
            assert 'total_cost' in stats
            assert 'by_feature' in stats
        finally:
            session.close()


class TestGraphStoreSearch:
    """Test search operations."""

    def test_search_by_filename(self, graph_store):
        """Test searching files by filename."""
        graph_store.add_file(
            original_path='/tmp/invoice_2024.pdf',
            filename='invoice_2024.pdf'
        )

        results = graph_store.search_files(
            query='invoice',
            search_filename=True,
            search_content=False
        )

        assert len(results) >= 1
        assert any('invoice' in f.filename.lower() for f in results)

    def test_search_by_content(self, graph_store):
        """Test searching files by extracted text."""
        graph_store.add_file(
            original_path='/tmp/doc.txt',
            filename='doc.txt',
            extracted_text='This document contains important financial data'
        )

        results = graph_store.search_files(
            query='financial',
            search_filename=False,
            search_content=True
        )

        assert len(results) >= 1
