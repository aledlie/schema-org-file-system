# Quick Start: Testing & Refactoring

**Goal:** Get testing infrastructure set up and write first tests this week.

## Step 1: Install Test Dependencies (5 minutes)

```bash
cd /Users/alyshialedlie/schema-org-file-system

# Update pyproject.toml with new dev dependencies (already has pytest)
pip install pytest pytest-cov pytest-mock pytest-asyncio faker factory-boy

# Verify installation
pytest --version
```

## Step 2: Create Test Infrastructure (10 minutes)

```bash
# Create test directories
mkdir -p tests/unit
mkdir -p tests/integration
mkdir -p tests/e2e
mkdir -p tests/fixtures/images
mkdir -p tests/fixtures/documents

# Create pytest config (tests/conftest.py)
```

## Step 3: Write Your First Test (30 minutes)

**Priority: Test the storage layer first (most critical)**

Create `tests/integration/test_storage_graph.py`:

```python
"""
Integration tests for GraphStore.

Tests database operations with real SQLite database.
"""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.storage.graph_store import GraphStore
from src.storage.models import FileStatus


@pytest.fixture
def temp_db():
    """Create temporary test database."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        yield str(db_path)


@pytest.fixture
def graph_store(temp_db):
    """Create GraphStore instance with temp database."""
    return GraphStore(db_path=temp_db)


class TestGraphStoreBasics:
    """Test basic GraphStore operations."""

    def test_initialization(self, graph_store):
        """Test GraphStore initializes correctly."""
        assert graph_store is not None
        assert graph_store.db_path is not None

    def test_add_file(self, graph_store):
        """Test adding a file to the store."""
        file = graph_store.add_file(
            original_path="/tmp/test.txt",
            filename="test.txt",
            mime_type="text/plain",
            status=FileStatus.PENDING
        )

        assert file is not None
        assert file.filename == "test.txt"
        assert file.mime_type == "text/plain"
        assert file.status == FileStatus.PENDING

    def test_get_file_by_id(self, graph_store):
        """Test retrieving file by ID."""
        # Add file
        file = graph_store.add_file(
            original_path="/tmp/test.txt",
            filename="test.txt"
        )

        # Retrieve file
        retrieved = graph_store.get_file(file.id)

        assert retrieved is not None
        assert retrieved.id == file.id
        assert retrieved.filename == file.filename

    def test_update_file_status(self, graph_store):
        """Test updating file status."""
        file = graph_store.add_file(
            original_path="/tmp/test.txt",
            filename="test.txt",
            status=FileStatus.PENDING
        )

        # Update status
        updated = graph_store.update_file_status(
            file.id,
            FileStatus.COMPLETED
        )

        assert updated.status == FileStatus.COMPLETED

    def test_duplicate_file_handling(self, graph_store):
        """Test handling of duplicate file paths."""
        # Add file twice
        file1 = graph_store.add_file(
            original_path="/tmp/duplicate.txt",
            filename="duplicate.txt"
        )

        file2 = graph_store.add_file(
            original_path="/tmp/duplicate.txt",
            filename="duplicate.txt"
        )

        # Should return same file or update existing
        assert file1.id == file2.id


class TestGraphStoreCategories:
    """Test category management."""

    def test_add_category(self, graph_store):
        """Test adding a category."""
        category = graph_store.add_category(
            name="Documents",
            description="Document files"
        )

        assert category is not None
        assert category.name == "Documents"

    def test_add_file_with_category(self, graph_store):
        """Test adding file with category."""
        category = graph_store.add_category(name="Images")

        file = graph_store.add_file(
            original_path="/tmp/photo.jpg",
            filename="photo.jpg",
            categories=[category]
        )

        assert len(file.categories) == 1
        assert file.categories[0].name == "Images"


class TestGraphStoreEntities:
    """Test entity management (companies, people)."""

    def test_add_company(self, graph_store):
        """Test adding a company entity."""
        company = graph_store.add_company(
            name="Acme Corp",
            canonical_id="org:acme-corp"
        )

        assert company is not None
        assert company.name == "Acme Corp"

    def test_add_person(self, graph_store):
        """Test adding a person entity."""
        person = graph_store.add_person(
            name="John Doe",
            canonical_id="person:john-doe"
        )

        assert person is not None
        assert person.name == "John Doe"


class TestGraphStoreQueries:
    """Test graph query capabilities."""

    def test_get_files_by_category(self, graph_store):
        """Test retrieving files by category."""
        category = graph_store.add_category(name="Videos")

        # Add files
        file1 = graph_store.add_file(
            original_path="/tmp/video1.mp4",
            filename="video1.mp4",
            categories=[category]
        )

        file2 = graph_store.add_file(
            original_path="/tmp/video2.mp4",
            filename="video2.mp4",
            categories=[category]
        )

        # Query
        files = graph_store.get_files_by_category(category.name)

        assert len(files) >= 2

    def test_get_files_by_status(self, graph_store):
        """Test retrieving files by status."""
        graph_store.add_file(
            original_path="/tmp/pending1.txt",
            filename="pending1.txt",
            status=FileStatus.PENDING
        )

        graph_store.add_file(
            original_path="/tmp/pending2.txt",
            filename="pending2.txt",
            status=FileStatus.PENDING
        )

        files = graph_store.get_files_by_status(FileStatus.PENDING)

        assert len(files) >= 2


class TestGraphStoreTransactions:
    """Test transaction handling."""

    def test_transaction_rollback_on_error(self, graph_store):
        """Test that transactions rollback on error."""
        # This test depends on implementation details
        # Adapt based on actual transaction methods
        pass

    def test_concurrent_access(self, graph_store):
        """Test concurrent database access."""
        # Test thread safety if applicable
        pass
```

## Step 4: Run Your First Test (2 minutes)

```bash
# Run the test
pytest tests/integration/test_storage_graph.py -v

# Run with coverage
pytest tests/integration/test_storage_graph.py --cov=src/storage/graph_store --cov-report=term-missing

# Expected output:
# ============================= test session starts ==============================
# collected X items
#
# tests/integration/test_storage_graph.py::TestGraphStoreBasics::test_initialization PASSED
# tests/integration/test_storage_graph.py::TestGraphStoreBasics::test_add_file PASSED
# ...
```

## Step 5: Add conftest.py (5 minutes)

Create `tests/conftest.py`:

```python
"""
Pytest configuration and shared fixtures.
"""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory


@pytest.fixture
def temp_dir():
    """Create temporary directory for tests."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_text_file(temp_dir):
    """Create sample text file."""
    file_path = temp_dir / "sample.txt"
    file_path.write_text("Sample content for testing.")
    return file_path


@pytest.fixture
def sample_json_file(temp_dir):
    """Create sample JSON file."""
    import json
    file_path = temp_dir / "sample.json"
    data = {
        "@context": "https://schema.org",
        "@type": "DigitalDocument",
        "name": "Test Document"
    }
    file_path.write_text(json.dumps(data, indent=2))
    return file_path


@pytest.fixture(scope="session")
def test_data_dir():
    """Return path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"


# Database fixtures
@pytest.fixture
def temp_db_path(temp_dir):
    """Create temporary database path."""
    return str(temp_dir / "test.db")


@pytest.fixture
def clean_db(temp_db_path):
    """Create clean test database."""
    from src.storage.graph_store import GraphStore
    store = GraphStore(db_path=temp_db_path)
    yield store
    # Cleanup handled by temp_dir fixture


# Mock fixtures
@pytest.fixture
def mock_cost_calculator():
    """Mock CostROICalculator for testing."""
    from unittest.mock import MagicMock
    mock = MagicMock()
    mock.track_operation.return_value.__enter__.return_value = None
    return mock


@pytest.fixture
def mock_sentry():
    """Mock Sentry for testing."""
    from unittest.mock import MagicMock, patch
    with patch('src.error_tracking.capture_error') as mock:
        yield mock
```

## Step 6: Measure Coverage (2 minutes)

```bash
# Run all tests with coverage
pytest --cov=src --cov-report=html --cov-report=term-missing

# Open HTML coverage report
open htmlcov/index.html

# Look for:
# - Red lines (not covered)
# - Green lines (covered)
# - Yellow lines (partially covered)
```

## Step 7: Next Steps

### This Week
1. ✅ Write storage layer tests (above)
2. ✅ Test `src/storage/models.py` - ORM models
3. ✅ Test `src/uri_utils.py` - URI generation
4. ✅ Achieve 80%+ coverage on storage

### Next Week
1. ✅ Test `src/generators.py` - enhance existing tests
2. ✅ Test `src/enrichment.py` - entity detection
3. ✅ Test `src/base.py` - base classes

### Week 3-4
1. ✅ Begin refactoring `file_organizer_content_based.py`
2. ✅ Extract `ContentClassifier` to `src/classifiers/`
3. ✅ Write tests for extracted modules

## Quick Commands Reference

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/integration/test_storage_graph.py

# Run specific test class
pytest tests/integration/test_storage_graph.py::TestGraphStoreBasics

# Run specific test
pytest tests/integration/test_storage_graph.py::TestGraphStoreBasics::test_add_file

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=src

# Run in parallel (faster)
pytest -n auto

# Run only failed tests from last run
pytest --lf

# Run tests matching pattern
pytest -k "test_add"

# Show print statements
pytest -s
```

## Troubleshooting

### Import Errors
```bash
# Make sure package is installed in editable mode
pip install -e .

# Or add to PYTHONPATH
export PYTHONPATH=/Users/alyshialedlie/schema-org-file-system:$PYTHONPATH
```

### Database Errors
```bash
# Ensure temp directory cleanup
# TemporaryDirectory automatically cleans up

# Manually check for stale DB files
ls /tmp/pytest-*
```

### Missing Dependencies
```bash
# Install all optional dependencies
pip install -e ".[all,dev]"

# Or specific groups
pip install -e ".[ai,docs,monitoring,dev]"
```

## Resources

- **Full Plan:** `docs/TEST_AND_REFACTOR_PLAN.md`
- **Pytest Docs:** https://docs.pytest.org/
- **Coverage.py:** https://coverage.readthedocs.io/
- **Factory Boy:** https://factoryboy.readthedocs.io/ (for test data)

---

**Start Time Estimate:** 1-2 hours to setup and run first tests
**Confidence Level:** High - storage layer is well-defined and testable
