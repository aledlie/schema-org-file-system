"""
Unit tests for Schema.org generators.

Tests all generator classes for proper Schema.org compliance,
including OrganizationGenerator and PersonGenerator.
"""

import pytest
from datetime import datetime
from typing import Any, Dict

from src.generators import (
    DocumentGenerator,
    ImageGenerator,
    VideoGenerator,
    AudioGenerator,
    CodeGenerator,
    DatasetGenerator,
    ArchiveGenerator,
    OrganizationGenerator,
    PersonGenerator,
    DOCUMENT_REQUIRED_PROPERTIES,
    DOCUMENT_RECOMMENDED_PROPERTIES,
    IMAGE_REQUIRED_PROPERTIES,
    IMAGE_RECOMMENDED_PROPERTIES,
    VIDEO_REQUIRED_PROPERTIES,
    AUDIO_REQUIRED_PROPERTIES,
    CODE_REQUIRED_PROPERTIES,
    DATASET_REQUIRED_PROPERTIES,
    ARCHIVE_REQUIRED_PROPERTIES,
    ORGANIZATION_REQUIRED_PROPERTIES,
    ORGANIZATION_RECOMMENDED_PROPERTIES,
    PERSON_REQUIRED_PROPERTIES,
    PERSON_RECOMMENDED_PROPERTIES,
)
from src.base import SchemaOrgBase, PropertyType, SchemaContext


# =============================================================================
# Test Constants
# =============================================================================

class TestPropertyConstants:
    """Test that property constants are properly defined."""

    def test_document_required_properties(self):
        """Test document required properties are defined."""
        assert "name" in DOCUMENT_REQUIRED_PROPERTIES
        assert "encodingFormat" in DOCUMENT_REQUIRED_PROPERTIES

    def test_image_required_properties(self):
        """Test image required properties are defined."""
        assert "contentUrl" in IMAGE_REQUIRED_PROPERTIES
        assert "encodingFormat" in IMAGE_REQUIRED_PROPERTIES

    def test_video_required_properties(self):
        """Test video required properties are defined."""
        assert "name" in VIDEO_REQUIRED_PROPERTIES
        assert "contentUrl" in VIDEO_REQUIRED_PROPERTIES
        assert "uploadDate" in VIDEO_REQUIRED_PROPERTIES

    def test_organization_required_properties(self):
        """Test organization required properties are defined."""
        assert "name" in ORGANIZATION_REQUIRED_PROPERTIES

    def test_organization_recommended_properties(self):
        """Test organization recommended properties are defined."""
        assert "url" in ORGANIZATION_RECOMMENDED_PROPERTIES
        assert "logo" in ORGANIZATION_RECOMMENDED_PROPERTIES
        assert "email" in ORGANIZATION_RECOMMENDED_PROPERTIES

    def test_person_required_properties(self):
        """Test person required properties are defined."""
        assert "name" in PERSON_REQUIRED_PROPERTIES

    def test_person_recommended_properties(self):
        """Test person recommended properties are defined."""
        assert "email" in PERSON_RECOMMENDED_PROPERTIES
        assert "telephone" in PERSON_RECOMMENDED_PROPERTIES
        assert "jobTitle" in PERSON_RECOMMENDED_PROPERTIES


# =============================================================================
# Test SchemaContext
# =============================================================================

class TestSchemaContext:
    """Test SchemaContext class."""

    def test_default_context(self):
        """Test default context structure."""
        assert SchemaContext.SCHEMA_ORG == "https://schema.org"
        assert "@context" in SchemaContext.DEFAULT_CONTEXT
        assert "@vocab" in SchemaContext.DEFAULT_CONTEXT

    def test_get_context_basic(self):
        """Test getting basic context."""
        context = SchemaContext.get_context()
        assert "@context" in context
        assert context["@context"] == "https://schema.org"

    def test_get_context_with_additional(self):
        """Test getting context with additional namespaces."""
        additional = {"owl": "http://www.w3.org/2002/07/owl#"}
        context = SchemaContext.get_context(additional)
        assert "owl" in context


# =============================================================================
# Test PropertyType
# =============================================================================

class TestPropertyType:
    """Test PropertyType enum."""

    def test_all_types_exist(self):
        """Test all property types are defined."""
        assert PropertyType.TEXT.value == "Text"
        assert PropertyType.URL.value == "URL"
        assert PropertyType.DATE.value == "Date"
        assert PropertyType.DATETIME.value == "DateTime"
        assert PropertyType.NUMBER.value == "Number"
        assert PropertyType.INTEGER.value == "Integer"
        assert PropertyType.BOOLEAN.value == "Boolean"
        assert PropertyType.OBJECT.value == "Object"
        assert PropertyType.ARRAY.value == "Array"


# =============================================================================
# Test DocumentGenerator
# =============================================================================

class TestDocumentGenerator:
    """Test DocumentGenerator class."""

    def test_basic_creation(self):
        """Test creating a basic document."""
        doc = DocumentGenerator()
        assert doc.data["@type"] == "DigitalDocument"
        assert "@id" in doc.data
        assert doc.data["@id"].startswith("urn:uuid:")

    def test_custom_type(self):
        """Test creating document with custom type."""
        doc = DocumentGenerator("ScholarlyArticle")
        assert doc.data["@type"] == "ScholarlyArticle"

    def test_custom_entity_id(self):
        """Test creating document with custom entity ID."""
        doc = DocumentGenerator(entity_id="urn:sha256:abc123")
        assert doc.data["@id"] == "urn:sha256:abc123"

    def test_set_basic_info(self):
        """Test setting basic information."""
        doc = DocumentGenerator()
        doc.set_basic_info("Test Doc", description="A test", abstract="Summary")

        assert doc.data["name"] == "Test Doc"
        assert doc.data["description"] == "A test"
        assert doc.data["abstract"] == "Summary"

    def test_set_file_info(self):
        """Test setting file information."""
        doc = DocumentGenerator()
        doc.set_file_info(
            encoding_format="application/pdf",
            url="https://example.com/doc.pdf",
            content_size=1024,
            sha256="abc123def456"
        )

        assert doc.data["encodingFormat"] == "application/pdf"
        assert doc.data["url"] == "https://example.com/doc.pdf"
        assert doc.data["contentSize"] == "1024B"
        assert "identifier" in doc.data

    def test_set_language(self):
        """Test setting language."""
        doc = DocumentGenerator()
        doc.set_language("en")
        assert doc.data["inLanguage"] == "en"

    def test_set_pagination(self):
        """Test setting pagination."""
        doc = DocumentGenerator()
        doc.set_pagination(42)
        assert doc.data["numberOfPages"] == 42

    def test_add_citation_string(self):
        """Test adding string citation."""
        doc = DocumentGenerator()
        doc.add_citation("Smith, J. (2024). Test Paper.")
        assert "citation" in doc.data
        assert len(doc.data["citation"]) == 1

    def test_add_citation_multiple(self):
        """Test adding multiple citations."""
        doc = DocumentGenerator()
        doc.add_citation("Citation 1")
        doc.add_citation("Citation 2")
        assert len(doc.data["citation"]) == 2

    def test_set_scholarly_info(self):
        """Test setting scholarly information."""
        doc = DocumentGenerator("ScholarlyArticle")
        doc.set_scholarly_info(
            doi="10.1234/test",
            issn="1234-5678",
            publication="Nature"
        )

        assert doc.data["sameAs"] == "https://doi.org/10.1234/test"
        assert doc.data["issn"] == "1234-5678"
        assert doc.data["publication"] == "Nature"

    def test_get_required_properties(self):
        """Test getting required properties."""
        doc = DocumentGenerator()
        required = doc.get_required_properties()
        assert "name" in required
        assert "encodingFormat" in required

    def test_get_recommended_properties(self):
        """Test getting recommended properties."""
        doc = DocumentGenerator()
        recommended = doc.get_recommended_properties()
        assert "author" in recommended
        assert "dateCreated" in recommended

    def test_method_chaining(self):
        """Test method chaining works."""
        doc = DocumentGenerator() \
            .set_basic_info("Test") \
            .set_file_info("application/pdf", "https://example.com/test.pdf") \
            .set_language("en") \
            .set_pagination(10)

        assert doc.data["name"] == "Test"
        assert doc.data["inLanguage"] == "en"


# =============================================================================
# Test ImageGenerator
# =============================================================================

class TestImageGenerator:
    """Test ImageGenerator class."""

    def test_basic_creation(self):
        """Test creating a basic image."""
        img = ImageGenerator()
        assert img.data["@type"] == "ImageObject"

    def test_photograph_type(self):
        """Test photograph type."""
        photo = ImageGenerator("Photograph")
        assert photo.data["@type"] == "Photograph"

    def test_set_basic_info(self):
        """Test setting basic info."""
        img = ImageGenerator()
        img.set_basic_info(
            name="Test Image",
            content_url="https://example.com/image.jpg",
            encoding_format="image/jpeg",
            description="A test image",
            caption="Test caption"
        )

        assert img.data["name"] == "Test Image"
        assert img.data["contentUrl"] == "https://example.com/image.jpg"
        assert img.data["caption"] == "Test caption"

    def test_set_dimensions(self):
        """Test setting dimensions."""
        img = ImageGenerator()
        img.set_dimensions(1920, 1080)
        assert img.data["width"] == 1920
        assert img.data["height"] == 1080

    def test_set_exif_data(self):
        """Test setting EXIF data."""
        img = ImageGenerator()
        exif = {
            "Make": "Canon",
            "Model": "EOS 5D",
            "DateTime": "2024-01-15T10:30:00"
        }
        img.set_exif_data(exif)

        assert "exifData" in img.data
        assert img.data["exifData"]["camera"] == "Canon"
        assert img.data["exifData"]["cameraModel"] == "EOS 5D"

    def test_set_exif_with_gps(self):
        """Test setting EXIF data with GPS coordinates."""
        img = ImageGenerator()
        exif = {
            "GPSLatitude": 37.7749,
            "GPSLongitude": -122.4194
        }
        img.set_exif_data(exif)

        assert "contentLocation" in img.data
        assert img.data["contentLocation"]["@type"] == "Place"

    def test_set_thumbnail(self):
        """Test setting thumbnail."""
        img = ImageGenerator()
        img.set_thumbnail("https://example.com/thumb.jpg")

        assert "thumbnail" in img.data
        assert img.data["thumbnail"]["@type"] == "ImageObject"
        assert img.data["thumbnail"]["contentUrl"] == "https://example.com/thumb.jpg"

    def test_add_depicted_item(self):
        """Test adding depicted item."""
        img = ImageGenerator()
        img.add_depicted_item("Mountain")
        img.add_depicted_item({"@type": "Place", "name": "Grand Canyon"})

        assert "associatedMedia" in img.data
        assert len(img.data["associatedMedia"]) == 2


# =============================================================================
# Test VideoGenerator
# =============================================================================

class TestVideoGenerator:
    """Test VideoGenerator class."""

    def test_basic_creation(self):
        """Test creating a basic video."""
        video = VideoGenerator()
        assert video.data["@type"] == "VideoObject"

    def test_movie_clip_type(self):
        """Test movie clip type."""
        clip = VideoGenerator("MovieClip")
        assert clip.data["@type"] == "MovieClip"

    def test_set_basic_info(self):
        """Test setting basic info."""
        video = VideoGenerator()
        upload_date = datetime(2024, 1, 15)
        video.set_basic_info(
            name="Test Video",
            content_url="https://example.com/video.mp4",
            upload_date=upload_date,
            description="A test video",
            thumbnail_url="https://example.com/thumb.jpg"
        )

        assert video.data["name"] == "Test Video"
        assert video.data["contentUrl"] == "https://example.com/video.mp4"
        assert video.data["thumbnailUrl"] == "https://example.com/thumb.jpg"

    def test_set_media_details(self):
        """Test setting media details."""
        video = VideoGenerator()
        video.set_media_details(
            duration="PT5M30S",
            width=1920,
            height=1080,
            encoding_format="video/mp4",
            bitrate="5000kbps"
        )

        assert video.data["duration"] == "PT5M30S"
        assert video.data["width"] == 1920
        assert video.data["bitrate"] == "5000kbps"

    def test_set_interaction_stats(self):
        """Test setting interaction statistics."""
        video = VideoGenerator()
        video.set_interaction_stats(view_count=10000, comment_count=500)

        assert "interactionStatistic" in video.data
        assert len(video.data["interactionStatistic"]) == 2

    def test_set_interaction_stats_partial(self):
        """Test setting partial interaction statistics."""
        video = VideoGenerator()
        video.set_interaction_stats(view_count=10000)

        assert len(video.data["interactionStatistic"]) == 1


# =============================================================================
# Test AudioGenerator
# =============================================================================

class TestAudioGenerator:
    """Test AudioGenerator class."""

    def test_basic_creation(self):
        """Test creating a basic audio."""
        audio = AudioGenerator()
        assert audio.data["@type"] == "AudioObject"

    def test_music_recording_type(self):
        """Test music recording type."""
        music = AudioGenerator("MusicRecording")
        assert music.data["@type"] == "MusicRecording"

    def test_podcast_type(self):
        """Test podcast type."""
        podcast = AudioGenerator("PodcastEpisode")
        assert podcast.data["@type"] == "PodcastEpisode"

    def test_set_basic_info(self):
        """Test setting basic info."""
        audio = AudioGenerator()
        audio.set_basic_info(
            name="Test Audio",
            content_url="https://example.com/audio.mp3",
            description="A test audio",
            duration="PT3M45S"
        )

        assert audio.data["name"] == "Test Audio"
        assert audio.data["duration"] == "PT3M45S"

    def test_set_music_info(self):
        """Test setting music info."""
        audio = AudioGenerator("MusicRecording")
        audio.set_music_info(
            album="Test Album",
            artist="Test Artist",
            genre="Rock",
            isrc="USRC12345678"
        )

        assert audio.data["inAlbum"]["@type"] == "MusicAlbum"
        assert audio.data["inAlbum"]["name"] == "Test Album"
        assert "byArtist" in audio.data
        assert audio.data["genre"] == "Rock"
        assert audio.data["isrcCode"] == "USRC12345678"

    def test_set_podcast_info(self):
        """Test setting podcast info."""
        audio = AudioGenerator("PodcastEpisode")
        audio.set_podcast_info(episode_number=42, series="Tech Talk")

        assert audio.data["episodeNumber"] == 42
        assert audio.data["partOfSeries"]["@type"] == "PodcastSeries"
        assert audio.data["partOfSeries"]["name"] == "Tech Talk"


# =============================================================================
# Test CodeGenerator
# =============================================================================

class TestCodeGenerator:
    """Test CodeGenerator class."""

    def test_basic_creation(self):
        """Test creating a basic code schema."""
        code = CodeGenerator()
        assert code.data["@type"] == "SoftwareSourceCode"

    def test_set_basic_info(self):
        """Test setting basic info."""
        code = CodeGenerator()
        code.set_basic_info(
            name="main.py",
            programming_language="Python",
            description="Main script",
            code_sample="print('Hello')"
        )

        assert code.data["name"] == "main.py"
        assert code.data["programmingLanguage"] == "Python"
        assert code.data["codeSampleType"] == "code snippet"
        assert code.data["text"] == "print('Hello')"

    def test_set_repository_info(self):
        """Test setting repository info."""
        code = CodeGenerator()
        code.set_repository_info(
            repository_url="https://github.com/user/repo",
            branch="main",
            commit="abc123"
        )

        assert code.data["codeRepository"] == "https://github.com/user/repo"
        assert code.data["branch"] == "main"
        assert "identifier" in code.data

    def test_set_runtime_info_string(self):
        """Test setting runtime info with string."""
        code = CodeGenerator()
        code.set_runtime_info("Node.js 18", target_product="Express")

        assert code.data["runtimePlatform"] == "Node.js 18"
        assert code.data["targetProduct"] == "Express"

    def test_set_runtime_info_list(self):
        """Test setting runtime info with list."""
        code = CodeGenerator()
        code.set_runtime_info(["Node.js 18", "Python 3.11"])

        assert code.data["runtimePlatform"] == "Node.js 18, Python 3.11"

    def test_add_dependency(self):
        """Test adding dependencies."""
        code = CodeGenerator()
        code.add_dependency("react", "18.2.0")
        code.add_dependency("axios")

        assert len(code.data["dependencies"]) == 2
        assert code.data["dependencies"][0]["name"] == "react"
        assert code.data["dependencies"][0]["softwareVersion"] == "18.2.0"
        assert code.data["dependencies"][1]["name"] == "axios"


# =============================================================================
# Test DatasetGenerator
# =============================================================================

class TestDatasetGenerator:
    """Test DatasetGenerator class."""

    def test_basic_creation(self):
        """Test creating a basic dataset."""
        dataset = DatasetGenerator()
        assert dataset.data["@type"] == "Dataset"

    def test_set_basic_info(self):
        """Test setting basic info."""
        dataset = DatasetGenerator()
        dataset.set_basic_info(
            name="Test Dataset",
            description="A test dataset",
            url="https://example.com/data"
        )

        assert dataset.data["name"] == "Test Dataset"
        assert dataset.data["description"] == "A test dataset"
        assert dataset.data["url"] == "https://example.com/data"

    def test_add_distribution(self):
        """Test adding distribution."""
        dataset = DatasetGenerator()
        dataset.add_distribution(
            content_url="https://example.com/data.csv",
            encoding_format="text/csv",
            content_size=1024
        )

        assert len(dataset.data["distribution"]) == 1
        assert dataset.data["distribution"][0]["@type"] == "DataDownload"
        assert dataset.data["distribution"][0]["contentSize"] == "1024B"

    def test_add_multiple_distributions(self):
        """Test adding multiple distributions."""
        dataset = DatasetGenerator()
        dataset.add_distribution("https://example.com/data.csv", "text/csv")
        dataset.add_distribution("https://example.com/data.json", "application/json")

        assert len(dataset.data["distribution"]) == 2

    def test_set_coverage(self):
        """Test setting coverage."""
        dataset = DatasetGenerator()
        dataset.set_coverage(
            temporal="2020-01-01/2020-12-31",
            spatial="San Francisco, CA"
        )

        assert dataset.data["temporalCoverage"] == "2020-01-01/2020-12-31"
        assert dataset.data["spatialCoverage"] == "San Francisco, CA"

    def test_add_variable_measured(self):
        """Test adding measured variables."""
        dataset = DatasetGenerator()
        dataset.add_variable_measured("temperature", "Temperature in Celsius")
        dataset.add_variable_measured("humidity")

        assert len(dataset.data["variableMeasured"]) == 2
        assert dataset.data["variableMeasured"][0]["@type"] == "PropertyValue"
        assert dataset.data["variableMeasured"][0]["description"] == "Temperature in Celsius"


# =============================================================================
# Test ArchiveGenerator
# =============================================================================

class TestArchiveGenerator:
    """Test ArchiveGenerator class."""

    def test_basic_creation(self):
        """Test creating a basic archive."""
        archive = ArchiveGenerator()
        assert archive.data["@type"] == "DigitalDocument"
        assert archive.data["additionalType"] == "Archive"

    def test_set_basic_info(self):
        """Test setting basic info."""
        archive = ArchiveGenerator()
        archive.set_basic_info(
            name="backup.zip",
            encoding_format="application/zip",
            description="System backup",
            content_size=10485760
        )

        assert archive.data["name"] == "backup.zip"
        assert archive.data["encodingFormat"] == "application/zip"
        assert archive.data["contentSize"] == "10485760B"

    def test_add_contained_file(self):
        """Test adding contained files."""
        archive = ArchiveGenerator()
        doc = DocumentGenerator()
        doc.set_basic_info("readme.txt")

        archive.add_contained_file(doc)

        assert "hasPart" in archive.data
        assert len(archive.data["hasPart"]) == 1

    def test_add_multiple_contained_files(self):
        """Test adding multiple contained files."""
        archive = ArchiveGenerator()
        doc1 = DocumentGenerator()
        doc1.set_basic_info("file1.txt")
        doc2 = DocumentGenerator()
        doc2.set_basic_info("file2.txt")

        archive.add_contained_file(doc1)
        archive.add_contained_file(doc2)

        assert len(archive.data["hasPart"]) == 2

    def test_set_compression_info(self):
        """Test setting compression info."""
        archive = ArchiveGenerator()
        archive.set_compression_info("deflate", compression_ratio=0.75)

        assert archive.data["compressionMethod"] == "deflate"
        assert archive.data["compressionRatio"] == 0.75


# =============================================================================
# Test OrganizationGenerator
# =============================================================================

class TestOrganizationGenerator:
    """Test OrganizationGenerator class."""

    def test_basic_creation(self):
        """Test creating a basic organization."""
        org = OrganizationGenerator()
        assert org.data["@type"] == "Organization"
        assert "@id" in org.data

    def test_custom_type(self):
        """Test creating organization with custom type."""
        corp = OrganizationGenerator("Corporation")
        assert corp.data["@type"] == "Corporation"

    def test_local_business_type(self):
        """Test creating local business."""
        biz = OrganizationGenerator("LocalBusiness")
        assert biz.data["@type"] == "LocalBusiness"

    def test_set_basic_info(self):
        """Test setting basic info."""
        org = OrganizationGenerator()
        org.set_basic_info(
            name="Test Corp",
            description="A test company",
            url="https://testcorp.com",
            logo="https://testcorp.com/logo.png"
        )

        assert org.data["name"] == "Test Corp"
        assert org.data["description"] == "A test company"
        assert org.data["url"] == "https://testcorp.com"
        assert org.data["logo"]["@type"] == "ImageObject"
        assert org.data["logo"]["url"] == "https://testcorp.com/logo.png"

    def test_set_legal_info(self):
        """Test setting legal information."""
        org = OrganizationGenerator()
        org.set_legal_info(
            legal_name="Test Corporation, Inc.",
            tax_id="12-3456789",
            vat_id="EU123456789",
            lei_code="ABCD1234567890EFGH12",
            duns="123456789"
        )

        assert org.data["legalName"] == "Test Corporation, Inc."
        assert org.data["taxID"] == "12-3456789"
        assert org.data["vatID"] == "EU123456789"
        assert org.data["leiCode"] == "ABCD1234567890EFGH12"
        assert org.data["duns"] == "123456789"

    def test_set_contact_info(self):
        """Test setting contact information."""
        org = OrganizationGenerator()
        org.set_contact_info(
            email="info@testcorp.com",
            telephone="+1-555-123-4567",
            fax="+1-555-123-4568"
        )

        assert org.data["email"] == "info@testcorp.com"
        assert org.data["telephone"] == "+1-555-123-4567"
        assert org.data["faxNumber"] == "+1-555-123-4568"

    def test_set_address(self):
        """Test setting address."""
        org = OrganizationGenerator()
        org.set_address(
            street="123 Main St",
            city="San Francisco",
            region="CA",
            postal_code="94102",
            country="USA"
        )

        assert "address" in org.data
        assert org.data["address"]["@type"] == "PostalAddress"
        assert org.data["address"]["streetAddress"] == "123 Main St"
        assert org.data["address"]["addressLocality"] == "San Francisco"
        assert org.data["address"]["addressRegion"] == "CA"
        assert org.data["address"]["postalCode"] == "94102"
        assert org.data["address"]["addressCountry"] == "USA"

    def test_set_address_minimal(self):
        """Test that empty address is not added."""
        org = OrganizationGenerator()
        org.set_address()  # No arguments

        assert "address" not in org.data

    def test_set_founding_info(self):
        """Test setting founding information."""
        org = OrganizationGenerator()
        org.set_founding_info(
            founding_date="2020-01-15",
            dissolution_date="2024-12-31",
            founding_location="San Francisco"
        )

        assert org.data["foundingDate"] == "2020-01-15"
        assert org.data["dissolutionDate"] == "2024-12-31"
        assert org.data["foundingLocation"]["@type"] == "Place"
        assert org.data["foundingLocation"]["name"] == "San Francisco"

    def test_add_founder(self):
        """Test adding founders."""
        org = OrganizationGenerator()
        org.add_founder("John Doe")
        org.add_founder("Jane Smith", person_id="urn:uuid:test-id")

        assert len(org.data["founder"]) == 2
        assert org.data["founder"][0]["@type"] == "Person"
        assert org.data["founder"][0]["name"] == "John Doe"
        assert org.data["founder"][1]["@id"] == "urn:uuid:test-id"

    def test_set_employee_count(self):
        """Test setting employee count."""
        org = OrganizationGenerator()
        org.set_employee_count(500)

        assert org.data["numberOfEmployees"]["@type"] == "QuantitativeValue"
        assert org.data["numberOfEmployees"]["value"] == 500

    def test_set_area_served_string(self):
        """Test setting area served with string."""
        org = OrganizationGenerator()
        org.set_area_served("North America")

        assert org.data["areaServed"] == "North America"

    def test_set_area_served_list(self):
        """Test setting area served with list."""
        org = OrganizationGenerator()
        org.set_area_served(["USA", "Canada", "Mexico"])

        assert len(org.data["areaServed"]) == 3
        assert org.data["areaServed"][0]["@type"] == "Place"

    def test_add_contact_point(self):
        """Test adding contact points."""
        org = OrganizationGenerator()
        org.add_contact_point(
            contact_type="customer service",
            telephone="+1-555-123-4567",
            email="support@test.com",
            available_language=["en", "es"]
        )

        assert len(org.data["contactPoint"]) == 1
        contact = org.data["contactPoint"][0]
        assert contact["@type"] == "ContactPoint"
        assert contact["contactType"] == "customer service"
        assert contact["telephone"] == "+1-555-123-4567"
        assert contact["email"] == "support@test.com"
        assert contact["availableLanguage"] == ["en", "es"]

    def test_add_same_as_string(self):
        """Test adding sameAs with string."""
        org = OrganizationGenerator()
        org.add_same_as("https://www.linkedin.com/company/testcorp")

        assert "https://www.linkedin.com/company/testcorp" in org.data["sameAs"]

    def test_add_same_as_list(self):
        """Test adding sameAs with list."""
        org = OrganizationGenerator()
        org.add_same_as([
            "https://www.linkedin.com/company/testcorp",
            "https://twitter.com/testcorp"
        ])

        assert len(org.data["sameAs"]) == 2

    def test_set_parent_organization(self):
        """Test setting parent organization."""
        org = OrganizationGenerator()
        org.set_parent_organization("Parent Corp", org_id="urn:uuid:parent-id")

        assert org.data["parentOrganization"]["@type"] == "Organization"
        assert org.data["parentOrganization"]["name"] == "Parent Corp"
        assert org.data["parentOrganization"]["@id"] == "urn:uuid:parent-id"

    def test_add_department(self):
        """Test adding departments."""
        org = OrganizationGenerator()
        org.add_department("Engineering")
        org.add_department("Marketing", dept_id="urn:uuid:marketing")

        assert len(org.data["department"]) == 2
        assert org.data["department"][0]["name"] == "Engineering"
        assert org.data["department"][1]["@id"] == "urn:uuid:marketing"

    def test_get_required_properties(self):
        """Test getting required properties."""
        org = OrganizationGenerator()
        required = org.get_required_properties()
        assert "name" in required

    def test_get_recommended_properties(self):
        """Test getting recommended properties."""
        org = OrganizationGenerator()
        recommended = org.get_recommended_properties()
        assert "url" in recommended
        assert "email" in recommended


# =============================================================================
# Test PersonGenerator
# =============================================================================

class TestPersonGenerator:
    """Test PersonGenerator class."""

    def test_basic_creation(self):
        """Test creating a basic person."""
        person = PersonGenerator()
        assert person.data["@type"] == "Person"
        assert "@id" in person.data

    def test_set_name_full(self):
        """Test setting full name."""
        person = PersonGenerator()
        person.set_name(name="John Doe")
        assert person.data["name"] == "John Doe"

    def test_set_name_parts(self):
        """Test setting name parts."""
        person = PersonGenerator()
        person.set_name(
            given_name="John",
            family_name="Doe",
            additional_name="Michael",
            honorific_prefix="Dr.",
            honorific_suffix="PhD"
        )

        assert person.data["givenName"] == "John"
        assert person.data["familyName"] == "Doe"
        assert person.data["additionalName"] == "Michael"
        assert person.data["honorificPrefix"] == "Dr."
        assert person.data["honorificSuffix"] == "PhD"

    def test_set_contact_info(self):
        """Test setting contact information."""
        person = PersonGenerator()
        person.set_contact_info(
            email="john@example.com",
            telephone="+1-555-123-4567",
            fax="+1-555-123-4568"
        )

        assert person.data["email"] == "john@example.com"
        assert person.data["telephone"] == "+1-555-123-4567"
        assert person.data["faxNumber"] == "+1-555-123-4568"

    def test_set_address(self):
        """Test setting address."""
        person = PersonGenerator()
        person.set_address(
            street="123 Main St",
            city="San Francisco",
            region="CA",
            postal_code="94102",
            country="USA"
        )

        assert "address" in person.data
        assert person.data["address"]["@type"] == "PostalAddress"

    def test_set_address_minimal(self):
        """Test that empty address is not added."""
        person = PersonGenerator()
        person.set_address()

        assert "address" not in person.data

    def test_set_birth_info(self):
        """Test setting birth information."""
        person = PersonGenerator()
        person.set_birth_info(birth_date="1990-01-15", birth_place="New York")

        assert person.data["birthDate"] == "1990-01-15"
        assert person.data["birthPlace"]["@type"] == "Place"
        assert person.data["birthPlace"]["name"] == "New York"

    def test_set_death_info(self):
        """Test setting death information."""
        person = PersonGenerator()
        person.set_death_info(death_date="2024-12-31", death_place="Los Angeles")

        assert person.data["deathDate"] == "2024-12-31"
        assert person.data["deathPlace"]["@type"] == "Place"

    def test_set_job_info(self):
        """Test setting job information."""
        person = PersonGenerator()
        person.set_job_info(
            job_title="Software Engineer",
            works_for="Tech Corp",
            works_for_id="urn:uuid:techcorp"
        )

        assert person.data["jobTitle"] == "Software Engineer"
        assert person.data["worksFor"]["@type"] == "Organization"
        assert person.data["worksFor"]["name"] == "Tech Corp"
        assert person.data["worksFor"]["@id"] == "urn:uuid:techcorp"

    def test_add_affiliation(self):
        """Test adding affiliations."""
        person = PersonGenerator()
        person.add_affiliation("IEEE")
        person.add_affiliation("ACM", org_id="urn:uuid:acm")

        assert len(person.data["affiliation"]) == 2
        assert person.data["affiliation"][1]["@id"] == "urn:uuid:acm"

    def test_add_alumni_of(self):
        """Test adding alumni information."""
        person = PersonGenerator()
        person.add_alumni_of("MIT")
        person.add_alumni_of("Stanford", org_id="urn:uuid:stanford")

        assert len(person.data["alumniOf"]) == 2
        assert person.data["alumniOf"][0]["@type"] == "EducationalOrganization"

    def test_set_nationality(self):
        """Test setting nationality."""
        person = PersonGenerator()
        person.set_nationality("USA")

        assert person.data["nationality"]["@type"] == "Country"
        assert person.data["nationality"]["name"] == "USA"

    def test_set_gender(self):
        """Test setting gender."""
        person = PersonGenerator()
        person.set_gender("Male")
        assert person.data["gender"] == "Male"

    def test_set_image(self):
        """Test setting profile image."""
        person = PersonGenerator()
        person.set_image("https://example.com/photo.jpg")

        assert person.data["image"]["@type"] == "ImageObject"
        assert person.data["image"]["url"] == "https://example.com/photo.jpg"

    def test_set_url(self):
        """Test setting personal URL."""
        person = PersonGenerator()
        person.set_url("https://johndoe.com")
        assert person.data["url"] == "https://johndoe.com"

    def test_add_same_as(self):
        """Test adding sameAs links."""
        person = PersonGenerator()
        person.add_same_as("https://twitter.com/johndoe")
        person.add_same_as(["https://linkedin.com/in/johndoe"])

        assert len(person.data["sameAs"]) == 2

    def test_add_knows(self):
        """Test adding known people."""
        person = PersonGenerator()
        person.add_knows("Jane Smith")
        person.add_knows("Bob Johnson", person_id="urn:uuid:bob")

        assert len(person.data["knows"]) == 2
        assert person.data["knows"][1]["@id"] == "urn:uuid:bob"

    def test_add_colleague(self):
        """Test adding colleagues."""
        person = PersonGenerator()
        person.add_colleague("Alice Williams")

        assert len(person.data["colleague"]) == 1
        assert person.data["colleague"][0]["@type"] == "Person"

    def test_set_spouse(self):
        """Test setting spouse."""
        person = PersonGenerator()
        person.set_spouse("Jane Doe", person_id="urn:uuid:jane")

        assert person.data["spouse"]["@type"] == "Person"
        assert person.data["spouse"]["name"] == "Jane Doe"
        assert person.data["spouse"]["@id"] == "urn:uuid:jane"

    def test_add_parent(self):
        """Test adding parents."""
        person = PersonGenerator()
        person.add_parent("John Doe Sr.")
        person.add_parent("Mary Doe")

        assert len(person.data["parent"]) == 2

    def test_add_child(self):
        """Test adding children."""
        person = PersonGenerator()
        person.add_child("John Doe Jr.", person_id="urn:uuid:jr")

        assert len(person.data["children"]) == 1
        assert person.data["children"][0]["@id"] == "urn:uuid:jr"

    def test_add_sibling(self):
        """Test adding siblings."""
        person = PersonGenerator()
        person.add_sibling("James Doe")

        assert len(person.data["sibling"]) == 1

    def test_get_required_properties(self):
        """Test getting required properties."""
        person = PersonGenerator()
        required = person.get_required_properties()
        assert "name" in required

    def test_get_recommended_properties(self):
        """Test getting recommended properties."""
        person = PersonGenerator()
        recommended = person.get_recommended_properties()
        assert "email" in recommended
        assert "jobTitle" in recommended


# =============================================================================
# Test SchemaOrgBase Methods
# =============================================================================

class TestSchemaOrgBaseMethods:
    """Test SchemaOrgBase methods via concrete implementations."""

    def test_set_id(self):
        """Test setting ID after creation."""
        doc = DocumentGenerator()
        doc.set_id("urn:sha256:abc123")
        assert doc.data["@id"] == "urn:sha256:abc123"

    def test_set_id_uuid_string(self):
        """Test setting ID with UUID string (auto-wraps in URN)."""
        doc = DocumentGenerator()
        doc.set_id("550e8400-e29b-41d4-a716-446655440000")
        assert doc.data["@id"] == "urn:uuid:550e8400-e29b-41d4-a716-446655440000"

    def test_get_id(self):
        """Test getting ID."""
        doc = DocumentGenerator(entity_id="urn:sha256:test123")
        assert doc.get_id() == "urn:sha256:test123"

    def test_set_property_with_none(self):
        """Test that setting None property is ignored."""
        doc = DocumentGenerator()
        doc.set_property("test", None)
        assert "test" not in doc.data

    def test_validate_and_convert_url_invalid(self):
        """Test URL validation with invalid URL."""
        doc = DocumentGenerator()
        with pytest.raises(ValueError, match="Invalid URL"):
            doc.set_property("url", "not-a-url", PropertyType.URL)

    def test_validate_and_convert_object_invalid(self):
        """Test object validation with invalid type."""
        doc = DocumentGenerator()
        with pytest.raises(ValueError, match="Expected object"):
            doc._validate_and_convert("string", PropertyType.OBJECT)

    def test_validate_and_convert_array_single_value(self):
        """Test array conversion with single value."""
        doc = DocumentGenerator()
        result = doc._validate_and_convert("single", PropertyType.ARRAY)
        assert result == ["single"]

    def test_add_nested_schema(self):
        """Test adding nested schema."""
        doc = DocumentGenerator()
        person = PersonGenerator()
        person.set_name(name="John Doe")

        doc.add_nested_schema("author", person)

        assert doc.data["author"]["@type"] == "Person"
        assert doc.data["author"]["name"] == "John Doe"

    def test_add_person_auto_id(self):
        """Test adding person with auto-generated ID."""
        doc = DocumentGenerator()
        doc.add_person("author", "John Doe")

        assert doc.data["author"]["@id"].startswith("urn:uuid:")

    def test_add_person_custom_id(self):
        """Test adding person with custom ID."""
        doc = DocumentGenerator()
        doc.add_person("author", "John Doe", person_id="urn:sha256:custom")

        assert doc.data["author"]["@id"] == "urn:sha256:custom"

    def test_add_organization_with_logo(self):
        """Test adding organization with logo."""
        doc = DocumentGenerator()
        doc.add_organization(
            "publisher",
            "Test Org",
            logo="https://example.com/logo.png"
        )

        assert "logo" in doc.data["publisher"]
        assert doc.data["publisher"]["logo"]["@type"] == "ImageObject"

    def test_add_place_with_geo(self):
        """Test adding place with geo coordinates."""
        doc = DocumentGenerator()
        doc.add_place(
            "contentLocation",
            "Test Location",
            geo={"latitude": 37.7749, "longitude": -122.4194}
        )

        assert doc.data["contentLocation"]["geo"]["@type"] == "GeoCoordinates"
        assert doc.data["contentLocation"]["geo"]["latitude"] == 37.7749

    def test_set_identifier_with_property_id(self):
        """Test setting identifier with property ID."""
        doc = DocumentGenerator()
        doc.set_identifier("abc123", property_id="sha256")

        assert doc.data["identifier"]["@type"] == "PropertyValue"
        assert doc.data["identifier"]["propertyID"] == "sha256"

    def test_set_identifier_simple(self):
        """Test setting simple identifier."""
        doc = DocumentGenerator()
        doc.set_identifier("abc123")

        assert doc.data["identifier"] == "abc123"

    def test_add_keywords_string(self):
        """Test adding keywords as string."""
        doc = DocumentGenerator()
        doc.add_keywords("test, keywords")

        assert doc.data["keywords"] == "test, keywords"

    def test_add_keywords_list(self):
        """Test adding keywords as list."""
        doc = DocumentGenerator()
        doc.add_keywords(["test", "keywords"])

        assert doc.data["keywords"] == "test, keywords"

    def test_set_dates(self):
        """Test setting dates."""
        doc = DocumentGenerator()
        now = datetime.now()
        doc.set_dates(created=now, modified=now, published=now)

        assert "dateCreated" in doc.data
        assert "dateModified" in doc.data
        assert "datePublished" in doc.data

    def test_add_relationship_string(self):
        """Test adding relationship with string."""
        doc = DocumentGenerator()
        doc.add_relationship("isPartOf", "https://example.com/collection")

        assert doc.data["isPartOf"] == "https://example.com/collection"

    def test_add_relationship_schema(self):
        """Test adding relationship with schema."""
        doc = DocumentGenerator()
        parent = DocumentGenerator()
        parent.set_basic_info("Parent Doc")

        doc.add_relationship("isPartOf", parent)

        assert doc.data["isPartOf"]["name"] == "Parent Doc"

    def test_to_dict(self):
        """Test converting to dictionary."""
        doc = DocumentGenerator()
        doc.set_basic_info("Test")

        data = doc.to_dict()

        assert isinstance(data, dict)
        assert data["name"] == "Test"
        # Verify it's a copy
        data["name"] = "Modified"
        assert doc.data["name"] == "Test"

    def test_to_json_ld(self):
        """Test converting to JSON-LD string."""
        doc = DocumentGenerator()
        doc.set_basic_info("Test")

        json_ld = doc.to_json_ld()

        assert '"@context"' in json_ld
        assert '"@type"' in json_ld
        assert '"name": "Test"' in json_ld

    def test_to_json_ld_script(self):
        """Test converting to JSON-LD script tag."""
        doc = DocumentGenerator()
        doc.set_basic_info("Test")

        script = doc.to_json_ld_script()

        assert '<script type="application/ld+json">' in script
        assert '</script>' in script

    def test_validate_required_properties(self):
        """Test validating required properties."""
        doc = DocumentGenerator()
        missing = doc.validate_required_properties()

        assert "name" in missing
        assert "encodingFormat" in missing

    def test_validate_required_properties_complete(self):
        """Test validating with all required properties."""
        doc = DocumentGenerator()
        doc.set_basic_info("Test")
        doc.set_file_info("application/pdf", "https://example.com/test.pdf")

        missing = doc.validate_required_properties()

        assert len(missing) == 0

    def test_get_completion_score_empty(self):
        """Test completion score for empty schema."""
        doc = DocumentGenerator()
        score = doc.get_completion_score()

        assert score == 0.0

    def test_get_completion_score_partial(self):
        """Test completion score for partial schema."""
        doc = DocumentGenerator()
        doc.set_basic_info("Test")

        score = doc.get_completion_score()

        assert 0.0 < score < 1.0

    def test_get_completion_score_full(self):
        """Test completion score for full schema."""
        doc = DocumentGenerator()
        doc.set_basic_info("Test")
        doc.set_file_info("application/pdf", "https://example.com/test.pdf")

        score = doc.get_completion_score()

        assert score == 1.0

    def test_str_representation(self):
        """Test string representation."""
        doc = DocumentGenerator()
        doc.set_basic_info("Test")

        result = str(doc)

        assert '"name": "Test"' in result

    def test_repr_representation(self):
        """Test repr representation."""
        doc = DocumentGenerator()

        result = repr(doc)

        assert "DocumentGenerator" in result
        assert "DigitalDocument" in result
