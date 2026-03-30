"""
Alternative schema.org representations for entities in different contexts.

Provides variant serializations for cases where a single entity may need
to be represented differently depending on the consumer:
  - CategoryVariants: DefinedTerm or simplified Intangible
  - PersonVariants: Person with contextual relationships
  - FileVariants: CreativeWork or media-type-specific MediaObject
"""

from typing import Any, Dict, List, Optional

SCHEMA_ORG_CONTEXT = "https://schema.org"


class CategoryVariants:
    """Alternative representations for Category entities."""

    @staticmethod
    def to_defined_term(
        canonical_id: str,
        name: str,
        description: Optional[str] = None,
        full_path: Optional[str] = None,
        parent_iri: Optional[str] = None,
        children_iris: Optional[Dict[str, str]] = None,
        file_count: int = 0,
        icon: Optional[str] = None,
        color: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Serialize a category as a schema.org DefinedTerm (primary representation).

        Args:
            canonical_id: Canonical UUID used to build the @id IRI.
            name: Human-readable category name.
            description: Optional description or definition.
            full_path: Hierarchical path (e.g. "Legal/Contracts").
            parent_iri: @id IRI of the parent DefinedTerm, if any.
            children_iris: Mapping of child IRI -> child name, if any.
            file_count: Number of files in this category.
            icon: Optional icon/emoji.
            color: Optional hex color string.

        Returns:
            JSON-LD dict with @context, @type DefinedTerm.
        """
        result: Dict[str, Any] = {
            "@context": SCHEMA_ORG_CONTEXT,
            "@type": "DefinedTerm",
            "@id": f"urn:uuid:{canonical_id}",
            "name": name,
            "inDefinedTermSet": {
                "@type": "DefinedTermSet",
                "@id": "urn:uuid:categories-taxonomy",
                "name": "File Organization Categories",
            },
        }

        result["definition"] = description if description else f"Category: {name}"

        if full_path:
            result["identifier"] = full_path.lower().replace("/", "-")

        if parent_iri:
            result["broader"] = {
                "@type": "DefinedTerm",
                "@id": parent_iri,
            }

        if children_iris:
            result["narrower"] = [
                {"@type": "DefinedTerm", "@id": iri, "name": child_name}
                for iri, child_name in children_iris.items()
            ]

        result["fileCount"] = file_count

        if icon:
            result["icon"] = icon

        if color:
            result["color"] = color

        return result

    @staticmethod
    def to_intangible(
        canonical_id: str,
        name: str,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Serialize a category as a simplified schema.org Intangible.

        Useful for lightweight consumers that do not need full taxonomy context.

        Args:
            canonical_id: Canonical UUID used to build the @id IRI.
            name: Human-readable category name.
            description: Optional description.

        Returns:
            JSON-LD dict with @context, @type Intangible.
        """
        result: Dict[str, Any] = {
            "@context": SCHEMA_ORG_CONTEXT,
            "@type": "Intangible",
            "@id": f"urn:uuid:{canonical_id}",
            "name": name,
        }

        if description:
            result["description"] = description

        return result


class PersonVariants:
    """Alternative representations for Person entities."""

    @staticmethod
    def to_person_with_context(
        canonical_id: str,
        name: str,
        email: Optional[str] = None,
        job_title: Optional[str] = None,
        works_for_iri: Optional[str] = None,
        works_for_name: Optional[str] = None,
        work_location_iri: Optional[str] = None,
        work_location_name: Optional[str] = None,
        mention_count: int = 0,
    ) -> Dict[str, Any]:
        """Serialize a person with optional organizational relationships.

        Args:
            canonical_id: Canonical UUID used to build the @id IRI.
            name: Full name.
            email: Optional email address.
            job_title: Optional job title / role.
            works_for_iri: @id IRI of the employing Organization, if known.
            works_for_name: Name of the employing Organization, if known.
            work_location_iri: @id IRI of the work Place, if known.
            work_location_name: Name of the work Place, if known.
            mention_count: Number of file mentions.

        Returns:
            JSON-LD dict with @context, @type Person.
        """
        result: Dict[str, Any] = {
            "@context": SCHEMA_ORG_CONTEXT,
            "@type": "Person",
            "@id": f"urn:uuid:{canonical_id}",
            "name": name,
            "mentionCount": mention_count,
        }

        if email:
            result["email"] = email

        if job_title:
            result["jobTitle"] = job_title

        if works_for_iri or works_for_name:
            works_for: Dict[str, Any] = {"@type": "Organization"}
            if works_for_iri:
                works_for["@id"] = works_for_iri
            if works_for_name:
                works_for["name"] = works_for_name
            result["worksFor"] = works_for

        if work_location_iri or work_location_name:
            work_location: Dict[str, Any] = {"@type": "Place"}
            if work_location_iri:
                work_location["@id"] = work_location_iri
            if work_location_name:
                work_location["name"] = work_location_name
            result["workLocation"] = work_location

        return result


class FileVariants:
    """Alternative representations for File entities."""

    @staticmethod
    def to_creative_work(
        iri: str,
        name: str,
        encoding_format: Optional[str] = None,
        content_size: Optional[int] = None,
        date_created: Optional[str] = None,
        date_modified: Optional[str] = None,
        url: Optional[str] = None,
        text: Optional[str] = None,
        about_iris: Optional[List[Dict[str, str]]] = None,
        mentions: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Serialize a file as a generic schema.org CreativeWork.

        Args:
            iri: @id IRI for this file.
            name: File name.
            encoding_format: MIME type string.
            content_size: Size in bytes.
            date_created: ISO-8601 datetime string.
            date_modified: ISO-8601 datetime string.
            url: Original file path / URL.
            text: Extracted text excerpt (will be truncated to 2000 chars).
            about_iris: List of {"@type", "@id", "name"} dicts for category refs.
            mentions: List of {"@type", "@id", "name"} dicts for entity mentions.

        Returns:
            JSON-LD dict with @context, @type CreativeWork.
        """
        result: Dict[str, Any] = {
            "@context": SCHEMA_ORG_CONTEXT,
            "@type": "CreativeWork",
            "@id": iri,
            "name": name,
        }

        if encoding_format:
            result["encodingFormat"] = encoding_format

        if content_size is not None:
            result["contentSize"] = str(content_size)

        if date_created:
            result["dateCreated"] = date_created

        if date_modified:
            result["dateModified"] = date_modified

        if url:
            result["url"] = url

        if text:
            result["text"] = text[:2000]

        if about_iris:
            result["mainEntityOfPage"] = about_iris[0]
            if len(about_iris) > 1:
                result["about"] = about_iris[1:]

        if mentions:
            result["mentions"] = mentions

        return result

    @staticmethod
    def to_media_object(
        iri: str,
        name: str,
        schema_type: str,
        encoding_format: Optional[str] = None,
        content_size: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        duration: Optional[str] = None,
        date_created: Optional[str] = None,
        url: Optional[str] = None,
        content_location: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Serialize a file as a media-specific schema.org MediaObject subtype.

        Args:
            iri: @id IRI for this file.
            name: File name.
            schema_type: One of ImageObject, VideoObject, AudioObject.
            encoding_format: MIME type.
            content_size: Size in bytes.
            width: Width in pixels (images/video).
            height: Height in pixels (images/video).
            duration: ISO-8601 duration (audio/video).
            date_created: ISO-8601 datetime string.
            url: Original file path / URL.
            content_location: Nested Place dict with geo coordinates.

        Returns:
            JSON-LD dict with @context, @type set to schema_type.
        """
        result: Dict[str, Any] = {
            "@context": SCHEMA_ORG_CONTEXT,
            "@type": schema_type,
            "@id": iri,
            "name": name,
        }

        if encoding_format:
            result["encodingFormat"] = encoding_format

        if content_size is not None:
            result["contentSize"] = str(content_size)

        if width is not None:
            result["width"] = width

        if height is not None:
            result["height"] = height

        if duration:
            result["duration"] = duration

        if date_created:
            result["dateCreated"] = date_created

        if url:
            result["url"] = url

        if content_location:
            result["contentLocation"] = content_location

        return result
