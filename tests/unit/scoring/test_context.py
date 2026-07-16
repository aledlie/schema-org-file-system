"""FileContext memoization and gating tests (UNIFIED_SCORING_PLAN §5.1)."""

from pathlib import Path
from types import SimpleNamespace

from src.scoring.context import FileContext


class CountingProvider:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def __call__(self, path):
        self.calls += 1
        return self.result


def make_ocr(text="hello world", confidence=0.9, language="en"):
    return SimpleNamespace(text=text, confidence=confidence, language=language)


class TestMemoization:
    def test_text_provider_called_once(self):
        provider = CountingProvider("body text")
        ctx = FileContext(
            path=Path("/tmp/doc.pdf"),
            schema_type="DigitalDocument",
            text_provider=provider,
        )
        assert ctx.ensure_text() == "body text"
        assert ctx.ensure_text() == "body text"
        assert provider.calls == 1
        assert ctx.text_length == len("body text")

    def test_ocr_provider_called_once_even_when_none(self):
        provider = CountingProvider(None)
        ctx = FileContext(
            path=Path("/tmp/img.png"),
            schema_type="ImageObject",
            ocr_provider=provider,
        )
        assert ctx.ensure_ocr() is None
        assert ctx.ensure_ocr() is None
        assert provider.calls == 1

    def test_clip_and_metadata_memoized(self):
        clip = CountingProvider({"a document": 0.8})
        metadata = CountingProvider({"gps_coordinates": (1.0, 2.0)})
        ctx = FileContext(
            path=Path("/tmp/img.png"),
            schema_type="ImageObject",
            clip_provider=clip,
            image_metadata_provider=metadata,
        )
        assert ctx.ensure_clip() == {"a document": 0.8}
        assert ctx.ensure_clip() == {"a document": 0.8}
        assert ctx.ensure_image_metadata()["gps_coordinates"] == (1.0, 2.0)
        assert ctx.ensure_image_metadata()
        assert clip.calls == 1
        assert metadata.calls == 1


class TestImageTextRouting:
    def test_image_text_comes_from_ocr(self):
        text_provider = CountingProvider("SHOULD NOT BE USED")
        ocr_provider = CountingProvider(make_ocr(text="ocr text"))
        ctx = FileContext(
            path=Path("/tmp/img.png"),
            schema_type="ImageObject",
            text_provider=text_provider,
            ocr_provider=ocr_provider,
        )
        assert ctx.ensure_text() == "ocr text"
        assert text_provider.calls == 0
        assert ocr_provider.calls == 1
        assert ctx.ocr_confidence == 0.9
        assert ctx.ocr_language == "en"

    def test_non_image_uses_text_provider(self):
        text_provider = CountingProvider("pdf body")
        ocr_provider = CountingProvider(make_ocr())
        ctx = FileContext(
            path=Path("/tmp/doc.pdf"),
            schema_type="DigitalDocument",
            text_provider=text_provider,
            ocr_provider=ocr_provider,
        )
        assert ctx.ensure_text() == "pdf body"
        assert ocr_provider.calls == 0


class TestKieGate:
    def test_kie_runs_when_ocr_confident(self):
        kie = CountingProvider({"fields": "yes"})
        ctx = FileContext(
            path=Path("/tmp/invoice.png"),
            schema_type="ImageObject",
            ocr_provider=CountingProvider(make_ocr(confidence=0.8)),
            kie_provider=kie,
        )
        assert ctx.ensure_kie() == {"fields": "yes"}
        assert kie.calls == 1

    def test_kie_blocked_below_gate(self):
        kie = CountingProvider({"fields": "yes"})
        ctx = FileContext(
            path=Path("/tmp/blurry.png"),
            schema_type="ImageObject",
            ocr_provider=CountingProvider(make_ocr(confidence=0.1)),
            kie_provider=kie,
        )
        assert ctx.ensure_kie() is None
        assert kie.calls == 0

    def test_kie_blocked_without_ocr(self):
        kie = CountingProvider({"fields": "yes"})
        ctx = FileContext(
            path=Path("/tmp/img.png"),
            schema_type="ImageObject",
            kie_provider=kie,
        )
        assert ctx.ensure_kie() is None
        assert kie.calls == 0

    def test_gate_is_configurable(self):
        kie = CountingProvider({"fields": "yes"})
        ctx = FileContext(
            path=Path("/tmp/img.png"),
            schema_type="ImageObject",
            ocr_provider=CountingProvider(make_ocr(confidence=0.1)),
            kie_provider=kie,
            ocr_confidence_gate=0.05,
        )
        assert ctx.ensure_kie() == {"fields": "yes"}


class TestNonForcingAccessors:
    def test_if_loaded_accessors_do_not_force(self):
        text = CountingProvider("body")
        ocr = CountingProvider(make_ocr())
        ctx = FileContext(
            path=Path("/tmp/doc.pdf"),
            schema_type="DigitalDocument",
            text_provider=text,
            ocr_provider=ocr,
        )
        assert ctx.text_if_loaded is None
        assert ctx.ocr_if_loaded is None
        assert ctx.clip_if_loaded is None
        assert ctx.image_metadata_if_loaded is None
        assert ctx.kie_if_loaded is None
        assert text.calls == 0
        assert ocr.calls == 0

    def test_if_loaded_reflects_computed_values(self):
        ctx = FileContext(
            path=Path("/tmp/doc.pdf"),
            schema_type="DigitalDocument",
            text_provider=CountingProvider("body"),
        )
        ctx.ensure_text()
        assert ctx.text_if_loaded == "body"

    def test_missing_providers_yield_empty_values(self):
        ctx = FileContext(path=Path("/tmp/doc.bin"), schema_type="DigitalDocument")
        assert ctx.ensure_text() == ""
        assert ctx.ensure_ocr() is None
        assert ctx.ensure_clip() == {}
        assert ctx.ensure_image_metadata() == {}
        assert ctx.ensure_kie() is None

    def test_metadata_skipped_for_non_images(self):
        metadata = CountingProvider({"datetime": "2026-01-01"})
        ctx = FileContext(
            path=Path("/tmp/doc.pdf"),
            schema_type="DigitalDocument",
            image_metadata_provider=metadata,
        )
        assert ctx.ensure_image_metadata() == {}
        assert metadata.calls == 0


class TestPatternPath:
    def test_display_path_preferred(self):
        ctx = FileContext(
            path=Path("/tmp/Screenshot 2026.png"),
            schema_type="ImageObject",
            display_path=Path("/tmp/terminal_session.png"),
        )
        assert ctx.pattern_path == Path("/tmp/terminal_session.png")

    def test_falls_back_to_physical_path(self):
        ctx = FileContext(path=Path("/tmp/file.png"), schema_type="ImageObject")
        assert ctx.pattern_path == Path("/tmp/file.png")
        assert ctx.is_image
