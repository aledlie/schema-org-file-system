#!/usr/bin/env python3
"""
Unit tests for src/enrichment.py - MetadataEnricher class.

Priority: P0-3 (High - Core entity detection enhancement)
Coverage: 90%+ target

Tests metadata enrichment from various sources including:
- EXIF data
- Document properties
- NLP results
- Audio/Video metadata
- Code analysis
- Dataset information
"""

import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def enricher():
    """Create a fresh MetadataEnricher instance."""
    from src.enrichment import MetadataEnricher
    return MetadataEnricher()


@pytest.fixture
def sample_exif_data():
    """Load sample EXIF test data."""
    fixtures_path = Path(__file__).parent.parent / "fixtures" / "sample_exif.json"
    with open(fixtures_path) as f:
        return json.load(f)


@pytest.fixture
def sample_document_props():
    """Load sample document properties test data."""
    fixtures_path = Path(__file__).parent.parent / "fixtures" / "sample_document_props.json"
    with open(fixtures_path) as f:
        return json.load(f)


@pytest.fixture
def sample_nlp_results():
    """Load sample NLP results test data."""
    fixtures_path = Path(__file__).parent.parent / "fixtures" / "sample_nlp_results.json"
    with open(fixtures_path) as f:
        return json.load(f)


@pytest.fixture
def sample_audio_meta():
    """Load sample audio metadata test data."""
    fixtures_path = Path(__file__).parent.parent / "fixtures" / "sample_audio_meta.json"
    with open(fixtures_path) as f:
        return json.load(f)


@pytest.fixture
def sample_video_meta():
    """Load sample video metadata test data."""
    fixtures_path = Path(__file__).parent.parent / "fixtures" / "sample_video_meta.json"
    with open(fixtures_path) as f:
        return json.load(f)


@pytest.fixture
def sample_code_analysis():
    """Load sample code analysis test data."""
    fixtures_path = Path(__file__).parent.parent / "fixtures" / "sample_code_analysis.json"
    with open(fixtures_path) as f:
        return json.load(f)


@pytest.fixture
def sample_dataset_info():
    """Load sample dataset info test data."""
    fixtures_path = Path(__file__).parent.parent / "fixtures" / "sample_dataset_info.json"
    with open(fixtures_path) as f:
        return json.load(f)


class TestMetadataEnricherInit:
    """Test MetadataEnricher initialization."""

    def test_init_creates_mime_mapping(self, enricher):
        """Enricher should initialize with MIME type mappings."""
        assert enricher.mime_to_format is not None
        assert isinstance(enricher.mime_to_format, dict)
        assert len(enricher.mime_to_format) > 0

    def test_mime_mapping_includes_common_types(self, enricher):
        """MIME mapping should include common file types."""
        assert 'application/pdf' in enricher.mime_to_format
        assert 'image/jpeg' in enricher.mime_to_format
        assert 'video/mp4' in enricher.mime_to_format
        assert 'audio/mpeg' in enricher.mime_to_format
        assert 'text/plain' in enricher.mime_to_format


class TestMimeDetection:
    """Test MIME type detection methods."""

    def test_detect_pdf_mime_type(self, enricher):
        """Should detect PDF MIME type from file path."""
        mime = enricher.detect_mime_type('/path/to/document.pdf')
        assert mime == 'application/pdf'

    def test_detect_jpeg_mime_type(self, enricher):
        """Should detect JPEG MIME type from file path."""
        mime = enricher.detect_mime_type('/path/to/photo.jpg')
        assert mime == 'image/jpeg'

    def test_detect_png_mime_type(self, enricher):
        """Should detect PNG MIME type from file path."""
        mime = enricher.detect_mime_type('/path/to/image.png')
        assert mime == 'image/png'

    def test_detect_unknown_returns_octet_stream(self, enricher):
        """Should return octet-stream for unknown file types."""
        mime = enricher.detect_mime_type('/path/to/file.unknownext')
        assert mime == 'application/octet-stream'

    def test_get_encoding_format_known_type(self, enricher):
        """Should return encoding format for known MIME types."""
        format_str = enricher.get_encoding_format('/path/to/doc.pdf')
        assert format_str == 'application/pdf'

    def test_get_encoding_format_unknown_type(self, enricher):
        """Should return MIME type itself for unknown formats."""
        # .unknownext has no registered MIME type
        format_str = enricher.get_encoding_format('/path/to/file.unknownext')
        assert format_str == 'application/octet-stream'


class TestFileStatsEnrichment:
    """Test enrichment from file system stats."""

    def test_enrich_from_file_stats_existing_file(self, enricher):
        """Should extract metadata from an existing file."""
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            f.write(b'Test content')
            temp_path = f.name

        try:
            result = enricher.enrich_from_file_stats(temp_path)

            assert '@id' in result
            assert result['@id'].startswith('urn:sha256:')
            assert 'name' in result
            assert result['name'] == Path(temp_path).name
            assert 'url' in result
            assert result['url'].startswith('file://')
            assert 'encodingFormat' in result
            assert 'contentSize' in result
            assert result['contentSize'] > 0
            assert 'dateCreated' in result
            assert 'dateModified' in result
        finally:
            Path(temp_path).unlink()

    def test_enrich_from_file_stats_nonexistent_file(self, enricher):
        """Should return empty dict for non-existent file."""
        result = enricher.enrich_from_file_stats('/nonexistent/path/file.txt')
        assert result == {}

    def test_file_stats_id_is_deterministic(self, enricher):
        """Same file path should always generate same @id."""
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            f.write(b'Test content')
            temp_path = f.name

        try:
            result1 = enricher.enrich_from_file_stats(temp_path)
            result2 = enricher.enrich_from_file_stats(temp_path)
            assert result1['@id'] == result2['@id']
        finally:
            Path(temp_path).unlink()


class TestExifEnrichment:
    """Test enrichment from EXIF data."""

    def test_enrich_from_full_exif(self, enricher, sample_exif_data):
        """Should extract all available EXIF metadata."""
        exif = sample_exif_data['basic_photo']
        result = enricher.enrich_from_exif(exif)

        # Check creator with @id
        assert 'creator' in result
        assert result['creator']['@type'] == 'Person'
        assert result['creator']['name'] == 'John Photographer'
        assert '@id' in result['creator']
        assert result['creator']['@id'].startswith('urn:uuid:')

        # Check camera info
        assert 'exifData' in result
        assert result['exifData']['@type'] == 'PropertyValue'
        assert 'Canon' in result['exifData']['value']

        # Check dates
        assert 'dateCreated' in result

        # Check location
        assert 'contentLocation' in result
        assert result['contentLocation']['@type'] == 'Place'
        assert result['contentLocation']['geo']['latitude'] == 37.7749

        # Check dimensions
        assert result['width'] == 5472
        assert result['height'] == 3648

        # Check copyright
        assert result['copyrightNotice'] == '2024 John Photographer'

        # Check description
        assert 'description' in result

    def test_enrich_from_minimal_exif(self, enricher, sample_exif_data):
        """Should handle minimal EXIF data."""
        exif = sample_exif_data['minimal_photo']
        result = enricher.enrich_from_exif(exif)

        assert 'exifData' in result
        assert 'iPhone' in result['exifData']['value']
        assert 'creator' not in result
        assert 'contentLocation' not in result

    def test_enrich_from_empty_exif(self, enricher):
        """Should handle empty EXIF data."""
        result = enricher.enrich_from_exif({})
        assert result == {}

    def test_person_id_is_deterministic(self, enricher, sample_exif_data):
        """Same artist name should generate same @id."""
        exif = sample_exif_data['basic_photo']
        result1 = enricher.enrich_from_exif(exif)
        result2 = enricher.enrich_from_exif(exif)
        assert result1['creator']['@id'] == result2['creator']['@id']

    def test_person_id_is_case_insensitive(self, enricher):
        """Person @id should be case-insensitive."""
        result1 = enricher.enrich_from_exif({'Artist': 'John Doe'})
        result2 = enricher.enrich_from_exif({'Artist': 'JOHN DOE'})
        result3 = enricher.enrich_from_exif({'Artist': 'john doe'})
        assert result1['creator']['@id'] == result2['creator']['@id']
        assert result2['creator']['@id'] == result3['creator']['@id']


class TestDocumentPropertiesEnrichment:
    """Test enrichment from document properties."""

    def test_enrich_from_full_document_props(self, enricher, sample_document_props):
        """Should extract all available document properties."""
        props = sample_document_props['pdf_document']
        result = enricher.enrich_from_document_properties(props)

        assert result['name'] == 'Q4 Financial Report'
        assert result['abstract'] == 'Quarterly financial analysis'
        assert result['description'] == 'Comprehensive Q4 2024 financial report with projections'
        assert result['keywords'] == 'finance, quarterly, analysis'
        assert 'author' in result
        assert result['author']['@type'] == 'Person'
        assert result['author']['name'] == 'Alice CFO'
        assert '@id' in result['author']
        assert result['dateCreated'] == '2024-12-01T10:00:00'
        assert result['dateModified'] == '2024-12-05T15:30:00'
        assert result['inLanguage'] == 'en'
        assert result['numberOfPages'] == 25

    def test_enrich_from_word_document_props(self, enricher, sample_document_props):
        """Should handle Word document properties with creator field."""
        props = sample_document_props['word_document']
        result = enricher.enrich_from_document_properties(props)

        assert result['name'] == 'Project Proposal'
        assert result['author']['name'] == 'Bob Manager'
        assert '@id' in result['author']

    def test_enrich_from_minimal_document_props(self, enricher, sample_document_props):
        """Should handle minimal document properties."""
        props = sample_document_props['minimal_document']
        result = enricher.enrich_from_document_properties(props)

        assert result['name'] == 'Notes'
        assert 'author' not in result

    def test_enrich_from_empty_document_props(self, enricher):
        """Should handle empty document properties."""
        result = enricher.enrich_from_document_properties({})
        assert result == {}


class TestNLPEnrichment:
    """Test enrichment from NLP analysis results."""

    def test_enrich_from_full_nlp(self, enricher, sample_nlp_results):
        """Should extract all available NLP data."""
        nlp = sample_nlp_results['full_analysis']
        result = enricher.enrich_from_nlp(nlp)

        # Check keywords
        assert 'keywords' in result
        assert 'machine learning' in result['keywords']

        # Check topics
        assert 'about' in result
        assert len(result['about']) == 2
        assert result['about'][0]['@type'] == 'Thing'
        assert result['about'][0]['name'] == 'artificial intelligence'

        # Check entities with @id
        assert 'mentions' in result
        assert len(result['mentions']) == 4

        # Find Person entity
        person = next(m for m in result['mentions'] if m['@type'] == 'Person')
        assert person['name'] == 'Alan Turing'
        assert '@id' in person
        assert person['@id'].startswith('urn:uuid:')

        # Find Organization entity
        org = next(m for m in result['mentions'] if m['@type'] == 'Organization')
        assert org['name'] == 'OpenAI'
        assert '@id' in org

        # Find Place entity
        place = next(m for m in result['mentions'] if m['@type'] == 'Place')
        assert place['name'] == 'San Francisco'
        assert '@id' in place

        # Check language
        assert result['inLanguage'] == 'en'

        # Check sentiment
        assert 'additionalProperty' in result
        sentiment_prop = result['additionalProperty'][0]
        assert sentiment_prop['name'] == 'sentiment'
        assert sentiment_prop['value'] == 0.75

        # Check summary
        assert 'abstract' in result

    def test_enrich_from_entity_only_nlp(self, enricher, sample_nlp_results):
        """Should handle NLP results with only entities."""
        nlp = sample_nlp_results['entity_only']
        result = enricher.enrich_from_nlp(nlp)

        assert 'mentions' in result
        assert len(result['mentions']) == 2
        assert 'keywords' not in result
        assert 'inLanguage' not in result

    def test_enrich_from_empty_nlp(self, enricher, sample_nlp_results):
        """Should handle empty NLP results."""
        result = enricher.enrich_from_nlp(sample_nlp_results['empty_analysis'])
        assert result == {}

    def test_entity_type_mapping(self, enricher):
        """Should correctly map NLP entity types to Schema.org types."""
        assert enricher._map_entity_type_to_schema('PERSON') == 'Person'
        assert enricher._map_entity_type_to_schema('ORG') == 'Organization'
        assert enricher._map_entity_type_to_schema('ORGANIZATION') == 'Organization'
        assert enricher._map_entity_type_to_schema('GPE') == 'Place'
        assert enricher._map_entity_type_to_schema('LOC') == 'Place'
        assert enricher._map_entity_type_to_schema('LOCATION') == 'Place'
        assert enricher._map_entity_type_to_schema('EVENT') == 'Event'
        assert enricher._map_entity_type_to_schema('UNKNOWN') == 'Thing'


class TestAudioEnrichment:
    """Test enrichment from audio metadata."""

    def test_enrich_from_full_audio(self, enricher, sample_audio_meta):
        """Should extract all available audio metadata."""
        audio = sample_audio_meta['full_track']
        result = enricher.enrich_from_audio_metadata(audio)

        assert result['name'] == 'Highway to the Danger Zone'

        # Check artist with @id
        assert 'byArtist' in result
        assert result['byArtist']['@type'] == 'Person'
        assert result['byArtist']['name'] == 'Kenny Loggins'
        assert '@id' in result['byArtist']

        # Check album with @id
        assert 'inAlbum' in result
        assert result['inAlbum']['@type'] == 'MusicAlbum'
        assert result['inAlbum']['name'] == 'Top Gun Soundtrack'
        assert '@id' in result['inAlbum']

        assert result['genre'] == 'Rock'
        assert result['duration'] == 'PT3M48S'  # 228.5 seconds
        assert result['bitrate'] == '320kbps'
        assert result['position'] == 1
        assert result['datePublished'] == '1986-01-01'
        assert result['isrcCode'] == 'USQY51000001'

    def test_enrich_from_minimal_audio(self, enricher, sample_audio_meta):
        """Should handle minimal audio metadata."""
        audio = sample_audio_meta['minimal_track']
        result = enricher.enrich_from_audio_metadata(audio)

        assert result['name'] == 'Untitled Track'
        assert 'byArtist' not in result
        assert 'inAlbum' not in result

    def test_enrich_from_empty_audio(self, enricher):
        """Should handle empty audio metadata."""
        result = enricher.enrich_from_audio_metadata({})
        assert result == {}


class TestVideoEnrichment:
    """Test enrichment from video metadata."""

    def test_enrich_from_full_video(self, enricher, sample_video_meta):
        """Should extract all available video metadata."""
        video = sample_video_meta['full_video']
        result = enricher.enrich_from_video_metadata(video)

        assert result['name'] == 'Product Demo 2024'
        assert result['description'] == 'Complete walkthrough of our new product features'
        assert result['width'] == 1920
        assert result['height'] == 1080
        assert result['duration'] == 'PT7M30S'  # 450 seconds
        assert result['bitrate'] == '5000kbps'
        assert result['videoCodec'] == 'H.264'
        assert result['audioCodec'] == 'AAC'
        assert result['uploadDate'] == '2024-10-15'

    def test_enrich_from_minimal_video(self, enricher, sample_video_meta):
        """Should handle minimal video metadata."""
        video = sample_video_meta['minimal_video']
        result = enricher.enrich_from_video_metadata(video)

        assert result['name'] == 'Quick Clip'
        assert 'width' not in result
        assert 'duration' not in result
        # Should still have uploadDate defaulted to now
        assert 'uploadDate' in result

    def test_enrich_from_empty_video(self, enricher):
        """Should handle empty video metadata."""
        result = enricher.enrich_from_video_metadata({})
        assert 'uploadDate' in result  # Default is set


class TestCodeAnalysisEnrichment:
    """Test enrichment from code analysis results."""

    def test_enrich_from_full_code_analysis(self, enricher, sample_code_analysis):
        """Should extract all available code analysis metadata."""
        code = sample_code_analysis['python_project']
        result = enricher.enrich_from_code_analysis(code)

        assert result['programmingLanguage'] == 'Python'
        assert result['codeRepository'] == 'https://github.com/example/myproject'
        assert result['targetProduct'] == 'main'
        assert result['runtimePlatform'] == 'Python 3.11'
        assert result['license'] == 'MIT'

        # Check author with @id
        assert 'author' in result
        assert result['author']['@type'] == 'Person'
        assert result['author']['name'] == 'Developer Dave'
        assert '@id' in result['author']

        # Check dependencies
        assert 'dependencies' in result
        assert len(result['dependencies']) == 2
        assert result['dependencies'][0]['@type'] == 'SoftwareApplication'
        assert result['dependencies'][0]['name'] == 'numpy'

        # Check function count description
        assert 'description' in result
        assert '3 functions' in result['description']

    def test_enrich_from_minimal_code_analysis(self, enricher, sample_code_analysis):
        """Should handle minimal code analysis."""
        code = sample_code_analysis['minimal_code']
        result = enricher.enrich_from_code_analysis(code)

        assert result['programmingLanguage'] == 'JavaScript'
        assert 'codeRepository' not in result

    def test_enrich_from_empty_code_analysis(self, enricher):
        """Should handle empty code analysis."""
        result = enricher.enrich_from_code_analysis({})
        assert result == {}


class TestDatasetEnrichment:
    """Test enrichment from dataset information."""

    def test_enrich_from_full_dataset(self, enricher, sample_dataset_info):
        """Should extract all available dataset metadata."""
        dataset = sample_dataset_info['full_dataset']
        result = enricher.enrich_from_dataset_info(dataset)

        assert result['name'] == 'Customer Sales Dataset'
        assert result['description'] == 'Historical sales data from 2020-2024'

        # Check variables
        assert 'variableMeasured' in result
        assert len(result['variableMeasured']) == 3
        assert result['variableMeasured'][0]['@type'] == 'PropertyValue'
        assert result['variableMeasured'][0]['name'] == 'customer_id'

        # Check temporal coverage
        assert result['temporalCoverage'] == '2020-01-01/2024-12-31'

        # Check spatial coverage
        assert result['spatialCoverage'] == 'United States'

        # Check distribution
        assert 'distribution' in result
        assert result['distribution'][0]['@type'] == 'DataDownload'
        assert result['distribution'][0]['encodingFormat'] == 'text/csv'

        # Check rows
        assert 'additionalProperty' in result
        rows_prop = result['additionalProperty'][0]
        assert rows_prop['name'] == 'rows'
        assert rows_prop['value'] == 1500000

    def test_enrich_from_simple_dataset(self, enricher, sample_dataset_info):
        """Should handle simple dataset with string temporal coverage."""
        dataset = sample_dataset_info['simple_dataset']
        result = enricher.enrich_from_dataset_info(dataset)

        assert result['name'] == 'Test Data'
        assert result['temporalCoverage'] == '2024'

    def test_enrich_from_empty_dataset(self, enricher):
        """Should handle empty dataset info."""
        result = enricher.enrich_from_dataset_info({})
        assert result == {}


class TestDurationConversion:
    """Test ISO 8601 duration conversion."""

    def test_seconds_to_iso_seconds_only(self, enricher):
        """Should convert seconds-only duration."""
        assert enricher._seconds_to_iso_duration(45) == 'PT45S'

    def test_seconds_to_iso_minutes_seconds(self, enricher):
        """Should convert minutes and seconds."""
        assert enricher._seconds_to_iso_duration(150) == 'PT2M30S'

    def test_seconds_to_iso_hours_minutes(self, enricher):
        """Should convert hours and minutes."""
        assert enricher._seconds_to_iso_duration(5400) == 'PT1H30M'

    def test_seconds_to_iso_hours_only(self, enricher):
        """Should convert hours only."""
        assert enricher._seconds_to_iso_duration(7200) == 'PT2H'

    def test_seconds_to_iso_zero(self, enricher):
        """Should handle zero seconds."""
        assert enricher._seconds_to_iso_duration(0) == 'PT0S'

    def test_seconds_to_iso_float(self, enricher):
        """Should handle float seconds (truncates to int)."""
        assert enricher._seconds_to_iso_duration(90.5) == 'PT1M30S'


class TestMetadataMerging:
    """Test metadata merging functionality."""

    def test_merge_empty_dicts(self, enricher):
        """Should handle merging empty dicts."""
        result = enricher.merge_metadata({}, {})
        assert result == {}

    def test_merge_non_overlapping(self, enricher):
        """Should merge non-overlapping dictionaries."""
        dict1 = {'name': 'Test', 'author': 'John'}
        dict2 = {'keywords': 'test, example', 'dateCreated': '2024-01-01'}
        result = enricher.merge_metadata(dict1, dict2)

        assert result['name'] == 'Test'
        assert result['author'] == 'John'
        assert result['keywords'] == 'test, example'
        assert result['dateCreated'] == '2024-01-01'

    def test_merge_overlapping_later_wins(self, enricher):
        """Later dictionaries should override earlier ones."""
        dict1 = {'name': 'Original', 'author': 'John'}
        dict2 = {'name': 'Updated', 'keywords': 'new'}
        result = enricher.merge_metadata(dict1, dict2)

        assert result['name'] == 'Updated'
        assert result['author'] == 'John'
        assert result['keywords'] == 'new'

    def test_merge_multiple_dicts(self, enricher):
        """Should merge multiple dictionaries in order."""
        dict1 = {'a': 1}
        dict2 = {'b': 2}
        dict3 = {'c': 3, 'a': 100}
        result = enricher.merge_metadata(dict1, dict2, dict3)

        assert result['a'] == 100  # Latest wins
        assert result['b'] == 2
        assert result['c'] == 3


class TestIDGeneration:
    """Test deterministic ID generation methods."""

    def test_generate_person_id_deterministic(self, enricher):
        """Person ID should be deterministic."""
        id1 = enricher._generate_person_id('John Doe')
        id2 = enricher._generate_person_id('John Doe')
        assert id1 == id2
        assert id1.startswith('urn:uuid:')

    def test_generate_person_id_case_insensitive(self, enricher):
        """Person ID should be case-insensitive."""
        id1 = enricher._generate_person_id('Jane Smith')
        id2 = enricher._generate_person_id('JANE SMITH')
        id3 = enricher._generate_person_id('jane smith')
        assert id1 == id2 == id3

    def test_generate_person_id_trims_whitespace(self, enricher):
        """Person ID should trim whitespace."""
        id1 = enricher._generate_person_id('Bob Builder')
        id2 = enricher._generate_person_id('  Bob Builder  ')
        assert id1 == id2

    def test_generate_org_id_deterministic(self, enricher):
        """Organization ID should be deterministic."""
        id1 = enricher._generate_org_id('Acme Corp')
        id2 = enricher._generate_org_id('Acme Corp')
        assert id1 == id2
        assert id1.startswith('urn:uuid:')

    def test_generate_org_id_different_from_person(self, enricher):
        """Organization ID should differ from Person ID for same name."""
        org_id = enricher._generate_org_id('Smith')
        person_id = enricher._generate_person_id('Smith')
        assert org_id != person_id

    def test_generate_place_id_deterministic(self, enricher):
        """Place ID should be deterministic."""
        id1 = enricher._generate_place_id('New York')
        id2 = enricher._generate_place_id('New York')
        assert id1 == id2
        assert id1.startswith('urn:uuid:')


class TestEnrichedSchemaCreation:
    """Test create_enriched_schema method."""

    def test_create_enriched_schema_basic(self, enricher):
        """Should create enriched schema from generator class."""
        from src.generators import DocumentGenerator

        base_metadata = {'name': 'Test Document'}
        result = enricher.create_enriched_schema(
            DocumentGenerator,
            base_metadata
        )

        assert result is not None
        # The generator should have the name set
        data = result.to_dict()
        assert data.get('name') == 'Test Document'

    def test_create_enriched_schema_with_multiple_sources(self, enricher):
        """Should merge multiple enrichment sources."""
        from src.generators import ImageGenerator

        base = {'name': 'My Photo'}
        exif_data = {'width': 1920, 'height': 1080}
        nlp_data = {'keywords': 'sunset, beach'}

        result = enricher.create_enriched_schema(
            ImageGenerator,
            base,
            exif_data,
            nlp_data
        )

        data = result.to_dict()
        assert data.get('name') == 'My Photo'
