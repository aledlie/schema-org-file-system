"""
Specialized Schema.org generators for different file types.

Each generator is optimized for specific file types and includes
appropriate properties and nested schemas.
"""

from typing import Any, Dict, List, Optional, Tuple, Union
from datetime import datetime

try:
    from .base import SchemaOrgBase, PropertyType
except ImportError:
    from base import SchemaOrgBase, PropertyType


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

    def set_basic_info(self, name: str, description: Optional[str] = None,
                      abstract: Optional[str] = None) -> 'DocumentGenerator':
        """
        Set basic document information.

        Args:
            name: Document name/title
            description: Document description
            abstract: Document abstract/summary

        Returns:
            Self for method chaining
        """
        self.set_property("name", name, PropertyType.TEXT)
        if description:
            self.set_property("description", description, PropertyType.TEXT)
        if abstract:
            self.set_property("abstract", abstract, PropertyType.TEXT)
        return self

    def set_file_info(self, encoding_format: str, url: str,
                     content_size: Optional[int] = None,
                     sha256: Optional[str] = None) -> 'DocumentGenerator':
        """
        Set file-specific information.

        Args:
            encoding_format: MIME type (e.g., 'application/pdf')
            url: File URL or path
            content_size: File size in bytes
            sha256: SHA-256 hash for integrity verification

        Returns:
            Self for method chaining
        """
        self.set_property("encodingFormat", encoding_format, PropertyType.TEXT)
        self.set_property("url", url, PropertyType.URL)
        if content_size:
            self.set_property("contentSize", f"{content_size}B", PropertyType.TEXT)
        if sha256:
            self.set_identifier(sha256, "sha256")
        return self

    def set_language(self, language: str) -> 'DocumentGenerator':
        """
        Set document language.

        Args:
            language: Language code (e.g., 'en', 'es', 'fr')

        Returns:
            Self for method chaining
        """
        self.set_property("inLanguage", language, PropertyType.TEXT)
        return self

    def set_pagination(self, page_count: int) -> 'DocumentGenerator':
        """
        Set document pagination.

        Args:
            page_count: Number of pages

        Returns:
            Self for method chaining
        """
        self.set_property("numberOfPages", page_count, PropertyType.INTEGER)
        return self

    def add_citation(self, citation: Union[str, Dict[str, Any]]) -> 'DocumentGenerator':
        """
        Add citation.

        Args:
            citation: Citation string or CreativeWork schema

        Returns:
            Self for method chaining
        """
        if "citation" not in self.data:
            self.data["citation"] = []
        if isinstance(self.data["citation"], str):
            self.data["citation"] = [self.data["citation"]]
        self.data["citation"].append(citation)
        return self

    def set_scholarly_info(self, doi: Optional[str] = None,
                          issn: Optional[str] = None,
                          publication: Optional[str] = None) -> 'DocumentGenerator':
        """
        Set scholarly article information.

        Args:
            doi: Digital Object Identifier
            issn: International Standard Serial Number
            publication: Publication name

        Returns:
            Self for method chaining
        """
        if doi:
            self.set_property("sameAs", f"https://doi.org/{doi}", PropertyType.URL)
        if issn:
            self.set_property("issn", issn, PropertyType.TEXT)
        if publication:
            self.set_property("publication", publication, PropertyType.TEXT)
        return self


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

    def set_basic_info(self, name: str, content_url: str,
                      encoding_format: str,
                      description: Optional[str] = None,
                      caption: Optional[str] = None) -> 'ImageGenerator':
        """
        Set basic image information.

        Args:
            name: Image name
            content_url: Image URL
            encoding_format: MIME type (e.g., 'image/jpeg')
            description: Image description
            caption: Image caption

        Returns:
            Self for method chaining
        """
        self.set_property("name", name, PropertyType.TEXT)
        self.set_property("contentUrl", content_url, PropertyType.URL)
        self.set_property("encodingFormat", encoding_format, PropertyType.TEXT)
        if description:
            self.set_property("description", description, PropertyType.TEXT)
        if caption:
            self.set_property("caption", caption, PropertyType.TEXT)
        return self

    def set_dimensions(self, width: int, height: int) -> 'ImageGenerator':
        """
        Set image dimensions.

        Args:
            width: Image width in pixels
            height: Image height in pixels

        Returns:
            Self for method chaining
        """
        self.set_property("width", width, PropertyType.INTEGER)
        self.set_property("height", height, PropertyType.INTEGER)
        return self

    def set_exif_data(self, exif: Dict[str, Any]) -> 'ImageGenerator':
        """
        Set EXIF metadata.

        Args:
            exif: EXIF data dictionary

        Returns:
            Self for method chaining
        """
        exif_data = {
            "@type": "PropertyValue"
        }

        # Map common EXIF fields
        if "Make" in exif:
            exif_data["camera"] = exif["Make"]
        if "Model" in exif:
            exif_data["cameraModel"] = exif["Model"]
        if "DateTime" in exif:
            self.set_property("dateCreated", exif["DateTime"], PropertyType.DATETIME)
        if "GPSLatitude" in exif and "GPSLongitude" in exif:
            self.add_place("contentLocation", "Photo Location",
                         geo={
                             "latitude": exif["GPSLatitude"],
                             "longitude": exif["GPSLongitude"]
                         })

        self.data["exifData"] = exif_data
        return self

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

    def add_depicted_item(self, item: Union[str, Dict[str, Any]]) -> 'ImageGenerator':
        """
        Add item depicted in the image.

        Args:
            item: Thing name or schema

        Returns:
            Self for method chaining
        """
        if "associatedMedia" not in self.data:
            self.data["associatedMedia"] = []
        self.data["associatedMedia"].append(item)
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

    def set_basic_info(self, name: str, content_url: str,
                      upload_date: datetime,
                      description: Optional[str] = None,
                      thumbnail_url: Optional[str] = None) -> 'VideoGenerator':
        """
        Set basic video information.

        Args:
            name: Video name
            content_url: Video URL
            upload_date: Upload date
            description: Video description
            thumbnail_url: Thumbnail URL

        Returns:
            Self for method chaining
        """
        self.set_property("name", name, PropertyType.TEXT)
        self.set_property("contentUrl", content_url, PropertyType.URL)
        self.set_property("uploadDate", upload_date, PropertyType.DATETIME)
        if description:
            self.set_property("description", description, PropertyType.TEXT)
        if thumbnail_url:
            self.set_property("thumbnailUrl", thumbnail_url, PropertyType.URL)
        return self

    def set_media_details(self, duration: str, width: int, height: int,
                         encoding_format: str,
                         bitrate: Optional[str] = None) -> 'VideoGenerator':
        """
        Set video media details.

        Args:
            duration: Duration in ISO 8601 format (e.g., 'PT1M30S')
            width: Video width in pixels
            height: Video height in pixels
            encoding_format: MIME type (e.g., 'video/mp4')
            bitrate: Bitrate (e.g., '1200kbps')

        Returns:
            Self for method chaining
        """
        self.set_property("duration", duration, PropertyType.TEXT)
        self.set_property("width", width, PropertyType.INTEGER)
        self.set_property("height", height, PropertyType.INTEGER)
        self.set_property("encodingFormat", encoding_format, PropertyType.TEXT)
        if bitrate:
            self.set_property("bitrate", bitrate, PropertyType.TEXT)
        return self

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

    def set_basic_info(self, name: str, content_url: str,
                      description: Optional[str] = None,
                      duration: Optional[str] = None) -> 'AudioGenerator':
        """
        Set basic audio information.

        Args:
            name: Audio name
            content_url: Audio URL
            description: Audio description
            duration: Duration in ISO 8601 format

        Returns:
            Self for method chaining
        """
        self.set_property("name", name, PropertyType.TEXT)
        self.set_property("contentUrl", content_url, PropertyType.URL)
        if description:
            self.set_property("description", description, PropertyType.TEXT)
        if duration:
            self.set_property("duration", duration, PropertyType.TEXT)
        return self

    def set_music_info(self, album: Optional[str] = None,
                      artist: Optional[str] = None,
                      genre: Optional[str] = None,
                      isrc: Optional[str] = None) -> 'AudioGenerator':
        """
        Set music recording information.

        Args:
            album: Album name
            artist: Artist name
            genre: Music genre
            isrc: International Standard Recording Code

        Returns:
            Self for method chaining
        """
        if album:
            self.data["inAlbum"] = {
                "@type": "MusicAlbum",
                "name": album
            }
        if artist:
            self.add_person("byArtist", artist)
        if genre:
            self.set_property("genre", genre, PropertyType.TEXT)
        if isrc:
            self.set_property("isrcCode", isrc, PropertyType.TEXT)
        return self

    def set_podcast_info(self, episode_number: Optional[int] = None,
                        series: Optional[str] = None) -> 'AudioGenerator':
        """
        Set podcast episode information.

        Args:
            episode_number: Episode number
            series: Podcast series name

        Returns:
            Self for method chaining
        """
        if episode_number is not None:
            self.set_property("episodeNumber", episode_number, PropertyType.INTEGER)
        if series:
            self.data["partOfSeries"] = {
                "@type": "PodcastSeries",
                "name": series
            }
        return self


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

    def set_basic_info(self, name: str, programming_language: str,
                      description: Optional[str] = None,
                      code_sample: Optional[str] = None) -> 'CodeGenerator':
        """
        Set basic code information.

        Args:
            name: File/module name
            programming_language: Programming language
            description: Code description
            code_sample: Sample code snippet

        Returns:
            Self for method chaining
        """
        self.set_property("name", name, PropertyType.TEXT)
        self.set_property("programmingLanguage", programming_language, PropertyType.TEXT)
        if description:
            self.set_property("description", description, PropertyType.TEXT)
        if code_sample:
            self.set_property("codeSampleType", "code snippet", PropertyType.TEXT)
            self.set_property("text", code_sample, PropertyType.TEXT)
        return self

    def set_repository_info(self, repository_url: str,
                          branch: Optional[str] = None,
                          commit: Optional[str] = None) -> 'CodeGenerator':
        """
        Set repository information.

        Args:
            repository_url: Repository URL
            branch: Branch name
            commit: Commit hash

        Returns:
            Self for method chaining
        """
        self.set_property("codeRepository", repository_url, PropertyType.URL)
        if branch:
            self.set_property("branch", branch, PropertyType.TEXT)
        if commit:
            self.set_identifier(commit, "git-commit")
        return self

    def set_runtime_info(self, runtime_platform: Union[str, List[str]],
                        target_product: Optional[str] = None) -> 'CodeGenerator':
        """
        Set runtime information.

        Args:
            runtime_platform: Runtime platform(s)
            target_product: Target product/framework

        Returns:
            Self for method chaining
        """
        if isinstance(runtime_platform, list):
            runtime_platform = ", ".join(runtime_platform)
        self.set_property("runtimePlatform", runtime_platform, PropertyType.TEXT)
        if target_product:
            self.set_property("targetProduct", target_product, PropertyType.TEXT)
        return self

    def add_dependency(self, name: str, version: Optional[str] = None) -> 'CodeGenerator':
        """
        Add a code dependency.

        Args:
            name: Dependency name
            version: Dependency version

        Returns:
            Self for method chaining
        """
        if "dependencies" not in self.data:
            self.data["dependencies"] = []

        dependency = {"@type": "SoftwareApplication", "name": name}
        if version:
            dependency["softwareVersion"] = version

        self.data["dependencies"].append(dependency)
        return self


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

    def set_basic_info(self, name: str, description: str,
                      url: Optional[str] = None) -> 'DatasetGenerator':
        """
        Set basic dataset information.

        Args:
            name: Dataset name
            description: Dataset description
            url: Dataset URL

        Returns:
            Self for method chaining
        """
        self.set_property("name", name, PropertyType.TEXT)
        self.set_property("description", description, PropertyType.TEXT)
        if url:
            self.set_property("url", url, PropertyType.URL)
        return self

    def add_distribution(self, content_url: str, encoding_format: str,
                        content_size: Optional[int] = None) -> 'DatasetGenerator':
        """
        Add dataset distribution.

        Args:
            content_url: Distribution URL
            encoding_format: File format (e.g., 'text/csv', 'application/json')
            content_size: File size in bytes

        Returns:
            Self for method chaining
        """
        if "distribution" not in self.data:
            self.data["distribution"] = []

        distribution = {
            "@type": "DataDownload",
            "contentUrl": content_url,
            "encodingFormat": encoding_format
        }
        if content_size:
            distribution["contentSize"] = f"{content_size}B"

        self.data["distribution"].append(distribution)
        return self

    def set_coverage(self, temporal: Optional[str] = None,
                    spatial: Optional[str] = None) -> 'DatasetGenerator':
        """
        Set dataset coverage.

        Args:
            temporal: Temporal coverage (e.g., '2020-01-01/2020-12-31')
            spatial: Spatial coverage (place name or coordinates)

        Returns:
            Self for method chaining
        """
        if temporal:
            self.set_property("temporalCoverage", temporal, PropertyType.TEXT)
        if spatial:
            self.set_property("spatialCoverage", spatial, PropertyType.TEXT)
        return self

    def add_variable_measured(self, variable: str,
                            description: Optional[str] = None) -> 'DatasetGenerator':
        """
        Add measured variable.

        Args:
            variable: Variable name
            description: Variable description

        Returns:
            Self for method chaining
        """
        if "variableMeasured" not in self.data:
            self.data["variableMeasured"] = []

        var_obj = {
            "@type": "PropertyValue",
            "name": variable
        }
        if description:
            var_obj["description"] = description

        self.data["variableMeasured"].append(var_obj)
        return self


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

    def set_basic_info(self, name: str, encoding_format: str,
                      description: Optional[str] = None,
                      content_size: Optional[int] = None) -> 'ArchiveGenerator':
        """
        Set basic archive information.

        Args:
            name: Archive name
            encoding_format: Archive format (e.g., 'application/zip')
            description: Archive description
            content_size: Archive size in bytes

        Returns:
            Self for method chaining
        """
        self.set_property("name", name, PropertyType.TEXT)
        self.set_property("encodingFormat", encoding_format, PropertyType.TEXT)
        if description:
            self.set_property("description", description, PropertyType.TEXT)
        if content_size:
            self.set_property("contentSize", f"{content_size}B", PropertyType.TEXT)
        return self

    def add_contained_file(self, file_schema: SchemaOrgBase) -> 'ArchiveGenerator':
        """
        Add a file contained in the archive.

        Args:
            file_schema: Schema for contained file

        Returns:
            Self for method chaining
        """
        if "hasPart" not in self.data:
            self.data["hasPart"] = []
        self.data["hasPart"].append(file_schema.to_dict())
        return self

    def set_compression_info(self, compression_method: str,
                           compression_ratio: Optional[float] = None) -> 'ArchiveGenerator':
        """
        Set compression information.

        Args:
            compression_method: Compression method used
            compression_ratio: Compression ratio

        Returns:
            Self for method chaining
        """
        self.set_property("compressionMethod", compression_method, PropertyType.TEXT)
        if compression_ratio:
            self.set_property("compressionRatio", compression_ratio, PropertyType.NUMBER)
        return self


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

    def set_basic_info(self, name: str, description: Optional[str] = None,
                      url: Optional[str] = None,
                      logo: Optional[str] = None) -> 'OrganizationGenerator':
        """
        Set basic organization information.

        Args:
            name: Organization name
            description: Organization description
            url: Organization website URL
            logo: Logo image URL

        Returns:
            Self for method chaining
        """
        self.set_property("name", name, PropertyType.TEXT)
        if description:
            self.set_property("description", description, PropertyType.TEXT)
        if url:
            self.set_property("url", url, PropertyType.URL)
        if logo:
            self.data["logo"] = {
                "@type": "ImageObject",
                "url": logo
            }
        return self

    def set_legal_info(self, legal_name: Optional[str] = None,
                      tax_id: Optional[str] = None,
                      vat_id: Optional[str] = None,
                      lei_code: Optional[str] = None,
                      duns: Optional[str] = None) -> 'OrganizationGenerator':
        """
        Set legal and identification information.

        Args:
            legal_name: Official registered name
            tax_id: Tax/Fiscal ID number
            vat_id: Value-added Tax ID
            lei_code: Legal entity identifier (ISO 17442)
            duns: Dun & Bradstreet DUNS number

        Returns:
            Self for method chaining
        """
        if legal_name:
            self.set_property("legalName", legal_name, PropertyType.TEXT)
        if tax_id:
            self.set_property("taxID", tax_id, PropertyType.TEXT)
        if vat_id:
            self.set_property("vatID", vat_id, PropertyType.TEXT)
        if lei_code:
            self.set_property("leiCode", lei_code, PropertyType.TEXT)
        if duns:
            self.set_property("duns", duns, PropertyType.TEXT)
        return self

    def set_contact_info(self, email: Optional[str] = None,
                        telephone: Optional[str] = None,
                        fax: Optional[str] = None) -> 'OrganizationGenerator':
        """
        Set contact information.

        Args:
            email: Contact email address
            telephone: Phone number
            fax: Fax number

        Returns:
            Self for method chaining
        """
        if email:
            self.set_property("email", email, PropertyType.TEXT)
        if telephone:
            self.set_property("telephone", telephone, PropertyType.TEXT)
        if fax:
            self.set_property("faxNumber", fax, PropertyType.TEXT)
        return self

    def set_address(self, street: Optional[str] = None,
                   city: Optional[str] = None,
                   region: Optional[str] = None,
                   postal_code: Optional[str] = None,
                   country: Optional[str] = None) -> 'OrganizationGenerator':
        """
        Set postal address.

        Args:
            street: Street address
            city: City/Locality
            region: State/Province/Region
            postal_code: Postal/ZIP code
            country: Country name or code

        Returns:
            Self for method chaining
        """
        address = {"@type": "PostalAddress"}
        if street:
            address["streetAddress"] = street
        if city:
            address["addressLocality"] = city
        if region:
            address["addressRegion"] = region
        if postal_code:
            address["postalCode"] = postal_code
        if country:
            address["addressCountry"] = country

        if len(address) > 1:  # More than just @type
            self.data["address"] = address
        return self

    def set_founding_info(self, founding_date: Optional[str] = None,
                         dissolution_date: Optional[str] = None,
                         founding_location: Optional[str] = None) -> 'OrganizationGenerator':
        """
        Set founding information.

        Args:
            founding_date: Date organization was founded (ISO 8601)
            dissolution_date: Date organization was dissolved (ISO 8601)
            founding_location: Place where organization was founded

        Returns:
            Self for method chaining
        """
        if founding_date:
            self.set_property("foundingDate", founding_date, PropertyType.DATE)
        if dissolution_date:
            self.set_property("dissolutionDate", dissolution_date, PropertyType.DATE)
        if founding_location:
            self.data["foundingLocation"] = {
                "@type": "Place",
                "name": founding_location
            }
        return self

    def add_founder(self, name: str, person_id: Optional[str] = None) -> 'OrganizationGenerator':
        """
        Add a founder.

        Args:
            name: Founder's name
            person_id: Optional @id for the person

        Returns:
            Self for method chaining
        """
        if "founder" not in self.data:
            self.data["founder"] = []

        founder = {
            "@type": "Person",
            "name": name
        }
        if person_id:
            founder["@id"] = person_id

        self.data["founder"].append(founder)
        return self

    def set_employee_count(self, count: int) -> 'OrganizationGenerator':
        """
        Set number of employees.

        Args:
            count: Number of employees

        Returns:
            Self for method chaining
        """
        self.data["numberOfEmployees"] = {
            "@type": "QuantitativeValue",
            "value": count
        }
        return self

    def set_area_served(self, areas: Union[str, List[str]]) -> 'OrganizationGenerator':
        """
        Set geographic areas served.

        Args:
            areas: Area name(s) or list of area names

        Returns:
            Self for method chaining
        """
        if isinstance(areas, str):
            self.set_property("areaServed", areas, PropertyType.TEXT)
        else:
            self.data["areaServed"] = [
                {"@type": "Place", "name": area} for area in areas
            ]
        return self

    def add_contact_point(self, contact_type: str,
                         telephone: Optional[str] = None,
                         email: Optional[str] = None,
                         available_language: Optional[Union[str, List[str]]] = None) -> 'OrganizationGenerator':
        """
        Add a contact point.

        Args:
            contact_type: Type of contact (e.g., 'customer service', 'sales', 'technical support')
            telephone: Phone number for this contact
            email: Email for this contact
            available_language: Language(s) available

        Returns:
            Self for method chaining
        """
        if "contactPoint" not in self.data:
            self.data["contactPoint"] = []

        contact = {
            "@type": "ContactPoint",
            "contactType": contact_type
        }
        if telephone:
            contact["telephone"] = telephone
        if email:
            contact["email"] = email
        if available_language:
            if isinstance(available_language, str):
                contact["availableLanguage"] = available_language
            else:
                contact["availableLanguage"] = available_language

        self.data["contactPoint"].append(contact)
        return self

    def add_same_as(self, urls: Union[str, List[str]]) -> 'OrganizationGenerator':
        """
        Add sameAs links (social profiles, Wikipedia, etc.).

        Args:
            urls: URL or list of URLs for equivalent pages

        Returns:
            Self for method chaining
        """
        if isinstance(urls, str):
            urls = [urls]

        if "sameAs" not in self.data:
            self.data["sameAs"] = []

        self.data["sameAs"].extend(urls)
        return self

    def set_parent_organization(self, name: str,
                               org_id: Optional[str] = None) -> 'OrganizationGenerator':
        """
        Set parent organization.

        Args:
            name: Parent organization name
            org_id: Optional @id for the parent organization

        Returns:
            Self for method chaining
        """
        parent = {
            "@type": "Organization",
            "name": name
        }
        if org_id:
            parent["@id"] = org_id

        self.data["parentOrganization"] = parent
        return self

    def add_department(self, name: str, dept_id: Optional[str] = None) -> 'OrganizationGenerator':
        """
        Add a department/sub-organization.

        Args:
            name: Department name
            dept_id: Optional @id for the department

        Returns:
            Self for method chaining
        """
        if "department" not in self.data:
            self.data["department"] = []

        dept = {
            "@type": "Organization",
            "name": name
        }
        if dept_id:
            dept["@id"] = dept_id

        self.data["department"].append(dept)
        return self


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

    def set_name(self, name: Optional[str] = None,
                given_name: Optional[str] = None,
                family_name: Optional[str] = None,
                additional_name: Optional[str] = None,
                honorific_prefix: Optional[str] = None,
                honorific_suffix: Optional[str] = None) -> 'PersonGenerator':
        """
        Set name information.

        Args:
            name: Full name
            given_name: First name
            family_name: Last name
            additional_name: Middle name or additional identifier
            honorific_prefix: Prefix (e.g., Dr., Mr., Ms.)
            honorific_suffix: Suffix (e.g., Jr., PhD, MD)

        Returns:
            Self for method chaining
        """
        if name:
            self.set_property("name", name, PropertyType.TEXT)
        if given_name:
            self.set_property("givenName", given_name, PropertyType.TEXT)
        if family_name:
            self.set_property("familyName", family_name, PropertyType.TEXT)
        if additional_name:
            self.set_property("additionalName", additional_name, PropertyType.TEXT)
        if honorific_prefix:
            self.set_property("honorificPrefix", honorific_prefix, PropertyType.TEXT)
        if honorific_suffix:
            self.set_property("honorificSuffix", honorific_suffix, PropertyType.TEXT)
        return self

    def set_contact_info(self, email: Optional[str] = None,
                        telephone: Optional[str] = None,
                        fax: Optional[str] = None) -> 'PersonGenerator':
        """
        Set contact information.

        Args:
            email: Email address
            telephone: Phone number
            fax: Fax number

        Returns:
            Self for method chaining
        """
        if email:
            self.set_property("email", email, PropertyType.TEXT)
        if telephone:
            self.set_property("telephone", telephone, PropertyType.TEXT)
        if fax:
            self.set_property("faxNumber", fax, PropertyType.TEXT)
        return self

    def set_address(self, street: Optional[str] = None,
                   city: Optional[str] = None,
                   region: Optional[str] = None,
                   postal_code: Optional[str] = None,
                   country: Optional[str] = None) -> 'PersonGenerator':
        """
        Set postal address.

        Args:
            street: Street address
            city: City/Locality
            region: State/Province/Region
            postal_code: Postal/ZIP code
            country: Country name or code

        Returns:
            Self for method chaining
        """
        address = {"@type": "PostalAddress"}
        if street:
            address["streetAddress"] = street
        if city:
            address["addressLocality"] = city
        if region:
            address["addressRegion"] = region
        if postal_code:
            address["postalCode"] = postal_code
        if country:
            address["addressCountry"] = country

        if len(address) > 1:  # More than just @type
            self.data["address"] = address
        return self

    def set_birth_info(self, birth_date: Optional[str] = None,
                      birth_place: Optional[str] = None) -> 'PersonGenerator':
        """
        Set birth information.

        Args:
            birth_date: Date of birth (ISO 8601)
            birth_place: Place of birth

        Returns:
            Self for method chaining
        """
        if birth_date:
            self.set_property("birthDate", birth_date, PropertyType.DATE)
        if birth_place:
            self.data["birthPlace"] = {
                "@type": "Place",
                "name": birth_place
            }
        return self

    def set_death_info(self, death_date: Optional[str] = None,
                      death_place: Optional[str] = None) -> 'PersonGenerator':
        """
        Set death information.

        Args:
            death_date: Date of death (ISO 8601)
            death_place: Place of death

        Returns:
            Self for method chaining
        """
        if death_date:
            self.set_property("deathDate", death_date, PropertyType.DATE)
        if death_place:
            self.data["deathPlace"] = {
                "@type": "Place",
                "name": death_place
            }
        return self

    def set_job_info(self, job_title: Optional[str] = None,
                    works_for: Optional[str] = None,
                    works_for_id: Optional[str] = None) -> 'PersonGenerator':
        """
        Set employment information.

        Args:
            job_title: Job title/position
            works_for: Employer organization name
            works_for_id: Optional @id for the employer organization

        Returns:
            Self for method chaining
        """
        if job_title:
            self.set_property("jobTitle", job_title, PropertyType.TEXT)
        if works_for:
            org = {
                "@type": "Organization",
                "name": works_for
            }
            if works_for_id:
                org["@id"] = works_for_id
            self.data["worksFor"] = org
        return self

    def add_affiliation(self, name: str, org_id: Optional[str] = None) -> 'PersonGenerator':
        """
        Add an organizational affiliation.

        Args:
            name: Organization name
            org_id: Optional @id for the organization

        Returns:
            Self for method chaining
        """
        if "affiliation" not in self.data:
            self.data["affiliation"] = []

        org = {
            "@type": "Organization",
            "name": name
        }
        if org_id:
            org["@id"] = org_id

        self.data["affiliation"].append(org)
        return self

    def add_alumni_of(self, name: str, org_id: Optional[str] = None) -> 'PersonGenerator':
        """
        Add an educational institution as alma mater.

        Args:
            name: Institution name
            org_id: Optional @id for the institution

        Returns:
            Self for method chaining
        """
        if "alumniOf" not in self.data:
            self.data["alumniOf"] = []

        org = {
            "@type": "EducationalOrganization",
            "name": name
        }
        if org_id:
            org["@id"] = org_id

        self.data["alumniOf"].append(org)
        return self

    def set_nationality(self, country: str) -> 'PersonGenerator':
        """
        Set nationality.

        Args:
            country: Country name or code

        Returns:
            Self for method chaining
        """
        self.data["nationality"] = {
            "@type": "Country",
            "name": country
        }
        return self

    def set_gender(self, gender: str) -> 'PersonGenerator':
        """
        Set gender.

        Args:
            gender: Gender (e.g., 'Male', 'Female', or other)

        Returns:
            Self for method chaining
        """
        self.set_property("gender", gender, PropertyType.TEXT)
        return self

    def set_image(self, image_url: str) -> 'PersonGenerator':
        """
        Set profile image.

        Args:
            image_url: URL to profile image

        Returns:
            Self for method chaining
        """
        self.data["image"] = {
            "@type": "ImageObject",
            "url": image_url
        }
        return self

    def set_url(self, url: str) -> 'PersonGenerator':
        """
        Set personal website URL.

        Args:
            url: Personal website URL

        Returns:
            Self for method chaining
        """
        self.set_property("url", url, PropertyType.URL)
        return self

    def add_same_as(self, urls: Union[str, List[str]]) -> 'PersonGenerator':
        """
        Add sameAs links (social profiles, Wikipedia, etc.).

        Args:
            urls: URL or list of URLs for equivalent pages

        Returns:
            Self for method chaining
        """
        if isinstance(urls, str):
            urls = [urls]

        if "sameAs" not in self.data:
            self.data["sameAs"] = []

        self.data["sameAs"].extend(urls)
        return self

    def add_knows(self, name: str, person_id: Optional[str] = None) -> 'PersonGenerator':
        """
        Add a person this person knows.

        Args:
            name: Person's name
            person_id: Optional @id for the person

        Returns:
            Self for method chaining
        """
        if "knows" not in self.data:
            self.data["knows"] = []

        person = {
            "@type": "Person",
            "name": name
        }
        if person_id:
            person["@id"] = person_id

        self.data["knows"].append(person)
        return self

    def add_colleague(self, name: str, person_id: Optional[str] = None) -> 'PersonGenerator':
        """
        Add a colleague.

        Args:
            name: Colleague's name
            person_id: Optional @id for the colleague

        Returns:
            Self for method chaining
        """
        if "colleague" not in self.data:
            self.data["colleague"] = []

        person = {
            "@type": "Person",
            "name": name
        }
        if person_id:
            person["@id"] = person_id

        self.data["colleague"].append(person)
        return self

    def set_spouse(self, name: str, person_id: Optional[str] = None) -> 'PersonGenerator':
        """
        Set spouse.

        Args:
            name: Spouse's name
            person_id: Optional @id for the spouse

        Returns:
            Self for method chaining
        """
        spouse = {
            "@type": "Person",
            "name": name
        }
        if person_id:
            spouse["@id"] = person_id

        self.data["spouse"] = spouse
        return self

    def add_parent(self, name: str, person_id: Optional[str] = None) -> 'PersonGenerator':
        """
        Add a parent.

        Args:
            name: Parent's name
            person_id: Optional @id for the parent

        Returns:
            Self for method chaining
        """
        if "parent" not in self.data:
            self.data["parent"] = []

        person = {
            "@type": "Person",
            "name": name
        }
        if person_id:
            person["@id"] = person_id

        self.data["parent"].append(person)
        return self

    def add_child(self, name: str, person_id: Optional[str] = None) -> 'PersonGenerator':
        """
        Add a child.

        Args:
            name: Child's name
            person_id: Optional @id for the child

        Returns:
            Self for method chaining
        """
        if "children" not in self.data:
            self.data["children"] = []

        person = {
            "@type": "Person",
            "name": name
        }
        if person_id:
            person["@id"] = person_id

        self.data["children"].append(person)
        return self

    def add_sibling(self, name: str, person_id: Optional[str] = None) -> 'PersonGenerator':
        """
        Add a sibling.

        Args:
            name: Sibling's name
            person_id: Optional @id for the sibling

        Returns:
            Self for method chaining
        """
        if "sibling" not in self.data:
            self.data["sibling"] = []

        person = {
            "@type": "Person",
            "name": name
        }
        if person_id:
            person["@id"] = person_id

        self.data["sibling"].append(person)
        return self
