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


class TestClipOcrGate:
    """CLIP-based OCR gate (FileContext._skip_ocr_by_clip_gate)."""

    _TEXT_LABELS = frozenset({"a document or text", "screenshot: a computer screen"})

    def _make_clip(self, scores: dict):
        return CountingProvider(scores)

    def _make_ocr(self):
        return CountingProvider(make_ocr(text="hello"))

    # Gate disabled ----------------------------------------------------------------

    def test_gate_disabled_when_topk_none(self):
        ocr = self._make_ocr()
        ctx = FileContext(
            path=Path("/tmp/photo.png"),
            schema_type="ImageObject",
            ocr_provider=ocr,
            clip_provider=self._make_clip({"a natural landscape": 0.9, "a portrait": 0.05}),
            ocr_clip_topk=None,
            clip_text_labels=self._TEXT_LABELS,
        )
        assert ctx.ensure_ocr() is not None
        assert ocr.calls == 1

    def test_gate_disabled_when_topk_zero(self):
        ocr = self._make_ocr()
        ctx = FileContext(
            path=Path("/tmp/photo.png"),
            schema_type="ImageObject",
            ocr_provider=ocr,
            clip_provider=self._make_clip({"a natural landscape": 0.9, "a portrait": 0.05}),
            ocr_clip_topk=0,
            clip_text_labels=self._TEXT_LABELS,
        )
        assert ctx.ensure_ocr() is not None
        assert ocr.calls == 1

    def test_gate_disabled_for_non_images(self):
        """Gate never fires on documents, even with K set."""
        ocr = self._make_ocr()
        ctx = FileContext(
            path=Path("/tmp/doc.pdf"),
            schema_type="DigitalDocument",
            ocr_provider=ocr,
            clip_provider=self._make_clip({"a natural landscape": 0.9}),
            ocr_clip_topk=3,
            clip_text_labels=self._TEXT_LABELS,
        )
        ctx.ensure_ocr()
        assert ocr.calls == 1

    # Gate fires — OCR skipped -----------------------------------------------------

    def test_photo_skips_ocr_when_no_text_label_in_topk(self):
        ocr = self._make_ocr()
        ctx = FileContext(
            path=Path("/tmp/landscape.png"),
            schema_type="ImageObject",
            ocr_provider=ocr,
            clip_provider=self._make_clip({
                "a natural landscape": 0.8,
                "a portrait": 0.1,
                "a product or object": 0.05,
                "a document or text": 0.02,
            }),
            ocr_clip_topk=3,
            clip_text_labels=self._TEXT_LABELS,
        )
        assert ctx.ensure_ocr() is None
        assert ocr.calls == 0
        assert ctx.ocr_gated is True

    def test_ocr_gated_is_false_when_gate_does_not_fire(self):
        ocr = self._make_ocr()
        ctx = FileContext(
            path=Path("/tmp/doc.png"),
            schema_type="ImageObject",
            ocr_provider=ocr,
            clip_provider=self._make_clip({"a document or text": 0.9}),
            ocr_clip_topk=3,
            clip_text_labels=self._TEXT_LABELS,
        )
        ctx.ensure_ocr()
        assert ctx.ocr_gated is False

    # Gate passes — OCR kept -------------------------------------------------------

    def test_document_image_keeps_ocr_when_text_label_top1(self):
        ocr = self._make_ocr()
        ctx = FileContext(
            path=Path("/tmp/scan.png"),
            schema_type="ImageObject",
            ocr_provider=ocr,
            clip_provider=self._make_clip({
                "a document or text": 0.7,
                "a natural landscape": 0.2,
                "a portrait": 0.1,
            }),
            ocr_clip_topk=3,
            clip_text_labels=self._TEXT_LABELS,
        )
        assert ctx.ensure_ocr() is not None
        assert ocr.calls == 1

    def test_screenshot_image_keeps_ocr_when_text_label_in_topk(self):
        ocr = self._make_ocr()
        ctx = FileContext(
            path=Path("/tmp/screen.png"),
            schema_type="ImageObject",
            ocr_provider=ocr,
            clip_provider=self._make_clip({
                "a natural landscape": 0.4,
                "a portrait": 0.3,
                "screenshot: a computer screen": 0.25,
                "a product or object": 0.05,
            }),
            ocr_clip_topk=3,
            clip_text_labels=self._TEXT_LABELS,
        )
        assert ctx.ensure_ocr() is not None
        assert ocr.calls == 1

    def test_text_label_in_topk_boundary(self):
        """Text label ranked exactly at K keeps OCR."""
        ocr = self._make_ocr()
        ctx = FileContext(
            path=Path("/tmp/img.png"),
            schema_type="ImageObject",
            ocr_provider=ocr,
            clip_provider=self._make_clip({
                "a natural landscape": 0.5,
                "a portrait": 0.3,
                "a document or text": 0.15,   # rank 3 of 4
                "a product or object": 0.05,
            }),
            ocr_clip_topk=3,
            clip_text_labels=self._TEXT_LABELS,
        )
        assert ctx.ensure_ocr() is not None

    def test_text_label_below_topk_skips_ocr(self):
        """Text label ranked below K skips OCR."""
        ocr = self._make_ocr()
        ctx = FileContext(
            path=Path("/tmp/img.png"),
            schema_type="ImageObject",
            ocr_provider=ocr,
            clip_provider=self._make_clip({
                "a natural landscape": 0.5,
                "a portrait": 0.3,
                "a product or object": 0.15,   # rank 3
                "a document or text": 0.05,    # rank 4 — outside top-3
            }),
            ocr_clip_topk=3,
            clip_text_labels=self._TEXT_LABELS,
        )
        assert ctx.ensure_ocr() is None
        assert ctx.ocr_gated is True

    # Fail-open behaviour ----------------------------------------------------------

    def test_fail_open_when_no_clip_provider(self):
        """No CLIP → ensure_clip() returns {} → gate fails open → OCR runs."""
        ocr = self._make_ocr()
        ctx = FileContext(
            path=Path("/tmp/photo.png"),
            schema_type="ImageObject",
            ocr_provider=ocr,
            clip_provider=None,
            ocr_clip_topk=3,
            clip_text_labels=self._TEXT_LABELS,
        )
        assert ctx.ensure_ocr() is not None
        assert ocr.calls == 1

    def test_fail_open_when_clip_returns_empty(self):
        """Empty CLIP scores → gate fails open → OCR runs."""
        ocr = self._make_ocr()
        ctx = FileContext(
            path=Path("/tmp/photo.png"),
            schema_type="ImageObject",
            ocr_provider=ocr,
            clip_provider=CountingProvider({}),
            ocr_clip_topk=3,
            clip_text_labels=self._TEXT_LABELS,
        )
        assert ctx.ensure_ocr() is not None

    def test_clip_called_once_when_gate_fires(self):
        """CLIP memoization: gate runs ensure_clip() which must call the provider once."""
        clip = CountingProvider({"a natural landscape": 0.9, "a portrait": 0.05})
        ocr = self._make_ocr()
        ctx = FileContext(
            path=Path("/tmp/photo.png"),
            schema_type="ImageObject",
            ocr_provider=ocr,
            clip_provider=clip,
            ocr_clip_topk=3,
            clip_text_labels=self._TEXT_LABELS,
        )
        ctx.ensure_ocr()
        ctx.ensure_clip()  # second call should be memoized
        assert clip.calls == 1

    def test_ocr_provider_not_called_when_gated(self):
        ctx = FileContext(
            path=Path("/tmp/photo.png"),
            schema_type="ImageObject",
            ocr_provider=CountingProvider(make_ocr()),
            clip_provider=self._make_clip({"a natural landscape": 0.9}),
            ocr_clip_topk=3,
            clip_text_labels=self._TEXT_LABELS,
        )
        result = ctx.ensure_ocr()
        assert result is None


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
