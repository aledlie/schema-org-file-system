"""
Comprehensive examples for Schema.org file organization system.

Demonstrates all major features and use cases.

Schemas are built with the generators' typed-container API: the inherited
``set_property(name, value, PropertyType)`` for scalar fields and direct
``generator.data[...]`` assignment for nested objects/lists, plus the
``add_person``/``add_organization``/``add_keywords``/``set_dates`` helpers.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from datetime import datetime  # noqa: E402
from generators import (  # noqa: E402
    DocumentGenerator,
    ImageGenerator,
    VideoGenerator,
    AudioGenerator,
    CodeGenerator,
    DatasetGenerator,
    ArchiveGenerator
)
from base import PropertyType  # noqa: E402
from validator import SchemaValidator, ValidationLevel  # noqa: E402
from integration import SchemaIntegration, OutputFormat, SchemaRegistry  # noqa: E402
from enrichment import MetadataEnricher  # noqa: E402


def example_1_basic_document():
    """Example 1: Create a basic document schema."""
    print("\n" + "="*60)
    print("Example 1: Basic Document Schema")
    print("="*60)

    # Create document generator
    doc = DocumentGenerator()

    # Set basic information
    doc.set_property("name", "User Guide", PropertyType.TEXT)
    doc.set_property(
        "description",
        "Comprehensive user guide for the application",
        PropertyType.TEXT,
    )
    doc.set_property(
        "abstract",
        "This guide covers installation, configuration, and usage",
        PropertyType.TEXT,
    )

    # Set file information
    doc.set_property("encodingFormat", "application/pdf", PropertyType.TEXT)
    doc.set_property("url", "https://example.com/docs/user-guide.pdf", PropertyType.URL)
    doc.set_property("contentSize", "2048000B", PropertyType.TEXT)
    doc.set_identifier("abc123def456", property_id="sha256")

    # Add author
    doc.add_person(
        "author",
        "Jane Smith",
        email="jane@example.com",
        affiliation="Example Corp"
    )

    # Set dates
    doc.set_dates(
        created=datetime(2024, 1, 1),
        modified=datetime(2024, 1, 15),
        published=datetime(2024, 1, 10)
    )

    # Add keywords
    doc.add_keywords(["documentation", "user guide", "tutorial"])

    # Set language and pagination
    doc.set_property("inLanguage", "en", PropertyType.TEXT)
    doc.set_property("numberOfPages", 45, PropertyType.INTEGER)

    # Output JSON-LD
    print("\nJSON-LD Output:")
    print(doc.to_json_ld())

    # Validate
    validator = SchemaValidator()
    report = validator.validate(doc.to_dict())
    print("\nValidation Result:", "VALID" if report.is_valid() else "INVALID")
    print(f"Completion Score: {doc.get_completion_score():.2%}")


def example_2_image_with_exif():
    """Example 2: Create image schema with EXIF data."""
    print("\n" + "="*60)
    print("Example 2: Image Schema with EXIF Data")
    print("="*60)

    # Create image generator
    img = ImageGenerator("Photograph")

    # Set basic info
    img.set_property("name", "Sunset Beach", PropertyType.TEXT)
    img.set_property("contentUrl", "https://example.com/photos/sunset.jpg", PropertyType.URL)
    img.set_property("encodingFormat", "image/jpeg", PropertyType.TEXT)
    img.set_property("description", "Beautiful sunset at the beach", PropertyType.TEXT)
    img.set_property("caption", "Golden hour at Pacific Coast", PropertyType.TEXT)

    # Set dimensions
    img.set_property("width", 4032, PropertyType.INTEGER)
    img.set_property("height", 3024, PropertyType.INTEGER)

    # Attach EXIF data as a nested object
    img.data["exifData"] = {
        "@type": "PropertyValue",
        "Make": "Canon",
        "Model": "EOS R5",
        "geo": {
            "@type": "GeoCoordinates",
            "latitude": 34.0522,
            "longitude": -118.2437,
        },
    }
    img.set_property("dateCreated", "2024-01-15T18:30:00", PropertyType.DATETIME)

    # Add creator
    img.add_person("creator", "John Photographer", url="https://example.com/photographers/john")

    # Add thumbnail (surviving helper)
    img.set_thumbnail("https://example.com/photos/sunset-thumb.jpg")

    print("\nJSON-LD Output:")
    print(img.to_json_ld())


def example_3_video_with_stats():
    """Example 3: Create video schema with interaction statistics."""
    print("\n" + "="*60)
    print("Example 3: Video Schema with Statistics")
    print("="*60)

    # Create video generator
    video = VideoGenerator()

    # Set basic info
    video.set_property("name", "Product Demo", PropertyType.TEXT)
    video.set_property("contentUrl", "https://example.com/videos/demo.mp4", PropertyType.URL)
    video.set_property("uploadDate", datetime(2024, 1, 10), PropertyType.DATETIME)
    video.set_property(
        "description",
        "Complete product demonstration and walkthrough",
        PropertyType.TEXT,
    )
    video.set_property(
        "thumbnailUrl", "https://example.com/videos/demo-thumb.jpg", PropertyType.URL
    )

    # Set media details
    video.set_property("duration", "PT15M30S", PropertyType.TEXT)  # 15 min 30 sec
    video.set_property("width", 1920, PropertyType.INTEGER)
    video.set_property("height", 1080, PropertyType.INTEGER)
    video.set_property("encodingFormat", "video/mp4", PropertyType.TEXT)
    video.set_property("bitrate", "5000kbps", PropertyType.TEXT)

    # Add creator
    video.add_person("creator", "Marketing Team")

    # Set interaction statistics (surviving helper)
    video.set_interaction_stats(
        view_count=50000,
        comment_count=342
    )

    print("\nJSON-LD Output:")
    print(video.to_json_ld())


def example_4_music_recording():
    """Example 4: Create music recording schema."""
    print("\n" + "="*60)
    print("Example 4: Music Recording Schema")
    print("="*60)

    # Create music recording generator
    music = AudioGenerator("MusicRecording")

    # Set basic info
    music.set_property("name", "Summer Vibes", PropertyType.TEXT)
    music.set_property("contentUrl", "https://example.com/music/summer-vibes.mp3", PropertyType.URL)
    music.set_property(
        "description", "Upbeat summer track with tropical influences", PropertyType.TEXT
    )
    music.set_property("duration", "PT3M45S", PropertyType.TEXT)

    # Set music info (nested album/artist objects)
    music.data["inAlbum"] = {"@type": "MusicAlbum", "name": "Summer Collection"}
    music.data["byArtist"] = {"@type": "MusicGroup", "name": "DJ Sunny"}
    music.set_property("genre", "Electronic Pop", PropertyType.TEXT)
    music.set_property("isrcCode", "USRC12345678", PropertyType.TEXT)

    # Set dates
    music.set_dates(published=datetime(2024, 6, 1))

    # Set language
    music.set_property("inLanguage", "en", PropertyType.TEXT)

    print("\nJSON-LD Output:")
    print(music.to_json_ld())


def example_5_source_code():
    """Example 5: Create source code schema."""
    print("\n" + "="*60)
    print("Example 5: Source Code Schema")
    print("="*60)

    # Create code generator
    code = CodeGenerator()

    # Set basic info
    code.set_property("name", "data_processor.py", PropertyType.TEXT)
    code.set_property("programmingLanguage", "Python", PropertyType.TEXT)
    code.set_property(
        "description", "Data processing utilities for file analysis", PropertyType.TEXT
    )

    # Set repository info
    code.set_property(
        "codeRepository", "https://github.com/example/file-organizer", PropertyType.URL
    )

    # Set runtime info
    code.set_property(
        "runtimePlatform",
        ["Python 3.9", "Python 3.10", "Python 3.11"],
        PropertyType.ARRAY,
    )
    code.set_property("targetProduct", "File Organizer System", PropertyType.TEXT)

    # Add dependencies (list of SoftwareApplication objects)
    code.data["dependencies"] = [
        {"@type": "SoftwareApplication", "name": "numpy"},
        {"@type": "SoftwareApplication", "name": "pandas"},
        {"@type": "SoftwareApplication", "name": "scikit-learn"},
    ]

    # Add author
    code.add_person("author", "Dev Team", email="dev@example.com")

    # Set dates
    code.set_dates(
        created=datetime(2023, 6, 1),
        modified=datetime(2024, 1, 15)
    )

    print("\nJSON-LD Output:")
    print(code.to_json_ld())


def example_6_dataset():
    """Example 6: Create dataset schema."""
    print("\n" + "="*60)
    print("Example 6: Dataset Schema")
    print("="*60)

    # Create dataset generator
    dataset = DatasetGenerator()

    # Set basic info
    dataset.set_property("name", "Global Temperature Data", PropertyType.TEXT)
    dataset.set_property(
        "description",
        "Historical temperature measurements from weather stations worldwide",
        PropertyType.TEXT,
    )
    dataset.set_property("url", "https://example.com/datasets/temperature", PropertyType.URL)

    # Add creator
    dataset.add_organization(
        "creator",
        "Global Weather Institute",
        url="https://example.com/gwi",
        logo="https://example.com/gwi/logo.png"
    )

    # Add distributions (list of DataDownload objects)
    dataset.data["distribution"] = [
        {
            "@type": "DataDownload",
            "contentUrl": "https://example.com/datasets/temperature.csv",
            "encodingFormat": "text/csv",
        },
        {
            "@type": "DataDownload",
            "contentUrl": "https://example.com/datasets/temperature.json",
            "encodingFormat": "application/json",
        },
    ]

    # Set coverage
    dataset.set_property("temporalCoverage", "2000-01-01/2023-12-31", PropertyType.TEXT)
    dataset.set_property("spatialCoverage", "Global", PropertyType.TEXT)

    # Add measured variables (list of PropertyValue objects)
    dataset.data["variableMeasured"] = [
        {"@type": "PropertyValue", "name": "temperature"},
        {"@type": "PropertyValue", "name": "humidity"},
        {"@type": "PropertyValue", "name": "pressure"},
    ]

    # Add keywords
    dataset.add_keywords(["climate", "temperature", "weather", "historical data"])

    # Set dates
    dataset.set_dates(published=datetime(2024, 1, 1))

    print("\nJSON-LD Output:")
    print(dataset.to_json_ld())


def example_7_archive_with_contents():
    """Example 7: Create archive schema with contained files."""
    print("\n" + "="*60)
    print("Example 7: Archive Schema with Contents")
    print("="*60)

    # Create archive generator
    archive = ArchiveGenerator()

    # Set basic info
    archive.set_property("name", "project-backup.zip", PropertyType.TEXT)
    archive.set_property("encodingFormat", "application/zip", PropertyType.TEXT)
    archive.set_property(
        "description",
        "Complete project backup including code, docs, and assets",
        PropertyType.TEXT,
    )
    archive.set_property("contentSize", "52428800B", PropertyType.TEXT)  # 50 MB

    # Set compression info
    archive.set_property("compressionMethod", "DEFLATE", PropertyType.TEXT)
    archive.set_property("compressionRatio", 0.65, PropertyType.NUMBER)

    # Create contained files
    readme = DocumentGenerator()
    readme.set_property("name", "README.md", PropertyType.TEXT)
    readme.set_property("encodingFormat", "text/markdown", PropertyType.TEXT)
    readme.set_property("url", "https://example.com/README.md", PropertyType.URL)

    source = CodeGenerator()
    source.set_property("name", "main.py", PropertyType.TEXT)
    source.set_property("programmingLanguage", "Python", PropertyType.TEXT)

    # Add contained files to archive (hasPart list)
    archive.data["hasPart"] = [readme.to_dict(), source.to_dict()]

    # Add creator
    archive.add_person("author", "Build System")

    # Set dates
    archive.set_dates(created=datetime(2024, 1, 1))

    print("\nJSON-LD Output:")
    print(archive.to_json_ld())


def example_8_metadata_enrichment():
    """Example 8: Use metadata enrichment."""
    print("\n" + "="*60)
    print("Example 8: Metadata Enrichment")
    print("="*60)

    # Create enricher
    enricher = MetadataEnricher()

    # Simulate file stats enrichment
    file_metadata = {
        'name': 'research-paper.pdf',
        'encodingFormat': 'application/pdf',
        'contentSize': 2048000
    }

    # Simulate document properties
    doc_props = {
        'title': 'Machine Learning Applications',
        'author': 'Dr. Alice Johnson',
        'subject': 'Artificial Intelligence',
        'keywords': 'machine learning, AI, neural networks',
        'created': datetime(2023, 6, 1),
        'modified': datetime(2024, 1, 10),
        'pages': 25
    }

    # Simulate NLP results
    nlp_results = {
        'language': 'en',
        'keywords': ['machine learning', 'deep learning', 'neural networks'],
        'topics': ['Artificial Intelligence', 'Data Science'],
        'entities': [
            {'type': 'ORG', 'text': 'Stanford University'},
            {'type': 'PERSON', 'text': 'Geoffrey Hinton'}
        ],
        'summary': 'This paper explores recent advances in machine learning applications.'
    }

    # Enrich metadata from different sources
    enriched_doc = enricher.enrich_from_document_properties(doc_props)
    enriched_nlp = enricher.enrich_from_nlp(nlp_results)

    # Merge all metadata
    merged = enricher.merge_metadata(file_metadata, enriched_doc, enriched_nlp)

    # Create document with enriched metadata
    doc = DocumentGenerator("ScholarlyArticle")
    for key, value in merged.items():
        try:
            # JSON-LD output needs serializable values; normalize datetimes.
            if isinstance(value, datetime):
                value = value.isoformat()
            doc.set_property(key, value)
        except Exception:
            pass

    print("\nEnriched JSON-LD Output:")
    print(doc.to_json_ld())


def example_9_multiple_formats():
    """Example 9: Export in multiple formats."""
    print("\n" + "="*60)
    print("Example 9: Multiple Output Formats")
    print("="*60)

    # Create a simple document
    doc = DocumentGenerator()
    doc.set_property("name", "Example Document", PropertyType.TEXT)
    doc.set_property("encodingFormat", "application/pdf", PropertyType.TEXT)
    doc.set_property("url", "https://example.com/doc.pdf", PropertyType.URL)

    # Create integration layer
    integration = SchemaIntegration()
    integration.add_schema(doc)

    # Export as JSON-LD
    print("\n--- JSON-LD Format ---")
    print(integration.to_json_ld())

    # Export as Microdata
    print("\n--- Microdata Format ---")
    print(integration.to_microdata(doc.to_dict()))

    # Export as RDFa
    print("\n--- RDFa Format ---")
    print(integration.to_rdfa(doc.to_dict()))

    # Create HTML page with embedded schema
    print("\n--- HTML Page with JSON-LD ---")
    html_page = integration.create_html_page(
        title="Example Document",
        content="<h1>Example Document</h1><p>Document content goes here.</p>",
        format=OutputFormat.JSON_LD
    )
    print(html_page[:500] + "...")


def example_10_registry_and_search():
    """Example 10: Use schema registry and search."""
    print("\n" + "="*60)
    print("Example 10: Schema Registry and Search")
    print("="*60)

    # Create registry
    registry = SchemaRegistry()

    # Create and register multiple schemas
    doc1 = DocumentGenerator()
    doc1.set_property("name", "Python Guide", PropertyType.TEXT)
    doc1.set_property("encodingFormat", "application/pdf", PropertyType.TEXT)
    doc1.set_property("url", "https://example.com/python.pdf", PropertyType.URL)

    doc2 = DocumentGenerator()
    doc2.set_property("name", "JavaScript Tutorial", PropertyType.TEXT)
    doc2.set_property("encodingFormat", "application/pdf", PropertyType.TEXT)
    doc2.set_property("url", "https://example.com/js.pdf", PropertyType.URL)

    img1 = ImageGenerator()
    img1.set_property("name", "Logo", PropertyType.TEXT)
    img1.set_property("contentUrl", "https://example.com/logo.png", PropertyType.URL)
    img1.set_property("encodingFormat", "image/png", PropertyType.TEXT)

    # Register schemas
    registry.register("doc-001", doc1.to_dict(), {"category": "programming"})
    registry.register("doc-002", doc2.to_dict(), {"category": "programming"})
    registry.register("img-001", img1.to_dict(), {"category": "branding"})

    # Get statistics
    stats = registry.get_statistics()
    print("\nRegistry Statistics:")
    print(f"Total schemas: {stats['total_schemas']}")
    print(f"Types: {stats['types']}")

    # Search
    print("\nSearch for 'Python':")
    results = registry.search("Python")
    print(f"Found {len(results)} results")

    # Get by type
    print("\nAll Documents:")
    docs = registry.get_by_type("DigitalDocument")
    print(f"Found {len(docs)} documents")

    # List all IDs
    print("\nAll Schema IDs:")
    print(registry.list_all())


def example_11_validation_workflow():
    """Example 11: Complete validation workflow."""
    print("\n" + "="*60)
    print("Example 11: Validation Workflow")
    print("="*60)

    # Create validator
    validator = SchemaValidator()

    # Create several schemas with varying quality
    schemas = []

    # Good schema
    good_doc = DocumentGenerator()
    good_doc.set_property("name", "Complete Document", PropertyType.TEXT)
    good_doc.set_property("description", "Full description", PropertyType.TEXT)
    good_doc.set_property("encodingFormat", "application/pdf", PropertyType.TEXT)
    good_doc.set_property("url", "https://example.com/good.pdf", PropertyType.URL)
    good_doc.add_person("author", "John Doe")
    good_doc.set_dates(created=datetime(2024, 1, 1))
    schemas.append(good_doc.to_dict())

    # Incomplete schema
    incomplete_doc = DocumentGenerator()
    incomplete_doc.set_property("name", "Incomplete Document", PropertyType.TEXT)
    # Missing encoding format and other recommended properties
    schemas.append(incomplete_doc.to_dict())

    # Invalid schema
    invalid_schema = {
        "@context": "https://schema.org",
        "@type": "ImageObject",
        "contentUrl": "not-a-valid-url",  # Invalid URL
        "name": "Bad Image"
    }
    schemas.append(invalid_schema)

    # Validate all schemas
    reports = validator.validate_batch(schemas)

    # Print individual reports
    for i, report in enumerate(reports):
        print(f"\n--- Schema {i+1} ---")
        print(f"Valid: {report.is_valid()}")
        print(f"Completion: {len(report.messages)} messages")
        if report.has_errors():
            print("Errors:")
            for error in report.get_messages_by_level(ValidationLevel.ERROR):
                print(f"  - {error.message}")

    # Generate summary report
    summary = validator.generate_summary_report(reports)
    print("\n--- Summary Report ---")
    print(f"Total schemas: {summary['total_schemas']}")
    print(f"Valid schemas: {summary['valid_schemas']}")
    print(f"Invalid schemas: {summary['invalid_schemas']}")
    print(f"Success rate: {summary['success_rate']:.1f}%")
    print(f"Total errors: {summary['total_errors']}")
    print(f"Total warnings: {summary['total_warnings']}")


def main():
    """Run all examples."""
    print("\n" + "="*60)
    print("Schema.org File Organization System - Examples")
    print("="*60)

    examples = [
        example_1_basic_document,
        example_2_image_with_exif,
        example_3_video_with_stats,
        example_4_music_recording,
        example_5_source_code,
        example_6_dataset,
        example_7_archive_with_contents,
        example_8_metadata_enrichment,
        example_9_multiple_formats,
        example_10_registry_and_search,
        example_11_validation_workflow
    ]

    for example in examples:
        try:
            example()
        except Exception as e:
            print(f"\nError in {example.__name__}: {str(e)}")

    print("\n" + "="*60)
    print("All examples completed!")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
