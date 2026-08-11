"""Shared constants for schema-org-file-system.

Organized by domain to eliminate magic numbers across the codebase.
"""

from pathlib import Path

# =============================================================================
# Filesystem Paths
# =============================================================================

# Canonical default database location, anchored to the repo root so it resolves
# the same regardless of the current working directory. Single-sourced here for
# src/cli.py, the storage/api modules, and scripts/shared/db_utils.py.
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "results" / "file_organization.db"

# =============================================================================
# Database Column Lengths
# =============================================================================

SHA256_HEX_LENGTH = 64  # SHA-256 hex digest = 64 characters
UUID_STRING_LENGTH = 36  # UUID with hyphens: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
MAX_STRING_LENGTH = 255  # General-purpose string fields
SHORT_STRING_LENGTH = 50  # Short fields (role, type, icon, namespace)
SHORT_FIELD_LENGTH = 20  # Very short fields (extension, color, value_type)
GEOHASH_MAX_LENGTH = 12  # Geohash precision characters
BASE_PATH_MAX_LENGTH = 500  # Session base path

# =============================================================================
# Time Conversions
# =============================================================================

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600

# =============================================================================
# Geographic Constants
# =============================================================================

KM_PER_DEGREE_LATITUDE = 111.0  # Approximate km per degree of latitude
COORDINATE_TOLERANCE_DEG = 0.001  # ~111m tolerance for location matching

# =============================================================================
# Display / Formatting
# =============================================================================

SEPARATOR_WIDTH_SMALL = 40
SEPARATOR_WIDTH_MEDIUM = 60
SEPARATOR_WIDTH_LARGE = 70

# =============================================================================
# Observability Defaults
# =============================================================================

DEFAULT_TRACES_SAMPLE_RATE = 0.1
DEFAULT_PROFILES_SAMPLE_RATE = 0.1

# =============================================================================
# Misc
# =============================================================================

URN_UUID_PREFIX = "urn:uuid:"
COST_DECIMAL_PLACES = 4
MIGRATION_VERIFICATION_THRESHOLD = 0.9
TOP_EXTENSIONS_LIMIT = 20
DEFAULT_SEARCH_LIMIT = 50
