"""MediaHeuristicSignal — extension/stem/EXIF media routing (§4 row 12).

Extracted from ``ContentOrganizer.classify_media_file``.
:func:`detect_media_match` reproduces the legacy method exactly and
additionally reports what the match was based on (extension, stem keyword,
GPS, or EXIF datetime); :func:`detect_media_category` is the spec-shaped
``(category, media_type, subcategory)`` wrapper the organizer delegates to.

Behavior divergences from the legacy chain (by design):

- ``None`` results (screenshot-named photos, ambiguous PNGs) emit ``[]`` so
  the other signals compete instead of the chain falling through in tier
  order (§4 row 12).
- The legacy chain's "Point B" hook (``photos/other`` rerouted through
  ``enhance_weak_image_classification``) is not reproduced here: the signal
  emits ``media/photos_other`` at ``MEDIA_MATCH_CONFIDENCE`` and the CLIP/OCR
  signals outscore it when they know better. The hook stays intact in the
  legacy chain.
- EXIF metadata is fetched via ``ctx.ensure_image_metadata()`` only for photo
  extensions (videos/audio never consulted EXIF in the legacy method either).
"""

from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from ..types import CategoryScore
from ..weights import W_MEDIA

# Media routing is a solid heuristic but not content-aware; content signals
# (OCR/CLIP) can overrule it.
MEDIA_MATCH_CONFIDENCE = 0.8

MEDIA_CATEGORY = "media"
VIDEOS_MEDIA_TYPE = "videos"
AUDIO_MEDIA_TYPE = "audio"
PHOTOS_MEDIA_TYPE = "photos"

SCREENCASTS_SUBCATEGORY = "screencasts"
EXPORTS_SUBCATEGORY = "exports"
RECORDINGS_SUBCATEGORY = "recordings"
PODCASTS_SUBCATEGORY = "podcasts"
MUSIC_SUBCATEGORY = "music"
DOCUMENTS_SUBCATEGORY = "documents"
TRAVEL_SUBCATEGORY = "travel"
OTHER_SUBCATEGORY = "other"

# Extension gates (verbatim from the legacy method). .wav/.ogg are absent
# from the audio list on purpose — game-asset detection owns those.
VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".flv", ".wmv")
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".flac", ".wma")
PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".heic", ".gif", ".webp", ".bmp", ".tiff", ".tif")
# Formats that are camera photos even without EXIF metadata.
CAMERA_PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".heic")

# Stem keyword groups (verbatim from the legacy method, in check order).
SCREENCAST_STEM_KEYWORDS = ("screen", "recording", "capture")
VIDEO_EXPORT_STEM_KEYWORDS = ("export", "render", "final", "cut")
PODCAST_STEM_KEYWORDS = ("podcast", "episode", "interview")
MUSIC_STEM_KEYWORDS = ("song", "album", "track", "music")
VOICE_STEM_KEYWORDS = ("recording", "voice", "memo", "audio")
DOCUMENT_STEM_KEYWORDS = ("scan", "receipt", "document", "invoice")

# Screenshot-named photos fall through to the OCR/CLIP screenshot tiers.
SCREENSHOT_FILENAME_PREFIX = "screenshot"
SCREENSHOT_SPACED_MARKER = "screen shot"
SCREENSHOT_STEM_MARKER = "screenshot"

# image_metadata keys consulted (shape of get_metadata_summary()).
GPS_METADATA_KEY = "gps_coordinates"
DATETIME_METADATA_KEY = "datetime"

# What the match was based on (evidence).
MATCHED_EXTENSION = "extension"
MATCHED_STEM = "stem"
MATCHED_GPS = "gps"
MATCHED_DATETIME = "datetime"


class MediaMatch(NamedTuple):
    """A media classification plus what it was based on."""

    category: str
    media_type: str
    subcategory: str
    matched: str  # MATCHED_EXTENSION | MATCHED_STEM | MATCHED_GPS | MATCHED_DATETIME


def detect_media_match(
    path: Any, image_metadata: Optional[Dict[str, Any]] = None
) -> Optional[MediaMatch]:
    """Classify a media file, reporting the basis of the match.

    Reproduces ``ContentOrganizer.classify_media_file`` exactly (extension
    gates, stem keyword order, screenshot fall-through, GPS/datetime checks);
    the legacy delegator discards the ``matched`` tag.
    """
    filename = path.name.lower()
    stem = path.stem.lower()
    ext = path.suffix.lower()

    # Videos
    if ext in VIDEO_EXTENSIONS:
        if any(keyword in stem for keyword in SCREENCAST_STEM_KEYWORDS):
            return MediaMatch(
                MEDIA_CATEGORY, VIDEOS_MEDIA_TYPE, SCREENCASTS_SUBCATEGORY, MATCHED_STEM
            )
        if any(keyword in stem for keyword in VIDEO_EXPORT_STEM_KEYWORDS):
            return MediaMatch(MEDIA_CATEGORY, VIDEOS_MEDIA_TYPE, EXPORTS_SUBCATEGORY, MATCHED_STEM)
        return MediaMatch(
            MEDIA_CATEGORY, VIDEOS_MEDIA_TYPE, RECORDINGS_SUBCATEGORY, MATCHED_EXTENSION
        )

    # Audio (but not game music — game-asset detection owns .wav/.ogg)
    if ext in AUDIO_EXTENSIONS:
        if any(keyword in stem for keyword in PODCAST_STEM_KEYWORDS):
            return MediaMatch(MEDIA_CATEGORY, AUDIO_MEDIA_TYPE, PODCASTS_SUBCATEGORY, MATCHED_STEM)
        if any(keyword in stem for keyword in MUSIC_STEM_KEYWORDS):
            return MediaMatch(MEDIA_CATEGORY, AUDIO_MEDIA_TYPE, MUSIC_SUBCATEGORY, MATCHED_STEM)
        if any(keyword in stem for keyword in VOICE_STEM_KEYWORDS):
            return MediaMatch(
                MEDIA_CATEGORY, AUDIO_MEDIA_TYPE, RECORDINGS_SUBCATEGORY, MATCHED_STEM
            )
        return MediaMatch(
            MEDIA_CATEGORY, AUDIO_MEDIA_TYPE, RECORDINGS_SUBCATEGORY, MATCHED_EXTENSION
        )

    # Photos
    if ext in PHOTO_EXTENSIONS:
        # Screenshots fall through so OCR/CLIP sub-classification can route
        # to Browser/Terminal/Docs/etc.
        if (
            filename.startswith(SCREENSHOT_FILENAME_PREFIX)
            or SCREENSHOT_SPACED_MARKER in filename
            or SCREENSHOT_STEM_MARKER in stem
        ):
            return None

        # Scanned documents/receipts (OCR will detect text)
        if any(keyword in stem for keyword in DOCUMENT_STEM_KEYWORDS):
            return MediaMatch(
                MEDIA_CATEGORY, PHOTOS_MEDIA_TYPE, DOCUMENTS_SUBCATEGORY, MATCHED_STEM
            )

        # Travel photos (GPS metadata present)
        if image_metadata and image_metadata.get(GPS_METADATA_KEY):
            return MediaMatch(MEDIA_CATEGORY, PHOTOS_MEDIA_TYPE, TRAVEL_SUBCATEGORY, MATCHED_GPS)

        # Photos with camera EXIF datetime are personal photos.
        if image_metadata and image_metadata.get(DATETIME_METADATA_KEY):
            return MediaMatch(
                MEDIA_CATEGORY, PHOTOS_MEDIA_TYPE, OTHER_SUBCATEGORY, MATCHED_DATETIME
            )

        # Camera formats without metadata are still actual photos.
        if ext in CAMERA_PHOTO_EXTENSIONS:
            return MediaMatch(
                MEDIA_CATEGORY, PHOTOS_MEDIA_TYPE, OTHER_SUBCATEGORY, MATCHED_EXTENSION
            )

        # PNG files without clear classification fall through (could be
        # screenshots, documents, or game assets that weren't caught).
        return None

    return None


def detect_media_category(
    path: Any, image_metadata: Optional[Dict[str, Any]] = None
) -> Optional[Tuple[str, str, str]]:
    """Legacy-shaped wrapper: ``(category, media_type, subcategory)`` or ``None``."""
    match = detect_media_match(path, image_metadata)
    if match is None:
        return None
    return (match.category, match.media_type, match.subcategory)


# Signal-local evidence keys.
EVIDENCE_MEDIA_TYPE = "media_type"
EVIDENCE_MATCHED = "matched"


class MediaHeuristicSignal:
    """Extension/stem/EXIF media routing over the shared taxonomy."""

    name = "media_heuristic"
    weight = W_MEDIA
    cost_tier = "cheap"

    def applies_to(self, ctx: Any) -> bool:
        return True

    def run(self, ctx: Any) -> List[CategoryScore]:
        ext = ctx.path.suffix.lower()
        # EXIF only informs the photo branch; videos/audio never need it.
        image_metadata = ctx.ensure_image_metadata() if ext in PHOTO_EXTENSIONS else None
        match = detect_media_match(ctx.path, image_metadata)
        if match is None:
            return []
        return [
            CategoryScore(
                category=match.category,
                subcategory=f"{match.media_type}_{match.subcategory}",
                confidence=MEDIA_MATCH_CONFIDENCE,
                signal_name=self.name,
                evidence={
                    EVIDENCE_MEDIA_TYPE: match.media_type,
                    EVIDENCE_MATCHED: match.matched,
                },
            )
        ]
