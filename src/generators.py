"""
Specialized Schema.org generators for different file types.

Each generator is optimized for specific file types and includes
appropriate properties and nested schemas.
"""

from typing import Any, Dict, List, Optional, Union
from datetime import datetime

try:
    from .base import SchemaOrgBase, PropertyType
except ImportError:
    from base import SchemaOrgBase, PropertyType


class DocumentGenerator(SchemaOrgBase):
    """
    Generator for document files (PDFs, Word docs, text files).

    Supports: DigitalDocument, Article, Report, ScholarlyArticle
    """

    def __init__(self, document_type: str = "DigitalDocument"):
        """
        Initialize document generator.

        Args:
            document_type: Specific document type (DigitalDocument, Article, Report, etc.)
        """
        super().__init__(document_type)
        self.document_type = document_type

    def get_required_properties(self) -> List[str]:
        """Required properties for documents."""
        return ["name", "encodingFormat"]

    def get_recommended_properties(self) -> List[str]:
        """Recommended properties for documents."""
        return [
            "author", "dateCreated", "dateModified", "keywords",
            "abstract", "inLanguage", "contentSize", "url"
        ]

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

    def __init__(self, image_type: str = "ImageObject"):
        """
        Initialize image generator.

        Args:
            image_type: Specific image type (ImageObject, Photograph)
        """
        super().__init__(image_type)

    def get_required_properties(self) -> List[str]:
        """Required properties for images."""
        return ["contentUrl", "encodingFormat"]

    def get_recommended_properties(self) -> List[str]:
        """Recommended properties for images."""
        return [
            "name", "description", "width", "height", "caption",
            "creator", "dateCreated", "exifData", "contentLocation"
        ]

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

    def __init__(self, video_type: str = "VideoObject"):
        """
        Initialize video generator.

        Args:
            video_type: Specific video type (VideoObject, MovieClip)
        """
        super().__init__(video_type)

    def get_required_properties(self) -> List[str]:
        """Required properties for videos."""
        return ["name", "contentUrl", "uploadDate"]

    def get_recommended_properties(self) -> List[str]:
        """Recommended properties for videos."""
        return [
            "description", "thumbnailUrl", "duration", "width", "height",
            "encodingFormat", "creator", "datePublished"
        ]

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

    def __init__(self, audio_type: str = "AudioObject"):
        """
        Initialize audio generator.

        Args:
            audio_type: Specific audio type (AudioObject, MusicRecording, PodcastEpisode)
        """
        super().__init__(audio_type)

    def get_required_properties(self) -> List[str]:
        """Required properties for audio."""
        return ["name", "contentUrl"]

    def get_recommended_properties(self) -> List[str]:
        """Recommended properties for audio."""
        return [
            "description", "duration", "encodingFormat", "creator",
            "datePublished", "inLanguage"
        ]

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

    def __init__(self):
        """Initialize code generator."""
        super().__init__("SoftwareSourceCode")

    def get_required_properties(self) -> List[str]:
        """Required properties for source code."""
        return ["name", "programmingLanguage"]

    def get_recommended_properties(self) -> List[str]:
        """Recommended properties for source code."""
        return [
            "description", "author", "dateCreated", "dateModified",
            "codeRepository", "license", "runtimePlatform"
        ]

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

    def __init__(self):
        """Initialize dataset generator."""
        super().__init__("Dataset")

    def get_required_properties(self) -> List[str]:
        """Required properties for datasets."""
        return ["name", "description"]

    def get_recommended_properties(self) -> List[str]:
        """Recommended properties for datasets."""
        return [
            "creator", "datePublished", "distribution", "keywords",
            "license", "spatial", "temporal", "variableMeasured"
        ]

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

    def __init__(self):
        """Initialize archive generator."""
        super().__init__("DigitalDocument")
        self.data["additionalType"] = "Archive"

    def get_required_properties(self) -> List[str]:
        """Required properties for archives."""
        return ["name", "encodingFormat"]

    def get_recommended_properties(self) -> List[str]:
        """Recommended properties for archives."""
        return [
            "description", "hasPart", "dateCreated", "contentSize"
        ]

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
