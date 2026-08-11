"""Unit tests for src/validator.py — SchemaValidator, ValidationReport, ValidationMessage."""

import json
import pytest

from src.validator import SchemaValidator, ValidationReport, ValidationLevel, ValidationMessage

# ---------------------------------------------------------------------------
# ValidationMessage
# ---------------------------------------------------------------------------


class TestValidationMessage:
    def test_to_dict_basic(self) -> None:
        msg = ValidationMessage(ValidationLevel.ERROR, "bad data")
        d = msg.to_dict()
        assert d["level"] == "error"
        assert d["message"] == "bad data"
        assert "timestamp" in d
        assert "property" not in d

    def test_to_dict_with_property_and_suggestion(self) -> None:
        msg = ValidationMessage(ValidationLevel.WARNING, "missing", "name", "add it")
        d = msg.to_dict()
        assert d["property"] == "name"
        assert d["suggestion"] == "add it"

    def test_str_contains_level_and_message(self) -> None:
        msg = ValidationMessage(ValidationLevel.INFO, "ok info")
        s = str(msg)
        assert "INFO" in s
        assert "ok info" in s


# ---------------------------------------------------------------------------
# ValidationReport
# ---------------------------------------------------------------------------


class TestValidationReport:
    def _report(self) -> ValidationReport:
        return ValidationReport("DigitalDocument")

    def test_is_valid_when_no_errors(self) -> None:
        r = self._report()
        r.add_warning("just a warning")
        assert r.is_valid()

    def test_is_invalid_when_errors_present(self) -> None:
        r = self._report()
        r.add_error("oops")
        assert not r.is_valid()

    def test_has_errors_false_without_errors(self) -> None:
        r = self._report()
        r.add_warning("w")
        assert not r.has_errors()

    def test_has_warnings_true_with_warning(self) -> None:
        r = self._report()
        r.add_warning("w")
        assert r.has_warnings()

    def test_has_warnings_false_without_warnings(self) -> None:
        r = self._report()
        r.add_error("e")
        assert not r.has_warnings()

    def test_get_messages_by_level(self) -> None:
        r = self._report()
        r.add_error("e1")
        r.add_warning("w1")
        r.add_info("i1")
        r.add_success("s1")
        assert len(r.get_messages_by_level(ValidationLevel.ERROR)) == 1
        assert len(r.get_messages_by_level(ValidationLevel.WARNING)) == 1
        assert len(r.get_messages_by_level(ValidationLevel.INFO)) == 1
        assert len(r.get_messages_by_level(ValidationLevel.SUCCESS)) == 1

    def test_get_statistics_counts(self) -> None:
        r = self._report()
        r.add_error("e")
        r.add_error("e2")
        r.add_warning("w")
        stats = r.get_statistics()
        assert stats["errors"] == 2
        assert stats["warnings"] == 1
        assert stats["total"] == 3

    def test_get_duration_positive(self) -> None:
        r = self._report()
        r.finalize()
        assert r.get_duration() >= 0.0

    def test_get_duration_before_finalize(self) -> None:
        r = self._report()
        dur = r.get_duration()
        assert dur >= 0.0

    def test_to_dict_structure(self) -> None:
        r = self._report()
        r.add_error("bad")
        r.finalize()
        d = r.to_dict()
        assert d["schema_type"] == "DigitalDocument"
        assert d["valid"] is False
        assert "statistics" in d
        assert "messages" in d
        assert "duration" in d

    def test_to_json_is_valid_json(self) -> None:
        r = self._report()
        r.add_warning("w")
        payload = r.to_json()
        data = json.loads(payload)
        assert data["schema_type"] == "DigitalDocument"

    def test_print_summary_outputs_messages(self, capsys: pytest.CaptureFixture) -> None:
        r = self._report()
        r.add_error("critical issue")
        r.print_summary()
        out = capsys.readouterr().out
        assert "critical issue" in out

    def test_str_representation(self) -> None:
        r = self._report()
        s = str(r)
        assert "DigitalDocument" in s

    def test_add_message_property_and_suggestion(self) -> None:
        r = self._report()
        r.add_error("missing name", property_name="name", suggestion="add it")
        msg = r.get_messages_by_level(ValidationLevel.ERROR)[0]
        assert msg.property_name == "name"
        assert msg.suggestion == "add it"


# ---------------------------------------------------------------------------
# SchemaValidator — structure checks
# ---------------------------------------------------------------------------


class TestSchemaValidatorStructure:
    def _v(self) -> SchemaValidator:
        return SchemaValidator()

    def _minimal_image(self) -> dict:
        return {
            "@context": "https://schema.org",
            "@type": "ImageObject",
            "contentUrl": "https://localhost/img.png",
            "name": "img.png",
        }

    def test_valid_image_object_is_valid(self) -> None:
        v = self._v()
        report = v.validate(self._minimal_image())
        assert report.is_valid()

    def test_missing_context_adds_error(self) -> None:
        v = self._v()
        schema = {"@type": "ImageObject", "contentUrl": "https://localhost/x.png"}
        report = v.validate(schema)
        errors = [m.message for m in report.get_messages_by_level(ValidationLevel.ERROR)]
        assert any("@context" in e for e in errors)

    def test_missing_type_adds_error(self) -> None:
        v = self._v()
        schema = {"@context": "https://schema.org"}
        report = v.validate(schema)
        assert not report.is_valid()
        errors = [m.message for m in report.get_messages_by_level(ValidationLevel.ERROR)]
        assert any("@type" in e for e in errors)

    def test_unknown_type_adds_warning(self) -> None:
        v = self._v()
        schema = {"@context": "https://schema.org", "@type": "FictionalType"}
        report = v.validate(schema)
        warnings = [m.message for m in report.get_messages_by_level(ValidationLevel.WARNING)]
        assert any("Unknown" in w for w in warnings)

    def test_known_type_adds_success(self) -> None:
        v = self._v()
        schema = {"@context": "https://schema.org", "@type": "DigitalDocument", "name": "x"}
        report = v.validate(schema)
        successes = report.get_messages_by_level(ValidationLevel.SUCCESS)
        assert any("DigitalDocument" in s.message for s in successes)


# ---------------------------------------------------------------------------
# SchemaValidator — required properties
# ---------------------------------------------------------------------------


class TestSchemaValidatorRequired:
    def _v(self) -> SchemaValidator:
        return SchemaValidator()

    def test_missing_required_property_is_error(self) -> None:
        v = self._v()
        # ImageObject requires contentUrl
        schema = {"@context": "https://schema.org", "@type": "ImageObject"}
        report = v.validate(schema)
        errors = [
            m.property_name
            for m in report.get_messages_by_level(ValidationLevel.ERROR)
            if m.property_name
        ]
        assert "contentUrl" in errors

    def test_empty_required_property_is_error(self) -> None:
        v = self._v()
        schema = {"@context": "https://schema.org", "@type": "ImageObject", "contentUrl": ""}
        report = v.validate(schema)
        errors = [m.message for m in report.get_messages_by_level(ValidationLevel.ERROR)]
        assert any("empty" in e.lower() for e in errors)

    def test_dataset_requires_name_and_description(self) -> None:
        v = self._v()
        schema = {"@context": "https://schema.org", "@type": "Dataset"}
        report = v.validate(schema)
        error_props = {m.property_name for m in report.get_messages_by_level(ValidationLevel.ERROR)}
        assert "name" in error_props
        assert "description" in error_props


# ---------------------------------------------------------------------------
# SchemaValidator — property types
# ---------------------------------------------------------------------------


class TestSchemaValidatorPropertyTypes:
    def _v(self) -> SchemaValidator:
        return SchemaValidator()

    def test_wrong_type_for_width_is_error(self) -> None:
        v = self._v()
        schema = {
            "@context": "https://schema.org",
            "@type": "ImageObject",
            "contentUrl": "https://localhost/x.png",
            "width": "not-an-int",  # should be int
        }
        report = v.validate(schema)
        errors = [m.message for m in report.get_messages_by_level(ValidationLevel.ERROR)]
        assert any("width" in e for e in errors)

    def test_correct_property_types_no_type_error(self) -> None:
        v = self._v()
        schema = {
            "@context": "https://schema.org",
            "@type": "ImageObject",
            "contentUrl": "https://localhost/x.png",
            "name": "image.png",
            "width": 800,
            "height": 600,
        }
        report = v.validate(schema)
        type_errors = [
            m
            for m in report.get_messages_by_level(ValidationLevel.ERROR)
            if "type" in m.message.lower() and m.property_name in ("width", "height")
        ]
        assert len(type_errors) == 0


# ---------------------------------------------------------------------------
# SchemaValidator — format validation
# ---------------------------------------------------------------------------


class TestSchemaValidatorFormats:
    def _v(self) -> SchemaValidator:
        return SchemaValidator()

    def test_invalid_url_adds_error(self) -> None:
        v = self._v()
        schema = {
            "@context": "https://schema.org",
            "@type": "ImageObject",
            "contentUrl": "not-a-url",
        }
        report = v.validate(schema)
        errors = [
            m.property_name
            for m in report.get_messages_by_level(ValidationLevel.ERROR)
            if m.property_name
        ]
        assert "contentUrl" in errors

    def test_valid_https_url_no_format_error(self) -> None:
        v = self._v()
        schema = {
            "@context": "https://schema.org",
            "@type": "ImageObject",
            "contentUrl": "https://example.com/img.png",
        }
        report = v.validate(schema)
        url_errors = [
            m
            for m in report.get_messages_by_level(ValidationLevel.ERROR)
            if m.property_name == "contentUrl" and "URL" in m.message
        ]
        assert len(url_errors) == 0

    def test_invalid_date_format_adds_warning(self) -> None:
        v = self._v()
        schema = {
            "@context": "https://schema.org",
            "@type": "DigitalDocument",
            "name": "doc",
            "dateCreated": "2024/01/01",  # wrong separator
        }
        report = v.validate(schema)
        warnings = [m.message for m in report.get_messages_by_level(ValidationLevel.WARNING)]
        assert any("dateCreated" in w or "Date format" in w for w in warnings)

    def test_valid_iso8601_date_no_warning(self) -> None:
        v = self._v()
        schema = {
            "@context": "https://schema.org",
            "@type": "DigitalDocument",
            "name": "doc",
            "dateCreated": "2024-01-15",
        }
        report = v.validate(schema)
        date_warnings = [
            m
            for m in report.get_messages_by_level(ValidationLevel.WARNING)
            if m.property_name == "dateCreated"
        ]
        assert len(date_warnings) == 0

    def test_invalid_duration_adds_warning(self) -> None:
        v = self._v()
        schema = {
            "@context": "https://schema.org",
            "@type": "AudioObject",
            "name": "clip",
            "duration": "90min",  # wrong format
        }
        report = v.validate(schema)
        warnings = [m.message for m in report.get_messages_by_level(ValidationLevel.WARNING)]
        assert any("duration" in w.lower() for w in warnings)

    def test_valid_iso8601_duration_no_warning(self) -> None:
        v = self._v()
        schema = {
            "@context": "https://schema.org",
            "@type": "AudioObject",
            "name": "clip",
            "duration": "PT1H30M",
        }
        report = v.validate(schema)
        dur_warnings = [
            m
            for m in report.get_messages_by_level(ValidationLevel.WARNING)
            if m.property_name == "duration"
        ]
        assert len(dur_warnings) == 0


# ---------------------------------------------------------------------------
# SchemaValidator — nested schemas and recommended
# ---------------------------------------------------------------------------


class TestSchemaValidatorNested:
    def _v(self) -> SchemaValidator:
        return SchemaValidator()

    def test_valid_nested_schema_no_warning(self) -> None:
        v = self._v()
        schema = {
            "@context": "https://schema.org",
            "@type": "DigitalDocument",
            "name": "doc",
            "publisher": {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "Acme",
            },
        }
        report = v.validate(schema)
        nested_warns = [
            m
            for m in report.get_messages_by_level(ValidationLevel.WARNING)
            if "publisher" in (m.property_name or "")
        ]
        assert len(nested_warns) == 0

    def test_invalid_nested_schema_adds_warning(self) -> None:
        v = self._v()
        schema = {
            "@context": "https://schema.org",
            "@type": "DigitalDocument",
            "name": "doc",
            "publisher": {
                "@type": "Organization",  # missing @context → error in nested
                "name": "Acme",
            },
        }
        report = v.validate(schema)
        nested_warns = [
            m
            for m in report.get_messages_by_level(ValidationLevel.WARNING)
            if "publisher" in (m.property_name or "")
        ]
        assert len(nested_warns) == 1

    def test_nested_schema_in_list_with_errors_adds_warning(self) -> None:
        v = self._v()
        schema = {
            "@context": "https://schema.org",
            "@type": "DigitalDocument",
            "name": "doc",
            "hasPart": [
                {"@type": "DigitalDocument"},  # missing @context
            ],
        }
        report = v.validate(schema)
        list_warns = [
            m
            for m in report.get_messages_by_level(ValidationLevel.WARNING)
            if "hasPart" in (m.property_name or "")
        ]
        assert len(list_warns) == 1

    def test_missing_recommended_properties_adds_info(self) -> None:
        v = self._v()
        # DigitalDocument recommends author and encodingFormat
        schema = {"@context": "https://schema.org", "@type": "DigitalDocument", "name": "doc"}
        report = v.validate(schema)
        infos = report.get_messages_by_level(ValidationLevel.INFO)
        assert len(infos) >= 1
        assert any("recommended" in i.message.lower() for i in infos)


# ---------------------------------------------------------------------------
# SchemaValidator — Rich Results compatibility
# ---------------------------------------------------------------------------


class TestRichResultsCompatibility:
    def _v(self) -> SchemaValidator:
        return SchemaValidator()

    def test_article_without_headline_is_error(self) -> None:
        v = self._v()
        schema = {"@context": "https://schema.org", "@type": "Article"}
        report = v.validate(schema)
        errors = [
            m.property_name
            for m in report.get_messages_by_level(ValidationLevel.ERROR)
            if m.property_name
        ]
        assert "headline" in errors

    def test_article_without_image_and_author_adds_warnings(self) -> None:
        v = self._v()
        schema = {"@context": "https://schema.org", "@type": "Article", "headline": "Test"}
        report = v.validate(schema)
        warn_props = {
            m.property_name for m in report.get_messages_by_level(ValidationLevel.WARNING)
        }
        assert "image" in warn_props
        assert "author" in warn_props

    def test_video_without_required_rich_fields_adds_errors(self) -> None:
        v = self._v()
        schema = {"@context": "https://schema.org", "@type": "VideoObject"}
        report = v.validate(schema)
        error_props = {
            m.property_name
            for m in report.get_messages_by_level(ValidationLevel.ERROR)
            if m.property_name
        }
        assert "thumbnailUrl" in error_props
        assert "uploadDate" in error_props


# ---------------------------------------------------------------------------
# SchemaValidator — batch and summary
# ---------------------------------------------------------------------------


class TestBatchAndSummary:
    def _v(self) -> SchemaValidator:
        return SchemaValidator()

    def test_validate_batch_returns_one_report_per_schema(self) -> None:
        v = self._v()
        schemas = [
            {
                "@context": "https://schema.org",
                "@type": "ImageObject",
                "contentUrl": "https://localhost/a.png",
            },
            {"@context": "https://schema.org", "@type": "DigitalDocument", "name": "b"},
        ]
        reports = v.validate_batch(schemas)
        assert len(reports) == 2

    def test_generate_summary_report_counts(self) -> None:
        v = self._v()
        # One valid, one invalid schema
        schemas = [
            {
                "@context": "https://schema.org",
                "@type": "ImageObject",
                "contentUrl": "https://localhost/a.png",
            },
            {"@context": "https://schema.org", "@type": "ImageObject"},  # missing contentUrl
        ]
        reports = v.validate_batch(schemas)
        summary = v.generate_summary_report(reports)
        assert summary["total_schemas"] == 2
        assert summary["valid_schemas"] == 1
        assert summary["invalid_schemas"] == 1
        assert summary["success_rate"] == 50.0

    def test_generate_summary_report_empty(self) -> None:
        v = self._v()
        summary = v.generate_summary_report([])
        assert summary["total_schemas"] == 0
        assert summary["success_rate"] == 0
