"""Unit tests for src.analyzers.image_analyzer.ImageContentAnalyzer."""

import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    # Annotation-only import of the real class: the runtime object comes from
    # the dynamic spec-load below (which avoids src.analyzers.__init__ and its
    # CLIP imports). Mirrors tests/unit/test_image_metadata.py.
    from src.analyzers.image_analyzer import ImageContentAnalyzer


# ---------------------------------------------------------------------------
# Inject stubs for all optional dependencies before importing the module
# ---------------------------------------------------------------------------


def _inject_stubs() -> None:
    # torch
    torch_mod: Any = types.ModuleType("torch")
    torch_mod.no_grad = MagicMock(
        return_value=MagicMock(
            __enter__=MagicMock(return_value=None), __exit__=MagicMock(return_value=False)
        )
    )
    sys.modules.setdefault("torch", torch_mod)

    # open_clip
    open_clip_mod: Any = types.ModuleType("open_clip")
    open_clip_mod.create_model_and_transforms = MagicMock(
        return_value=(MagicMock(), MagicMock(), MagicMock())
    )
    open_clip_mod.get_tokenizer = MagicMock(return_value=MagicMock())
    sys.modules.setdefault("open_clip", open_clip_mod)

    # torch.nn and torch.nn.functional (needed by clip_utils)
    torch_nn: Any = types.ModuleType("torch.nn")
    torch_nn_functional: Any = types.ModuleType("torch.nn.functional")
    torch_nn_functional.normalize = MagicMock()
    torch_nn_functional.cosine_similarity = MagicMock()
    torch_nn.functional = torch_nn_functional
    torch_mod.nn = torch_nn
    sys.modules.setdefault("torch.nn", torch_nn)
    sys.modules.setdefault("torch.nn.functional", torch_nn_functional)

    # torch.backends.mps
    torch_backends: Any = types.ModuleType("torch.backends")
    torch_backends_mps: Any = types.ModuleType("torch.backends.mps")
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
    clip_utils_mod: Any = types.ModuleType("shared.clip_utils")
    mock_classifier = MagicMock()
    mock_classifier.classify_raw = MagicMock(return_value=[])
    clip_utils_mod.get_clip_classifier = MagicMock(return_value=mock_classifier)
    clip_utils_mod.CLIP_AVAILABLE = True
    clip_utils_mod.CLIPClassifier = MagicMock()
    sys.modules.setdefault("shared.clip_utils", clip_utils_mod)
    sys.modules.setdefault("shared", types.ModuleType("shared"))

    # cv2
    cv2_mod: Any = types.ModuleType("cv2")
    cv2_data = types.SimpleNamespace(haarcascades="/fake/path/")
    cv2_mod.data = cv2_data
    cv2_mod.imread = MagicMock(return_value=None)
    cv2_mod.cvtColor = MagicMock()
    cv2_mod.COLOR_BGR2GRAY = 6
    cv2_mod.CascadeClassifier = MagicMock()
    sys.modules.setdefault("cv2", cv2_mod)

    # PIL
    pil: Any = types.ModuleType("PIL")
    image_mod: Any = types.ModuleType("PIL.Image")
    image_mod.open = MagicMock()
    pil.Image = image_mod
    sys.modules.setdefault("PIL", pil)
    sys.modules.setdefault("PIL.Image", image_mod)

    # cost_roi_calculator
    croi: Any = types.ModuleType("cost_roi_calculator")
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
assert _spec is not None and _spec.loader is not None
_analyzer_module: Any = importlib.util.module_from_spec(_spec)
sys.modules["src.analyzers.image_analyzer"] = _analyzer_module
_spec.loader.exec_module(_analyzer_module)

# Force vision available so analyzer logic executes
_analyzer_module._CV2_AVAILABLE = True
_analyzer_module.CLIP_AVAILABLE = True
# Disable CLIP cache so tests exercise the direct CLIPClassifier path
_analyzer_module.CLIP_CACHE_AVAILABLE = False

if not TYPE_CHECKING:  # runtime object; the annotation name is imported above
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
    def test_returns_false_when_cv2_unavailable(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        with patch.object(_analyzer_module, "_CV2_AVAILABLE", False):
            assert analyzer.detect_people(dummy_path) is False

    def test_returns_false_when_no_cascade(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        analyzer.face_cascade = None
        assert analyzer.detect_people(dummy_path) is False

    def test_returns_false_when_image_unreadable(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        with patch("src.analyzers.image_analyzer.cv2.imread", return_value=None):
            assert analyzer.detect_people(dummy_path) is False

    def test_returns_true_when_faces_found(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        fake_img = MagicMock()
        fake_gray = MagicMock()
        fake_faces = [(10, 10, 50, 50)]  # one face

        # face_cascade is a real CascadeClassifier | None on the class; the
        # fixture installs a MagicMock, so reach it through Any to configure it.
        cascade: Any = analyzer.face_cascade
        cascade.detectMultiScale.return_value = fake_faces

        with (
            patch("src.analyzers.image_analyzer.cv2.imread", return_value=fake_img),
            patch("src.analyzers.image_analyzer.cv2.cvtColor", return_value=fake_gray),
        ):
            result = analyzer.detect_people(dummy_path)

        assert result is True

    def test_returns_false_when_no_faces(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        fake_img = MagicMock()
        fake_gray = MagicMock()
        cascade: Any = analyzer.face_cascade
        cascade.detectMultiScale.return_value = []

        with (
            patch("src.analyzers.image_analyzer.cv2.imread", return_value=fake_img),
            patch("src.analyzers.image_analyzer.cv2.cvtColor", return_value=fake_gray),
        ):
            result = analyzer.detect_people(dummy_path)

        assert result is False

    def test_returns_false_on_exception(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        with patch("src.analyzers.image_analyzer.cv2.imread", side_effect=RuntimeError("crash")):
            assert analyzer.detect_people(dummy_path) is False


# ---------------------------------------------------------------------------
# classify_image_content
# ---------------------------------------------------------------------------


class TestClassifyImageContent:
    def test_returns_empty_when_vision_unavailable(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        analyzer.vision_available = False
        assert analyzer.classify_image_content(dummy_path) == {}

    def test_returns_dict_via_clip_classifier(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        mod = sys.modules["src.analyzers.image_analyzer"]
        n = len(mod._ALL_CATEGORIES)
        fake_results = [(cat, 1.0 / n) for cat in mod._ALL_CATEGORIES]

        mock_classifier = MagicMock()
        mock_classifier.classify_raw.return_value = fake_results

        with patch(
            "src.analyzers.image_analyzer.get_clip_classifier", return_value=mock_classifier
        ):
            result = analyzer.classify_image_content(dummy_path)

        assert isinstance(result, dict)
        for cat in mod._ALL_CATEGORIES:
            assert cat in result

    def test_returns_empty_on_exception(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        mock_classifier = MagicMock()
        mock_classifier.classify_raw.side_effect = OSError("bad")

        with patch(
            "src.analyzers.image_analyzer.get_clip_classifier", return_value=mock_classifier
        ):
            result = analyzer.classify_image_content(dummy_path)
        assert result == {}


# ---------------------------------------------------------------------------
# has_people_in_photo
# ---------------------------------------------------------------------------


class TestHasPeopleInPhoto:
    def test_returns_false_when_vision_unavailable(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        analyzer.vision_available = False
        result, scores = analyzer.has_people_in_photo(dummy_path)
        assert result is False
        assert scores == {}

    def test_returns_false_when_classify_empty(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        with patch.object(analyzer, "classify_image_content", return_value={}):
            result, scores = analyzer.has_people_in_photo(dummy_path)
        assert result is False

    def test_detects_people_via_score(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        scores = {cat: 0.0 for cat in ["a photo of people", _analyzer_module._SCREENSHOT_LABEL]}
        scores["a photo of people"] = 0.5

        with (
            patch.object(analyzer, "classify_image_content", return_value=scores),
            patch.object(analyzer, "detect_people", return_value=False),
        ):
            result, _ = analyzer.has_people_in_photo(dummy_path)
        assert result is True

    def test_detects_people_via_face_detection(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        scores = {"a photo of people": 0.0, _analyzer_module._SCREENSHOT_LABEL: 0.0}

        with (
            patch.object(analyzer, "classify_image_content", return_value=scores),
            patch.object(analyzer, "detect_people", return_value=True),
        ):
            result, _ = analyzer.has_people_in_photo(dummy_path)
        assert result is True

    def test_screenshot_suppresses_people_detection(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        scores = {"a photo of people": 0.9, _analyzer_module._SCREENSHOT_LABEL: 0.9}

        with (
            patch.object(analyzer, "classify_image_content", return_value=scores),
            patch.object(analyzer, "detect_people", return_value=True),
        ):
            result, _ = analyzer.has_people_in_photo(dummy_path)
        assert result is False


# ---------------------------------------------------------------------------
# analyze_for_organization
# ---------------------------------------------------------------------------


class TestAnalyzeForOrganization:
    """Covers the dual-flag logic in analyze_for_organization.

    Key regression: interior images with a weak people signal (between
    _PEOPLE_SCORE_LOW_THRESHOLD and _PEOPLE_SCORE_THRESHOLD, no faces) were
    returning has_people=True *and* is_home_interior_no_people=True because
    the two flags used different thresholds.  They must be mutually exclusive.
    """

    def _make_scores(
        self,
        people: float = 0.0,
        interior: float = 0.0,
        screenshot: float = 0.0,
    ) -> dict:
        mod = _analyzer_module
        base = {cat: 0.0 for cat in mod._ALL_CATEGORIES}
        base["a photo of people"] = people
        base["a photo of a home interior room"] = interior
        base[mod._SCREENSHOT_LABEL] = screenshot
        return base

    def test_returns_triple_false_when_vision_unavailable(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        analyzer.vision_available = False
        assert analyzer.analyze_for_organization(dummy_path) == (False, False, {})

    def test_returns_triple_false_when_classify_empty(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        with patch.object(analyzer, "classify_image_content", return_value={}):
            assert analyzer.analyze_for_organization(dummy_path) == (False, False, {})

    def test_clear_people_signal_routes_social(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        scores = self._make_scores(people=0.5)
        with (
            patch.object(analyzer, "classify_image_content", return_value=scores),
            patch.object(analyzer, "detect_people", return_value=False),
        ):
            has_people, is_interior, _ = analyzer.analyze_for_organization(dummy_path)
        assert has_people is True
        assert is_interior is False

    def test_clear_interior_no_people_routes_property(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        scores = self._make_scores(interior=0.4)
        with (
            patch.object(analyzer, "classify_image_content", return_value=scores),
            patch.object(analyzer, "detect_people", return_value=False),
        ):
            has_people, is_interior, _ = analyzer.analyze_for_organization(dummy_path)
        assert has_people is False
        assert is_interior is True

    def test_flags_mutually_exclusive_in_gray_zone(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        """Regression: people_score in (LOW_THRESHOLD, THRESHOLD) + interior must not
        produce has_people=True AND is_home_interior_no_people=True simultaneously."""
        mod = _analyzer_module
        # people_score sits between the two thresholds; interior is clearly present
        gray_people_score = (
            mod._PEOPLE_SCORE_LOW_THRESHOLD + mod._PEOPLE_SCORE_THRESHOLD
        ) / 2  # e.g. 0.175
        scores = self._make_scores(people=gray_people_score, interior=0.4)
        with (
            patch.object(analyzer, "classify_image_content", return_value=scores),
            patch.object(analyzer, "detect_people", return_value=False),
        ):
            has_people, is_interior_flag, _ = analyzer.analyze_for_organization(dummy_path)
        # has_people fires (low threshold crossed) — the interior flag must be suppressed
        assert has_people is True
        assert (
            is_interior_flag is False
        ), "Interior flag must be False when has_people is True (gray-zone misfire)"

    def test_face_detection_suppresses_interior_flag(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        scores = self._make_scores(interior=0.4)
        with (
            patch.object(analyzer, "classify_image_content", return_value=scores),
            patch.object(analyzer, "detect_people", return_value=True),
        ):
            has_people, is_interior_flag, _ = analyzer.analyze_for_organization(dummy_path)
        assert has_people is True
        assert is_interior_flag is False
