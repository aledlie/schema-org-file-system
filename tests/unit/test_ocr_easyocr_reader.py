"""Warning-suppression tests for scripts/shared/ocr_easyocr.py.

Covers the two scoped torch-noise filters:

- Reader construction: easyocr's ``quantize=True`` default triggers torch's
  quint8 deprecation UserWarning (pytorch/pytorch#184982).
- readtext calls: easyocr's recognizer builds a DataLoader(pin_memory=True)
  per call, and torch warns that MPS cannot pin memory (Apple Silicon).

Each suppression must be scoped to its exact message at its site — unrelated
warnings raised at the same site must still propagate.

Uses a stub ``easyocr`` module (no model download, no heavy import).
"""

import sys
import types
import warnings

import pytest

from shared import ocr_easyocr

TORCH_DEPRECATION_MESSAGE = (
    "torch.quantize_per_tensor, torch.quantize_per_channel and other quantized "
    "tensor creation functions that produce tensors with dtype torch.quint8, "
    "torch.qint8, and torch.qint32 are deprecated and will be removed in a "
    "future PyTorch release."
)

PIN_MEMORY_MESSAGE = (
    "'pin_memory' argument is set as true but not supported on MPS now, "
    "device pinned memory won't be used."
)


def _install_stub(monkeypatch, init_warning=None):
    """Install a stub easyocr module whose Reader emits ``init_warning``."""

    class StubReader:
        def __init__(self, langs, gpu=False, verbose=False):
            if init_warning is not None:
                warnings.warn(init_warning, UserWarning, stacklevel=2)

    stub = types.ModuleType("easyocr")
    stub.Reader = StubReader
    monkeypatch.setitem(sys.modules, "easyocr", stub)
    monkeypatch.setattr(ocr_easyocr, "EASYOCR_AVAILABLE", True)
    monkeypatch.setattr(ocr_easyocr, "_use_gpu", lambda: False)
    return StubReader


@pytest.fixture(autouse=True)
def _fresh_reader_singleton():
    ocr_easyocr.clear_reader()
    yield
    ocr_easyocr.clear_reader()


class TestQuantizeDeprecationSuppression:
    def test_torch_quantize_deprecation_is_suppressed(self, monkeypatch):
        _install_stub(monkeypatch, init_warning=TORCH_DEPRECATION_MESSAGE)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            reader = ocr_easyocr._get_reader()

        assert reader is not None
        assert caught == [], [str(w.message) for w in caught]

    def test_unrelated_construction_warning_still_propagates(self, monkeypatch):
        _install_stub(monkeypatch, init_warning="easyocr: some genuinely new problem")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ocr_easyocr._get_reader()

        assert [str(w.message) for w in caught] == ["easyocr: some genuinely new problem"]

    def test_filter_scope_ends_after_construction(self, monkeypatch):
        # The catch_warnings context must not leak: the same deprecation text
        # emitted AFTER construction (e.g. from a different torch call in the
        # host process) must still surface.
        _install_stub(monkeypatch, init_warning=None)
        ocr_easyocr._get_reader()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warnings.warn(TORCH_DEPRECATION_MESSAGE, UserWarning, stacklevel=2)

        assert len(caught) == 1

    def test_singleton_reused_without_reconstruction(self, monkeypatch):
        stub_cls = _install_stub(monkeypatch, init_warning=TORCH_DEPRECATION_MESSAGE)
        constructed = []
        original_init = stub_cls.__init__

        def counting_init(self, *args, **kwargs):
            constructed.append(1)
            original_init(self, *args, **kwargs)

        stub_cls.__init__ = counting_init
        first = ocr_easyocr._get_reader()
        second = ocr_easyocr._get_reader()
        assert first is second
        assert len(constructed) == 1


class _WarningReader:
    """Stub reader whose readtext emits ``warning_message`` then returns."""

    def __init__(self, warning_message=None, result=("HELLO", "WORLD")):
        self._warning_message = warning_message
        self._result = list(result)

    def readtext(self, image, **kwargs):
        if self._warning_message is not None:
            warnings.warn(self._warning_message, UserWarning, stacklevel=2)
        return self._result


class TestPinMemorySuppression:
    def test_pin_memory_warning_is_suppressed(self):
        reader = _WarningReader(warning_message=PIN_MEMORY_MESSAGE)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = ocr_easyocr._quiet_readtext(reader, "/tmp/x.png", detail=0)

        assert result == ["HELLO", "WORLD"]
        assert caught == [], [str(w.message) for w in caught]

    def test_unrelated_readtext_warning_still_propagates(self):
        reader = _WarningReader(warning_message="easyocr: some genuinely new problem")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ocr_easyocr._quiet_readtext(reader, "/tmp/x.png", detail=0)

        assert [str(w.message) for w in caught] == ["easyocr: some genuinely new problem"]

    def test_filter_scope_ends_after_call(self):
        reader = _WarningReader(warning_message=None)
        ocr_easyocr._quiet_readtext(reader, "/tmp/x.png", detail=0)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warnings.warn(PIN_MEMORY_MESSAGE, UserWarning, stacklevel=2)

        assert len(caught) == 1

    def test_extraction_funnel_uses_quiet_readtext(self, monkeypatch, tmp_path):
        # End-to-end through a public extraction function: the stub reader
        # warns like torch does, and the funnel keeps the call silent.
        reader = _WarningReader(warning_message=PIN_MEMORY_MESSAGE)
        monkeypatch.setattr(ocr_easyocr, "EASYOCR_AVAILABLE", True)
        monkeypatch.setattr(ocr_easyocr, "_get_reader", lambda: reader)
        img = tmp_path / "shot.png"
        img.write_bytes(b"not really a png")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            text = ocr_easyocr.extract_text_easyocr(img)

        assert text == "HELLO WORLD"
        assert caught == [], [str(w.message) for w in caught]
