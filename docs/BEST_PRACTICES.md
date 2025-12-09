# Best Practices for Schema.org in File Management

This guide provides best practices for using Schema.org structured data in file organization and management systems.

## Table of Contents

1. [Schema Selection](#schema-selection)
2. [Property Guidelines](#property-guidelines)
3. [Validation Strategy](#validation-strategy)
4. [Performance Optimization](#performance-optimization)
5. [Integration Patterns](#integration-patterns)
6. [Common Pitfalls](#common-pitfalls)

---

## Schema Selection

### Choose the Most Specific Type

Always use the most specific Schema.org type available:

**Good:**
```python
# Use specific type for research paper
doc = DocumentGenerator("ScholarlyArticle")
```

**Bad:**
```python
# Using generic type
doc = DocumentGenerator("CreativeWork")
```

### Type Hierarchy

Understand the Schema.org type hierarchy:

```
Thing
└── CreativeWork
    ├── Article
    │   ├── NewsArticle
    │   ├── BlogPosting
    │   └── ScholarlyArticle
    ├── DigitalDocument
    │   └── (Your files)
    ├── MediaObject
    │   ├── ImageObject
    │   │   └── Photograph
    │   ├── VideoObject
    │   └── AudioObject
    │       ├── MusicRecording
    │       └── PodcastEpisode
    ├── SoftwareSourceCode
    └── Dataset
```

### File Type Mapping

| File Extension | Primary Type | Alternative Types |
|---------------|-------------|-------------------|
| .pdf | DigitalDocument | Article, Report, ScholarlyArticle |
| .jpg, .png | ImageObject | Photograph |
| .mp4, .mov | VideoObject | MovieClip |
| .mp3, .wav | AudioObject | MusicRecording, PodcastEpisode |
| .py, .js | SoftwareSourceCode | - |
| .csv, .json | Dataset | - |
| .zip, .tar | DigitalDocument | Archive |

---

## Property Guidelines

### Required vs Recommended

Always include required properties, aim for recommended properties:

```python
# Required properties (will fail validation)
doc.set_property("name", "Document Title")
doc.set_property("encodingFormat", "application/pdf")

# Recommended properties (improves quality)
doc.add_person("author", "Jane Smith")
doc.set_dates(created=datetime.now())
doc.add_keywords(["topic1", "topic2"])
```

### URL Best Practices

**Always use absolute URLs:**

```python
# Good - Absolute URL
doc.set_property("url", "https://example.com/file.pdf")

# Bad - Relative URL
doc.set_property("url", "/files/file.pdf")

# Good - File URL for local files
doc.set_property("url", "file:///path/to/file.pdf")
```

### Date Formats

Use ISO 8601 format for all dates:

```python
# Good - ISO 8601
doc.set_dates(
    created=datetime(2024, 1, 15, 10, 30, 0),
    published=datetime(2024, 1, 20)
)

# Result: "2024-01-15T10:30:00" and "2024-01-20"
```

### Duration Format

Use ISO 8601 duration format:

```python
# Good examples
video.set_property("duration", "PT5M30S")  # 5 minutes 30 seconds
video.set_property("duration", "PT1H30M")  # 1 hour 30 minutes
audio.set_property("duration", "PT3M45S")  # 3 minutes 45 seconds

# Helper method
def seconds_to_iso_duration(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"PT{hours}H{minutes}M{secs}S" if hours else f"PT{minutes}M{secs}S"
```

### Keywords and Tags

Be specific and use consistent terminology:

```python
# Good - Specific, consistent keywords
doc.add_keywords([
    "machine learning",
    "neural networks",
    "artificial intelligence"
])

# Bad - Too generic, inconsistent
doc.add_keywords([
    "ML",  # Use full term
    "AI stuff",  # Too vague
    "Neural Networks",  # Inconsistent capitalization
])
```

---

## Validation Strategy

### Validate Early and Often

```python
def create_and_validate_schema(generator, data):
    """Pattern: Create, validate, handle errors."""

    # Create schema
    schema = generator.create_from_data(data)

    # Validate immediately
    validator = SchemaValidator()
    report = validator.validate(schema.to_dict())

    # Handle validation results
    if not report.is_valid():
        # Log errors
        for error in report.get_messages_by_level(ValidationLevel.ERROR):
            logger.error(f"Schema validation error: {error.message}")

        # Decide: fail fast or continue with warnings
        raise ValueError("Invalid schema")

    # Check completion
    if schema.get_completion_score() < 0.7:
        logger.warning("Schema completion score below 70%")

    return schema
```

### Batch Validation

For processing multiple files:

```python
def validate_file_collection(schemas: List[Dict]) -> Dict:
    """Validate multiple schemas efficiently."""

    validator = SchemaValidator()
    reports = validator.validate_batch(schemas)

    # Generate summary
    summary = validator.generate_summary_report(reports)

    # Log results
    logger.info(f"Validated {summary['total_schemas']} schemas")
    logger.info(f"Success rate: {summary['success_rate']:.1f}%")

    # Handle failures
    if summary['invalid_schemas'] > 0:
        logger.warning(f"{summary['invalid_schemas']} schemas failed validation")

        # Collect failed schemas for review
        failed = [
            (i, report) for i, report in enumerate(reports)
            if not report.is_valid()
        ]

        return {
            'summary': summary,
            'failed': failed
        }

    return {'summary': summary}
```

### Pre-Production Validation

Before deploying schemas:

```python
def pre_production_validation(schema: Dict) -> bool:
    """Comprehensive pre-production checks."""

    validator = SchemaValidator()
    report = validator.validate(schema)

    # Check 1: No errors
    if report.has_errors():
        return False

    # Check 2: Required properties present
    required_props = ["name", "@type", "@context"]
    if not all(prop in schema for prop in required_props):
        return False

    # Check 3: URLs are absolute
    url_props = ["url", "contentUrl", "thumbnailUrl"]
    for prop in url_props:
        if prop in schema:
            if not schema[prop].startswith(('http://', 'https://', 'file://')):
                return False

    # Check 4: Completion score threshold
    # (implementation depends on your SchemaOrgBase instance)

    return True
```

---

## Performance Optimization

### Lazy Schema Generation

Generate schemas on-demand:

```python
class FileMetadata:
    """Lazy schema generation pattern."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._schema = None
        self._json_ld = None

    @property
    def schema(self) -> Dict:
        """Generate schema only when accessed."""
        if self._schema is None:
            self._schema = self._generate_schema()
        return self._schema

    @property
    def json_ld(self) -> str:
        """Generate JSON-LD only when accessed."""
        if self._json_ld is None:
            self._json_ld = json.dumps(self.schema, indent=2)
        return self._json_ld

    def _generate_schema(self) -> Dict:
        # Schema generation logic
        pass
```

### Caching Strategy

Cache generated schemas for frequently accessed files:

```python
from functools import lru_cache
import hashlib

class SchemaCache:
    """Cache schemas based on file content hash."""

    def __init__(self, maxsize=1000):
        self.cache = {}
        self.maxsize = maxsize

    def get_file_hash(self, file_path: str) -> str:
        """Calculate file hash for cache key."""
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hasher.update(chunk)
        return hasher.hexdigest()

    def get_schema(self, file_path: str) -> Optional[Dict]:
        """Get cached schema."""
        file_hash = self.get_file_hash(file_path)
        return self.cache.get(file_hash)

    def set_schema(self, file_path: str, schema: Dict):
        """Cache schema."""
        if len(self.cache) >= self.maxsize:
            # Remove oldest entry
            self.cache.pop(next(iter(self.cache)))

        file_hash = self.get_file_hash(file_path)
        self.cache[file_hash] = schema
```

### Batch Processing

Process multiple files efficiently:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def process_files_batch(file_paths: List[str], max_workers: int = 4) -> List[Dict]:
    """Process multiple files in parallel."""

    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_file = {
            executor.submit(generate_schema, fp): fp
            for fp in file_paths
        }

        # Collect results as they complete
        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                schema = future.result()
                results.append({
                    'file': file_path,
                    'schema': schema,
                    'status': 'success'
                })
            except Exception as e:
                results.append({
                    'file': file_path,
                    'error': str(e),
                    'status': 'failed'
                })

    return results
```

---

## Integration Patterns

### Repository Pattern

Manage schemas with a repository:

```python
class SchemaRepository:
    """Repository pattern for schema management."""

    def __init__(self, storage_backend):
        self.storage = storage_backend
        self.validator = SchemaValidator()

    def save(self, schema_id: str, schema: Dict) -> bool:
        """Save schema after validation."""
        report = self.validator.validate(schema)
        if not report.is_valid():
            raise ValueError("Invalid schema")

        return self.storage.save(schema_id, schema)

    def get(self, schema_id: str) -> Optional[Dict]:
        """Retrieve schema."""
        return self.storage.get(schema_id)

    def find_by_type(self, schema_type: str) -> List[Dict]:
        """Find all schemas of given type."""
        return self.storage.find_by_type(schema_type)

    def update(self, schema_id: str, updates: Dict) -> bool:
        """Update existing schema."""
        schema = self.get(schema_id)
        if not schema:
            return False

        schema.update(updates)

        # Re-validate
        report = self.validator.validate(schema)
        if not report.is_valid():
            raise ValueError("Updated schema is invalid")

        return self.storage.save(schema_id, schema)
```

### Event-Driven Updates

Update schemas when files change:

```python
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class SchemaUpdateHandler(FileSystemEventHandler):
    """Update schemas when files change."""

    def __init__(self, schema_repository):
        self.repository = schema_repository
        self.enricher = MetadataEnricher()

    def on_modified(self, event):
        """Handle file modification."""
        if not event.is_directory:
            self._update_schema(event.src_path)

    def _update_schema(self, file_path: str):
        """Regenerate schema for modified file."""
        # Extract new metadata
        metadata = self.enricher.enrich_from_file_stats(file_path)

        # Get existing schema
        schema_id = self._get_schema_id(file_path)
        schema = self.repository.get(schema_id)

        if schema:
            # Update modification date
            schema['dateModified'] = datetime.now().isoformat()

            # Update other metadata
            if 'contentSize' in metadata:
                schema['contentSize'] = metadata['contentSize']

            # Save updated schema
            self.repository.update(schema_id, schema)
```

### API Response Pattern

Provide Schema.org data through APIs:

```python
from flask import Flask, jsonify, request

app = Flask(__name__)

@app.route('/api/files/<file_id>/schema', methods=['GET'])
def get_file_schema(file_id: str):
    """Return file schema in requested format."""

    # Get schema
    schema = repository.get(file_id)
    if not schema:
        return jsonify({'error': 'File not found'}), 404

    # Get format parameter
    format = request.args.get('format', 'json-ld')

    # Convert to requested format
    integration = SchemaIntegration()
    integration.add_schema(schema)

    if format == 'json-ld':
        return jsonify(schema)
    elif format == 'microdata':
        return integration.to_microdata(schema), 200, {'Content-Type': 'text/html'}
    elif format == 'rdfa':
        return integration.to_rdfa(schema), 200, {'Content-Type': 'text/html'}
    else:
        return jsonify({'error': 'Unsupported format'}), 400

@app.route('/api/files/<file_id>/schema', methods=['PUT'])
def update_file_schema(file_id: str):
    """Update file schema."""

    schema = request.json

    # Validate
    validator = SchemaValidator()
    report = validator.validate(schema)

    if not report.is_valid():
        return jsonify({
            'error': 'Invalid schema',
            'validation': report.to_dict()
        }), 400

    # Update
    success = repository.update(file_id, schema)

    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Update failed'}), 500
```

---

## Common Pitfalls

### Pitfall 1: Missing Required Properties

**Problem:**
```python
doc = DocumentGenerator()
doc.set_basic_info("My Document")
# Missing encodingFormat - will fail validation
```

**Solution:**
```python
doc = DocumentGenerator()
doc.set_basic_info("My Document")
doc.set_file_info(
    encoding_format="application/pdf",  # Always include
    url="https://example.com/doc.pdf"
)
```

### Pitfall 2: Relative URLs

**Problem:**
```python
img.set_property("contentUrl", "/images/photo.jpg")  # Relative URL
```

**Solution:**
```python
base_url = "https://example.com"
img.set_property("contentUrl", f"{base_url}/images/photo.jpg")
```

### Pitfall 3: Inconsistent Data

**Problem:**
```python
# File says it's 100KB but schema says 50KB
file_size = os.path.getsize(file_path)  # 102400
doc.set_property("contentSize", "50000B")  # Wrong!
```

**Solution:**
```python
# Always use actual file data
file_size = os.path.getsize(file_path)
doc.set_property("contentSize", f"{file_size}B")
```

### Pitfall 4: Over-Nesting

**Problem:**
```python
# Too many nested levels
doc.add_person("author", ...)
doc.author.add_person("mentor", ...)
doc.author.mentor.add_organization("employer", ...)  # Too deep!
```

**Solution:**
```python
# Keep it simple - 1-2 levels max
doc.add_person("author", "Jane Smith", affiliation="University")
```

### Pitfall 5: Not Validating Before Storage

**Problem:**
```python
# Save without validation
schema = doc.to_dict()
database.save(schema)  # Might be invalid!
```

**Solution:**
```python
# Always validate first
schema = doc.to_dict()
validator = SchemaValidator()
report = validator.validate(schema)

if report.is_valid():
    database.save(schema)
else:
    handle_validation_errors(report)
```

### Pitfall 6: Ignoring Recommended Properties

**Problem:**
```python
# Minimal schema - low quality
doc = DocumentGenerator()
doc.set_property("name", "Document")
doc.set_property("encodingFormat", "application/pdf")
# Nothing else!
```

**Solution:**
```python
# Include recommended properties
doc = DocumentGenerator()
doc.set_property("name", "Document")
doc.set_property("encodingFormat", "application/pdf")
doc.add_person("author", "Author Name")  # Recommended
doc.set_dates(created=datetime.now())  # Recommended
doc.add_keywords(["topic1", "topic2"])  # Recommended
doc.set_property("description", "Clear description")  # Recommended
```

### Pitfall 7: Wrong Date Formats

**Problem:**
```python
# Non-standard date format
doc.set_property("dateCreated", "01/15/2024")  # US format
doc.set_property("dateCreated", "15-01-2024")  # EU format
```

**Solution:**
```python
# Use ISO 8601
from datetime import datetime

doc.set_dates(created=datetime(2024, 1, 15))
# Results in: "2024-01-15T00:00:00"
```

---

## Monitoring and Maintenance

### Quality Metrics

Track schema quality over time:

```python
class SchemaQualityMonitor:
    """Monitor schema quality metrics."""

    def __init__(self):
        self.metrics = {
            'total_schemas': 0,
            'valid_schemas': 0,
            'avg_completion_score': 0.0,
            'validation_errors': []
        }

    def record_schema(self, schema: Dict, completion_score: float):
        """Record schema metrics."""
        self.metrics['total_schemas'] += 1

        validator = SchemaValidator()
        report = validator.validate(schema)

        if report.is_valid():
            self.metrics['valid_schemas'] += 1

        # Update average completion
        current_avg = self.metrics['avg_completion_score']
        total = self.metrics['total_schemas']
        self.metrics['avg_completion_score'] = (
            (current_avg * (total - 1) + completion_score) / total
        )

        # Record errors
        if report.has_errors():
            self.metrics['validation_errors'].extend([
                error.message for error in
                report.get_messages_by_level(ValidationLevel.ERROR)
            ])

    def get_report(self) -> Dict:
        """Get quality report."""
        return {
            'total': self.metrics['total_schemas'],
            'valid': self.metrics['valid_schemas'],
            'validity_rate': (
                self.metrics['valid_schemas'] / self.metrics['total_schemas']
                if self.metrics['total_schemas'] > 0 else 0
            ),
            'avg_completion': self.metrics['avg_completion_score'],
            'common_errors': self._get_common_errors()
        }

    def _get_common_errors(self) -> List[Tuple[str, int]]:
        """Get most common errors."""
        from collections import Counter
        errors = Counter(self.metrics['validation_errors'])
        return errors.most_common(5)
```

---

## Summary

Follow these best practices for optimal Schema.org implementation:

1. **Use specific types** - Choose the most specific Schema.org type
2. **Include all required properties** - Validate before storing
3. **Add recommended properties** - Improve schema quality and rich results
4. **Use absolute URLs** - Always use fully qualified URLs
5. **Follow ISO standards** - Use ISO 8601 for dates and durations
6. **Validate early and often** - Catch errors before production
7. **Cache when possible** - Optimize performance for frequently accessed schemas
8. **Monitor quality** - Track validation rates and completion scores
9. **Document extensions** - Clearly document any custom properties
10. **Test thoroughly** - Include comprehensive test coverage

Following these practices will ensure high-quality, maintainable, and search engine-friendly structured data for your file organization system.
