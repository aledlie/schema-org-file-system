"""Unit tests for src.integration — SchemaIntegration and SchemaRegistry."""

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from src.integration import OutputFormat, SchemaIntegration, SchemaRegistry


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

IMAGE_SCHEMA: Dict[str, Any] = {
    "@context": "https://schema.org",
    "@type": "ImageObject",
    "name": "photo.jpg",
    "description": "A test image",
    "contentUrl": "https://example.com/photo.jpg",
}

DOC_SCHEMA: Dict[str, Any] = {
    "@context": "https://schema.org",
    "@type": "DigitalDocument",
    "name": "report.pdf",
    "description": "A test document",
}

NESTED_SCHEMA: Dict[str, Any] = {
    "@type": "Organization",
    "name": "Acme",
    "address": {
        "@type": "PostalAddress",
        "streetAddress": "123 Main St",
    },
    "url": "https://acme.example",
    "logo": "https://acme.example/logo.png",
}


# ---------------------------------------------------------------------------
# OutputFormat enum
# ---------------------------------------------------------------------------


class TestOutputFormat:
    def test_values(self) -> None:
        assert OutputFormat.JSON_LD.value == "json-ld"
        assert OutputFormat.MICRODATA.value == "microdata"
        assert OutputFormat.RDFA.value == "rdfa"
        assert OutputFormat.JSON.value == "json"


# ---------------------------------------------------------------------------
# SchemaIntegration
# ---------------------------------------------------------------------------


class TestSchemaIntegrationAddSchema:
    def test_add_dict_schema(self) -> None:
        si = SchemaIntegration()
        result = si.add_schema(IMAGE_SCHEMA)
        assert result is si  # fluent return
        assert len(si.schemas) == 1
        assert si.schemas[0] is IMAGE_SCHEMA

    def test_add_schema_org_base_like_object(self) -> None:
        """Objects with a to_dict() method should be unwrapped."""

        class FakeSchema:
            def to_dict(self) -> Dict[str, Any]:
                return {"@type": "Thing", "name": "fake"}

        si = SchemaIntegration()
        si.add_schema(FakeSchema())  # type: ignore[arg-type]
        assert si.schemas[0]["@type"] == "Thing"

    def test_add_multiple_schemas(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA).add_schema(DOC_SCHEMA)
        assert len(si.schemas) == 2


class TestSchemaIntegrationJsonLd:
    def test_single_schema_returned_directly(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA)
        out = si.to_json_ld()
        data = json.loads(out)
        assert data["@type"] == "ImageObject"
        assert "@graph" not in data

    def test_multiple_schemas_wrapped_in_graph(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA).add_schema(DOC_SCHEMA)
        out = si.to_json_ld()
        data = json.loads(out)
        assert "@graph" in data
        assert len(data["@graph"]) == 2

    def test_explicit_schema_arg(self) -> None:
        si = SchemaIntegration()
        out = si.to_json_ld(schema=DOC_SCHEMA)
        data = json.loads(out)
        assert data["@type"] == "DigitalDocument"

    def test_indentation(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA)
        out_2 = si.to_json_ld(indent=2)
        out_4 = si.to_json_ld(indent=4)
        assert "    " in out_4
        assert "  " in out_2

    def test_json_ld_script_tag(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA)
        tag = si.to_json_ld_script()
        assert tag.startswith('<script type="application/ld+json">')
        assert tag.endswith("</script>")
        # JSON inside the tag should be valid
        inner = tag.split("\n", 1)[1].rsplit("\n", 1)[0]
        data = json.loads(inner)
        assert data["@type"] == "ImageObject"


class TestSchemaIntegrationMicrodata:
    def test_basic_microdata(self) -> None:
        si = SchemaIntegration()
        html = si.to_microdata(IMAGE_SCHEMA)
        assert 'itemscope' in html
        assert 'itemtype="https://schema.org/ImageObject"' in html

    def test_url_property_uses_link_tag(self) -> None:
        si = SchemaIntegration()
        html = si.to_microdata(IMAGE_SCHEMA)
        assert "<link" in html
        assert 'itemprop="contentUrl"' in html

    def test_logo_as_string_uses_link(self) -> None:
        si = SchemaIntegration()
        html = si.to_microdata({"@type": "Organization", "logo": "https://example.com/logo.png"})
        assert '<link itemprop="logo"' in html

    def test_nested_dict_is_recursed(self) -> None:
        si = SchemaIntegration()
        html = si.to_microdata(NESTED_SCHEMA)
        # Nested PostalAddress should produce its own itemscope block
        assert "PostalAddress" in html

    def test_list_values(self) -> None:
        schema = {"@type": "Thing", "keywords": ["a", "b"]}
        si = SchemaIntegration()
        html = si.to_microdata(schema)
        assert "keywords" in html

    def test_list_of_dicts_recursed(self) -> None:
        schema = {
            "@type": "ItemList",
            "itemListElement": [{"@type": "ListItem", "position": 1}],
        }
        si = SchemaIntegration()
        html = si.to_microdata(schema)
        assert "ListItem" in html

    def test_closing_tag(self) -> None:
        si = SchemaIntegration()
        html = si.to_microdata(IMAGE_SCHEMA, tag="article")
        assert html.startswith("<article")
        assert html.endswith("</article>")

    def test_at_keys_skipped(self) -> None:
        si = SchemaIntegration()
        html = si.to_microdata(IMAGE_SCHEMA)
        # @context/@type keys should not appear as itemprop
        assert 'itemprop="@context"' not in html
        assert 'itemprop="@type"' not in html


class TestSchemaIntegrationRdfa:
    def test_basic_rdfa(self) -> None:
        si = SchemaIntegration()
        html = si.to_rdfa(IMAGE_SCHEMA)
        assert 'vocab="https://schema.org/"' in html
        assert 'typeof="ImageObject"' in html

    def test_url_property_uses_link(self) -> None:
        si = SchemaIntegration()
        html = si.to_rdfa(IMAGE_SCHEMA)
        assert "<link" in html
        assert 'property="contentUrl"' in html

    def test_nested_dict_recursed(self) -> None:
        si = SchemaIntegration()
        html = si.to_rdfa(NESTED_SCHEMA)
        assert "PostalAddress" in html

    def test_list_values_with_dict(self) -> None:
        schema = {
            "@type": "ItemList",
            "itemListElement": [{"@type": "ListItem", "position": 1}],
        }
        si = SchemaIntegration()
        html = si.to_rdfa(schema)
        assert "ListItem" in html

    def test_list_scalar_values(self) -> None:
        schema = {"@type": "Thing", "keywords": ["x", "y"]}
        si = SchemaIntegration()
        html = si.to_rdfa(schema)
        assert "keywords" in html

    def test_closing_tag(self) -> None:
        si = SchemaIntegration()
        html = si.to_rdfa(IMAGE_SCHEMA, tag="section")
        assert html.startswith("<section")
        assert html.endswith("</section>")


class TestSchemaIntegrationExportFormat:
    def test_json_ld_format(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA)
        out = si.export_format(OutputFormat.JSON_LD)
        data = json.loads(out)
        assert data["@type"] == "ImageObject"

    def test_microdata_format(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA)
        out = si.export_format(OutputFormat.MICRODATA)
        assert "itemscope" in out

    def test_rdfa_format(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA)
        out = si.export_format(OutputFormat.RDFA)
        assert "vocab" in out

    def test_json_format(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA)
        out = si.export_format(OutputFormat.JSON)
        data = json.loads(out)
        assert data["@type"] == "ImageObject"

    def test_unsupported_format_raises(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA)
        with pytest.raises(ValueError):
            si.export_format("unsupported")  # type: ignore[arg-type]

    def test_export_all(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA).add_schema(DOC_SCHEMA)
        results = si.export_all(OutputFormat.JSON)
        assert len(results) == 2
        assert json.loads(results[0])["@type"] == "ImageObject"
        assert json.loads(results[1])["@type"] == "DigitalDocument"

    def test_export_format_with_empty_schemas_uses_none(self) -> None:
        si = SchemaIntegration()
        # No schemas added; passes schema=None which leads to schema=None fallthrough
        # export_format with JSON format and no schema set → json.dumps(None)
        out = si.export_format(OutputFormat.JSON)
        assert out == "null"


class TestSchemaIntegrationCreateHtmlPage:
    def test_returns_valid_html(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA)
        html = si.create_html_page("Test Page", "<p>content</p>")
        assert "<!DOCTYPE html>" in html
        assert "<title>Test Page</title>" in html
        assert "<p>content</p>" in html
        assert "application/ld+json" in html

    def test_microdata_format_note(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA)
        html = si.create_html_page("T", "", format=OutputFormat.MICRODATA)
        assert "Microdata" in html

    def test_rdfa_format_note(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA)
        html = si.create_html_page("T", "", format=OutputFormat.RDFA)
        assert "RDFa" in html


class TestSchemaIntegrationGetApiResponse:
    def test_returns_all_when_no_id(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA).add_schema(DOC_SCHEMA)
        resp = si.get_api_response()
        assert resp["success"] is True
        assert resp["count"] == 2

    def test_returns_specific_schema_when_id_given(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA)
        resp = si.get_api_response(schema_id="some-id")
        assert resp["success"] is True
        assert resp["data"]["@type"] == "ImageObject"


class TestSchemaIntegrationExportBulk:
    def test_json_ld_single_to_file(self, tmp_path: Path) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA)
        out = tmp_path / "out.json"
        si.export_bulk(OutputFormat.JSON_LD, str(out))
        data = json.loads(out.read_text())
        assert data["@type"] == "ImageObject"

    def test_json_ld_multiple_wrapped_in_graph(self, tmp_path: Path) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA).add_schema(DOC_SCHEMA)
        out = tmp_path / "out.json"
        si.export_bulk(OutputFormat.JSON_LD, str(out))
        data = json.loads(out.read_text())
        assert "@graph" in data

    def test_microdata_creates_per_schema_files(self, tmp_path: Path) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA).add_schema(DOC_SCHEMA)
        out = tmp_path / "schemas.html"
        si.export_bulk(OutputFormat.MICRODATA, str(out))
        files = list(tmp_path.iterdir())
        assert len(files) == 2


class TestSchemaIntegrationClear:
    def test_clear_empties_schemas(self) -> None:
        si = SchemaIntegration()
        si.add_schema(IMAGE_SCHEMA).add_schema(DOC_SCHEMA)
        assert len(si.schemas) == 2
        si.clear()
        assert si.schemas == []


# ---------------------------------------------------------------------------
# SchemaRegistry
# ---------------------------------------------------------------------------


class TestSchemaRegistryBasics:
    def test_initial_state(self) -> None:
        reg = SchemaRegistry()
        assert reg.count() == 0
        assert reg.list_all() == []

    def test_register_and_get(self) -> None:
        reg = SchemaRegistry()
        reg.register("img-1", IMAGE_SCHEMA)
        schema = reg.get("img-1")
        assert schema is not None
        assert schema["@type"] == "ImageObject"

    def test_get_missing_returns_none(self) -> None:
        reg = SchemaRegistry()
        assert reg.get("no-such-id") is None

    def test_register_with_metadata(self) -> None:
        reg = SchemaRegistry()
        reg.register("img-1", IMAGE_SCHEMA, metadata={"source": "upload"})
        entry = reg.registry["img-1"]
        assert entry["metadata"]["source"] == "upload"

    def test_count(self) -> None:
        reg = SchemaRegistry()
        reg.register("a", IMAGE_SCHEMA)
        reg.register("b", DOC_SCHEMA)
        assert reg.count() == 2

    def test_list_all(self) -> None:
        reg = SchemaRegistry()
        reg.register("x", IMAGE_SCHEMA)
        reg.register("y", DOC_SCHEMA)
        ids = reg.list_all()
        assert "x" in ids
        assert "y" in ids


class TestSchemaRegistryGetByType:
    def test_returns_matching_types(self) -> None:
        reg = SchemaRegistry()
        reg.register("i", IMAGE_SCHEMA)
        reg.register("d", DOC_SCHEMA)
        images = reg.get_by_type("ImageObject")
        assert len(images) == 1
        assert images[0]["@type"] == "ImageObject"

    def test_returns_empty_when_no_match(self) -> None:
        reg = SchemaRegistry()
        reg.register("i", IMAGE_SCHEMA)
        assert reg.get_by_type("VideoObject") == []


class TestSchemaRegistrySearch:
    def test_finds_by_name(self) -> None:
        reg = SchemaRegistry()
        reg.register("img", IMAGE_SCHEMA)
        reg.register("doc", DOC_SCHEMA)
        results = reg.search("photo")
        assert any(s["@type"] == "ImageObject" for s in results)

    def test_finds_by_description(self) -> None:
        reg = SchemaRegistry()
        reg.register("img", IMAGE_SCHEMA)
        results = reg.search("test image")
        assert len(results) == 1

    def test_case_insensitive(self) -> None:
        reg = SchemaRegistry()
        reg.register("img", IMAGE_SCHEMA)
        results = reg.search("PHOTO")
        assert len(results) == 1

    def test_no_match_returns_empty(self) -> None:
        reg = SchemaRegistry()
        reg.register("img", IMAGE_SCHEMA)
        assert reg.search("zzznomatch") == []


class TestSchemaRegistryRemove:
    def test_remove_existing(self) -> None:
        reg = SchemaRegistry()
        reg.register("img", IMAGE_SCHEMA)
        removed = reg.remove("img")
        assert removed is True
        assert reg.count() == 0

    def test_remove_missing_returns_false(self) -> None:
        reg = SchemaRegistry()
        assert reg.remove("no-such-id") is False

    def test_remove_does_not_affect_others(self) -> None:
        reg = SchemaRegistry()
        reg.register("a", IMAGE_SCHEMA)
        reg.register("b", DOC_SCHEMA)
        reg.remove("a")
        assert reg.count() == 1
        assert reg.get("b") is not None


class TestSchemaRegistryExportAll:
    def test_export_all_schemas(self) -> None:
        reg = SchemaRegistry()
        reg.register("i", IMAGE_SCHEMA)
        reg.register("d", DOC_SCHEMA)
        schemas = reg.export_all()
        types = {s["@type"] for s in schemas}
        assert types == {"ImageObject", "DigitalDocument"}


class TestSchemaRegistryStatistics:
    def test_empty_registry(self) -> None:
        reg = SchemaRegistry()
        stats = reg.get_statistics()
        assert stats["total_schemas"] == 0
        assert stats["types"] == {}

    def test_counts_by_type(self) -> None:
        reg = SchemaRegistry()
        reg.register("i1", IMAGE_SCHEMA)
        reg.register("i2", IMAGE_SCHEMA.copy())
        reg.register("d", DOC_SCHEMA)
        stats = reg.get_statistics()
        assert stats["total_schemas"] == 3
        assert stats["types"]["ImageObject"] == 2
        assert stats["types"]["DigitalDocument"] == 1

    def test_unknown_type_counted(self) -> None:
        reg = SchemaRegistry()
        reg.register("t", {"name": "no type"})
        stats = reg.get_statistics()
        assert "Unknown" in stats["types"]
