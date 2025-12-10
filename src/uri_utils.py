"""
URI generation utilities for Schema.org @id fields.

Provides functions for generating valid IRIs (Internationalized Resource Identifiers)
for use in JSON-LD Schema.org metadata. Follows best practices for:
- Distributed systems (collision-proof)
- Deduplication (deterministic canonical IDs)
- Semantic web compatibility (valid IRIs)
- Merge tracking (historical ID preservation)

Usage:
    from src.uri_utils import generate_file_iri, generate_canonical_iri

    # For files (content-addressed)
    file_iri = generate_file_iri("/path/to/document.pdf")
    # Returns: urn:sha256:abc123...

    # For entities (deterministic from name)
    company_iri = generate_canonical_iri('company', 'Acme Corporation')
    # Returns: urn:uuid:c0e1a2b3-... (always same for "Acme Corporation")
"""

import uuid
import hashlib
from typing import Optional
from urllib.parse import quote
from pathlib import Path


# Namespace UUIDs for deterministic ID generation (UUID v5)
# These are fixed UUIDs that serve as namespaces for generating
# deterministic IDs based on natural keys (names, paths, etc.)
NAMESPACES = {
    'file': uuid.UUID('f4e8a9c0-1234-5678-9abc-def012345678'),
    'category': uuid.UUID('c4e8a9c0-2345-6789-abcd-ef0123456789'),
    'company': uuid.UUID('c0e1a2b3-4567-89ab-cdef-012345678901'),
    'person': uuid.UUID('d1e2a3b4-5678-9abc-def0-123456789012'),
    'location': uuid.UUID('e2e3a4b5-6789-abcd-ef01-234567890123'),
    'session': uuid.UUID('f3e4a5b6-789a-bcde-f012-345678901234'),
    'merge_event': uuid.UUID('a1b2c3d4-89ab-cdef-0123-456789abcdef'),
}

# Base URI for public HTTPS URLs (configure for your domain)
BASE_URI = "https://schema.example.com"


def generate_file_iri(file_path: str, use_hash: bool = True) -> str:
    """
    Generate IRI for a file.

    Uses SHA-256 hash of the absolute path for content-addressed URN.
    This ensures the same file always gets the same IRI, enabling
    deduplication and linking across systems.

    Args:
        file_path: Path to file (relative or absolute)
        use_hash: If True, use content-addressed URN. Otherwise use HTTPS URI.

    Returns:
        IRI string (e.g., "urn:sha256:abc123..." or "https://...")

    Examples:
        >>> generate_file_iri("/Users/john/doc.pdf")
        'urn:sha256:abc123def456...'

        >>> generate_file_iri("/Users/john/doc.pdf", use_hash=False)
        'https://schema.example.com/files/%2FUsers%2Fjohn%2Fdoc.pdf'
    """
    # Normalize to absolute path
    path = Path(file_path).resolve()
    path_str = str(path)

    if use_hash:
        file_hash = hashlib.sha256(path_str.encode()).hexdigest()
        return f"urn:sha256:{file_hash}"
    else:
        # URL-safe path encoding
        safe_path = quote(path_str, safe='')
        return f"{BASE_URI}/files/{safe_path}"


def generate_canonical_iri(entity_type: str, natural_key: str) -> str:
    """
    Generate deterministic canonical IRI using UUID v5.

    Same input always produces the same output, enabling:
    - Deduplication across distributed systems
    - Idempotent operations (retries produce identical IDs)
    - Linking entities across different data sources

    Args:
        entity_type: Type of entity ('company', 'person', 'category', 'location')
        natural_key: Natural key for entity (e.g., normalized name)

    Returns:
        Canonical IRI (e.g., "urn:uuid:c0e1a2b3-...")

    Raises:
        ValueError: If entity_type is not recognized

    Examples:
        >>> generate_canonical_iri('company', 'Acme Corporation')
        'urn:uuid:c0e1a2b3-4567-89ab-cdef-012345678901'

        >>> # Same input = same output (deterministic)
        >>> id1 = generate_canonical_iri('company', 'Acme Corporation')
        >>> id2 = generate_canonical_iri('company', 'Acme Corporation')
        >>> id1 == id2
        True

        >>> # Case-insensitive normalization
        >>> id1 = generate_canonical_iri('company', 'ACME')
        >>> id2 = generate_canonical_iri('company', 'acme')
        >>> id1 == id2
        True
    """
    entity_type_lower = entity_type.lower()
    namespace = NAMESPACES.get(entity_type_lower)

    if not namespace:
        valid_types = ', '.join(NAMESPACES.keys())
        raise ValueError(
            f"Unknown entity type: '{entity_type}'. "
            f"Valid types: {valid_types}"
        )

    # Normalize the natural key (lowercase, trimmed)
    normalized_key = natural_key.lower().strip()

    # Generate deterministic UUID v5
    canonical_uuid = uuid.uuid5(namespace, normalized_key)

    return f"urn:uuid:{canonical_uuid}"


def generate_random_iri(entity_type: Optional[str] = None) -> str:
    """
    Generate a random IRI using UUID v4.

    Use this when you don't have a natural key for deterministic IDs.
    Each call produces a unique IRI.

    Args:
        entity_type: Optional entity type for URL-style IRI

    Returns:
        Random IRI

    Examples:
        >>> generate_random_iri()
        'urn:uuid:550e8400-e29b-41d4-a716-446655440000'

        >>> generate_random_iri('company')
        'https://schema.example.com/companies/550e8400-e29b-41d4-a716-446655440000'
    """
    random_uuid = uuid.uuid4()

    if entity_type:
        return generate_entity_url(entity_type, str(random_uuid))

    return f"urn:uuid:{random_uuid}"


def generate_entity_url(entity_type: str, entity_id: str) -> str:
    """
    Generate HTTPS URL for an entity.

    Creates a dereferenceable URL that could return JSON-LD when fetched.
    Useful for public APIs and web-accessible resources.

    Args:
        entity_type: Type of entity (pluralized in URL)
        entity_id: Entity ID (UUID string)

    Returns:
        HTTPS URL

    Examples:
        >>> generate_entity_url('company', 'abc123')
        'https://schema.example.com/companies/abc123'

        >>> generate_entity_url('person', 'def456')
        'https://schema.example.com/persons/def456'
    """
    # Pluralize entity type for URL
    plural_map = {
        'company': 'companies',
        'person': 'persons',
        'category': 'categories',
        'location': 'locations',
        'file': 'files',
        'session': 'sessions',
    }
    plural = plural_map.get(entity_type.lower(), f"{entity_type.lower()}s")

    return f"{BASE_URI}/{plural}/{entity_id}"


def is_valid_iri(iri: str) -> bool:
    """
    Check if a string is a valid IRI for JSON-LD @id.

    Valid IRIs for Schema.org @id include:
    - HTTPS URLs (https://...)
    - HTTP URLs (http://...)
    - URN schemes (urn:uuid:..., urn:sha256:...)

    Args:
        iri: String to validate

    Returns:
        True if valid IRI, False otherwise

    Examples:
        >>> is_valid_iri('urn:uuid:550e8400-e29b-41d4-a716-446655440000')
        True

        >>> is_valid_iri('https://example.com/entity/123')
        True

        >>> is_valid_iri('just-a-string')
        False
    """
    if not iri or not isinstance(iri, str):
        return False

    valid_prefixes = (
        'http://',
        'https://',
        'urn:uuid:',
        'urn:sha256:',
        'urn:isbn:',
        'urn:issn:',
        'urn:doi:',
    )

    return iri.startswith(valid_prefixes)


def normalize_to_iri(value: str) -> str:
    """
    Normalize a value to a valid IRI.

    If the value is already a valid IRI, return it unchanged.
    Otherwise, treat it as a UUID and wrap in urn:uuid:.

    Args:
        value: String that might be an IRI or UUID

    Returns:
        Valid IRI string

    Examples:
        >>> normalize_to_iri('https://example.com/entity')
        'https://example.com/entity'

        >>> normalize_to_iri('550e8400-e29b-41d4-a716-446655440000')
        'urn:uuid:550e8400-e29b-41d4-a716-446655440000'

        >>> normalize_to_iri('urn:uuid:abc123')
        'urn:uuid:abc123'
    """
    if is_valid_iri(value):
        return value

    # Check if it looks like a UUID
    try:
        uuid.UUID(value)
        return f"urn:uuid:{value}"
    except (ValueError, AttributeError):
        pass

    # Treat as SHA-256 hash if 64 hex characters
    if len(value) == 64 and all(c in '0123456789abcdef' for c in value.lower()):
        return f"urn:sha256:{value}"

    # Fallback: wrap in urn:uuid: with generated UUID from value
    deterministic_uuid = uuid.uuid5(NAMESPACES['file'], value)
    return f"urn:uuid:{deterministic_uuid}"


def extract_uuid_from_iri(iri: str) -> Optional[str]:
    """
    Extract UUID from an IRI if present.

    Args:
        iri: IRI string

    Returns:
        UUID string if found, None otherwise

    Examples:
        >>> extract_uuid_from_iri('urn:uuid:550e8400-e29b-41d4-a716-446655440000')
        '550e8400-e29b-41d4-a716-446655440000'

        >>> extract_uuid_from_iri('https://example.com/entities/abc-123-def')
        'abc-123-def'

        >>> extract_uuid_from_iri('urn:sha256:abc123')
        None
    """
    if not iri:
        return None

    if iri.startswith('urn:uuid:'):
        return iri[9:]  # Remove 'urn:uuid:' prefix

    if iri.startswith(('http://', 'https://')):
        # Extract last path segment
        parts = iri.rstrip('/').split('/')
        if parts:
            return parts[-1]

    return None


def generate_merge_event_id() -> str:
    """
    Generate a unique ID for a merge event.

    Returns:
        Unique merge event IRI
    """
    return f"urn:uuid:{uuid.uuid4()}"


def generate_same_as_jsonld(canonical_iri: str, merged_iris: list) -> dict:
    """
    Generate JSON-LD with owl:sameAs for merged entities.

    Used when deduplicating entities to preserve the semantic
    relationship between the canonical entity and merged entities.

    Args:
        canonical_iri: IRI of the canonical (surviving) entity
        merged_iris: List of IRIs that were merged into canonical

    Returns:
        JSON-LD dict with owl:sameAs relationship

    Example:
        >>> generate_same_as_jsonld(
        ...     'urn:uuid:canonical-123',
        ...     ['urn:uuid:merged-1', 'urn:uuid:merged-2']
        ... )
        {
            '@id': 'urn:uuid:canonical-123',
            'owl:sameAs': ['urn:uuid:merged-1', 'urn:uuid:merged-2']
        }
    """
    return {
        '@id': canonical_iri,
        'owl:sameAs': merged_iris if len(merged_iris) > 1 else merged_iris[0]
    }
