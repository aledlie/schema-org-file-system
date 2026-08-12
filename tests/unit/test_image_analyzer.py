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

import importlib.util  # noqa: E402

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
    ImageContentAnalyzer = _analyzer_module.ImageContentAnalyzer  # noqa: F811


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
        # Screenshot outranks people. The fixture used to tie both at 0.9, which
        # expressed "both cleared their magnitude thresholds"; under a rank test
        # a tie is not a ranking, so the intent is now written as an ordering.
        scores = {"a photo of people": 0.2, _analyzer_module._SCREENSHOT_LABEL: 0.9}

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

    Key regression: interior images with a people signal and no faces were
    returning has_people=True *and* is_home_interior_no_people=True because the
    two flags used different thresholds.  They must be mutually exclusive.

    The people/screenshot gates are rank tests, not magnitude tests — the score
    values in these fixtures are ordering fixtures only.  The absolute
    thresholds they replaced (0.15/0.2/0.4) were unreachable in production: real
    scores are an unscaled-cosine softmax that maxes at ~0.10, so the synthetic
    0.5 values below exercised a branch live data could never take.
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

    def test_flags_mutually_exclusive_when_people_and_interior_both_present(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        """Regression: an interior image that also reads as people must not
        produce has_people=True AND is_home_interior_no_people=True at once."""
        # People outranks interior, and interior also clears its own gate — the
        # shape that used to set both flags when they read different thresholds.
        scores = self._make_scores(people=0.5, interior=0.4)
        with (
            patch.object(analyzer, "classify_image_content", return_value=scores),
            patch.object(analyzer, "detect_people", return_value=False),
        ):
            has_people, is_interior_flag, _ = analyzer.analyze_for_organization(dummy_path)
        assert has_people is True
        assert is_interior_flag is False, "Interior flag must be False when has_people is True"

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


class TestRankBasedPeopleGate:
    """The people/screenshot gates read rank, never magnitude.

    Absolute thresholds (0.15/0.2/0.4) were written in 681c5ed against
    `logits_per_image.softmax()`, which applied CLIP's trained logit_scale.
    33264df removed that scaling as "boilerplate" while keeping the public API,
    which flattened the distribution to the uniform floor and made every one of
    those thresholds unreachable. Rank survives that class of change because
    softmax is order-preserving.
    """

    def _scores(self, **overrides: float) -> dict:
        mod = _analyzer_module
        base = {cat: 0.01 for cat in mod._ALL_CATEGORIES}
        for label, value in overrides.items():
            key = {
                "people": mod._PEOPLE_LABEL,
                "screenshot": mod._SCREENSHOT_LABEL,
                "logo": mod._GRAPHIC_LABELS[0],
                "graphic": mod._GRAPHIC_LABELS[1],
                "interior": "a photo of a home interior room",
            }[label]
            base[key] = value
        return base

    def _has_people(
        self,
        analyzer: ImageContentAnalyzer,
        path: Path,
        scores: dict,
        faces: bool,
    ) -> bool:
        with (
            patch.object(analyzer, "classify_image_content", return_value=scores),
            patch.object(analyzer, "detect_people", return_value=faces),
        ):
            # Annotate where the value enters: the module is spec-loaded as Any,
            # so the call is Any and would flow straight out of a bool return.
            has_people: bool = analyzer.analyze_for_organization(path)[0]
        return has_people

    def test_decision_is_invariant_to_scale(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        """The whole point of rank: restoring logit_scale must not change this.

        Same ordering, magnitudes ~100x apart — the flat distribution the code
        actually sees, and the peaked one it would see if the scaling came back.
        """
        flat = self._scores(people=0.0958, interior=0.0930)
        peaked = {label: value * 100 for label, value in flat.items()}
        assert self._has_people(analyzer, dummy_path, flat, faces=False) is True
        assert self._has_people(analyzer, dummy_path, peaked, faces=False) is True

    def test_floor_level_people_score_still_fires(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        # A real measured value: 0.0958 never reached the old 0.15 threshold, so
        # this is precisely the case that was dead before the conversion.
        scores = self._scores(people=0.0958)
        assert self._has_people(analyzer, dummy_path, scores, faces=False) is True

    def test_logo_does_not_read_as_people(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        # Without a graphic label a logo is out-of-vocabulary and the argmax
        # landed on people for 9 of 9 measured logos.
        scores = self._scores(logo=0.5, people=0.2)
        assert self._has_people(analyzer, dummy_path, scores, faces=False) is False

    def test_graphic_does_not_read_as_people(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        scores = self._scores(graphic=0.5, people=0.2)
        assert self._has_people(analyzer, dummy_path, scores, faces=False) is False

    def test_screenshot_suppresses_people_even_with_faces(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        # The surviving reason for the screenshot clause: a face detected inside
        # a screenshot (video call, photo of a photo) is not a social photo.
        scores = self._scores(screenshot=0.5)
        assert self._has_people(analyzer, dummy_path, scores, faces=True) is False

    def test_faces_still_fire_without_any_people_ranking(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        # Face detection remains the primary path — the CLIP rank only adds the
        # profile/occluded cases the cascade misses.
        scores = self._scores(interior=0.5)
        assert self._has_people(analyzer, dummy_path, scores, faces=True) is True

    def test_graphic_labels_are_in_the_vocabulary(self) -> None:
        mod = _analyzer_module
        for label in mod._GRAPHIC_LABELS:
            assert label in mod._ALL_CATEGORIES


class TestGraphicSuppressesPeople:
    """A face inside a graphic does not make it somebody's photo.

    The cv2 cascade is usually right that a face is present — sprites and event
    flyers contain real faces — but Media/Photos/Social is the wrong home for
    them. Measured over 300 images: 10 files changed behaviour, all of them
    faces-only (CLIP never ranked people top), and all 10 were correct
    suppressions — 7 GameAssets sprites and 3 event promo flyers. No genuine
    social photo was affected.
    """

    def _scores(self, **overrides: float) -> dict:
        mod = _analyzer_module
        base = {cat: 0.01 for cat in mod._ALL_CATEGORIES}
        for label, value in overrides.items():
            key = {
                "people": mod._PEOPLE_LABEL,
                "screenshot": mod._SCREENSHOT_LABEL,
                "logo": mod._GRAPHIC_LABELS[0],
                "graphic": mod._GRAPHIC_LABELS[1],
                "outdoors": "a photo of outdoors",
            }[label]
            base[key] = value
        return base

    def _has_people(self, analyzer, path, scores, faces: bool) -> bool:
        with (
            patch.object(analyzer, "classify_image_content", return_value=scores),
            patch.object(analyzer, "detect_people", return_value=faces),
        ):
            has_people: bool = analyzer.analyze_for_organization(path)[0]
        return has_people

    def test_faces_in_a_graphic_are_suppressed(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        # The event-flyer case: real faces, but a promotional graphic.
        scores = self._scores(graphic=0.5, people=0.2)
        assert self._has_people(analyzer, dummy_path, scores, faces=True) is False

    def test_faces_in_a_logo_are_suppressed(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        scores = self._scores(logo=0.5, people=0.2)
        assert self._has_people(analyzer, dummy_path, scores, faces=True) is False

    def test_faces_in_an_ordinary_photo_still_fire(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        # The guard must not swallow the primary path: a non-graphic scene with
        # a detected face is still a people photo.
        scores = self._scores(outdoors=0.5)
        assert self._has_people(analyzer, dummy_path, scores, faces=True) is True

    def test_people_ranked_top_still_fires_without_faces(
        self, dummy_path: Path, analyzer: ImageContentAnalyzer
    ) -> None:
        # Every file the measurement flipped was faces-only; a photo CLIP itself
        # calls people must be unaffected by the graphic clause.
        scores = self._scores(people=0.5)
        assert self._has_people(analyzer, dummy_path, scores, faces=False) is True

    def test_suppression_labels_cover_screenshot_and_graphics(self) -> None:
        mod = _analyzer_module
        assert mod._SCREENSHOT_LABEL in mod._NOT_A_PERSONAL_PHOTO_LABELS
        for label in mod._GRAPHIC_LABELS:
            assert label in mod._NOT_A_PERSONAL_PHOTO_LABELS
