"""
Specialized Schema.org generators for different file types.

Each generator is optimized for specific file types and includes
appropriate properties and nested schemas.
"""

from typing import List, Optional, Tuple

try:
    from .base import SchemaOrgBase
except ImportError:
    from base import SchemaOrgBase

# =============================================================================
# Required Properties Constants
# =============================================================================

DOCUMENT_REQUIRED_PROPERTIES: Tuple[str, ...] = (
    "name",
    "encodingFormat",
)

IMAGE_REQUIRED_PROPERTIES: Tuple[str, ...] = (
    "contentUrl",
    "encodingFormat",
)

VIDEO_REQUIRED_PROPERTIES: Tuple[str, ...] = (
    "name",
    "contentUrl",
    "uploadDate",
)

AUDIO_REQUIRED_PROPERTIES: Tuple[str, ...] = (
    "name",
    "contentUrl",
)

CODE_REQUIRED_PROPERTIES: Tuple[str, ...] = (
    "name",
    "programmingLanguage",
)

DATASET_REQUIRED_PROPERTIES: Tuple[str, ...] = (
    "name",
    "description",
)

ARCHIVE_REQUIRED_PROPERTIES: Tuple[str, ...] = (
    "name",
    "encodingFormat",
)


# =============================================================================
# Recommended Properties Constants
# =============================================================================

DOCUMENT_RECOMMENDED_PROPERTIES: Tuple[str, ...] = (
    "author",
    "dateCreated",
    "dateModified",
    "keywords",
    "abstract",
    "inLanguage",
    "contentSize",
    "url",
)

IMAGE_RECOMMENDED_PROPERTIES: Tuple[str, ...] = (
    "name",
    "description",
    "width",
    "height",
    "caption",
    "creator",
    "dateCreated",
    "exifData",
    "contentLocation",
)

VIDEO_RECOMMENDED_PROPERTIES: Tuple[str, ...] = (
    "description",
    "thumbnailUrl",
    "duration",
    "width",
    "height",
    "encodingFormat",
    "creator",
    "datePublished",
)

AUDIO_RECOMMENDED_PROPERTIES: Tuple[str, ...] = (
    "description",
    "duration",
    "encodingFormat",
    "creator",
    "datePublished",
    "inLanguage",
)

CODE_RECOMMENDED_PROPERTIES: Tuple[str, ...] = (
    "description",
    "author",
    "dateCreated",
    "dateModified",
    "codeRepository",
    "license",
    "runtimePlatform",
)

DATASET_RECOMMENDED_PROPERTIES: Tuple[str, ...] = (
    "creator",
    "datePublished",
    "distribution",
    "keywords",
    "license",
    "spatial",
    "temporal",
    "variableMeasured",
)

ARCHIVE_RECOMMENDED_PROPERTIES: Tuple[str, ...] = (
    "description",
    "hasPart",
    "dateCreated",
    "contentSize",
)

ORGANIZATION_REQUIRED_PROPERTIES: Tuple[str, ...] = (
    "name",
)

ORGANIZATION_RECOMMENDED_PROPERTIES: Tuple[str, ...] = (
    "description",
    "url",
    "logo",
    "email",
    "telephone",
    "address",
    "legalName",
    "foundingDate",
    "founder",
    "numberOfEmployees",
    "areaServed",
    "sameAs",
)

PERSON_REQUIRED_PROPERTIES: Tuple[str, ...] = (
    "name",
)

PERSON_RECOMMENDED_PROPERTIES: Tuple[str, ...] = (
    "givenName",
    "familyName",
    "email",
    "telephone",
    "jobTitle",
    "worksFor",
    "address",
    "image",
    "url",
    "sameAs",
    "birthDate",
    "nationality",
)


class DocumentGenerator(SchemaOrgBase):
    """
    Generator for document files (PDFs, Word docs, text files).

    Supports: DigitalDocument, Article, Report, ScholarlyArticle
    """

    def __init__(self, document_type: str = "DigitalDocument", entity_id: Optional[str] = None):
        """
        Initialize document generator.

        Args:
            document_type: Specific document type (DigitalDocument, Article, Report, etc.)
            entity_id: Optional entity ID for @id field. If not provided, generates UUID v4.
        """
        super().__init__(document_type, entity_id=entity_id)
        self.document_type = document_type

    def get_required_properties(self) -> List[str]:
        """Required properties for documents."""
        return list(DOCUMENT_REQUIRED_PROPERTIES)

    def get_recommended_properties(self) -> List[str]:
        """Recommended properties for documents."""
        return list(DOCUMENT_RECOMMENDED_PROPERTIES)


class ImageGenerator(SchemaOrgBase):
    """
    Generator for image files.

    Supports: ImageObject, Photograph
    """

    def __init__(self, image_type: str = "ImageObject", entity_id: Optional[str] = None):
        """
        Initialize image generator.

        Args:
            image_type: Specific image type (ImageObject, Photograph)
            entity_id: Optional entity ID for @id field. If not provided, generates UUID v4.
        """
        super().__init__(image_type, entity_id=entity_id)

    def get_required_properties(self) -> List[str]:
        """Required properties for images."""
        return list(IMAGE_REQUIRED_PROPERTIES)

    def get_recommended_properties(self) -> List[str]:
        """Recommended properties for images."""
        return list(IMAGE_RECOMMENDED_PROPERTIES)

    def set_thumbnail(self, thumbnail_url: str) -> 'ImageGenerator':
        """
        Set thumbnail image.

        Args:
            thumbnail_url: Thumbnail URL

        Returns:
            Self for method chaining
        """
        self.data["thumbnail"] = {
            "@type": "ImageObject",
            "contentUrl": thumbnail_url
        }
        return self


class VideoGenerator(SchemaOrgBase):
    """
    Generator for video files.

    Supports: VideoObject, MovieClip
    """

    def __init__(self, video_type: str = "VideoObject", entity_id: Optional[str] = None):
        """
        Initialize video generator.

        Args:
            video_type: Specific video type (VideoObject, MovieClip)
            entity_id: Optional entity ID for @id field. If not provided, generates UUID v4.
        """
        super().__init__(video_type, entity_id=entity_id)

    def get_required_properties(self) -> List[str]:
        """Required properties for videos."""
        return list(VIDEO_REQUIRED_PROPERTIES)

    def get_recommended_properties(self) -> List[str]:
        """Recommended properties for videos."""
        return list(VIDEO_RECOMMENDED_PROPERTIES)

    def set_interaction_stats(self, view_count: Optional[int] = None,
                              comment_count: Optional[int] = None) -> 'VideoGenerator':
        """
        Set interaction statistics.

        Args:
            view_count: Number of views
            comment_count: Number of comments

        Returns:
            Self for method chaining
        """
        interaction_statistic = []
        if view_count is not None:
            interaction_statistic.append({
                "@type": "InteractionCounter",
                "interactionType": "https://schema.org/WatchAction",
                "userInteractionCount": view_count
            })
        if comment_count is not None:
            interaction_statistic.append({
                "@type": "InteractionCounter",
                "interactionType": "https://schema.org/CommentAction",
                "userInteractionCount": comment_count
            })
        if interaction_statistic:
            self.data["interactionStatistic"] = interaction_statistic
        return self


class AudioGenerator(SchemaOrgBase):
    """
    Generator for audio files.

    Supports: AudioObject, MusicRecording, PodcastEpisode
    """

    def __init__(self, audio_type: str = "AudioObject", entity_id: Optional[str] = None):
        """
        Initialize audio generator.

        Args:
            audio_type: Specific audio type (AudioObject, MusicRecording, PodcastEpisode)
            entity_id: Optional entity ID for @id field. If not provided, generates UUID v4.
        """
        super().__init__(audio_type, entity_id=entity_id)

    def get_required_properties(self) -> List[str]:
        """Required properties for audio."""
        return list(AUDIO_REQUIRED_PROPERTIES)

    def get_recommended_properties(self) -> List[str]:
        """Recommended properties for audio."""
        return list(AUDIO_RECOMMENDED_PROPERTIES)


class CodeGenerator(SchemaOrgBase):
    """
    Generator for source code files.

    Supports: SoftwareSourceCode, CreativeWork
    """

    def __init__(self, entity_id: Optional[str] = None):
        """
        Initialize code generator.

        Args:
            entity_id: Optional entity ID for @id field. If not provided, generates UUID v4.
        """
        super().__init__("SoftwareSourceCode", entity_id=entity_id)

    def get_required_properties(self) -> List[str]:
        """Required properties for source code."""
        return list(CODE_REQUIRED_PROPERTIES)

    def get_recommended_properties(self) -> List[str]:
        """Recommended properties for source code."""
        return list(CODE_RECOMMENDED_PROPERTIES)


class DatasetGenerator(SchemaOrgBase):
    """
    Generator for dataset files.

    Supports: Dataset
    """

    def __init__(self, entity_id: Optional[str] = None):
        """
        Initialize dataset generator.

        Args:
            entity_id: Optional entity ID for @id field. If not provided, generates UUID v4.
        """
        super().__init__("Dataset", entity_id=entity_id)

    def get_required_properties(self) -> List[str]:
        """Required properties for datasets."""
        return list(DATASET_REQUIRED_PROPERTIES)

    def get_recommended_properties(self) -> List[str]:
        """Recommended properties for datasets."""
        return list(DATASET_RECOMMENDED_PROPERTIES)


class ArchiveGenerator(SchemaOrgBase):
    """
    Generator for archive files (ZIP, TAR, etc.).

    Supports: DigitalDocument with hasPart relationships
    """

    def __init__(self, entity_id: Optional[str] = None):
        """
        Initialize archive generator.

        Args:
            entity_id: Optional entity ID for @id field. If not provided, generates UUID v4.
        """
        super().__init__("DigitalDocument", entity_id=entity_id)
        self.data["additionalType"] = "Archive"

    def get_required_properties(self) -> List[str]:
        """Required properties for archives."""
        return list(ARCHIVE_REQUIRED_PROPERTIES)

    def get_recommended_properties(self) -> List[str]:
        """Recommended properties for archives."""
        return list(ARCHIVE_RECOMMENDED_PROPERTIES)


class OrganizationGenerator(SchemaOrgBase):
    """
    Generator for organizations.

    Supports: Organization, Corporation, LocalBusiness, NGO, EducationalOrganization
    """

    def __init__(self, org_type: str = "Organization", entity_id: Optional[str] = None):
        """
        Initialize organization generator.

        Args:
            org_type: Specific organization type (Organization, Corporation, LocalBusiness, etc.)
            entity_id: Optional entity ID for @id field. If not provided, generates UUID v4.
        """
        super().__init__(org_type, entity_id=entity_id)

    def get_required_properties(self) -> List[str]:
        """Required properties for organizations."""
        return list(ORGANIZATION_REQUIRED_PROPERTIES)

    def get_recommended_properties(self) -> List[str]:
        """Recommended properties for organizations."""
        return list(ORGANIZATION_RECOMMENDED_PROPERTIES)


class PersonGenerator(SchemaOrgBase):
    """
    Generator for people.

    Supports: Person
    """

    def __init__(self, entity_id: Optional[str] = None):
        """
        Initialize person generator.

        Args:
            entity_id: Optional entity ID for @id field. If not provided, generates UUID v4.
        """
        super().__init__("Person", entity_id=entity_id)

    def get_required_properties(self) -> List[str]:
        """Required properties for people."""
        return list(PERSON_REQUIRED_PROPERTIES)

    def get_recommended_properties(self) -> List[str]:
        """Recommended properties for people."""
        return list(PERSON_RECOMMENDED_PROPERTIES)
