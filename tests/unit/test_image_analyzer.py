"""Unit tests for src.analyzers.image_analyzer.ImageContentAnalyzer."""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Inject stubs for all optional dependencies before importing the module
# ---------------------------------------------------------------------------

def _inject_stubs() -> None:
    # torch
    torch_mod = types.ModuleType("torch")
    torch_mod.no_grad = MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=None), __exit__=MagicMock(return_value=False)))
    sys.modules.setdefault("torch", torch_mod)

    # open_clip
    open_clip_mod = types.ModuleType("open_clip")
    open_clip_mod.create_model_and_transforms = MagicMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
    open_clip_mod.get_tokenizer = MagicMock(return_value=MagicMock())
    sys.modules.setdefault("open_clip", open_clip_mod)

    # torch.nn and torch.nn.functional (needed by clip_utils)
    torch_nn = types.ModuleType("torch.nn")
    torch_nn_functional = types.ModuleType("torch.nn.functional")
    torch_nn_functional.normalize = MagicMock()
    torch_nn_functional.cosine_similarity = MagicMock()
    torch_nn.functional = torch_nn_functional
    torch_mod.nn = torch_nn
    sys.modules.setdefault("torch.nn", torch_nn)
    sys.modules.setdefault("torch.nn.functional", torch_nn_functional)

    # torch.backends.mps
    torch_backends = types.ModuleType("torch.backends")
    torch_backends_mps = types.ModuleType("torch.backends.mps")
    torch_backends_mps.is_available = MagicMock(return_value=False)
    torch_backends.mps = torch_backends_mps
    torch_mod.backends = torch_backends
    torch_mod.cuda = MagicMock()
    torch_mod.cuda.is_available = MagicMock(return_value=False)
    torch_mod.float16 = "float16"
    torch_mod.float32 = "float32"
    torch_mod.stack = MagicMock()
    sys.modules.setdefault("torch.backends", torch_backends)
    sys.modules.setdefault("torch.backends.mps", torch_backends_mps)

    # shared.clip_utils — stub the singleton factory
    clip_utils_mod = types.ModuleType("shared.clip_utils")
    mock_classifier = MagicMock()
    mock_classifier.classify_raw = MagicMock(return_value=[])
    clip_utils_mod.get_clip_classifier = MagicMock(return_value=mock_classifier)
    clip_utils_mod.CLIP_AVAILABLE = True
    clip_utils_mod.CLIPClassifier = MagicMock()
    sys.modules.setdefault("shared.clip_utils", clip_utils_mod)
    sys.modules.setdefault("shared", types.ModuleType("shared"))

    # cv2
    cv2_mod = types.ModuleType("cv2")
    cv2_data = types.SimpleNamespace(haarcascades="/fake/path/")
    cv2_mod.data = cv2_data
    cv2_mod.imread = MagicMock(return_value=None)
    cv2_mod.cvtColor = MagicMock()
    cv2_mod.COLOR_BGR2GRAY = 6
    cv2_mod.CascadeClassifier = MagicMock()
    sys.modules.setdefault("cv2", cv2_mod)

    # PIL
    pil = types.ModuleType("PIL")
    image_mod = types.ModuleType("PIL.Image")
    image_mod.open = MagicMock()
    pil.Image = image_mod
    sys.modules.setdefault("PIL", pil)
    sys.modules.setdefault("PIL.Image", image_mod)

    # cost_roi_calculator
    croi = types.ModuleType("cost_roi_calculator")
    croi.CostROICalculator = MagicMock
    croi.CostTracker = MagicMock
    sys.modules.setdefault("cost_roi_calculator", croi)


_inject_stubs()

import importlib.util

# Import specific submodule directly to avoid triggering __init__
_spec = importlib.util.spec_from_file_location(
    "src.analyzers.image_analyzer",
    str(Path(__file__).parent.parent.parent / "src" / "analyzers" / "image_analyzer.py"),
)
_analyzer_module = importlib.util.module_from_spec(_spec)
sys.modules["src.analyzers.image_analyzer"] = _analyzer_module
_spec.loader.exec_module(_analyzer_module)  # type: ignore[union-attr]

# Force vision available so analyzer logic executes
_analyzer_module._CV2_AVAILABLE = True
_analyzer_module.CLIP_AVAILABLE = True
# Disable CLIP cache so tests exercise the direct CLIPClassifier path
_analyzer_module.CLIP_CACHE_AVAILABLE = False

ImageContentAnalyzer = _analyzer_module.ImageContentAnalyzer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def analyzer() -> ImageContentAnalyzer:
    """Return an analyzer with vision enabled at instance level (avoids model download)."""
    a = ImageContentAnalyzer.__new__(ImageContentAnalyzer)
    a.vision_available = True
    a.face_cascade = MagicMock()
    a.cost_calculator = None
    return a


@pytest.fixture()
def dummy_path(tmp_path: Path) -> Path:
    f = tmp_path / "img.jpg"
    f.write_bytes(b"fake")
    return f


# ---------------------------------------------------------------------------
# detect_people
# ---------------------------------------------------------------------------

class TestDetectPeople:
    def test_returns_false_when_cv2_unavailable(self, dummy_path: Path, analyzer: ImageContentAnalyzer) -> None:
        with patch.object(_analyzer_module, "_CV2_AVAILABLE", False):
            assert analyzer.detect_people(dummy_path) is False

    def test_returns_false_when_no_cascade(self, dummy_path: Path, analyzer: ImageContentAnalyzer) -> None:
        analyzer.face_cascade = None
        assert analyzer.detect_people(dummy_path) is False

    def test_returns_false_when_image_unreadable(self, dummy_path: Path, analyzer: ImageContentAnalyzer) -> None:
        with patch("src.analyzers.image_analyzer.cv2.imread", return_value=None):
            assert analyzer.detect_people(dummy_path) is False

    def test_returns_true_when_faces_found(self, dummy_path: Path, analyzer: ImageContentAnalyzer) -> None:
        fake_img = MagicMock()
        fake_gray = MagicMock()
        fake_faces = [(10, 10, 50, 50)]  # one face

        analyzer.face_cascade.detectMultiScale.return_value = fake_faces

        with patch("src.analyzers.image_analyzer.cv2.imread", return_value=fake_img), \
             patch("src.analyzers.image_analyzer.cv2.cvtColor", return_value=fake_gray):
            result = analyzer.detect_people(dummy_path)

        assert result is True

    def test_returns_false_when_no_faces(self, dummy_path: Path, analyzer: ImageContentAnalyzer) -> None:
        fake_img = MagicMock()
        fake_gray = MagicMock()
        analyzer.face_cascade.detectMultiScale.return_value = []

        with patch("src.analyzers.image_analyzer.cv2.imread", return_value=fake_img), \
             patch("src.analyzers.image_analyzer.cv2.cvtColor", return_value=fake_gray):
            result = analyzer.detect_people(dummy_path)

        assert result is False

    def test_returns_false_on_exception(self, dummy_path: Path, analyzer: ImageContentAnalyzer) -> None:
        with patch("src.analyzers.image_analyzer.cv2.imread", side_effect=RuntimeError("crash")):
            assert analyzer.detect_people(dummy_path) is False


# ---------------------------------------------------------------------------
# classify_image_content
# ---------------------------------------------------------------------------

class TestClassifyImageContent:
    def test_returns_empty_when_vision_unavailable(self, dummy_path: Path, analyzer: ImageContentAnalyzer) -> None:
        analyzer.vision_available = False
        assert analyzer.classify_image_content(dummy_path) == {}

    def test_returns_dict_via_clip_classifier(self, dummy_path: Path, analyzer: ImageContentAnalyzer) -> None:
        mod = sys.modules["src.analyzers.image_analyzer"]
        n = len(mod._ALL_CATEGORIES)
        fake_results = [(cat, 1.0 / n) for cat in mod._ALL_CATEGORIES]

        mock_classifier = MagicMock()
        mock_classifier.classify_raw.return_value = fake_results

        with patch("src.analyzers.image_analyzer.get_clip_classifier", return_value=mock_classifier):
            result = analyzer.classify_image_content(dummy_path)

        assert isinstance(result, dict)
        for cat in mod._ALL_CATEGORIES:
            assert cat in result

    def test_returns_empty_on_exception(self, dummy_path: Path, analyzer: ImageContentAnalyzer) -> None:
        mock_classifier = MagicMock()
        mock_classifier.classify_raw.side_effect = OSError("bad")

        with patch("src.analyzers.image_analyzer.get_clip_classifier", return_value=mock_classifier):
            result = analyzer.classify_image_content(dummy_path)
        assert result == {}


# ---------------------------------------------------------------------------
# has_people_in_photo
# ---------------------------------------------------------------------------

class TestHasPeopleInPhoto:
    def test_returns_false_when_vision_unavailable(self, dummy_path: Path, analyzer: ImageContentAnalyzer) -> None:
        analyzer.vision_available = False
        result, scores = analyzer.has_people_in_photo(dummy_path)
        assert result is False
        assert scores == {}

    def test_returns_false_when_classify_empty(self, dummy_path: Path, analyzer: ImageContentAnalyzer) -> None:
        with patch.object(analyzer, "classify_image_content", return_value={}):
            result, scores = analyzer.has_people_in_photo(dummy_path)
        assert result is False

    def test_detects_people_via_score(self, dummy_path: Path, analyzer: ImageContentAnalyzer) -> None:
        scores = {cat: 0.0 for cat in ["a photo of people", "a screenshot"]}
        scores["a photo of people"] = 0.5

        with patch.object(analyzer, "classify_image_content", return_value=scores), \
             patch.object(analyzer, "detect_people", return_value=False):
            result, _ = analyzer.has_people_in_photo(dummy_path)
        assert result is True

    def test_detects_people_via_face_detection(self, dummy_path: Path, analyzer: ImageContentAnalyzer) -> None:
        scores = {"a photo of people": 0.0, "a screenshot": 0.0}

        with patch.object(analyzer, "classify_image_content", return_value=scores), \
             patch.object(analyzer, "detect_people", return_value=True):
            result, _ = analyzer.has_people_in_photo(dummy_path)
        assert result is True

    def test_screenshot_suppresses_people_detection(self, dummy_path: Path, analyzer: ImageContentAnalyzer) -> None:
        scores = {"a photo of people": 0.9, "a screenshot": 0.9}

        with patch.object(analyzer, "classify_image_content", return_value=scores), \
             patch.object(analyzer, "detect_people", return_value=True):
            result, _ = analyzer.has_people_in_photo(dummy_path)
        assert result is False
