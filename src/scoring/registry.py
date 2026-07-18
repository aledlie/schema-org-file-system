"""Ordered signal registry (UNIFIED_SCORING_PLAN §3.4).

Registration order is load-bearing: it is the deterministic tie-break
fallback (§3.3 #4) and the precedence order for merged entity evidence.
Kept aligned with the §4 table (priors descending).

Adding or removing a signal is one line here — never an orchestrator edit.
"""

from __future__ import annotations

from typing import Any, List, Optional

from .signals.clip_vision import ClipVisionSignal
from .signals.filename_pattern import FilenamePatternSignal
from .signals.filepath import FilepathSignal
from .signals.game_asset import GameAssetSignal
from .signals.graphic_detection import GraphicDetectionSignal
from .signals.identity_document import IdentityDocumentSignal
from .signals.interior import InteriorSignal
from .signals.kie_structured import KieStructuredSignal
from .signals.legal_content import LegalContentSignal
from .signals.media_heuristic import MediaHeuristicSignal
from .signals.mime_fallback import MimeFallbackSignal
from .signals.organization import OrganizationKeywordSignal
from .signals.personal_doc import PersonalDocSignal
from .signals.photo_composition import PhotoCompositionSignal
from .signals.renamed_screenshot import RenamedScreenshotSignal
from .signals.scene import SceneSignal
from .signals.screenshot_ocr import ScreenshotOcrSignal
from .signals.text_content import TextContentSignal
from .types import Signal


def build_default_signals(
    *,
    classifier: Any = None,
    screenshot_classifier: Any = None,
    image_analyzer: Any = None,
    category_paths: Optional[dict] = None,
    game_sprite_keywords: Optional[List[str]] = None,
) -> List[Signal]:
    """Build the production signal list in §4 order (priors descending).

    Dependency parameters mirror what ``ContentOrganizer`` owns today:

    - ``classifier``: ContentClassifier (keyword scoring + entity extraction).
      Signals that require it are omitted when it is ``None`` (lightweight /
      test organizers degrade gracefully instead of erroring per file).
    - ``screenshot_classifier``: ContentClassifier for screenshot OCR
      sub-classification (the production script passes the image renamer's).
    - ``image_analyzer``: ImageContentAnalyzer; ``PhotoCompositionSignal``
      gates itself on its availability.
    - ``category_paths``: the organizer's (deep-copied) content taxonomy —
      the screenshots sub-dict keys drive renamed-screenshot/OCR routing.
    - ``game_sprite_keywords``: the caller's sprite vocabulary for the
      filename rules (defaults to the shared constant inside each signal).
    """
    screenshots_dict: dict = {}
    if category_paths:
        screenshots_dict = category_paths.get("media", {}).get("photos", {}).get("screenshots", {})

    signals: List[Signal] = [
        RenamedScreenshotSignal(screenshots_dict),  # W_RENAMED = 1.2
        FilenamePatternSignal(list(game_sprite_keywords or [])),  # W_FILENAME = 1.1
    ]
    if classifier is not None:
        signals.append(KieStructuredSignal(classifier))  # W_KIE = 1.1
        signals.append(IdentityDocumentSignal(classifier))  # W_ID = 1.0
        signals.append(OrganizationKeywordSignal(classifier))  # W_ORG = 1.0
        signals.append(PersonalDocSignal(classifier))  # W_PERSON = 0.9
        signals.append(LegalContentSignal(classifier))  # W_LEGAL = 0.85
    # Always-on (no classifier dep) — trained CLIP-embedding scene probe slot.
    # Transition guard (MEDIA_EXTERIORS_PLAN §Sequencing): the multi-class
    # SceneSignal replaces the binary interior probe only once its trained
    # artifact (results/scene_probe.joblib) is present — never swap ahead of
    # a trained probe. Until then the shipped InteriorSignal keeps interior
    # detection live. Swap completion (artifact committed): delete this
    # fallback + interior.py, retire photo_composition's is_property_mgmt
    # vote, and update backtest_scoring.WEIGHT_SIGNALS to ("W_SCENE", "scene").
    scene = SceneSignal()  # W_SCENE = 0.85
    if scene.is_loaded:
        signals.append(scene)
    else:
        signals.append(InteriorSignal())  # W_INTERIOR = 0.85
    signals.append(
        GameAssetSignal(
            sprite_keywords=game_sprite_keywords,  # None → shared constant
        )  # W_GAME = 0.8
    )
    if classifier is not None:
        signals.append(TextContentSignal(classifier))  # W_TEXT = 0.8
    signals.append(
        ScreenshotOcrSignal(
            screenshot_classifier=screenshot_classifier,
            screenshots_dict=screenshots_dict,
        )  # W_UI = 0.75
    )
    signals.append(GraphicDetectionSignal())  # W_GRAPHIC = 0.75
    signals.append(ClipVisionSignal())  # W_CLIP = 0.7
    signals.append(MediaHeuristicSignal())  # W_MEDIA = 0.65
    signals.append(PhotoCompositionSignal(image_analyzer))  # W_PEOPLE_PHOTO = 0.65
    signals.append(FilepathSignal())  # W_PATH = 0.6
    signals.append(MimeFallbackSignal())  # W_MIME = 0.4
    return signals
