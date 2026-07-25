"""ArchiveManifestSignal — classify archives by their member listing.

The filename rules route every archive to Technical/Other on extension alone;
a zip of iPhone photos and a zip holding a DNA report both land in the same
technical bucket. The member *listing* is cheap authoritative evidence — this
signal reads the zip central directory (never extracts, never decompresses
member data) and classifies by what the archive actually holds:

- members matching medical-report name tokens (``promethease``, ``23andme``,
  ``bloodwork``, …) → ``medical/records``;
- all-media member sets → ``media/{photos,videos,audio}_other`` by majority
  kind, ``media/other`` when mixed;
- anything else (code, documents, mixed junk) → no emission, so the
  graduated archive filename verdict (see EVENTS-style downgrade in
  filename_pattern.py) still commits Technical/Other alone.

Zip only: stdlib ``zipfile`` gives the listing for free; other
ARCHIVE_EXTENSIONS (.rar/.7z need third-party readers, bare .gz has no
listing) keep the extension-only routing.
"""

from __future__ import annotations

import zipfile
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:
    from ..context import FileContext

from shared.constants import IMAGE_EXTENSIONS_WIDE

from ..types import CategoryScore
from ..weights import W_ARCHIVE
from .media_heuristic import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS

ARCHIVE_SIGNAL_NAME = "archive_manifest"
ZIP_EXTENSION = ".zip"

MEDIA_CATEGORY = "media"
MEDICAL_CATEGORY = "medical"
MEDICAL_RECORDS_SUBCATEGORY = "records"

# Majority-kind → media subcategory (get_destination_path resolves the
# underscored forms through the nested media taxonomy).
PHOTOS_SUBCATEGORY = "photos_other"
VIDEOS_SUBCATEGORY = "videos_other"
AUDIO_SUBCATEGORY = "audio_other"
MIXED_MEDIA_SUBCATEGORY = "other"

# An enumerated all-media member list is near-certain; a mostly-media list
# (stray .txt sidecar, checksum file) is still strong.
ALL_MEDIA_CONFIDENCE = 0.9
MOSTLY_MEDIA_CONFIDENCE = 0.7
MOSTLY_MEDIA_THRESHOLD = 0.8

# Report-name tokens are specific but only names, not content.
MEDICAL_MATCH_CONFIDENCE = 0.8

# Substring tokens in member names that identify medical/genetic reports.
# Deliberately multi-character and unambiguous — a bare "dna" would match
# inside unrelated words.
MEDICAL_NAME_TOKENS = (
    "promethease",
    "23andme",
    "ancestrydna",
    "genome",
    "genetic",
    "bloodwork",
    "lab_results",
    "labresults",
    "medical_record",
    "health_record",
)

# macOS/Windows archive litter that must not count toward the member census.
JUNK_BASENAMES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})
MACOS_RESOURCE_PREFIX = "__macosx/"

# Evidence keys (signal-local).
EVIDENCE_MEMBER_COUNT = "member_count"
EVIDENCE_MEDIA_MEMBERS = "media_members"
EVIDENCE_MEDICAL_TOKENS = "matched_medical_tokens"

_IMAGE_EXTS = frozenset(IMAGE_EXTENSIONS_WIDE)
_VIDEO_EXTS = frozenset(VIDEO_EXTENSIONS)
_AUDIO_EXTS = frozenset(AUDIO_EXTENSIONS)


def list_zip_members(path) -> Optional[List[str]]:
    """Member file names from the zip central directory, junk filtered;
    ``None`` when the file is not a readable zip (corrupt, truncated)."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except Exception:
        return None
    members = []
    for name in names:
        lower = name.lower()
        if lower.endswith("/") or lower.startswith(MACOS_RESOURCE_PREFIX):
            continue
        basename = PurePosixPath(lower).name
        if basename in JUNK_BASENAMES or basename.startswith("."):
            continue
        members.append(name)
    return members


def match_medical_tokens(members: List[str]) -> List[str]:
    """MEDICAL_NAME_TOKENS present in any member name (token order)."""
    joined = "\n".join(member.lower() for member in members)
    return [token for token in MEDICAL_NAME_TOKENS if token in joined]


def classify_media_members(members: List[str]) -> Optional[Tuple[str, float, int]]:
    """(media subcategory, confidence, media member count) when the archive
    is (mostly) media."""
    images = videos = audio = 0
    for member in members:
        ext = PurePosixPath(member.lower()).suffix
        if ext in _IMAGE_EXTS:
            images += 1
        elif ext in _VIDEO_EXTS:
            videos += 1
        elif ext in _AUDIO_EXTS:
            audio += 1
    media_total = images + videos + audio
    fraction = media_total / len(members)
    if fraction < MOSTLY_MEDIA_THRESHOLD:
        return None
    confidence = ALL_MEDIA_CONFIDENCE if fraction == 1.0 else MOSTLY_MEDIA_CONFIDENCE
    kinds = [(images, PHOTOS_SUBCATEGORY), (videos, VIDEOS_SUBCATEGORY), (audio, AUDIO_SUBCATEGORY)]
    present = [(count, subcategory) for count, subcategory in kinds if count]
    if len(present) == 1:
        return present[0][1], confidence, media_total
    return MIXED_MEDIA_SUBCATEGORY, confidence, media_total


class ArchiveManifestSignal:
    """Zip member listing → medical/records or media/* (else silent)."""

    name = ARCHIVE_SIGNAL_NAME
    weight = W_ARCHIVE
    cost_tier = "mid"

    def applies_to(self, ctx: FileContext) -> bool:
        return ctx.path.suffix.lower() == ZIP_EXTENSION

    def run(self, ctx: FileContext) -> List[CategoryScore]:
        members = list_zip_members(ctx.path)
        if not members:
            return []

        medical_tokens = match_medical_tokens(members)
        if medical_tokens:
            return [
                CategoryScore(
                    category=MEDICAL_CATEGORY,
                    subcategory=MEDICAL_RECORDS_SUBCATEGORY,
                    confidence=MEDICAL_MATCH_CONFIDENCE,
                    signal_name=self.name,
                    evidence={
                        EVIDENCE_MEMBER_COUNT: len(members),
                        EVIDENCE_MEDICAL_TOKENS: medical_tokens,
                    },
                )
            ]

        media_result = classify_media_members(members)
        if media_result is None:
            return []
        subcategory, confidence, media_total = media_result
        return [
            CategoryScore(
                category=MEDIA_CATEGORY,
                subcategory=subcategory,
                confidence=confidence,
                signal_name=self.name,
                evidence={
                    EVIDENCE_MEMBER_COUNT: len(members),
                    EVIDENCE_MEDIA_MEMBERS: media_total,
                },
            )
        ]
