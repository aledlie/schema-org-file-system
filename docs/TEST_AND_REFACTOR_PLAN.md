# Test Coverage & Refactoring Plan
## Schema.org File Organization System

**Date:** 2025-12-10
**Status:** Planning Phase
**Priority:** High (Code Quality & Maintainability)

---

## Executive Summary

This document provides a comprehensive plan for:
1. **Test Coverage** - Adding unit and integration tests to critical modules
2. **Refactoring** - Breaking up monolithic "god scripts" into modular components

### Current State Analysis

**Total Python Files:** 18 scripts + 17 src modules = 35 files
**Lines of Code (LOC):**
- Scripts: ~10,594 LOC
- Src modules: ~10,120 LOC
- **Total: ~20,714 LOC**

**Test Coverage:**
- ✅ Existing: `tests/test_generators.py` (420 lines), `tests/test_validator.py` (258 lines)
- ❌ Missing: Core organizer logic, storage layer, CLI, enrichment, cost tracking

---

## Part 1: Test Coverage Strategy

### 1.1 Priority Modules Needing Tests

#### **CRITICAL Priority** (P0 - Test First)

| Module | LOC | Complexity | Test Priority | Rationale |
|--------|-----|-----------|---------------|-----------|
| `src/storage/graph_store.py` | 1,146 | High | **P0-1** | Database operations, data integrity critical |
| `src/generators.py` | 1,714 | Medium | **P0-2** | Core metadata generation (partially tested) |
| `src/enrichment.py` | 666 | Medium | **P0-3** | Entity detection & metadata enrichment |
| `src/storage/models.py` | 864 | Medium | **P0-4** | ORM models, relationships, canonical IDs |

#### **HIGH Priority** (P1 - Test Soon)

| Module | LOC | Complexity | Test Priority | Rationale |
|--------|-----|-----------|---------------|-----------|
| `src/base.py` | 540 | Medium | **P1-1** | Foundation for all generators |
| `src/validator.py` | 488 | Medium | **P1-2** | Schema.org compliance (partially tested) |
| `src/uri_utils.py` | 354 | Low | **P1-3** | IRI generation, canonical ID logic |
| `src/storage/migration.py` | 842 | High | **P1-4** | Database migrations, data integrity |
| `src/cost_roi_calculator.py` | 824 | Medium | **P1-5** | Cost tracking & ROI calculations |

#### **MEDIUM Priority** (P2 - Test Later)

| Module | LOC | Complexity | Test Priority | Rationale |
|--------|-----|-----------|---------------|-----------|
| `src/cli.py` | 282 | Low | **P2-1** | CLI integration testing |
| `src/health_check.py` | 375 | Low | **P2-2** | Dependency validation |
| `src/error_tracking.py` | 392 | Low | **P2-3** | Sentry integration |
| `src/storage/kv_store.py` | 758 | Medium | **P2-4** | Key-value store operations |

### 1.2 Test File Structure

```
tests/
├── __init__.py
├── conftest.py                          # Pytest fixtures
├── fixtures/                            # Test data
│   ├── images/
│   │   ├── test_photo.jpg
│   │   ├── test_screenshot.png
│   │   └── test_heic.HEIC
│   ├── documents/
│   │   ├── test_invoice.pdf
│   │   ├── test_resume.docx
│   │   └── test_legal.pdf
│   └── sample_metadata.json
│
├── unit/                                # Unit tests (isolated)
│   ├── test_base.py                     # P1-1: Base classes
│   ├── test_generators.py               # P0-2: EXISTING (enhance)
│   ├── test_validator.py                # P1-2: EXISTING (enhance)
│   ├── test_enrichment.py               # P0-3: NEW
│   ├── test_uri_utils.py                # P1-3: NEW
│   ├── test_cost_calculator.py          # P1-5: NEW
│   ├── test_error_tracking.py           # P2-3: NEW
│   └── test_health_check.py             # P2-2: NEW
│
├── integration/                         # Integration tests
│   ├── test_storage_graph.py            # P0-1: Graph store operations
│   ├── test_storage_models.py           # P0-4: ORM models & relationships
│   ├── test_storage_migration.py        # P1-4: Database migrations
│   ├── test_cli.py                      # P2-1: CLI commands
│   ├── test_file_organization.py        # End-to-end file organization
│   └── test_kv_store.py                 # P2-4: Key-value operations
│
└── e2e/                                 # End-to-end tests
    ├── test_content_organizer.py        # Full organization pipeline
    └── test_name_organizer.py           # Name-based organization
```

### 1.3 Test Framework & Tools

**Primary Framework:** `pytest` (already configured in `pyproject.toml`)

**Additional Testing Libraries:**
```toml
# Add to pyproject.toml [project.optional-dependencies.dev]
dev = [
    "pytest>=7.4.0",
    "pytest-cov>=4.1.0",           # Coverage reporting
    "pytest-mock>=3.12.0",         # Mocking support
    "pytest-asyncio>=0.21.0",      # Async test support
    "pytest-xdist>=3.5.0",         # Parallel test execution
    "faker>=20.0.0",               # Test data generation
    "factory-boy>=3.3.0",          # Model factories
    "hypothesis>=6.92.0",          # Property-based testing
    "black>=23.7.0",
    "flake8>=6.1.0",
    "mypy>=1.5.0",
    "isort>=5.12.0",
]
```

### 1.4 Testing Patterns & Conventions

#### Unit Test Template
```python
"""
Unit tests for <module_name>.

Tests <module_name> functionality in isolation with mocked dependencies.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Import module under test
from src.<module_name> import <ClassName>


class Test<ClassName>:
    """Test <ClassName> class."""

    @pytest.fixture
    def instance(self):
        """Create test instance with mocked dependencies."""
        return <ClassName>()

    def test_basic_functionality(self, instance):
        """Test basic functionality works as expected."""
        result = instance.method()
        assert result is not None

    def test_error_handling(self, instance):
        """Test error handling for invalid inputs."""
        with pytest.raises(ValueError):
            instance.method(invalid_input)

    @patch('src.<module_name>.external_dependency')
    def test_with_mocked_dependency(self, mock_dep, instance):
        """Test with mocked external dependency."""
        mock_dep.return_value = "mocked"
        result = instance.method()
        assert result == "expected"
```

#### Integration Test Template
```python
"""
Integration tests for <module_name>.

Tests <module_name> with real dependencies and database.
"""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.<module_name> import <ClassName>


@pytest.fixture
def temp_db():
    """Create temporary test database."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        yield str(db_path)


class TestIntegration<ClassName>:
    """Integration tests for <ClassName>."""

    def test_database_operations(self, temp_db):
        """Test database CRUD operations."""
        instance = <ClassName>(db_path=temp_db)
        # Test create, read, update, delete

    def test_transaction_rollback(self, temp_db):
        """Test transaction rollback on error."""
        instance = <ClassName>(db_path=temp_db)
        # Test that errors rollback transactions
```

### 1.5 Coverage Goals

| Module Category | Target Coverage | Timeline |
|----------------|----------------|----------|
| **Storage layer** (`src/storage/*`) | 85%+ | Week 1-2 |
| **Core generators** (`src/generators.py`) | 90%+ | Week 2-3 |
| **Enrichment** (`src/enrichment.py`) | 80%+ | Week 3 |
| **Utilities** (`src/base.py`, `uri_utils.py`) | 85%+ | Week 4 |
| **Overall codebase** | 75%+ | Month 1 |

**Coverage Measurement:**
```bash
# Run tests with coverage
pytest --cov=src --cov-report=html --cov-report=term-missing

# View HTML report
open htmlcov/index.html
```

---

## Part 2: Refactoring "God Scripts"

### 2.1 Scripts Requiring Refactoring

#### **God Script #1: `file_organizer_content_based.py`** (2,691 LOC)

**Status:** 🔴 CRITICAL - Monolithic, multiple responsibilities
**Target:** Break into modular components under `src/`

**Current Structure:**
```
file_organizer_content_based.py (2,691 LOC)
├── Class: ContentClassifier (375 LOC)
│   ├── Company/People pattern matching
│   ├── Category classification (legal, medical, financial, etc.)
│   └── OCR text analysis
├── Class: ImageMetadataParser (230 LOC)
│   ├── EXIF extraction
│   ├── GPS geocoding
│   └── Timestamp parsing
├── Class: ImageContentAnalyzer (186 LOC)
│   ├── CLIP vision classification
│   ├── Face detection
│   └── Content scoring
├── Class: ContentBasedFileOrganizer (1,577 LOC)
│   ├── File organization logic
│   ├── OCR processing
│   ├── Category determination
│   ├── Schema.org metadata generation
│   ├── Database persistence
│   └── Cost tracking
└── main() function (323 LOC)
```

**Proposed Modular Architecture:**

```
src/
├── classifiers/
│   ├── __init__.py
│   ├── content_classifier.py         # Extract ContentClassifier
│   ├── entity_detector.py            # Extract company/people detection
│   └── category_rules.py             # Classification patterns/rules
│
├── analyzers/
│   ├── __init__.py
│   ├── image_metadata.py             # Extract ImageMetadataParser
│   ├── image_content.py              # Extract ImageContentAnalyzer
│   ├── ocr_processor.py              # OCR extraction logic
│   └── vision_classifier.py          # CLIP vision logic
│
├── organizers/
│   ├── __init__.py
│   ├── base_organizer.py             # Abstract base class
│   ├── content_organizer.py          # Refactored ContentBasedFileOrganizer
│   ├── name_organizer.py             # Move from script
│   ├── type_organizer.py             # Move from script
│   └── folder_strategy.py            # Folder structure logic
│
└── pipeline/
    ├── __init__.py
    ├── file_processor.py             # Single file processing
    ├── batch_processor.py            # Batch file processing
    └── workflow.py                   # Orchestration logic
```

**Refactoring Steps (Incremental):**

1. **Week 1:** Extract `ContentClassifier` → `src/classifiers/content_classifier.py`
2. **Week 1:** Extract entity detection → `src/classifiers/entity_detector.py`
3. **Week 2:** Extract `ImageMetadataParser` → `src/analyzers/image_metadata.py`
4. **Week 2:** Extract `ImageContentAnalyzer` → `src/analyzers/image_content.py`
5. **Week 3:** Extract OCR logic → `src/analyzers/ocr_processor.py`
6. **Week 3:** Refactor main organizer → `src/organizers/content_organizer.py`
7. **Week 4:** Extract workflow orchestration → `src/pipeline/workflow.py`
8. **Week 4:** Update `scripts/file_organizer_content_based.py` to thin wrapper

**Final Script (Post-Refactor):**
```python
#!/usr/bin/env python3
"""
Content-Based File Organizer - CLI Wrapper

DEPRECATED: This script is a thin wrapper around src.organizers.
Use `organize-files content` CLI command instead.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from organizers.content_organizer import ContentBasedFileOrganizer
from pipeline.workflow import OrganizationWorkflow


def main():
    """Main entry point - delegates to src modules."""
    import argparse

    parser = argparse.ArgumentParser(description="AI-powered file organization")
    # ... argument parsing ...

    workflow = OrganizationWorkflow(
        organizer_class=ContentBasedFileOrganizer,
        **vars(args)
    )
    workflow.run()


if __name__ == '__main__':
    main()
```

#### **God Script #2: `file_organizer.py`** (958 LOC)

**Status:** 🟡 MODERATE - Base organizer, cleaner than content-based
**Target:** Extract reusable components

**Current Structure:**
```
file_organizer.py (958 LOC)
├── Class: FileOrganizer (869 LOC)
│   ├── Category path definitions
│   ├── MIME type mapping
│   ├── File organization logic
│   └── Schema.org metadata generation
└── main() function (89 LOC)
```

**Proposed Refactoring:**

```
src/organizers/
├── base_organizer.py           # Abstract base with common logic
├── category_config.py          # Category definitions (from FileOrganizer)
├── mime_classifier.py          # MIME type classification
└── simple_organizer.py         # Refactored FileOrganizer
```

**Refactoring Steps:**
1. Extract category definitions → `src/organizers/category_config.py`
2. Extract MIME logic → `src/organizers/mime_classifier.py`
3. Create abstract base → `src/organizers/base_organizer.py`
4. Refactor FileOrganizer → `src/organizers/simple_organizer.py`

#### **Large Script #3: `file_organizer_by_name.py`** (806 LOC)

**Status:** 🟡 MODERATE - Standalone utility
**Target:** Move to `src/organizers/name_organizer.py`

**Refactoring:** Direct move to src with minimal changes
```
src/organizers/name_organizer.py  # Move entire FileOrganizerByName class
```

#### **Large Script #4: `data_preprocessing.py`** (651 LOC)

**Status:** 🟢 LOW PRIORITY - ML training utility, used less frequently
**Target:** Extract to `src/ml/` module

```
src/ml/
├── __init__.py
├── data_preprocessor.py       # Extract preprocessing logic
├── feature_extractor.py       # Feature engineering
└── training_pipeline.py       # ML training workflow
```

#### **Large Script #5: `correction_feedback.py`** (620 LOC)

**Status:** 🟢 LOW PRIORITY - User feedback system
**Target:** Move to `src/feedback/`

```
src/feedback/
├── __init__.py
├── correction_tracker.py      # User corrections
├── feedback_loop.py           # Feedback integration
└── label_manager.py           # Label management
```

### 2.2 Refactoring Principles

**SOLID Principles:**
1. **Single Responsibility** - Each class does one thing
2. **Open/Closed** - Open for extension, closed for modification
3. **Liskov Substitution** - Subclasses interchangeable
4. **Interface Segregation** - Small, focused interfaces
5. **Dependency Inversion** - Depend on abstractions

**Design Patterns to Apply:**
- **Strategy Pattern** - Different organization strategies (content, name, type)
- **Factory Pattern** - Generator creation
- **Template Method** - Base organizer workflow
- **Observer Pattern** - Cost tracking, error tracking
- **Repository Pattern** - Already used in graph_store

**Code Quality Standards:**
- Maximum function length: 50 lines
- Maximum class length: 300 lines
- Maximum file length: 500 lines
- Cyclomatic complexity: ≤10 per function

### 2.3 Dependency Injection

**Current Problem:** Hard-coded dependencies
**Solution:** Inject dependencies via constructor

**Example Refactoring:**

**Before:**
```python
class ContentBasedFileOrganizer:
    def __init__(self, base_path: str = None):
        self.enricher = MetadataEnricher()  # Hard-coded
        self.validator = SchemaValidator()  # Hard-coded
        self.classifier = ContentClassifier()  # Hard-coded
```

**After:**
```python
class ContentBasedFileOrganizer:
    def __init__(
        self,
        base_path: str = None,
        enricher: Optional[MetadataEnricher] = None,
        validator: Optional[SchemaValidator] = None,
        classifier: Optional[ContentClassifier] = None
    ):
        self.enricher = enricher or MetadataEnricher()
        self.validator = validator or SchemaValidator()
        self.classifier = classifier or ContentClassifier()
```

**Benefits:**
- Easier unit testing (inject mocks)
- Better flexibility (swap implementations)
- Clearer dependencies

---

## Part 3: Implementation Order

### Phase 1: Foundation (Week 1-2)

**Week 1: Storage Layer Tests**
- [ ] Create `tests/conftest.py` with fixtures
- [ ] Write `tests/integration/test_storage_models.py` (P0-4)
- [ ] Write `tests/integration/test_storage_graph.py` (P0-1)
- [ ] Write `tests/unit/test_uri_utils.py` (P1-3)
- [ ] Achieve 80%+ coverage on storage layer

**Week 2: Core Generators Tests**
- [ ] Enhance `tests/unit/test_generators.py` (P0-2)
- [ ] Write `tests/unit/test_enrichment.py` (P0-3)
- [ ] Write `tests/unit/test_base.py` (P1-1)
- [ ] Achieve 85%+ coverage on generators

### Phase 2: Refactor God Script #1 (Week 3-4)

**Week 3: Extract Classifiers & Analyzers**
- [ ] Create `src/classifiers/` module
- [ ] Extract `ContentClassifier` → `src/classifiers/content_classifier.py`
- [ ] Extract entity detection → `src/classifiers/entity_detector.py`
- [ ] Create `src/analyzers/` module
- [ ] Extract `ImageMetadataParser` → `src/analyzers/image_metadata.py`
- [ ] Extract `ImageContentAnalyzer` → `src/analyzers/image_content.py`
- [ ] Write unit tests for extracted modules

**Week 4: Extract Organizer & Pipeline**
- [ ] Create `src/organizers/` module
- [ ] Create `src/organizers/base_organizer.py` (abstract base)
- [ ] Refactor `ContentBasedFileOrganizer` → `src/organizers/content_organizer.py`
- [ ] Create `src/pipeline/` module
- [ ] Extract workflow → `src/pipeline/workflow.py`
- [ ] Update `scripts/file_organizer_content_based.py` to thin wrapper
- [ ] Write integration tests for organizer

### Phase 3: Additional Tests (Week 5-6)

**Week 5: Validator & Migration Tests**
- [ ] Enhance `tests/unit/test_validator.py` (P1-2)
- [ ] Write `tests/integration/test_storage_migration.py` (P1-4)
- [ ] Write `tests/unit/test_cost_calculator.py` (P1-5)
- [ ] Achieve 75%+ overall coverage

**Week 6: CLI & E2E Tests**
- [ ] Write `tests/integration/test_cli.py` (P2-1)
- [ ] Write `tests/e2e/test_content_organizer.py`
- [ ] Write `tests/unit/test_health_check.py` (P2-2)
- [ ] Achieve 80%+ overall coverage

### Phase 4: Refactor Remaining Scripts (Week 7-8)

**Week 7: Base Organizers**
- [ ] Extract category config from `file_organizer.py`
- [ ] Create `src/organizers/category_config.py`
- [ ] Create `src/organizers/mime_classifier.py`
- [ ] Create `src/organizers/base_organizer.py`
- [ ] Move `FileOrganizerByName` → `src/organizers/name_organizer.py`

**Week 8: Polish & Documentation**
- [ ] Update CLI to use refactored modules
- [ ] Update all docstrings
- [ ] Generate API documentation
- [ ] Update CLAUDE.md with new architecture
- [ ] Final test coverage push (85%+ goal)

---

## Part 4: Success Metrics

### Test Coverage Metrics

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| Overall Coverage | 0% (untested) | 85% | `pytest --cov` |
| Storage Layer | 0% | 90% | Module-specific coverage |
| Core Generators | ~40% (partial) | 95% | Module-specific coverage |
| Critical Paths | 0% | 100% | Integration tests |

### Code Quality Metrics

| Metric | Baseline | Target | Tool |
|--------|----------|--------|------|
| Average LOC/File | ~590 | <500 | `wc -l` |
| Max LOC/File | 2,691 | <600 | `wc -l` |
| Cyclomatic Complexity | Unknown | <10/function | `radon cc` |
| Code Duplication | Unknown | <5% | `pylint` |
| Type Coverage | ~0% | 80% | `mypy` |

### Architecture Metrics

| Metric | Baseline | Target |
|--------|----------|--------|
| Scripts > 500 LOC | 5 | 0 |
| Modules in `src/` | 17 | 30+ |
| Reusable Components | ~10 | 25+ |
| Dependency Coupling | High | Low (measured via imports) |

---

## Part 5: Risk Mitigation

### Risks & Mitigation Strategies

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Breaking changes during refactor | High | High | - Incremental changes<br>- Deprecation warnings<br>- Backward compatibility layer |
| Test coverage gaps | Medium | Medium | - Code review for test completeness<br>- Coverage thresholds in CI |
| Performance regression | Low | Medium | - Benchmark before/after<br>- Performance tests |
| Database migration failures | Low | High | - Test migrations thoroughly<br>- Backup strategy<br>- Rollback plan |

### Rollback Plan

1. **Git Tags:** Tag stable versions before major refactors
2. **Feature Flags:** Use flags for new modules (can disable if broken)
3. **Deprecation Period:** Keep old scripts for 1-2 releases
4. **Documentation:** Clear migration guides for users

---

## Part 6: Tools & CI/CD Integration

### Development Tools

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/unit/test_generators.py -v

# Run tests in parallel
pytest -n auto

# Check code quality
black src/ tests/
isort src/ tests/
flake8 src/ tests/
mypy src/

# Measure complexity
radon cc src/ -a
```

### CI/CD Pipeline (GitHub Actions)

**Add `.github/workflows/test.yml`:**
```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.8", "3.9", "3.10", "3.11", "3.12"]

    steps:
    - uses: actions/checkout@v3
    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}

    - name: Install system dependencies
      run: |
        sudo apt-get update
        sudo apt-get install -y tesseract-ocr poppler-utils

    - name: Install Python dependencies
      run: |
        pip install -e ".[all,dev]"

    - name: Run tests with coverage
      run: |
        pytest --cov=src --cov-report=xml --cov-report=term

    - name: Upload coverage to Codecov
      uses: codecov/codecov-action@v3

    - name: Check code quality
      run: |
        black --check src/ tests/
        flake8 src/ tests/
        mypy src/
```

### Pre-commit Hooks

**Add `.pre-commit-config.yaml`:**
```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.7.0
    hooks:
      - id: black
        language_version: python3

  - repo: https://github.com/pycqa/isort
    rev: 5.12.0
    hooks:
      - id: isort

  - repo: https://github.com/pycqa/flake8
    rev: 6.1.0
    hooks:
      - id: flake8

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.5.0
    hooks:
      - id: mypy
        additional_dependencies: [types-all]

  - repo: local
    hooks:
      - id: pytest
        name: pytest
        entry: pytest
        language: system
        pass_filenames: false
        always_run: true
```

---

## Part 7: Documentation Updates

### Files to Update

1. **CLAUDE.md** - Update architecture section with new module structure
2. **README.md** - Add testing section, coverage badges
3. **docs/ARCHITECTURE.md** - NEW: Detailed architecture documentation
4. **docs/TESTING.md** - NEW: Testing guide for contributors
5. **docs/CONTRIBUTING.md** - NEW: Contribution guidelines

### API Documentation

**Use `pdoc3` for auto-generated docs:**
```bash
pip install pdoc3
pdoc --html --output-dir docs/api src/
```

---

## Part 8: Next Steps

### Immediate Actions (This Week)

1. **Review & Approve Plan** - Get stakeholder sign-off
2. **Setup Test Infrastructure** - Install pytest, create fixtures
3. **Create First Test** - `tests/integration/test_storage_graph.py`
4. **Setup CI/CD** - Add GitHub Actions workflow

### Month 1 Goals

- ✅ 75% test coverage on critical modules
- ✅ Refactor `file_organizer_content_based.py` into modules
- ✅ All storage layer tests passing
- ✅ CI/CD pipeline operational

### Month 2 Goals

- ✅ 85% overall test coverage
- ✅ All "god scripts" refactored
- ✅ API documentation published
- ✅ Performance benchmarks established

### Month 3 Goals

- ✅ 90% test coverage
- ✅ Zero scripts > 500 LOC
- ✅ Full type coverage with mypy
- ✅ Contributor documentation complete

---

## Appendix A: Test Fixtures

### Sample Test Fixtures to Create

**`tests/fixtures/images/test_photo.jpg`**
- Real photo with EXIF data
- GPS coordinates
- Known timestamp

**`tests/fixtures/documents/test_invoice.pdf`**
- PDF with text "INVOICE"
- Company name
- Date and amount

**`tests/fixtures/sample_metadata.json`**
```json
{
  "@context": "https://schema.org",
  "@type": "DigitalDocument",
  "name": "Test Document",
  "encodingFormat": "application/pdf",
  "dateCreated": "2024-01-15T10:00:00Z"
}
```

---

## Appendix B: Complexity Analysis

### Most Complex Functions (Candidates for Refactoring)

**Run complexity analysis:**
```bash
pip install radon
radon cc src/ scripts/ -s -a --total-average
```

**Expected High-Complexity Functions:**
- `ContentBasedFileOrganizer.organize_file()` - Main organization logic
- `ContentClassifier.classify_content()` - Multi-pattern matching
- `ImageContentAnalyzer.analyze_image_content()` - CLIP + face detection
- `GraphStore.add_file()` - Complex database operations

**Refactoring Strategy:**
- Extract helper functions
- Use early returns to reduce nesting
- Break into smaller methods
- Apply strategy pattern for variants

---

## Appendix C: Migration Guide (For Future Reference)

### For Script Users

**Old (Deprecated):**
```bash
python scripts/file_organizer_content_based.py --sources ~/Downloads
```

**New (Recommended):**
```bash
organize-files content --source ~/Downloads
```

### For Developers

**Old Import:**
```python
from scripts.file_organizer_content_based import ContentBasedFileOrganizer
```

**New Import:**
```python
from src.organizers.content_organizer import ContentBasedFileOrganizer
```

---

**Document Version:** 1.0
**Last Updated:** 2025-12-10
**Next Review:** 2025-12-24 (after Phase 1 completion)
