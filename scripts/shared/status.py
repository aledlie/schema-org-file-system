"""Unified status tracking for image classification and renaming."""

from enum import Enum


class ProcessingStatus(Enum):
    """Status of image processing result."""

    PENDING = "pending"
    SKIPPED = "skipped"
    RENAMED = "renamed"
    WOULD_RENAME = "would_rename"
    NO_CONTENT = "no_content"
    LOW_CONFIDENCE = "low_confidence"
    ERROR = "error"


def create_result_dict(
    original_name: str,
    status: ProcessingStatus = ProcessingStatus.PENDING,
) -> dict:
    """Create a unified result dict for processing status.

    Args:
      original_name: Original filename
      status: Initial processing status

    Returns:
      Dict with standard result fields
    """
    return {
        "original": original_name,
        "new_name": None,
        "status": status,
        "error": None,
        "confidence": None,
        "category": None,
        "all_scores": {},
    }


def update_stats_from_status(stats: dict, status: ProcessingStatus) -> None:
    """Update stats counters based on result status.

    Args:
      stats: Stats dict to update
      status: Processing status to count
    """
    status_map = {
        ProcessingStatus.RENAMED: "renamed",
        ProcessingStatus.WOULD_RENAME: "renamed",
        ProcessingStatus.SKIPPED: "skipped",
        ProcessingStatus.NO_CONTENT: "no_content",
        ProcessingStatus.LOW_CONFIDENCE: "skipped",
        ProcessingStatus.ERROR: "errors",
    }

    counter_name = status_map.get(status)
    if counter_name:
        stats[counter_name] = stats.get(counter_name, 0) + 1
