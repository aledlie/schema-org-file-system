# Schema.org File Organization System

A comprehensive, production-ready Python system for generating, validating, and managing Schema.org structured data for intelligent file organization applications.

## Quick Links

- [Full Documentation](docs/README.md)
- [Best Practices](docs/BEST_PRACTICES.md)
- [Examples](examples/example_usage.py)
- [Tests](tests/)

## Overview

This system enables you to add rich, semantic metadata to any file type using Schema.org vocabulary. Perfect for:

- Intelligent file organization systems
- Digital asset management (DAM)
- Content management systems (CMS)
- Search and discovery platforms
- AI/ML training pipelines
- SEO-optimized file repositories

## Features

- **7 Specialized Generators** - Document, Image, Video, Audio, Code, Dataset, Archive
- **Automatic Validation** - Built-in Schema.org compliance checking
- **Multiple Output Formats** - JSON-LD, Microdata, RDFa
- **Metadata Enrichment** - Extract from EXIF, NLP, document properties
- **No External Dependencies** - Uses Python standard library only
- **Production Ready** - Comprehensive tests, validation, error handling

## Quick Start

### Installation

```bash
# Clone or download the system
cd schema-org-file-system

# No installation required - uses Python standard library
```

### Basic Usage

```python
import sys
sys.path.insert(0, '/path/to/schema-org-file-system/src')

from generators import DocumentGenerator
from validator import SchemaValidator
from datetime import datetime

# Create a document schema
doc = DocumentGenerator()
doc.set_basic_info(
    name="User Guide",
    description="Complete application user guide"
)

doc.set_file_info(
    encoding_format="application/pdf",
    url="https://example.com/guide.pdf",
    content_size=2048000
)

doc.add_person("author", "Jane Smith", email="jane@example.com")
doc.set_dates(created=datetime.now())

# Output JSON-LD
print(doc.to_json_ld())

# Validate
validator = SchemaValidator()
report = validator.validate(doc.to_dict())
print("Valid:", report.is_valid())
```

## Supported File Types

| Type | Schema.org Types | Features |
|------|-----------------|----------|
| **Documents** | DigitalDocument, Article, ScholarlyArticle | Author info, citations, pagination |
| **Images** | ImageObject, Photograph | EXIF data, dimensions, geolocation |
| **Videos** | VideoObject, MovieClip | Duration, resolution, statistics |
| **Audio** | AudioObject, MusicRecording, PodcastEpisode | Artist info, album, duration |
| **Code** | SoftwareSourceCode | Language, dependencies, repository |
| **Datasets** | Dataset | Variables, distributions, coverage |
| **Archives** | DigitalDocument (Archive) | Contents, compression |

## Project Structure

```
schema-org-file-system/
├── src/
│   ├── __init__.py          # Package initialization
│   ├── base.py              # Base classes and abstractions
│   ├── generators.py        # Specialized generators
│   ├── validator.py         # Validation system
│   ├── integration.py       # Output formats and registry
│   └── enrichment.py        # Metadata enrichment
├── tests/
│   ├── test_generators.py  # Generator tests
│   └── test_validator.py   # Validator tests
├── examples/
│   └── example_usage.py    # Comprehensive examples
├── docs/
│   ├── README.md           # Full documentation
│   └── BEST_PRACTICES.md   # Best practices guide
└── requirements.txt        # Optional dependencies
```

## Examples

### Create Image Schema with EXIF

```python
from generators import ImageGenerator

img = ImageGenerator("Photograph")
img.set_basic_info(
    name="Sunset Beach",
    content_url="https://example.com/sunset.jpg",
    encoding_format="image/jpeg"
)

img.set_dimensions(4032, 3024)

exif = {
    "Make": "Canon",
    "Model": "EOS R5",
    "GPSLatitude": 34.0522,
    "GPSLongitude": -118.2437
}
img.set_exif_data(exif)

print(img.to_json_ld())
```

### Create Source Code Schema

```python
from generators import CodeGenerator

code = CodeGenerator()
code.set_basic_info(
    name="app.py",
    programming_language="Python",
    description="Main application file"
)

code.set_repository_info(
    repository_url="https://github.com/user/repo",
    branch="main"
)

code.add_dependency("flask", "2.3.0")
code.add_dependency("sqlalchemy", "2.0.0")

print(code.to_json_ld())
```

### Validate and Export

```python
from validator import SchemaValidator
from integration import SchemaIntegration, OutputFormat

# Validate
validator = SchemaValidator()
report = validator.validate(code.to_dict())

if report.is_valid():
    # Export in multiple formats
    integration = SchemaIntegration()
    integration.add_schema(code)

    # JSON-LD
    json_ld = integration.to_json_ld()

    # Microdata HTML
    microdata = integration.to_microdata(code.to_dict())

    # RDFa HTML
    rdfa = integration.to_rdfa(code.to_dict())
```

## Running Tests

```bash
# Run generator tests
python tests/test_generators.py

# Run validator tests
python tests/test_validator.py

# Run examples
python examples/example_usage.py
```

## Documentation

- **[Full Documentation](docs/README.md)** - Complete API reference and usage guide
- **[Best Practices](docs/BEST_PRACTICES.md)** - Guidelines for optimal Schema.org implementation
- **[Examples](examples/example_usage.py)** - 11 comprehensive examples covering all features

## Key Components

### Generators (`src/generators.py`)

Specialized generators for each file type with type-specific methods:

- `DocumentGenerator` - PDFs, Word docs, articles
- `ImageGenerator` - Images with EXIF support
- `VideoGenerator` - Videos with media metadata
- `AudioGenerator` - Audio, music, podcasts
- `CodeGenerator` - Source code with dependencies
- `DatasetGenerator` - Data files with variables
- `ArchiveGenerator` - ZIP/TAR archives

### Validator (`src/validator.py`)

Comprehensive validation system:

- Schema.org specification compliance
- Required property checking
- Data type and format validation
- Google Rich Results compatibility
- Detailed validation reports

### Integration (`src/integration.py`)

Multiple output formats and management:

- JSON-LD (primary format)
- Microdata HTML
- RDFa HTML
- Schema registry and search
- Bulk export

### Enrichment (`src/enrichment.py`)

Metadata extraction and enrichment:

- File system metadata
- EXIF data extraction
- Document properties mapping
- NLP results integration
- Audio/video metadata
- Code analysis integration

## Best Practices

1. **Use specific Schema.org types** - Choose the most specific type available
2. **Include required properties** - Always validate before storing
3. **Add recommended properties** - Improve quality and rich results
4. **Use absolute URLs** - Never use relative paths
5. **Follow ISO standards** - Use ISO 8601 for dates and durations
6. **Validate early** - Catch errors before production
7. **Monitor quality** - Track validation rates over time

See [BEST_PRACTICES.md](docs/BEST_PRACTICES.md) for detailed guidelines.

## Requirements

- **Python 3.8+** (3.9+ recommended)
- **No external dependencies** (uses standard library only)

Optional dependencies for enhanced functionality:
- `Pillow` - EXIF extraction
- `spacy` - NLP enrichment
- `flask` - REST API
- `watchdog` - File watching

## Performance

- **Lightweight** - Minimal memory footprint
- **Fast** - Efficient schema generation
- **Scalable** - Batch processing support
- **Cacheable** - Schema caching patterns included

## Use Cases

### File Organization System

```python
def organize_file(file_path: str) -> Dict:
    """Organize file with Schema.org metadata."""

    enricher = MetadataEnricher()
    file_meta = enricher.enrich_from_file_stats(file_path)

    # Determine type and generate schema
    mime_type = enricher.detect_mime_type(file_path)

    if mime_type == 'application/pdf':
        generator = DocumentGenerator()
    elif mime_type.startswith('image/'):
        generator = ImageGenerator()
    # ... etc

    # Apply metadata
    for key, value in file_meta.items():
        generator.set_property(key, value)

    return {
        'schema': generator.to_dict(),
        'json_ld': generator.to_json_ld()
    }
```

### Search Integration

```python
from integration import SchemaRegistry

registry = SchemaRegistry()

# Register all file schemas
for file in files:
    schema = generate_schema(file)
    registry.register(file.id, schema)

# Search
results = registry.search("machine learning")

# Get by type
images = registry.get_by_type("ImageObject")
```

### REST API

```python
from flask import Flask, jsonify
from integration import SchemaIntegration

app = Flask(__name__)

@app.route('/api/files/<file_id>/schema')
def get_schema(file_id):
    schema = repository.get(file_id)
    return jsonify(schema)
```

## Validation

All schemas can be validated using:

1. **Internal Validator** - Built-in Schema.org compliance checking
2. **Schema.org Validator** - https://validator.schema.org
3. **Google Rich Results Test** - https://search.google.com/test/rich-results

```python
# Internal validation
validator = SchemaValidator()
report = validator.validate(schema)

if report.is_valid():
    print("Schema is valid!")
    print(f"Completion: {generator.get_completion_score():.1%}")
else:
    report.print_summary()
```

## License

This Schema.org File Organization System is provided as-is for use in intelligent file organization applications.

## Support

For detailed documentation, see:
- [Full Documentation](docs/README.md)
- [Best Practices Guide](docs/BEST_PRACTICES.md)
- [API Reference](docs/README.md#api-reference)

## Contributing

To extend the system:

1. Create new generator by extending `SchemaOrgBase`
2. Implement required methods: `get_required_properties()`, `get_recommended_properties()`
3. Add specialized methods for your schema type
4. Create tests in `tests/`
5. Update documentation

Example:

```python
from base import SchemaOrgBase

class CustomGenerator(SchemaOrgBase):
    def __init__(self):
        super().__init__("CustomType")

    def get_required_properties(self) -> List[str]:
        return ["name"]

    def get_recommended_properties(self) -> List[str]:
        return ["description", "author"]

    # Add custom methods
    def set_custom_property(self, value: str):
        self.set_property("customProperty", value)
        return self
```

## Changelog

### Version 1.0.0 (2024)

- Initial release
- 7 specialized file type generators
- Comprehensive validation system
- Multiple output formats (JSON-LD, Microdata, RDFa)
- Metadata enrichment utilities
- Registry and search capabilities
- Complete test suite
- Full documentation and examples

---

**Built for intelligent file organization applications**

For questions, issues, or contributions, please refer to the documentation or contact the development team.
