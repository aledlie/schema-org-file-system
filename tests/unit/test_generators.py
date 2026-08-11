"""
Unit tests for Schema.org generators.

Tests all generator classes for proper Schema.org compliance,
including OrganizationGenerator and PersonGenerator.
"""

import pytest
from datetime import datetime

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
    IMAGE_REQUIRED_PROPERTIES,
    VIDEO_REQUIRED_PROPERTIES,
    ORGANIZATION_REQUIRED_PROPERTIES,
    ORGANIZATION_RECOMMENDED_PROPERTIES,
    PERSON_REQUIRED_PROPERTIES,
    PERSON_RECOMMENDED_PROPERTIES,
)
from src.base import PropertyType, SchemaContext

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


# =============================================================================
# Test CodeGenerator
# =============================================================================


class TestCodeGenerator:
    """Test CodeGenerator class."""

    def test_basic_creation(self):
        """Test creating a basic code schema."""
        code = CodeGenerator()
        assert code.data["@type"] == "SoftwareSourceCode"


# =============================================================================
# Test DatasetGenerator
# =============================================================================


class TestDatasetGenerator:
    """Test DatasetGenerator class."""

    def test_basic_creation(self):
        """Test creating a basic dataset."""
        dataset = DatasetGenerator()
        assert dataset.data["@type"] == "Dataset"


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

    def test_set_dates(self):
        """Test setting dates."""
        doc = DocumentGenerator()
        now = datetime.now()
        doc.set_dates(created=now, modified=now, published=now)

        assert "dateCreated" in doc.data
        assert "dateModified" in doc.data
        assert "datePublished" in doc.data

    def test_to_dict(self):
        """Test converting to dictionary."""
        doc = DocumentGenerator()
        doc.set_property("name", "Test", PropertyType.TEXT)

        data = doc.to_dict()

        assert isinstance(data, dict)
        assert data["name"] == "Test"
        # Verify it's a copy
        data["name"] = "Modified"
        assert doc.data["name"] == "Test"

    def test_to_json_ld(self):
        """Test converting to JSON-LD string."""
        doc = DocumentGenerator()
        doc.set_property("name", "Test", PropertyType.TEXT)

        json_ld = doc.to_json_ld()

        assert '"@context"' in json_ld
        assert '"@type"' in json_ld
        assert '"name": "Test"' in json_ld

    def test_to_json_ld_script(self):
        """Test converting to JSON-LD script tag."""
        doc = DocumentGenerator()
        doc.set_property("name", "Test", PropertyType.TEXT)

        script = doc.to_json_ld_script()

        assert '<script type="application/ld+json">' in script
        assert "</script>" in script

    def test_validate_required_properties(self):
        """Test validating required properties."""
        doc = DocumentGenerator()
        missing = doc.validate_required_properties()

        assert "name" in missing
        assert "encodingFormat" in missing

    def test_validate_required_properties_complete(self):
        """Test validating with all required properties."""
        doc = DocumentGenerator()
        doc.set_property("name", "Test", PropertyType.TEXT)
        doc.set_property("encodingFormat", "application/pdf", PropertyType.TEXT)
        doc.set_property("url", "https://example.com/test.pdf", PropertyType.URL)

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
        doc.set_property("name", "Test", PropertyType.TEXT)

        score = doc.get_completion_score()

        assert 0.0 < score < 1.0

    def test_get_completion_score_full(self):
        """Test completion score for full schema."""
        doc = DocumentGenerator()
        doc.set_property("name", "Test", PropertyType.TEXT)
        doc.set_property("encodingFormat", "application/pdf", PropertyType.TEXT)
        doc.set_property("url", "https://example.com/test.pdf", PropertyType.URL)

        score = doc.get_completion_score()

        assert score == 1.0

    def test_str_representation(self):
        """Test string representation."""
        doc = DocumentGenerator()
        doc.set_property("name", "Test", PropertyType.TEXT)

        result = str(doc)

        assert '"name": "Test"' in result

    def test_repr_representation(self):
        """Test repr representation."""
        doc = DocumentGenerator()

        result = repr(doc)

        assert "DocumentGenerator" in result
        assert "DigitalDocument" in result
