#!/usr/bin/env python3
"""Backtest the unified scorer against stored classification runs.

UNIFIED_SCORING_PLAN §7.2: replay ``results/file_organization.db`` File rows
through the REAL signal registry + Scorer, rebuilding each ``FileContext``
from persisted columns only — no disk I/O, no OCR/CLIP models:

- ``original_path``/``filename`` drive the filename/filepath signals (the
  original path is what the production classification saw; ``current_path``
  would leak the stored filing decision back into ``FilepathSignal``).
- ``extracted_text`` is served by the text provider; for image rows it is
  wrapped in an OCRResult-shaped ``SimpleNamespace`` when a stored
  ``ocr_confidence`` exists (image rows with text but no confidence replay
  filename-only, mirroring ``FileContext.ensure_text``'s image routing).
- ``kie_fields`` (persisted as ``{class: [{"value", "confidence"}]}`` by
  ``FileProcessor._persist_to_graph_store``) is reconstructed into the
  ``SimpleNamespace(fields=...)`` shape ``ContentClassifier.classify_with_kie``
  reads; unreconstructable payloads skip KIE for that row.
- ``image_classification`` (CLIP label→score JSON) feeds ``ensure_clip``
  when present as a numeric dict.
- The screenshot-OCR signal's internal disk OCR is replaced by a stub that
  re-scores the STORED text against ``SCREENSHOT_KEYWORDS`` (pass 1 of
  ``shared.ocr_classifier.classify_by_ocr``), so screenshot-named rows
  replay deterministically without touching the filesystem.

Outputs: decision distribution by (category, subcategory), decision-state
distribution, per-signal win participation, agreement vs stored category
associations (with top disagreement pairs), optional accuracy vs a labeled
test.json, and — with ``--weights-sensitivity`` — a decision-flip count per
``src/scoring/weights.py`` prior at ±20%.

Usage:
    python scripts/backtest_scoring.py [--db-path PATH] [--labels PATH]
        [--output PATH] [--limit N] [--weights-sensitivity]

Rows whose stored data cannot build a context are counted and skipped,
never fatal.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# Bootstrap: allow `python scripts/backtest_scoring.py` from the project root
# (sys.path[0] is scripts/, so src.* needs the root; shared.* needs scripts/).
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
for _path in (str(_PROJECT_ROOT), str(_SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from shared.constants import GAME_SPRITE_KEYWORDS  # noqa: E402
from shared.ocr_classifier import SCREENSHOT_KEYWORDS, SCREENSHOT_MIN_HITS  # noqa: E402
from src.constants import DEFAULT_DB_PATH  # noqa: E402
from src.organizers.category_config import CONTENT_CATEGORY_PATHS  # noqa: E402
from src.scoring.context import FileContext  # noqa: E402
from src.scoring.registry import build_default_signals  # noqa: E402
from src.scoring.scorer import Scorer  # noqa: E402
from src.scoring.signals.screenshot_ocr import ScreenshotOcrSignal  # noqa: E402
from src.scoring.weights import (  # noqa: E402
    W_CLIP,
    W_FILENAME,
    W_GAME,
    W_ID,
    W_INTERIOR,
    W_KIE,
    W_LEGAL,
    W_MEDIA,
    W_MIME,
    W_ORG,
    W_PATH,
    W_PEOPLE_PHOTO,
    W_PERSON,
    W_RENAMED,
    W_TEXT,
    W_UI,
)

BANNER = "Unified scoring backtest (UNIFIED_SCORING_PLAN §7.2)"

EXIT_OK = 0
EXIT_NO_DATA = 1

# Sensitivity mode reruns the replay 2× per weight; cap the default corpus so
# 15 weights × 2 runs stays tractable (§7.2).
SENSITIVITY_DEFAULT_LIMIT = 500

# Each weight is perturbed to base × (1 ± this fraction).
WEIGHT_DELTA_FRACTION = 0.20

# Report keys for the two perturbation directions.
SENSITIVITY_DOWN_KEY = "down_flips"
SENSITIVITY_UP_KEY = "up_flips"

# Max (stored -> predicted) disagreement pairs listed in the report.
TOP_DISAGREEMENT_PAIRS = 10

# Coarse Schema.org types the pipeline uses (content_organizer._derive_schema_type).
IMAGE_SCHEMA_TYPE = "ImageObject"
VIDEO_SCHEMA_TYPE = "VideoObject"
AUDIO_SCHEMA_TYPE = "AudioObject"
DEFAULT_SCHEMA_TYPE = "DigitalDocument"
COARSE_SCHEMA_TYPES = (
    IMAGE_SCHEMA_TYPE,
    VIDEO_SCHEMA_TYPE,
    AUDIO_SCHEMA_TYPE,
    DEFAULT_SCHEMA_TYPE,
)

IMAGE_MIME_PREFIX = "image/"
VIDEO_MIME_PREFIX = "video/"
AUDIO_MIME_PREFIX = "audio/"

# Registry name of the signal whose disk OCR is replaced by the stored-text stub.
SCREENSHOT_OCR_SIGNAL_NAME = "screenshot_ocr"

# Persisted kie_fields entry keys (FileProcessor._persist_to_graph_store).
KIE_VALUE_KEY = "value"
KIE_CONFIDENCE_KEY = "confidence"

# Declared weight-constant → registered-signal mapping for the sensitivity
# sweep (§7.2 "∂decisions/∂weight"). Explicitly enumerated — no introspection.
WEIGHT_SIGNALS: List[Tuple[str, float, str]] = [
    ("W_RENAMED", W_RENAMED, "renamed_screenshot"),
    ("W_FILENAME", W_FILENAME, "filename_pattern"),
    ("W_KIE", W_KIE, "kie_structured"),
    ("W_ID", W_ID, "identity_document"),
    ("W_ORG", W_ORG, "organization_keyword"),
    ("W_PERSON", W_PERSON, "personal_doc"),
    ("W_LEGAL", W_LEGAL, "legal_content"),
    ("W_INTERIOR", W_INTERIOR, "interior"),
    ("W_GAME", W_GAME, "game_asset"),
    ("W_TEXT", W_TEXT, "text_content"),
    ("W_UI", W_UI, "screenshot_ocr"),
    ("W_CLIP", W_CLIP, "clip_vision"),
    ("W_MEDIA", W_MEDIA, "media_heuristic"),
    ("W_PEOPLE_PHOTO", W_PEOPLE_PHOTO, "photo_composition"),
    ("W_PATH", W_PATH, "filepath"),
    ("W_MIME", W_MIME, "mime_fallback"),
]

# Skip-reason counter keys (rows counted, never fatal).
SKIP_UNBUILDABLE = "unbuildable_context"
SKIP_CLASSIFY_ERROR = "classify_error"


@dataclass(frozen=True)
class ReplayRow:
    """Snapshot of one stored File row (detached from the ORM session)."""

    file_id: str
    original_path: str
    current_path: str
    filename: str
    mime_type: Optional[str]
    schema_type: Optional[str]
    extracted_text: str
    ocr_confidence: Optional[float]
    detected_language: Optional[str]
    kie_fields: Any
    clip_scores: Any
    stored_category: Optional[str]
    stored_subcategory: Optional[str]


@dataclass(frozen=True)
class ReplayOutcome:
    """One replayed row with its unified ClassificationDecision."""

    row: ReplayRow
    decision: Any


# --------------------------------------------------------------------------- #
# DB loading                                                                    #
# --------------------------------------------------------------------------- #


def _stored_pair(record: Any) -> Tuple[Optional[str], Optional[str]]:
    """(category, subcategory) from the row's first category association.

    ``add_file_to_category`` links files to the SUBCATEGORY node whose
    ``full_path`` is ``"category/subcategory"`` (or a root node when no
    subcategory was recorded).
    """
    for category in record.categories or []:
        full_path = category.full_path or category.name or ""
        if not full_path:
            continue
        parts = full_path.split("/", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return parts[0], None
    return None, None


def load_replay_rows(db_path: Path, limit: Optional[int] = None) -> List[ReplayRow]:
    """Load stored File rows (deterministic ``File.id`` order) as snapshots."""
    from src.storage.graph_store import GraphStore
    from src.storage.models import File

    store = GraphStore(db_path=db_path)
    session = store.get_session()
    try:
        query = session.query(File).order_by(File.id)
        if limit is not None:
            query = query.limit(limit)
        rows: List[ReplayRow] = []
        for record in query:
            stored_category, stored_subcategory = _stored_pair(record)
            rows.append(
                ReplayRow(
                    file_id=record.id,
                    original_path=record.original_path or "",
                    current_path=record.current_path or "",
                    filename=record.filename or "",
                    mime_type=record.mime_type,
                    schema_type=record.schema_type,
                    extracted_text=record.extracted_text or "",
                    ocr_confidence=record.ocr_confidence,
                    detected_language=record.detected_language,
                    kie_fields=record.kie_fields,
                    clip_scores=record.image_classification,
                    stored_category=stored_category,
                    stored_subcategory=stored_subcategory,
                )
            )
        return rows
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# Context reconstruction (pure)                                                #
# --------------------------------------------------------------------------- #


def derive_schema_type(mime_type: Optional[str], stored_schema_type: Optional[str] = None) -> str:
    """Coarse Schema.org type from MIME (mirrors the production unified path).

    Falls back to the stored ``schema_type`` when it is already one of the
    coarse pipeline types, then to ``DigitalDocument``.
    """
    if mime_type:
        if mime_type.startswith(IMAGE_MIME_PREFIX):
            return IMAGE_SCHEMA_TYPE
        if mime_type.startswith(VIDEO_MIME_PREFIX):
            return VIDEO_SCHEMA_TYPE
        if mime_type.startswith(AUDIO_MIME_PREFIX):
            return AUDIO_SCHEMA_TYPE
        return DEFAULT_SCHEMA_TYPE
    if stored_schema_type in COARSE_SCHEMA_TYPES:
        return stored_schema_type
    return DEFAULT_SCHEMA_TYPE


def reconstruct_kie(raw: Any) -> Optional[SimpleNamespace]:
    """Rebuild the KIEResult-shaped object ``classify_with_kie`` consumes.

    Accepts only the persisted ``{class: [{"value", "confidence"}]}`` shape;
    anything else returns ``None`` (KIE replay skipped for the row).
    """
    if not isinstance(raw, dict) or not raw:
        return None
    fields: Dict[str, List[SimpleNamespace]] = {}
    for class_name, entries in raw.items():
        if not isinstance(entries, list):
            return None
        rebuilt = []
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or KIE_VALUE_KEY not in entry
                or not isinstance(entry.get(KIE_CONFIDENCE_KEY), (int, float))
            ):
                return None
            rebuilt.append(
                SimpleNamespace(
                    value=entry[KIE_VALUE_KEY],
                    confidence=float(entry[KIE_CONFIDENCE_KEY]),
                )
            )
        fields[str(class_name)] = rebuilt
    return SimpleNamespace(fields=fields)


def reconstruct_clip(raw: Any) -> Optional[Dict[str, float]]:
    """CLIP label→score dict for ``ensure_clip``, or None when not replayable."""
    if not isinstance(raw, dict) or not raw:
        return None
    scores: Dict[str, float] = {}
    for label, value in raw.items():
        if not isinstance(value, (int, float)):
            return None
        scores[str(label)] = float(value)
    return scores


def context_path(row: ReplayRow) -> str:
    """The path the replayed context classifies under (original, pre-move)."""
    return row.original_path or row.current_path or row.filename


def _constant_provider(value: Any) -> Callable[[Path], Any]:
    """A FileContext provider that returns a fixed persisted value."""

    def provider(_path: Path) -> Any:
        return value

    return provider


def build_context(row: ReplayRow) -> Optional[FileContext]:
    """FileContext over the row's persisted columns, or None when unbuildable."""
    path_str = context_path(row)
    if not path_str:
        return None

    schema_type = derive_schema_type(row.mime_type, row.schema_type)
    text = row.extracted_text or ""

    text_provider = _constant_provider(text) if text else None

    ocr_provider = None
    if schema_type == IMAGE_SCHEMA_TYPE and text and row.ocr_confidence is not None:
        ocr = SimpleNamespace(
            text=text,
            confidence=row.ocr_confidence,
            language=row.detected_language,
        )
        ocr_provider = _constant_provider(ocr)

    kie = reconstruct_kie(row.kie_fields)
    kie_provider = _constant_provider(kie) if kie is not None else None

    clip = reconstruct_clip(row.clip_scores)
    clip_provider = _constant_provider(clip) if clip is not None else None

    return FileContext(
        path=Path(path_str),
        schema_type=schema_type,
        mime_type=row.mime_type,
        text_provider=text_provider,
        ocr_provider=ocr_provider,
        clip_provider=clip_provider,
        kie_provider=kie_provider,
    )


# --------------------------------------------------------------------------- #
# Scorer assembly (shared with `organize-files evaluate --classifier unified`)  #
# --------------------------------------------------------------------------- #


def build_screenshots_taxonomy() -> Dict[str, Any]:
    """Replicate ``ContentOrganizer.__init__``'s screenshots-taxonomy extension."""
    screenshots = deepcopy(CONTENT_CATEGORY_PATHS)["media"]["photos"]["screenshots"]
    for key in SCREENSHOT_KEYWORDS:
        if key not in screenshots:
            folder = key.replace("_", " ").title().replace(" ", "")
            screenshots[key] = f"Media/Photos/Screenshots/{folder}"
    return screenshots


def screenshot_ocr_from_text(text: str) -> Optional[Tuple[str, float, Dict[str, float], str]]:
    """Pass-1 of ``classify_by_ocr`` over already-extracted text (no disk OCR)."""
    if not text:
        return None
    text_lower = text.lower()
    scores: Dict[str, float] = {}
    hits: Dict[str, int] = {}
    for category, keywords in SCREENSHOT_KEYWORDS.items():
        matched = sum(1 for keyword in keywords if keyword in text_lower)
        if matched:
            hits[category] = matched
            scores[category] = matched / len(keywords)
    if not scores:
        return None
    best = max(scores, key=lambda category: scores[category])
    if hits[best] < SCREENSHOT_MIN_HITS:
        return None
    return (best, scores[best], scores, text)


def make_screenshot_ocr_stub(
    text_by_path: Optional[Dict[str, str]] = None,
) -> Callable[..., Optional[Tuple[str, float, Dict[str, float], str]]]:
    """OCR-classify replacement scoring stored text instead of reading disk."""
    lookup = text_by_path or {}

    def _stub(path: Path, content_classifier: Any = None, text: str | None = None):
        # The signal now sources text from ctx.ensure_ocr() and passes it through
        # (P3 dedup). In replay ctx.ensure_ocr().text is the stored extracted_text
        # — the same value this lookup holds — so preferring `text` and falling
        # back to the lookup (when a row had text but no ocr_confidence, so no
        # ocr_provider was wired) keeps replay results identical.
        return screenshot_ocr_from_text(text or lookup.get(str(path), ""))

    return _stub


def build_replay_scorer(
    classifier: Any,
    screenshot_text_by_path: Optional[Dict[str, str]] = None,
    weight_overrides: Optional[Dict[str, float]] = None,
) -> Scorer:
    """The production registry wired for replay: no disk I/O, no models.

    Mirrors the golden-suite construction (real ContentClassifier for the
    keyword signals, same classifier for screenshot sub-classification, no
    image analyzer) and swaps ``ScreenshotOcrSignal``'s disk OCR for the
    stored-text stub. ``weight_overrides`` maps signal names to replacement
    priors (instance-level; ``src/scoring/weights.py`` is untouched).
    """
    screenshots_dict = build_screenshots_taxonomy()
    signals = build_default_signals(
        classifier=classifier,
        screenshot_classifier=classifier,
        image_analyzer=None,
        category_paths={"media": {"photos": {"screenshots": screenshots_dict}}},
        game_sprite_keywords=list(GAME_SPRITE_KEYWORDS),
    )
    stub = make_screenshot_ocr_stub(screenshot_text_by_path)
    signals = [
        (
            ScreenshotOcrSignal(
                screenshot_classifier=classifier,
                screenshots_dict=screenshots_dict,
                ocr_classify=stub,
            )
            if signal.name == SCREENSHOT_OCR_SIGNAL_NAME
            else signal
        )
        for signal in signals
    ]
    for signal in signals:
        override = (weight_overrides or {}).get(signal.name)
        if override is not None:
            signal.weight = override
    return Scorer(signals)


def screenshot_text_lookup(rows: Sequence[ReplayRow]) -> Dict[str, str]:
    """Stored text keyed by the context path, for the screenshot-OCR stub."""
    lookup: Dict[str, str] = {}
    for row in rows:
        path_str = context_path(row)
        if path_str and row.extracted_text:
            lookup[path_str] = row.extracted_text
    return lookup


# --------------------------------------------------------------------------- #
# Replay + report (pure)                                                        #
# --------------------------------------------------------------------------- #


def replay_rows(
    rows: Sequence[ReplayRow], scorer: Scorer
) -> Tuple[List[ReplayOutcome], Dict[str, int]]:
    """Classify every buildable row; count (never raise on) the rest."""
    outcomes: List[ReplayOutcome] = []
    skipped = {SKIP_UNBUILDABLE: 0, SKIP_CLASSIFY_ERROR: 0}
    for row in rows:
        context = build_context(row)
        if context is None:
            skipped[SKIP_UNBUILDABLE] += 1
            continue
        try:
            decision = scorer.classify(context)
        except Exception as exc:  # replay must never crash on one row
            print(f"  classify error for {context_path(row)}: {exc}")
            skipped[SKIP_CLASSIFY_ERROR] += 1
            continue
        outcomes.append(ReplayOutcome(row=row, decision=decision))
    return outcomes, skipped


def _pair_text(category: str, subcategory: Optional[str]) -> str:
    return f"{category}/{subcategory}" if subcategory else str(category)


def _stored_agreement(outcomes: Sequence[ReplayOutcome]) -> Optional[Dict[str, Any]]:
    """Agreement vs stored category associations, or None when none exist.

    A row agrees when the predicted category matches the stored category and
    — when a stored subcategory exists — the subcategories match too.
    """
    with_stored = [outcome for outcome in outcomes if outcome.row.stored_category]
    if not with_stored:
        return None
    agree = 0
    disagreement_pairs: Counter = Counter()
    for outcome in with_stored:
        stored_category = outcome.row.stored_category
        stored_subcategory = outcome.row.stored_subcategory
        category_match = outcome.decision.category == stored_category
        subcategory_match = (
            stored_subcategory is None or outcome.decision.subcategory == stored_subcategory
        )
        if category_match and subcategory_match:
            agree += 1
            continue
        disagreement_pairs[
            (
                _pair_text(stored_category, stored_subcategory),
                _pair_text(outcome.decision.category, outcome.decision.subcategory),
            )
        ] += 1
    ranked = sorted(disagreement_pairs.items(), key=lambda item: (-item[1], item[0]))
    return {
        "rows_with_stored_category": len(with_stored),
        "agree_count": agree,
        "agreement_rate": round(agree / len(with_stored), 4),
        "top_disagreements": [
            {"stored": stored, "predicted": predicted, "count": count}
            for (stored, predicted), count in ranked[:TOP_DISAGREEMENT_PAIRS]
        ],
    }


def summarize_replay(outcomes: Sequence[ReplayOutcome], skipped: Dict[str, int]) -> Dict[str, Any]:
    """Aggregate replay outcomes into the report structure."""
    decision_counts = Counter(
        _pair_text(outcome.decision.category, outcome.decision.subcategory) for outcome in outcomes
    )
    state_counts = Counter(outcome.decision.decision_state for outcome in outcomes)
    signal_wins = Counter(
        signal_name for outcome in outcomes for signal_name in outcome.decision.winning_signals
    )
    return {
        "total_rows": len(outcomes) + sum(skipped.values()),
        "replayed": len(outcomes),
        "skipped": dict(skipped),
        "decision_distribution": dict(
            sorted(decision_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "decision_states": dict(sorted(state_counts.items())),
        "signal_wins": dict(sorted(signal_wins.items(), key=lambda item: (-item[1], item[0]))),
        "stored_agreement": _stored_agreement(outcomes),
    }


def score_against_labels(
    outcomes: Sequence[ReplayOutcome], labels: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    """Accuracy of replay decisions against a labeled test.json corpus.

    Label records are matched to rows by exact filepath (against either the
    original or the current stored path).
    """
    by_path: Dict[str, Tuple[Any, Any]] = {}
    for record in labels:
        filepath = record.get("filepath")
        if filepath:
            by_path[str(filepath)] = (record.get("category"), record.get("subcategory"))

    matched = 0
    category_correct = 0
    subcategory_correct = 0
    for outcome in outcomes:
        label = by_path.get(outcome.row.original_path) or by_path.get(outcome.row.current_path)
        if label is None:
            continue
        matched += 1
        expected_category, expected_subcategory = label
        if outcome.decision.category == expected_category:
            category_correct += 1
            if outcome.decision.subcategory == expected_subcategory:
                subcategory_correct += 1
    return {
        "labels_total": len(labels),
        "matched": matched,
        "category_accuracy": round(category_correct / matched, 4) if matched else None,
        "subcategory_accuracy": round(subcategory_correct / matched, 4) if matched else None,
    }


def weight_sensitivity(
    rows: Sequence[ReplayRow],
    classifier: Any,
    screenshot_text_by_path: Dict[str, str],
    baseline_outcomes: Sequence[ReplayOutcome],
    weight_signals: Sequence[Tuple[str, float, str]] = tuple(WEIGHT_SIGNALS),
    delta_fraction: float = WEIGHT_DELTA_FRACTION,
) -> Dict[str, Any]:
    """Decision-flip count per weight at ±``delta_fraction`` (∂decisions/∂weight).

    For each declared ``(constant, base value, signal name)`` the replay is
    rerun twice with only that signal's prior scaled; a flip is a row whose
    (category, subcategory) differs from the baseline replay.
    """
    baseline_by_id = {
        outcome.row.file_id: (outcome.decision.category, outcome.decision.subcategory)
        for outcome in baseline_outcomes
    }
    report: Dict[str, Any] = {}
    for constant_name, base_value, signal_name in weight_signals:
        entry: Dict[str, Any] = {"signal": signal_name, "base_weight": base_value}
        for direction_key, factor in (
            (SENSITIVITY_DOWN_KEY, 1.0 - delta_fraction),
            (SENSITIVITY_UP_KEY, 1.0 + delta_fraction),
        ):
            scorer = build_replay_scorer(
                classifier,
                screenshot_text_by_path=screenshot_text_by_path,
                weight_overrides={signal_name: base_value * factor},
            )
            outcomes, _skipped = replay_rows(rows, scorer)
            flips = sum(
                1
                for outcome in outcomes
                if baseline_by_id.get(outcome.row.file_id)
                not in (None, (outcome.decision.category, outcome.decision.subcategory))
            )
            entry[direction_key] = flips
        report[constant_name] = entry
    return report


# --------------------------------------------------------------------------- #
# Rendering + entry point                                                       #
# --------------------------------------------------------------------------- #


def format_report(report: Dict[str, Any]) -> str:
    """Render the report dict as the stdout summary."""
    lines = [
        f"Total rows:    {report['total_rows']}",
        f"Replayed:      {report['replayed']}",
    ]
    for reason, count in report["skipped"].items():
        lines.append(f"Skipped:       {count} ({reason})")

    lines.append("Decision states:")
    if report["decision_states"]:
        for state, count in report["decision_states"].items():
            lines.append(f"  {state:<16} {count}")
    else:
        lines.append("  (none)")

    lines.append("Decision distribution (category/subcategory):")
    if report["decision_distribution"]:
        for pair, count in report["decision_distribution"].items():
            lines.append(f"  {count:>5}  {pair}")
    else:
        lines.append("  (none)")

    lines.append("Signal win participation:")
    if report["signal_wins"]:
        for signal_name, count in report["signal_wins"].items():
            lines.append(f"  {count:>5}  {signal_name}")
    else:
        lines.append("  (none)")

    agreement = report.get("stored_agreement")
    if agreement is not None:
        lines.append(
            "Agreement vs stored categories: "
            f"{agreement['agree_count']}/{agreement['rows_with_stored_category']} "
            f"({agreement['agreement_rate']:.2%})"
        )
        if agreement["top_disagreements"]:
            lines.append("Top disagreements (stored -> predicted):")
            for item in agreement["top_disagreements"]:
                lines.append(f"  {item['count']:>5}  {item['stored']} -> {item['predicted']}")

    labels = report.get("labels")
    if labels is not None:
        category_accuracy = labels["category_accuracy"]
        accuracy_text = f"{category_accuracy:.2%}" if category_accuracy is not None else "n/a"
        lines.append(
            f"Labeled accuracy: {accuracy_text} on {labels['matched']} matched "
            f"of {labels['labels_total']} labels"
        )

    sensitivity = report.get("weight_sensitivity")
    if sensitivity is not None:
        lines.append(f"Weight sensitivity (±{int(WEIGHT_DELTA_FRACTION * 100)}% decision flips):")
        for constant_name, entry in sensitivity.items():
            lines.append(
                f"  {constant_name:<16} ({entry['signal']}, base {entry['base_weight']:.2f}) "
                f"-{int(WEIGHT_DELTA_FRACTION * 100)}%={entry[SENSITIVITY_DOWN_KEY]} "
                f"+{int(WEIGHT_DELTA_FRACTION * 100)}%={entry[SENSITIVITY_UP_KEY]}"
            )

    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay stored classification runs through the unified scorer (§7.2)"
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path(DEFAULT_DB_PATH),
        help=f"SQLite database to replay (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=None,
        help="Labeled test.json to score decisions against (matched by filepath)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the full report as JSON to this path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max File rows to replay (default: all; "
        f"{SENSITIVITY_DEFAULT_LIMIT} under --weights-sensitivity)",
    )
    parser.add_argument(
        "--weights-sensitivity",
        action="store_true",
        help=f"Rerun the replay with each weights.py prior at ±"
        f"{int(WEIGHT_DELTA_FRACTION * 100)}% and report decision flips",
    )
    args = parser.parse_args(argv)

    print(BANNER)
    print("=" * len(BANNER))

    if not args.db_path.exists():
        print(
            f"Error: database not found at {args.db_path} "
            "(run `organize-files content` first, or pass --db-path)"
        )
        return EXIT_NO_DATA

    limit = args.limit
    if args.weights_sensitivity and limit is None:
        limit = SENSITIVITY_DEFAULT_LIMIT

    rows = load_replay_rows(args.db_path, limit=limit)
    if not rows:
        print(f"Error: no stored File rows to replay in {args.db_path}")
        return EXIT_NO_DATA

    labels: Optional[List[Dict[str, Any]]] = None
    if args.labels is not None:
        if not args.labels.exists():
            print(f"Error: labels file not found at {args.labels}")
            return EXIT_NO_DATA
        labels = json.loads(args.labels.read_text(encoding="utf-8"))

    from src.classifiers.content_classifier import ContentClassifier

    classifier = ContentClassifier()
    text_by_path = screenshot_text_lookup(rows)
    scorer = build_replay_scorer(classifier, screenshot_text_by_path=text_by_path)

    print(f"Replaying {len(rows)} stored rows from {args.db_path} ...")
    outcomes, skipped = replay_rows(rows, scorer)
    report = summarize_replay(outcomes, skipped)

    if labels is not None:
        report["labels"] = score_against_labels(outcomes, labels)

    if args.weights_sensitivity:
        print(f"Running weight sensitivity ({len(WEIGHT_SIGNALS)} weights × 2 runs) ...")
        report["weight_sensitivity"] = weight_sensitivity(rows, classifier, text_by_path, outcomes)

    print(format_report(report))

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\nJSON report written to {args.output}")

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
