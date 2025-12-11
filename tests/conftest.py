"""
Pytest configuration and shared fixtures.

Provides common fixtures for testing the schema-org-file-system:
- Temporary directories and files
- Database fixtures (temp SQLite)
- Mock objects for external services
- Sample data generators
"""

import json
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime
from typing import Generator


# ===========================================================================
# Directory Fixtures
# ===========================================================================

@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create temporary directory for tests."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"


# ===========================================================================
# File Fixtures
# ===========================================================================

@pytest.fixture
def sample_text_file(temp_dir: Path) -> Path:
    """Create sample text file."""
    file_path = temp_dir / "sample.txt"
    file_path.write_text("Sample content for testing.")
    return file_path


@pytest.fixture
def sample_json_file(temp_dir: Path) -> Path:
    """Create sample JSON file."""
    file_path = temp_dir / "sample.json"
    data = {
        "@context": "https://schema.org",
        "@type": "DigitalDocument",
        "name": "Test Document"
    }
    file_path.write_text(json.dumps(data, indent=2))
    return file_path


@pytest.fixture
def sample_image_file(temp_dir: Path) -> Path:
    """Create a minimal valid PNG file for testing."""
    file_path = temp_dir / "sample.png"
    # Minimal 1x1 transparent PNG
    png_data = bytes([
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,  # PNG signature
        0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,  # IHDR chunk
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,  # 1x1
        0x08, 0x06, 0x00, 0x00, 0x00, 0x1f, 0x15, 0xc4,
        0x89, 0x00, 0x00, 0x00, 0x0a, 0x49, 0x44, 0x41,  # IDAT chunk
        0x54, 0x78, 0x9c, 0x63, 0x00, 0x01, 0x00, 0x00,
        0x05, 0x00, 0x01, 0x0d, 0x0a, 0x2d, 0xb4, 0x00,
        0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae,  # IEND chunk
        0x42, 0x60, 0x82,
    ])
    file_path.write_bytes(png_data)
    return file_path


# ===========================================================================
# Database Fixtures
# ===========================================================================

@pytest.fixture
def temp_db_path(temp_dir: Path) -> str:
    """Create temporary database path."""
    return str(temp_dir / "test.db")


@pytest.fixture
def graph_store(temp_db_path: str):
    """Create GraphStore instance with temp database."""
    from src.storage.graph_store import GraphStore
    return GraphStore(db_path=temp_db_path)


@pytest.fixture
def clean_db(temp_db_path: str):
    """Create clean test database and return GraphStore."""
    from src.storage.graph_store import GraphStore
    store = GraphStore(db_path=temp_db_path)
    yield store
    # Cleanup handled by temp_dir fixture


# ===========================================================================
# Mock Fixtures
# ===========================================================================

@pytest.fixture
def mock_cost_calculator():
    """Mock CostROICalculator for testing."""
    from unittest.mock import MagicMock
    mock = MagicMock()
    mock.track_operation.return_value.__enter__ = MagicMock(return_value=None)
    mock.track_operation.return_value.__exit__ = MagicMock(return_value=False)
    return mock


@pytest.fixture
def mock_sentry():
    """Mock Sentry for testing."""
    from unittest.mock import MagicMock, patch
    with patch('src.error_tracking.capture_error') as mock:
        yield mock


# ===========================================================================
# Sample Data Fixtures
# ===========================================================================

@pytest.fixture
def sample_file_data():
    """Sample file data for testing.

    Note: file_extension is auto-calculated from filename in add_file,
    so we don't include it here to avoid conflicts.
    """
    return {
        'original_path': '/tmp/test/sample.jpg',
        'filename': 'sample.jpg',
        'mime_type': 'image/jpeg',
        'file_size': 1024,
    }


@pytest.fixture
def sample_schema_data():
    """Sample Schema.org metadata."""
    return {
        "@context": "https://schema.org",
        "@type": "ImageObject",
        "name": "Test Image",
        "contentUrl": "/path/to/image.jpg",
        "encodingFormat": "image/jpeg",
        "width": 1920,
        "height": 1080,
    }


@pytest.fixture
def sample_company_names():
    """Sample company names for testing."""
    return [
        "Acme Corp",
        "Tech Solutions Inc",
        "Global Industries",
        "Test Company LLC",
    ]


@pytest.fixture
def sample_person_names():
    """Sample person names for testing."""
    return [
        "John Doe",
        "Jane Smith",
        "Bob Johnson",
        "Alice Williams",
    ]


@pytest.fixture
def sample_category_names():
    """Sample category names for testing."""
    return [
        "GameAssets",
        "Documents",
        "Financial",
        "Media",
        "Technical",
    ]


# ===========================================================================
# Integration Test Helpers
# ===========================================================================

# Note: The populated_db fixture was removed because integration tests
# now manage their own sessions to avoid SQLAlchemy DetachedInstanceError.
# Tests should create their own data within a session context.


# ===========================================================================
# Pytest Configuration
# ===========================================================================

def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "e2e: marks tests as end-to-end tests"
    )
