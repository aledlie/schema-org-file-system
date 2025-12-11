"""
Comprehensive examples for Schema.org file organization system.

Demonstrates all major features and use cases.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from datetime import datetime
from generators import (
    DocumentGenerator,
    ImageGenerator,
    VideoGenerator,
    AudioGenerator,
    CodeGenerator,
    DatasetGenerator,
    ArchiveGenerator
)
from validator import SchemaValidator
from integration import SchemaIntegration, OutputFormat, SchemaRegistry
from enrichment import MetadataEnricher


def example_1_basic_document():
    """Example 1: Create a basic document schema."""
    print("\n" + "="*60)
    print("Example 1: Basic Document Schema")
    print("="*60)

    # Create document generator
    doc = DocumentGenerator()

    # Set basic information
    doc.set_basic_info(
        name="User Guide",
        description="Comprehensive user guide for the application",
        abstract="This guide covers installation, configuration, and usage"
    )

    # Set file information
    doc.set_file_info(
        encoding_format="application/pdf",
        url="https://example.com/docs/user-guide.pdf",
        content_size=2048000,
        sha256="abc123def456"
    )

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
    doc.set_language("en").set_pagination(45)

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
    img.set_basic_info(
        name="Sunset Beach",
        content_url="https://example.com/photos/sunset.jpg",
        encoding_format="image/jpeg",
        description="Beautiful sunset at the beach",
        caption="Golden hour at Pacific Coast"
    )

    # Set dimensions
    img.set_dimensions(4032, 3024)

    # Add EXIF data
    exif = {
        "Make": "Canon",
        "Model": "EOS R5",
        "DateTime": "2024-01-15T18:30:00",
        "GPSLatitude": 34.0522,
        "GPSLongitude": -118.2437
    }
    img.set_exif_data(exif)

    # Add creator
    img.add_person("creator", "John Photographer", url="https://example.com/photographers/john")

    # Add thumbnail
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
    video.set_basic_info(
        name="Product Demo",
        content_url="https://example.com/videos/demo.mp4",
        upload_date=datetime(2024, 1, 10),
        description="Complete product demonstration and walkthrough",
        thumbnail_url="https://example.com/videos/demo-thumb.jpg"
    )

    # Set media details
    video.set_media_details(
        duration="PT15M30S",  # 15 minutes 30 seconds
        width=1920,
        height=1080,
        encoding_format="video/mp4",
        bitrate="5000kbps"
    )

    # Add creator
    video.add_person("creator", "Marketing Team")

    # Set interaction statistics
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
    music.set_basic_info(
        name="Summer Vibes",
        content_url="https://example.com/music/summer-vibes.mp3",
        description="Upbeat summer track with tropical influences",
        duration="PT3M45S"
    )

    # Set music info
    music.set_music_info(
        album="Summer Collection",
        artist="DJ Sunny",
        genre="Electronic Pop",
        isrc="USRC12345678"
    )

    # Set dates
    music.set_dates(published=datetime(2024, 6, 1))

    # Set language
    music.set_language("en")

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
    code.set_basic_info(
        name="data_processor.py",
        programming_language="Python",
        description="Data processing utilities for file analysis"
    )

    # Set repository info
    code.set_repository_info(
        repository_url="https://github.com/example/file-organizer",
        branch="main",
        commit="abc123def456789"
    )

    # Set runtime info
    code.set_runtime_info(
        runtime_platform=["Python 3.9", "Python 3.10", "Python 3.11"],
        target_product="File Organizer System"
    )

    # Add dependencies
    code.add_dependency("numpy", "1.24.0")
    code.add_dependency("pandas", "2.0.0")
    code.add_dependency("scikit-learn", "1.3.0")

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
    dataset.set_basic_info(
        name="Global Temperature Data",
        description="Historical temperature measurements from weather stations worldwide",
        url="https://example.com/datasets/temperature"
    )

    # Add creator
    dataset.add_organization(
        "creator",
        "Global Weather Institute",
        url="https://example.com/gwi",
        logo="https://example.com/gwi/logo.png"
    )

    # Add distributions
    dataset.add_distribution(
        content_url="https://example.com/datasets/temperature.csv",
        encoding_format="text/csv",
        content_size=10485760
    )
    dataset.add_distribution(
        content_url="https://example.com/datasets/temperature.json",
        encoding_format="application/json",
        content_size=15728640
    )

    # Set coverage
    dataset.set_coverage(
        temporal="2000-01-01/2023-12-31",
        spatial="Global"
    )

    # Add measured variables
    dataset.add_variable_measured("temperature", "Temperature in Celsius")
    dataset.add_variable_measured("humidity", "Relative humidity percentage")
    dataset.add_variable_measured("pressure", "Atmospheric pressure in hPa")

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
    archive.set_basic_info(
        name="project-backup.zip",
        encoding_format="application/zip",
        description="Complete project backup including code, docs, and assets",
        content_size=52428800  # 50 MB
    )

    # Set compression info
    archive.set_compression_info(
        compression_method="DEFLATE",
        compression_ratio=0.65
    )

    # Create contained files
    readme = DocumentGenerator()
    readme.set_basic_info(name="README.md").set_file_info(
        encoding_format="text/markdown",
        url="file:///README.md"
    )

    source = CodeGenerator()
    source.set_basic_info(name="main.py", programming_language="Python")

    # Add contained files to archive
    archive.add_contained_file(readme)
    archive.add_contained_file(source)

    # Add creator
    archive.add_person("author", "Build System")

    # Set dates
    archive.set_dates(created=datetime.now())

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
            doc.set_property(key, value)
        except:
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
    doc.set_basic_info("Example Document").set_file_info(
        "application/pdf",
        "https://example.com/doc.pdf"
    )

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
    doc1.set_basic_info("Python Guide").set_file_info("application/pdf", "https://example.com/python.pdf")

    doc2 = DocumentGenerator()
    doc2.set_basic_info("JavaScript Tutorial").set_file_info("application/pdf", "https://example.com/js.pdf")

    img1 = ImageGenerator()
    img1.set_basic_info("Logo", "https://example.com/logo.png", "image/png")

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
    good_doc.set_basic_info("Complete Document", "Full description")
    good_doc.set_file_info("application/pdf", "https://example.com/good.pdf")
    good_doc.add_person("author", "John Doe")
    good_doc.set_dates(created=datetime.now())
    schemas.append(good_doc.to_dict())

    # Incomplete schema
    incomplete_doc = DocumentGenerator()
    incomplete_doc.set_basic_info("Incomplete Document")
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
