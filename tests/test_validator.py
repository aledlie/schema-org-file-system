"""
Test suite for Schema.org validator.

Tests validation rules and compliance checking.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import unittest
from validator import SchemaValidator, ValidationReport, ValidationLevel


class TestSchemaValidator(unittest.TestCase):
    """Test SchemaValidator class."""

    def setUp(self):
        """Set up test fixtures."""
        self.validator = SchemaValidator()

    def test_valid_schema(self):
        """Test validation of a valid schema."""
        schema = {
            "@context": "https://schema.org",
            "@type": "DigitalDocument",
            "name": "Test Document",
            "encodingFormat": "application/pdf"
        }

        report = self.validator.validate(schema)
        self.assertTrue(report.is_valid())
        self.assertFalse(report.has_errors())

    def test_missing_context(self):
        """Test detection of missing @context."""
        schema = {
            "@type": "DigitalDocument",
            "name": "Test Document"
        }

        report = self.validator.validate(schema)
        self.assertTrue(report.has_errors())
        errors = report.get_messages_by_level(ValidationLevel.ERROR)
        self.assertTrue(any("@context" in msg.message for msg in errors))

    def test_missing_type(self):
        """Test detection of missing @type."""
        schema = {
            "@context": "https://schema.org",
            "name": "Test Document"
        }

        report = self.validator.validate(schema)
        self.assertTrue(report.has_errors())

    def test_missing_required_properties(self):
        """Test detection of missing required properties."""
        schema = {
            "@context": "https://schema.org",
            "@type": "DigitalDocument"
            # Missing 'name' which is required
        }

        report = self.validator.validate(schema)
        # Should have warning about missing recommended properties
        self.assertTrue(len(report.messages) > 0)

    def test_invalid_url_format(self):
        """Test detection of invalid URL format."""
        schema = {
            "@context": "https://schema.org",
            "@type": "ImageObject",
            "contentUrl": "not-a-valid-url",
            "name": "Test Image"
        }

        report = self.validator.validate(schema)
        self.assertTrue(report.has_errors())

    def test_recommended_properties(self):
        """Test checking of recommended properties."""
        schema = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": "Test Article"
            # Missing recommended properties like author, datePublished
        }

        report = self.validator.validate(schema)
        info_messages = report.get_messages_by_level(ValidationLevel.INFO)
        self.assertTrue(len(info_messages) > 0)

    def test_nested_schema_validation(self):
        """Test validation of nested schemas."""
        schema = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": "Test Article",
            "author": {
                "@type": "Person",
                "name": "John Doe"
            }
        }

        report = self.validator.validate(schema)
        # Nested schema should be validated
        self.assertIsNotNone(report)

    def test_rich_results_compatibility(self):
        """Test Google Rich Results compatibility checks."""
        # Article without required fields for Rich Results
        schema = {
            "@context": "https://schema.org",
            "@type": "Article",
            "name": "Test"
            # Missing headline, image, author, datePublished
        }

        report = self.validator.validate(schema)
        self.assertTrue(report.has_errors() or report.has_warnings())

    def test_video_object_requirements(self):
        """Test VideoObject requirements for Rich Results."""
        schema = {
            "@context": "https://schema.org",
            "@type": "VideoObject",
            "name": "Test Video"
            # Missing description, thumbnailUrl, uploadDate
        }

        report = self.validator.validate(schema)
        self.assertTrue(report.has_errors())

    def test_batch_validation(self):
        """Test batch validation of multiple schemas."""
        schemas = [
            {
                "@context": "https://schema.org",
                "@type": "DigitalDocument",
                "name": "Doc 1",
                "encodingFormat": "application/pdf"
            },
            {
                "@context": "https://schema.org",
                "@type": "ImageObject",
                "contentUrl": "https://example.com/img.jpg",
                "name": "Image 1"
            }
        ]

        reports = self.validator.validate_batch(schemas)
        self.assertEqual(len(reports), 2)

    def test_summary_report(self):
        """Test generation of summary report."""
        schemas = [
            {
                "@context": "https://schema.org",
                "@type": "DigitalDocument",
                "name": "Valid Doc",
                "encodingFormat": "application/pdf"
            },
            {
                "@context": "https://schema.org",
                "@type": "ImageObject"
                # Invalid - missing required properties
            }
        ]

        reports = self.validator.validate_batch(schemas)
        summary = self.validator.generate_summary_report(reports)

        self.assertEqual(summary["total_schemas"], 2)
        self.assertIn("valid_schemas", summary)
        self.assertIn("success_rate", summary)


class TestValidationReport(unittest.TestCase):
    """Test ValidationReport class."""

    def setUp(self):
        """Set up test fixtures."""
        self.report = ValidationReport("DigitalDocument")

    def test_add_messages(self):
        """Test adding messages to report."""
        self.report.add_error("Error message", "propertyName")
        self.report.add_warning("Warning message")
        self.report.add_info("Info message")

        self.assertEqual(len(self.report.messages), 3)
        self.assertTrue(self.report.has_errors())
        self.assertTrue(self.report.has_warnings())

    def test_validation_status(self):
        """Test validation status determination."""
        self.assertTrue(self.report.is_valid())

        self.report.add_warning("Warning")
        self.assertTrue(self.report.is_valid())  # Warnings don't invalidate

        self.report.add_error("Error")
        self.assertFalse(self.report.is_valid())  # Errors invalidate

    def test_statistics(self):
        """Test statistics generation."""
        self.report.add_error("Error 1")
        self.report.add_error("Error 2")
        self.report.add_warning("Warning 1")
        self.report.add_info("Info 1")

        stats = self.report.get_statistics()
        self.assertEqual(stats["errors"], 2)
        self.assertEqual(stats["warnings"], 1)
        self.assertEqual(stats["info"], 1)
        self.assertEqual(stats["total"], 4)

    def test_messages_by_level(self):
        """Test filtering messages by level."""
        self.report.add_error("Error")
        self.report.add_warning("Warning")

        errors = self.report.get_messages_by_level(ValidationLevel.ERROR)
        warnings = self.report.get_messages_by_level(ValidationLevel.WARNING)

        self.assertEqual(len(errors), 1)
        self.assertEqual(len(warnings), 1)

    def test_to_dict(self):
        """Test conversion to dictionary."""
        self.report.add_error("Test error")
        self.report.finalize()

        report_dict = self.report.to_dict()
        self.assertIn("schema_type", report_dict)
        self.assertIn("valid", report_dict)
        self.assertIn("statistics", report_dict)
        self.assertIn("messages", report_dict)

    def test_duration_tracking(self):
        """Test duration tracking."""
        import time
        time.sleep(0.1)
        self.report.finalize()

        duration = self.report.get_duration()
        self.assertGreater(duration, 0)


def run_tests():
    """Run all tests."""
    unittest.main(argv=[''], verbosity=2, exit=False)


if __name__ == '__main__':
    run_tests()
