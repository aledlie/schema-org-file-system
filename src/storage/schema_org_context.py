"""
JSON-LD @context document generation for schema.org exports.

Generates a standalone context document that maps all custom and schema.org
terms used in exports from the five entity models (File, Category, Company,
Person, Location).
"""

from pathlib import Path
from typing import Dict, Union
import json

SCHEMA_ORG_VOCAB = "https://schema.org/"
ML_NAMESPACE = "https://schema-org-fs.example.com/ml#"

# Full @context document covering all emitted properties from all five models
_CONTEXT_DOCUMENT: Dict[str, Dict[str, str]] = {
    "@context": {
        # Vocab and standard prefixes
        "@vocab": SCHEMA_ORG_VOCAB,
        "schema": SCHEMA_ORG_VOCAB,
        "ml": ML_NAMESPACE,

        # ---------------------------------------------------------------
        # File (ImageObject / VideoObject / DigitalDocument / AudioObject)
        # ---------------------------------------------------------------
        "name": "schema:name",
        "dateCreated": "schema:dateCreated",
        "dateModified": "schema:dateModified",
        "datePublished": "schema:datePublished",
        "encodingFormat": "schema:encodingFormat",
        "contentSize": "schema:contentSize",
        "url": "schema:url",
        "text": "schema:text",
        "width": "schema:width",
        "height": "schema:height",
        "contentLocation": "schema:contentLocation",

        # Custom ml: extension — not a standard schema.org property
        "hasFaces": "ml:hasFaces",

        # ---------------------------------------------------------------
        # Category (DefinedTerm)
        # ---------------------------------------------------------------
        "identifier": "schema:identifier",
        "definition": "schema:description",
        "inDefinedTermSet": "schema:inDefinedTermSet",
        "broader": "schema:broader",
        "narrower": "schema:narrower",

        # Non-standard extensions on Category
        "fileCount": "ml:fileCount",
        "hierarchyLevel": "ml:hierarchyLevel",

        # ---------------------------------------------------------------
        # Company (Organization)
        # ---------------------------------------------------------------
        "knowsAbout": "schema:knowsAbout",
        "dateFounded": "schema:foundingDate",
        "sameAs": "schema:sameAs",

        # Non-standard extension shared by Company/Person/Location
        "mentionCount": "ml:mentionCount",

        # ---------------------------------------------------------------
        # Person
        # ---------------------------------------------------------------
        "email": "schema:email",
        "jobTitle": "schema:jobTitle",
        "worksFor": "schema:worksFor",
        "workLocation": "schema:workLocation",

        # ---------------------------------------------------------------
        # Location (Place / City / Country)
        # ---------------------------------------------------------------
        "address": "schema:address",
        "geo": "schema:geo",

        # Non-standard geohash extension
        "geoHash": "ml:geoHash",

        # Nested types used in address / geo
        "PostalAddress": "schema:PostalAddress",
        "GeoCoordinates": "schema:GeoCoordinates",
        "addressLocality": "schema:addressLocality",
        "addressRegion": "schema:addressRegion",
        "addressCountry": "schema:addressCountry",
        "latitude": "schema:latitude",
        "longitude": "schema:longitude",

        # ---------------------------------------------------------------
        # @graph export format
        # ---------------------------------------------------------------
        # @context, @type, @id, and @graph are JSON-LD keywords —
        # no explicit mapping needed; listed here for documentation.
    }
}


def get_context_document() -> Dict[str, Dict[str, str]]:
    """Return the JSON-LD @context document as a Python dict.

    Returns:
        Dict containing the standalone @context document.
    """
    return _CONTEXT_DOCUMENT


def export_context(output_path: Union[str, Path], pretty: bool = True) -> None:
    """Save the JSON-LD @context document to a file.

    Args:
        output_path: Destination file path.
        pretty: Whether to pretty-print (indent=2).
    """
    indent = 2 if pretty else None
    Path(output_path).write_text(
        json.dumps(_CONTEXT_DOCUMENT, indent=indent),
        encoding="utf-8",
    )
