"""
Metadata enrichment utilities for Schema.org generation.

Extracts and enriches file metadata from various sources including
EXIF, document properties, NLP results, and embeddings.
"""

from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from pathlib import Path
import mimetypes


class MetadataEnricher:
    """
    Enriches file metadata for Schema.org generation.

    Extracts metadata from various sources and maps them to
    appropriate Schema.org properties.
    """

    def __init__(self):
        """Initialize metadata enricher."""
        self.mime_to_format = self._build_mime_mapping()

    def _build_mime_mapping(self) -> Dict[str, str]:
        """Build MIME type to encoding format mapping."""
        return {
            # Documents
            'application/pdf': 'application/pdf',
            'application/msword': 'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'text/plain': 'text/plain',
            'text/markdown': 'text/markdown',
            'text/html': 'text/html',

            # Images
            'image/jpeg': 'image/jpeg',
            'image/png': 'image/png',
            'image/gif': 'image/gif',
            'image/webp': 'image/webp',
            'image/svg+xml': 'image/svg+xml',

            # Videos
            'video/mp4': 'video/mp4',
            'video/mpeg': 'video/mpeg',
            'video/webm': 'video/webm',
            'video/quicktime': 'video/quicktime',

            # Audio
            'audio/mpeg': 'audio/mpeg',
            'audio/mp4': 'audio/mp4',
            'audio/wav': 'audio/wav',
            'audio/ogg': 'audio/ogg',

            # Code
            'text/x-python': 'text/x-python',
            'text/javascript': 'text/javascript',
            'text/x-java': 'text/x-java',
            'text/x-c': 'text/x-c',

            # Archives
            'application/zip': 'application/zip',
            'application/x-tar': 'application/x-tar',
            'application/gzip': 'application/gzip',

            # Data
            'text/csv': 'text/csv',
            'application/json': 'application/json',
            'application/xml': 'application/xml',
        }

    def detect_mime_type(self, file_path: str) -> str:
        """
        Detect MIME type from file path.

        Args:
            file_path: Path to file

        Returns:
            MIME type string
        """
        mime_type, _ = mimetypes.guess_type(file_path)
        return mime_type or 'application/octet-stream'

    def get_encoding_format(self, file_path: str) -> str:
        """
        Get encoding format for Schema.org.

        Args:
            file_path: Path to file

        Returns:
            Encoding format string
        """
        mime_type = self.detect_mime_type(file_path)
        return self.mime_to_format.get(mime_type, mime_type)

    def enrich_from_file_stats(self, file_path: str) -> Dict[str, Any]:
        """
        Extract metadata from file system stats.

        Args:
            file_path: Path to file

        Returns:
            Metadata dictionary
        """
        path = Path(file_path)
        if not path.exists():
            return {}

        stats = path.stat()
        return {
            'name': path.name,
            'url': f'file://{path.absolute()}',
            'encodingFormat': self.get_encoding_format(file_path),
            'contentSize': stats.st_size,
            'dateCreated': datetime.fromtimestamp(stats.st_ctime),
            'dateModified': datetime.fromtimestamp(stats.st_mtime),
            'identifier': path.stem,
        }

    def enrich_from_exif(self, exif_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract metadata from EXIF data.

        Args:
            exif_data: EXIF data dictionary

        Returns:
            Enriched metadata
        """
        metadata: Dict[str, Any] = {}

        # Creator information
        if 'Artist' in exif_data:
            metadata['creator'] = {
                '@type': 'Person',
                'name': exif_data['Artist']
            }

        # Camera information
        camera_info = []
        if 'Make' in exif_data:
            camera_info.append(exif_data['Make'])
        if 'Model' in exif_data:
            camera_info.append(exif_data['Model'])
        if camera_info:
            metadata['exifData'] = {
                '@type': 'PropertyValue',
                'name': 'Camera',
                'value': ' '.join(camera_info)
            }

        # Dates
        date_fields = ['DateTime', 'DateTimeOriginal', 'DateTimeDigitized']
        for field in date_fields:
            if field in exif_data:
                try:
                    # EXIF dates are typically in format: YYYY:MM:DD HH:MM:SS
                    date_str = exif_data[field].replace(':', '-', 2)
                    metadata['dateCreated'] = date_str
                    break
                except:
                    pass

        # Location
        if 'GPSLatitude' in exif_data and 'GPSLongitude' in exif_data:
            metadata['contentLocation'] = {
                '@type': 'Place',
                'geo': {
                    '@type': 'GeoCoordinates',
                    'latitude': exif_data['GPSLatitude'],
                    'longitude': exif_data['GPSLongitude']
                }
            }

        # Dimensions
        if 'ImageWidth' in exif_data:
            metadata['width'] = exif_data['ImageWidth']
        if 'ImageHeight' in exif_data:
            metadata['height'] = exif_data['ImageHeight']

        # Copyright
        if 'Copyright' in exif_data:
            metadata['copyrightNotice'] = exif_data['Copyright']

        # Description
        if 'ImageDescription' in exif_data:
            metadata['description'] = exif_data['ImageDescription']

        return metadata

    def enrich_from_document_properties(self, doc_props: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract metadata from document properties.

        Args:
            doc_props: Document properties dictionary

        Returns:
            Enriched metadata
        """
        metadata: Dict[str, Any] = {}

        # Basic properties
        property_mapping = {
            'title': 'name',
            'subject': 'abstract',
            'description': 'description',
            'keywords': 'keywords',
            'creator': 'author',
            'author': 'author',
            'created': 'dateCreated',
            'modified': 'dateModified',
            'language': 'inLanguage',
            'pages': 'numberOfPages',
        }

        for doc_key, schema_key in property_mapping.items():
            if doc_key in doc_props:
                value = doc_props[doc_key]

                if schema_key in ['author', 'creator'] and isinstance(value, str):
                    metadata[schema_key] = {
                        '@type': 'Person',
                        'name': value
                    }
                else:
                    metadata[schema_key] = value

        return metadata

    def enrich_from_nlp(self, nlp_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract metadata from NLP analysis results.

        Args:
            nlp_results: NLP analysis results

        Returns:
            Enriched metadata
        """
        metadata: Dict[str, Any] = {}

        # Keywords and topics
        if 'keywords' in nlp_results:
            metadata['keywords'] = ', '.join(nlp_results['keywords'])

        if 'topics' in nlp_results:
            metadata['about'] = [
                {'@type': 'Thing', 'name': topic}
                for topic in nlp_results['topics']
            ]

        # Entities
        if 'entities' in nlp_results:
            mentions = []
            for entity in nlp_results['entities']:
                entity_type = entity.get('type', 'Thing')
                schema_type = self._map_entity_type_to_schema(entity_type)
                mentions.append({
                    '@type': schema_type,
                    'name': entity.get('text', entity.get('name', ''))
                })
            if mentions:
                metadata['mentions'] = mentions

        # Language
        if 'language' in nlp_results:
            metadata['inLanguage'] = nlp_results['language']

        # Sentiment (as custom property)
        if 'sentiment' in nlp_results:
            metadata['additionalProperty'] = [{
                '@type': 'PropertyValue',
                'name': 'sentiment',
                'value': nlp_results['sentiment']
            }]

        # Summary
        if 'summary' in nlp_results:
            metadata['abstract'] = nlp_results['summary']

        return metadata

    def enrich_from_audio_metadata(self, audio_meta: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract metadata from audio file metadata.

        Args:
            audio_meta: Audio metadata dictionary

        Returns:
            Enriched metadata
        """
        metadata: Dict[str, Any] = {}

        # Basic properties
        if 'title' in audio_meta:
            metadata['name'] = audio_meta['title']
        if 'artist' in audio_meta:
            metadata['byArtist'] = {
                '@type': 'Person',
                'name': audio_meta['artist']
            }
        if 'album' in audio_meta:
            metadata['inAlbum'] = {
                '@type': 'MusicAlbum',
                'name': audio_meta['album']
            }
        if 'genre' in audio_meta:
            metadata['genre'] = audio_meta['genre']
        if 'duration' in audio_meta:
            # Convert seconds to ISO 8601 duration
            duration_sec = audio_meta['duration']
            metadata['duration'] = self._seconds_to_iso_duration(duration_sec)

        # Audio quality
        if 'bitrate' in audio_meta:
            metadata['bitrate'] = f"{audio_meta['bitrate']}kbps"
        if 'sample_rate' in audio_meta:
            metadata['encodingFormat'] = f"{metadata.get('encodingFormat', 'audio/mpeg')} ({audio_meta['sample_rate']}Hz)"

        # Track number
        if 'track_number' in audio_meta:
            metadata['position'] = audio_meta['track_number']

        # Year/date
        if 'year' in audio_meta:
            metadata['datePublished'] = f"{audio_meta['year']}-01-01"

        # ISRC
        if 'isrc' in audio_meta:
            metadata['isrcCode'] = audio_meta['isrc']

        return metadata

    def enrich_from_video_metadata(self, video_meta: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract metadata from video file metadata.

        Args:
            video_meta: Video metadata dictionary

        Returns:
            Enriched metadata
        """
        metadata: Dict[str, Any] = {}

        # Basic properties
        if 'title' in video_meta:
            metadata['name'] = video_meta['title']
        if 'description' in video_meta:
            metadata['description'] = video_meta['description']

        # Dimensions
        if 'width' in video_meta:
            metadata['width'] = video_meta['width']
        if 'height' in video_meta:
            metadata['height'] = video_meta['height']

        # Duration
        if 'duration' in video_meta:
            duration_sec = video_meta['duration']
            metadata['duration'] = self._seconds_to_iso_duration(duration_sec)

        # Quality
        if 'bitrate' in video_meta:
            metadata['bitrate'] = f"{video_meta['bitrate']}kbps"

        # Codec
        if 'codec' in video_meta:
            metadata['videoCodec'] = video_meta['codec']
        if 'audio_codec' in video_meta:
            metadata['audioCodec'] = video_meta['audio_codec']

        # Upload date (default to current)
        if 'upload_date' in video_meta:
            metadata['uploadDate'] = video_meta['upload_date']
        else:
            metadata['uploadDate'] = datetime.now()

        return metadata

    def enrich_from_code_analysis(self, code_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract metadata from code analysis results.

        Args:
            code_analysis: Code analysis results

        Returns:
            Enriched metadata
        """
        metadata: Dict[str, Any] = {}

        # Language
        if 'language' in code_analysis:
            metadata['programmingLanguage'] = code_analysis['language']

        # Repository info
        if 'repository' in code_analysis:
            repo = code_analysis['repository']
            metadata['codeRepository'] = repo.get('url', '')
            if 'branch' in repo:
                metadata['targetProduct'] = repo['branch']

        # Dependencies
        if 'dependencies' in code_analysis:
            metadata['dependencies'] = [
                {
                    '@type': 'SoftwareApplication',
                    'name': dep['name'],
                    'softwareVersion': dep.get('version', '')
                }
                for dep in code_analysis['dependencies']
            ]

        # Runtime
        if 'runtime' in code_analysis:
            metadata['runtimePlatform'] = code_analysis['runtime']

        # License
        if 'license' in code_analysis:
            metadata['license'] = code_analysis['license']

        # Author
        if 'author' in code_analysis:
            metadata['author'] = {
                '@type': 'Person',
                'name': code_analysis['author']
            }

        # Functions/classes (as description)
        if 'functions' in code_analysis:
            func_count = len(code_analysis['functions'])
            metadata['description'] = f"Contains {func_count} functions"

        return metadata

    def enrich_from_dataset_info(self, dataset_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract metadata from dataset information.

        Args:
            dataset_info: Dataset information dictionary

        Returns:
            Enriched metadata
        """
        metadata: Dict[str, Any] = {}

        # Basic properties
        if 'name' in dataset_info:
            metadata['name'] = dataset_info['name']
        if 'description' in dataset_info:
            metadata['description'] = dataset_info['description']

        # Variables/columns
        if 'columns' in dataset_info:
            metadata['variableMeasured'] = [
                {
                    '@type': 'PropertyValue',
                    'name': col['name'],
                    'description': col.get('description', '')
                }
                for col in dataset_info['columns']
            ]

        # Coverage
        if 'temporal_coverage' in dataset_info:
            temporal = dataset_info['temporal_coverage']
            if isinstance(temporal, dict):
                start = temporal.get('start', '')
                end = temporal.get('end', '')
                metadata['temporalCoverage'] = f"{start}/{end}"
            else:
                metadata['temporalCoverage'] = temporal

        if 'spatial_coverage' in dataset_info:
            metadata['spatialCoverage'] = dataset_info['spatial_coverage']

        # Distribution
        if 'format' in dataset_info:
            metadata['distribution'] = [{
                '@type': 'DataDownload',
                'encodingFormat': dataset_info['format']
            }]

        # Size
        if 'rows' in dataset_info:
            metadata['additionalProperty'] = [{
                '@type': 'PropertyValue',
                'name': 'rows',
                'value': dataset_info['rows']
            }]

        return metadata

    def _map_entity_type_to_schema(self, entity_type: str) -> str:
        """
        Map NLP entity type to Schema.org type.

        Args:
            entity_type: Entity type from NLP

        Returns:
            Schema.org type
        """
        mapping = {
            'PERSON': 'Person',
            'ORG': 'Organization',
            'ORGANIZATION': 'Organization',
            'GPE': 'Place',
            'LOC': 'Place',
            'LOCATION': 'Place',
            'EVENT': 'Event',
            'WORK_OF_ART': 'CreativeWork',
            'PRODUCT': 'Product',
            'DATE': 'Date',
            'TIME': 'Time',
        }
        return mapping.get(entity_type.upper(), 'Thing')

    def _seconds_to_iso_duration(self, seconds: Union[int, float]) -> str:
        """
        Convert seconds to ISO 8601 duration format.

        Args:
            seconds: Duration in seconds

        Returns:
            ISO 8601 duration string (e.g., 'PT1H30M')
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        parts = ['PT']
        if hours > 0:
            parts.append(f'{hours}H')
        if minutes > 0:
            parts.append(f'{minutes}M')
        if secs > 0 or (hours == 0 and minutes == 0):
            parts.append(f'{secs}S')

        return ''.join(parts)

    def merge_metadata(self, *metadata_dicts: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge multiple metadata dictionaries.

        Later dictionaries override earlier ones.

        Args:
            *metadata_dicts: Variable number of metadata dictionaries

        Returns:
            Merged metadata dictionary
        """
        merged: Dict[str, Any] = {}
        for metadata in metadata_dicts:
            for key, value in metadata.items():
                if key not in merged or value is not None:
                    merged[key] = value
        return merged

    def create_enriched_schema(self, generator_class, base_metadata: Dict[str, Any],
                              *enrichment_sources: Dict[str, Any]) -> Any:
        """
        Create enriched schema from multiple metadata sources.

        Args:
            generator_class: Schema generator class to use
            base_metadata: Base metadata dictionary
            *enrichment_sources: Additional enrichment source dictionaries

        Returns:
            Configured schema generator instance
        """
        # Merge all metadata
        merged = self.merge_metadata(base_metadata, *enrichment_sources)

        # Create generator instance
        generator = generator_class()

        # Apply metadata to generator
        for key, value in merged.items():
            if hasattr(generator, 'set_property'):
                try:
                    generator.set_property(key, value)
                except:
                    pass  # Skip properties that can't be set

        return generator
