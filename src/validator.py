"""
Schema.org validation system.

Validates Schema.org structured data against specifications,
checks required properties, verifies data types, and generates
comprehensive validation reports.
"""

from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum
from datetime import datetime
import re
import json


class ValidationLevel(Enum):
    """Validation message levels."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    SUCCESS = "success"


class ValidationMessage:
    """Represents a validation message."""

    def __init__(self, level: ValidationLevel, message: str,
                 property_name: Optional[str] = None,
                 suggestion: Optional[str] = None):
        """
        Initialize validation message.

        Args:
            level: Message level
            message: Message text
            property_name: Property that caused the message
            suggestion: Suggested fix
        """
        self.level = level
        self.message = message
        self.property_name = property_name
        self.suggestion = suggestion
        self.timestamp = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "level": self.level.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat()
        }
        if self.property_name:
            result["property"] = self.property_name
        if self.suggestion:
            result["suggestion"] = self.suggestion
        return result

    def __str__(self) -> str:
        """String representation."""
        prefix = f"[{self.level.value.upper()}]"
        prop = f" ({self.property_name})" if self.property_name else ""
        return f"{prefix}{prop}: {self.message}"


class ValidationReport:
    """
    Comprehensive validation report.

    Tracks validation messages, statistics, and provides
    detailed reporting capabilities.
    """

    def __init__(self, schema_type: str):
        """
        Initialize validation report.

        Args:
            schema_type: Schema.org type being validated
        """
        self.schema_type = schema_type
        self.messages: List[ValidationMessage] = []
        self.start_time = datetime.now()
        self.end_time: Optional[datetime] = None

    def add_message(self, level: ValidationLevel, message: str,
                   property_name: Optional[str] = None,
                   suggestion: Optional[str] = None) -> None:
        """
        Add validation message.

        Args:
            level: Message level
            message: Message text
            property_name: Property name
            suggestion: Suggested fix
        """
        self.messages.append(
            ValidationMessage(level, message, property_name, suggestion)
        )

    def add_error(self, message: str, property_name: Optional[str] = None,
                 suggestion: Optional[str] = None) -> None:
        """Add error message."""
        self.add_message(ValidationLevel.ERROR, message, property_name, suggestion)

    def add_warning(self, message: str, property_name: Optional[str] = None,
                   suggestion: Optional[str] = None) -> None:
        """Add warning message."""
        self.add_message(ValidationLevel.WARNING, message, property_name, suggestion)

    def add_info(self, message: str, property_name: Optional[str] = None,
                suggestion: Optional[str] = None) -> None:
        """Add info message."""
        self.add_message(ValidationLevel.INFO, message, property_name, suggestion)

    def add_success(self, message: str) -> None:
        """Add success message."""
        self.add_message(ValidationLevel.SUCCESS, message)

    def finalize(self) -> None:
        """Finalize the report."""
        self.end_time = datetime.now()

    def has_errors(self) -> bool:
        """Check if report has errors."""
        return any(msg.level == ValidationLevel.ERROR for msg in self.messages)

    def has_warnings(self) -> bool:
        """Check if report has warnings."""
        return any(msg.level == ValidationLevel.WARNING for msg in self.messages)

    def is_valid(self) -> bool:
        """Check if validation passed (no errors)."""
        return not self.has_errors()

    def get_messages_by_level(self, level: ValidationLevel) -> List[ValidationMessage]:
        """Get messages by level."""
        return [msg for msg in self.messages if msg.level == level]

    def get_statistics(self) -> Dict[str, int]:
        """Get validation statistics."""
        return {
            "total": len(self.messages),
            "errors": len(self.get_messages_by_level(ValidationLevel.ERROR)),
            "warnings": len(self.get_messages_by_level(ValidationLevel.WARNING)),
            "info": len(self.get_messages_by_level(ValidationLevel.INFO)),
            "success": len(self.get_messages_by_level(ValidationLevel.SUCCESS))
        }

    def get_duration(self) -> float:
        """Get validation duration in seconds."""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return (datetime.now() - self.start_time).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "schema_type": self.schema_type,
            "valid": self.is_valid(),
            "statistics": self.get_statistics(),
            "duration": self.get_duration(),
            "messages": [msg.to_dict() for msg in self.messages],
            "timestamp": self.start_time.isoformat()
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def print_summary(self) -> None:
        """Print validation summary."""
        stats = self.get_statistics()
        print(f"\n{'='*60}")
        print(f"Schema.org Validation Report: {self.schema_type}")
        print(f"{'='*60}")
        print(f"Status: {'VALID' if self.is_valid() else 'INVALID'}")
        print(f"Duration: {self.get_duration():.3f}s")
        print(f"\nStatistics:")
        print(f"  Total messages: {stats['total']}")
        print(f"  Errors: {stats['errors']}")
        print(f"  Warnings: {stats['warnings']}")
        print(f"  Info: {stats['info']}")
        print(f"  Success: {stats['success']}")

        if self.messages:
            print(f"\nMessages:")
            for msg in self.messages:
                print(f"  {msg}")

        print(f"{'='*60}\n")

    def __str__(self) -> str:
        """String representation."""
        return f"ValidationReport(type={self.schema_type}, valid={self.is_valid()}, messages={len(self.messages)})"


class SchemaValidator:
    """
    Validates Schema.org structured data.

    Performs comprehensive validation including:
    - Required property checks
    - Data type validation
    - Format validation (URLs, dates, etc.)
    - Schema.org specification compliance
    - Google Rich Results compatibility
    """

    # Known Schema.org types and their requirements
    SCHEMA_TYPES = {
        "Thing": {"required": [], "recommended": ["name", "description"]},
        "CreativeWork": {"required": ["name"], "recommended": ["author", "datePublished"]},
        "DigitalDocument": {"required": ["name"], "recommended": ["author", "encodingFormat"]},
        "Article": {"required": ["headline"], "recommended": ["author", "datePublished", "image"]},
        "ImageObject": {"required": ["contentUrl"], "recommended": ["name", "description"]},
        "VideoObject": {"required": ["name", "uploadDate"], "recommended": ["description", "thumbnailUrl"]},
        "AudioObject": {"required": ["name"], "recommended": ["contentUrl", "duration"]},
        "SoftwareSourceCode": {"required": ["name"], "recommended": ["programmingLanguage", "codeRepository"]},
        "Dataset": {"required": ["name", "description"], "recommended": ["creator", "distribution"]},
    }

    # Expected property types
    PROPERTY_TYPES = {
        "name": str,
        "description": str,
        "url": str,
        "contentUrl": str,
        "thumbnailUrl": str,
        "dateCreated": str,
        "dateModified": str,
        "datePublished": str,
        "uploadDate": str,
        "width": int,
        "height": int,
        "duration": str,
        "encodingFormat": str,
        "keywords": str,
    }

    def __init__(self):
        """Initialize validator."""
        self.url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
            r'localhost|'  # localhost
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # IP
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE
        )

        self.date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
        self.datetime_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}')
        self.duration_pattern = re.compile(r'^P(?:\d+Y)?(?:\d+M)?(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?$')

    def validate(self, schema_data: Dict[str, Any]) -> ValidationReport:
        """
        Validate Schema.org structured data.

        Args:
            schema_data: Schema.org data dictionary

        Returns:
            Validation report
        """
        schema_type = schema_data.get("@type", "Unknown")
        report = ValidationReport(schema_type)

        # Validate basic structure
        self._validate_structure(schema_data, report)

        # Validate required properties
        self._validate_required_properties(schema_data, report)

        # Validate property types
        self._validate_property_types(schema_data, report)

        # Validate formats
        self._validate_formats(schema_data, report)

        # Validate nested schemas
        self._validate_nested_schemas(schema_data, report)

        # Check recommended properties
        self._check_recommended_properties(schema_data, report)

        # Google Rich Results checks
        self._validate_rich_results_compatibility(schema_data, report)

        report.finalize()
        return report

    def _validate_structure(self, data: Dict[str, Any], report: ValidationReport) -> None:
        """Validate basic structure."""
        if "@context" not in data:
            report.add_error(
                "Missing @context property",
                "@context",
                "Add '@context': 'https://schema.org'"
            )

        if "@type" not in data:
            report.add_error(
                "Missing @type property",
                "@type",
                "Specify the Schema.org type (e.g., 'DigitalDocument')"
            )
        else:
            schema_type = data["@type"]
            if schema_type not in self.SCHEMA_TYPES:
                report.add_warning(
                    f"Unknown Schema.org type: {schema_type}",
                    "@type",
                    "Verify the type exists in Schema.org vocabulary"
                )
            else:
                report.add_success(f"Valid Schema.org type: {schema_type}")

    def _validate_required_properties(self, data: Dict[str, Any], report: ValidationReport) -> None:
        """Validate required properties."""
        schema_type = data.get("@type")
        if schema_type in self.SCHEMA_TYPES:
            required = self.SCHEMA_TYPES[schema_type]["required"]
            for prop in required:
                if prop not in data:
                    report.add_error(
                        f"Missing required property: {prop}",
                        prop,
                        f"Add the '{prop}' property with an appropriate value"
                    )
                elif not data[prop]:
                    report.add_error(
                        f"Required property is empty: {prop}",
                        prop,
                        f"Provide a value for '{prop}'"
                    )

    def _validate_property_types(self, data: Dict[str, Any], report: ValidationReport) -> None:
        """Validate property types."""
        for prop, expected_type in self.PROPERTY_TYPES.items():
            if prop in data:
                value = data[prop]
                if not isinstance(value, (expected_type, dict, list)):
                    report.add_error(
                        f"Invalid type for {prop}: expected {expected_type.__name__}, got {type(value).__name__}",
                        prop,
                        f"Convert {prop} to {expected_type.__name__}"
                    )

    def _validate_formats(self, data: Dict[str, Any], report: ValidationReport) -> None:
        """Validate format of specific properties."""
        # Validate URLs
        url_properties = ["url", "contentUrl", "thumbnailUrl", "codeRepository", "sameAs"]
        for prop in url_properties:
            if prop in data and isinstance(data[prop], str):
                if not self.url_pattern.match(data[prop]):
                    report.add_error(
                        f"Invalid URL format: {prop}",
                        prop,
                        "Use absolute URLs starting with http:// or https://"
                    )

        # Validate dates
        date_properties = ["dateCreated", "dateModified", "datePublished", "uploadDate"]
        for prop in date_properties:
            if prop in data and isinstance(data[prop], str):
                value = data[prop]
                if not (self.date_pattern.match(value) or self.datetime_pattern.match(value)):
                    report.add_warning(
                        f"Date format may be invalid: {prop}",
                        prop,
                        "Use ISO 8601 format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"
                    )

        # Validate duration
        if "duration" in data and isinstance(data["duration"], str):
            if not self.duration_pattern.match(data["duration"]):
                report.add_warning(
                    "Duration format may be invalid",
                    "duration",
                    "Use ISO 8601 duration format (e.g., PT1H30M for 1 hour 30 minutes)"
                )

    def _validate_nested_schemas(self, data: Dict[str, Any], report: ValidationReport) -> None:
        """Validate nested schemas."""
        for key, value in data.items():
            if isinstance(value, dict) and "@type" in value:
                # Recursively validate nested schema
                nested_report = self.validate(value)
                if nested_report.has_errors():
                    report.add_warning(
                        f"Nested schema '{key}' has validation errors",
                        key,
                        "Review nested schema validation"
                    )
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict) and "@type" in item:
                        nested_report = self.validate(item)
                        if nested_report.has_errors():
                            report.add_warning(
                                f"Nested schema in '{key}[{i}]' has validation errors",
                                key,
                                "Review nested schema validation"
                            )

    def _check_recommended_properties(self, data: Dict[str, Any], report: ValidationReport) -> None:
        """Check recommended properties."""
        schema_type = data.get("@type")
        if schema_type in self.SCHEMA_TYPES:
            recommended = self.SCHEMA_TYPES[schema_type]["recommended"]
            missing_recommended = []
            for prop in recommended:
                if prop not in data:
                    missing_recommended.append(prop)

            if missing_recommended:
                report.add_info(
                    f"Missing recommended properties: {', '.join(missing_recommended)}",
                    suggestion="Adding these properties improves search visibility"
                )

    def _validate_rich_results_compatibility(self, data: Dict[str, Any], report: ValidationReport) -> None:
        """Validate Google Rich Results compatibility."""
        schema_type = data.get("@type")

        # Article requirements for Google
        if schema_type in ["Article", "NewsArticle", "BlogPosting"]:
            if "headline" not in data:
                report.add_error("Articles require 'headline' for Rich Results", "headline")
            if "image" not in data:
                report.add_warning("Articles should include 'image' for Rich Results", "image")
            if "author" not in data:
                report.add_warning("Articles should include 'author' for Rich Results", "author")
            if "datePublished" not in data:
                report.add_warning("Articles should include 'datePublished' for Rich Results", "datePublished")

        # Video requirements for Google
        if schema_type == "VideoObject":
            required_video = ["name", "description", "thumbnailUrl", "uploadDate"]
            for prop in required_video:
                if prop not in data:
                    report.add_error(
                        f"Videos require '{prop}' for Rich Results",
                        prop
                    )

        # Image requirements
        if schema_type == "ImageObject":
            if "contentUrl" not in data:
                report.add_error("Images require 'contentUrl' for Rich Results", "contentUrl")

    def validate_batch(self, schemas: List[Dict[str, Any]]) -> List[ValidationReport]:
        """
        Validate multiple schemas.

        Args:
            schemas: List of schema dictionaries

        Returns:
            List of validation reports
        """
        return [self.validate(schema) for schema in schemas]

    def generate_summary_report(self, reports: List[ValidationReport]) -> Dict[str, Any]:
        """
        Generate summary report for batch validation.

        Args:
            reports: List of validation reports

        Returns:
            Summary dictionary
        """
        total_schemas = len(reports)
        valid_schemas = sum(1 for r in reports if r.is_valid())
        total_errors = sum(len(r.get_messages_by_level(ValidationLevel.ERROR)) for r in reports)
        total_warnings = sum(len(r.get_messages_by_level(ValidationLevel.WARNING)) for r in reports)

        return {
            "total_schemas": total_schemas,
            "valid_schemas": valid_schemas,
            "invalid_schemas": total_schemas - valid_schemas,
            "success_rate": (valid_schemas / total_schemas * 100) if total_schemas > 0 else 0,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "reports": [r.to_dict() for r in reports]
        }
