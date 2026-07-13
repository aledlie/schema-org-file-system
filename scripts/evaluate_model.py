#!/usr/bin/env python3
"""
Model Evaluation Script

Runs the existing file categorization model on the test dataset
and generates evaluation metrics and results.
"""

import os
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any
from collections import Counter, defaultdict

from shared.constants import (
    GAME_AUDIO_KEYWORDS, GAME_MUSIC_KEYWORDS, GAME_SPRITE_KEYWORDS,
    SCREENSHOT_PATTERNS, DOCUMENT_PATTERNS,
)

# An image is only assigned the 'media' catch-all when it has positive photo
# evidence; otherwise the prediction is low-confidence and routes to
# 'uncategorized' (see backlog: low-confidence -> uncategorized rule).
# parent_folder values that count as positive evidence an image is a real photo:
PHOTO_PARENT_FOLDERS = {"Camera", "Photos", "Photos (2)", "Photos 3",
                        "Screenshots", "Social_Media", "WhatsApp"}

# Minimum per-class support (actual samples of that class) required before its
# precision/recall/F1 are treated as reliable enough to report. Classes below
# this are segregated into `low_support_categories` and excluded from the macro
# average, so a class with 1-2 samples cannot drag the headline metric toward a
# misleading 0% (see backlog: "report per-class metrics only for classes with
# adequate support").
DEFAULT_MIN_SUPPORT = 5


class FileCategorizationModel:
    """Simulates the categorization logic from file_organizer_content_based.py"""

    def __init__(self):
        self.all_game_keywords = {
            k.lstrip('_')
            for k in GAME_AUDIO_KEYWORDS + GAME_MUSIC_KEYWORDS + GAME_SPRITE_KEYWORDS
        }

    def predict_category(self, feature: Dict) -> Tuple[str, str, float]:
        """
        Predict category based on features.

        Returns:
            Tuple of (predicted_category, predicted_subcategory, confidence)
        """
        filename = feature.get('filename', '').lower()
        filename_tokens = feature.get('filename_tokens', [])
        extension = feature.get('extension', '').lower()
        extension_category = feature.get('extension_category', '')
        parent_folder = feature.get('parent_folder', '')

        # Check for screenshots first
        if self._matches_patterns(filename, SCREENSHOT_PATTERNS):
            if extension in ['.png', '.jpg', '.jpeg']:
                return ('media', 'photos_screenshots', 0.95)

        # Check for game assets
        game_score = self._calculate_game_asset_score(filename_tokens, extension)
        if game_score >= 0.3:
            subcategory = self._determine_game_subcategory(filename_tokens, extension)
            return ('game_assets', subcategory, game_score)

        # Check for documents
        if self._matches_patterns(filename, DOCUMENT_PATTERNS):
            return ('legal', 'other', 0.7)

        # Media files
        if extension_category == 'image':
            # Filepath fallback: if no stronger signal fired and the file lives in
            # a Games/ folder, prefer game_assets (matches production's filepath
            # priority stage in detect_file_category).
            if parent_folder == 'Games':
                subcategory = self._determine_game_subcategory(filename_tokens, extension)
                return ('game_assets', subcategory, 0.7)
            # Only assign the 'media' catch-all when there is positive photo
            # evidence; otherwise the prediction is low-confidence and routes to
            # 'uncategorized' rather than over-claiming media.
            if self._has_photo_evidence(feature):
                return ('media', 'photos_other', 0.6)
            return ('uncategorized', 'other', 0.3)
        elif extension_category == 'video':
            return ('media', 'videos_recordings', 0.6)
        elif extension_category == 'audio':
            # Could be game audio or regular audio
            if game_score > 0.3:
                return ('game_assets', 'audio', 0.7)
            return ('media', 'audio', 0.5)

        # Technical files
        if extension in ['.js', '.ts', '.py', '.json', '.xml', '.yaml', '.yml']:
            return ('technical', 'code', 0.7)

        # Default to uncategorized
        return ('uncategorized', 'other', 0.3)

    def _has_photo_evidence(self, feature: Dict) -> bool:
        """Positive evidence that an image is a real photo (vs an unknown asset).

        Used to gate the 'media' catch-all: camera/EXIF/date-stamped images and
        those living in photo folders are real media; generic images in 'Other'
        with no such signal are low-confidence and route to 'uncategorized'.
        """
        return bool(
            feature.get('has_datetime')
            or feature.get('has_gps')
            or feature.get('starts_with_date')
            or feature.get('parent_folder') in PHOTO_PARENT_FOLDERS
        )

    def _matches_patterns(self, text: str, patterns: List[str]) -> bool:
        """Check if text matches any patterns."""
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def _calculate_game_asset_score(self, tokens: List[str], extension: str) -> float:
        """Calculate likelihood of being a game asset."""
        if not tokens:
            return 0.0

        # Count matching keywords (also try singular form for plurals)
        def _matches(token: str) -> bool:
            t = token.lower()
            if t in self.all_game_keywords:
                return True
            return t.endswith('s') and t[:-1] in self.all_game_keywords

        matches = sum(1 for t in tokens if _matches(t))

        # Base score from keyword matches
        score = min(matches / max(len(tokens), 1) * 1.5, 1.0)

        # Boost for game-typical extensions
        if extension in ['.png', '.wav', '.ogg', '.mp3']:
            score = min(score + 0.1, 1.0)

        # Boost for numeric suffixes (common in game assets)
        if tokens and tokens[-1].isdigit():
            score = min(score + 0.1, 1.0)

        return score

    def _determine_game_subcategory(self, tokens: List[str], extension: str) -> str:
        """Determine the game asset subcategory."""
        tokens_lower = [t.lower() for t in tokens]

        # Audio files
        if extension in ['.wav', '.ogg', '.mp3']:
            # Check for music keywords
            music_matches = sum(1 for t in tokens_lower if t in GAME_MUSIC_KEYWORDS)
            audio_matches = sum(1 for t in tokens_lower if t in GAME_AUDIO_KEYWORDS)

            if music_matches > audio_matches:
                return 'music'
            return 'audio'

        # Image files - sprites or textures
        if extension in ['.png', '.jpg', '.jpeg', '.gif', '.svg']:
            # Check for texture-related keywords
            texture_keywords = ['texture', 'wall', 'floor', 'tile', 'seamless', 'pattern']
            texture_matches = sum(1 for t in tokens_lower if t in texture_keywords)

            if texture_matches > 0:
                return 'textures'
            return 'sprites'

        return 'other'


class ContentClassifierModel:
    """Adapter over the production ContentBasedFileOrganizer classifier.

    Runs the real CLIP + OCR pipeline (detect_file_category) instead of the
    filename-only heuristic. Because it reads file content, each test entry's
    'filepath' must point to a file that exists on disk; entries whose file is
    missing return the SKIP sentinel and are excluded from metrics.
    """

    SKIP = "__skip__"

    def __init__(self) -> None:
        from file_organizer_content_based import ContentBasedFileOrganizer
        # No cost tracking or DB writes during evaluation.
        self.organizer = ContentBasedFileOrganizer(
            enable_cost_tracking=False, db_path=None,
        )

    def predict_category(self, feature: Dict) -> Tuple[str, str, float]:
        path = Path(feature.get('filepath') or '')
        if not path.exists():
            return (self.SKIP, self.SKIP, 0.0)
        main_category, subcategory, *_ = self.organizer.detect_file_category(path)
        # detect_file_category has no scalar confidence; fall back to the last
        # OCR confidence when present, else treat a first-match rule as certain.
        confidence = getattr(self.organizer, '_last_file_ocr_confidence', None) or 1.0
        return (main_category, subcategory, confidence)


def evaluate_model(test_data_path: str, output_path: str = None,
                   classifier: str = 'baseline',
                   min_support: int = DEFAULT_MIN_SUPPORT) -> Dict[str, Any]:
    """
    Evaluate the categorization model on test data.

    Args:
        test_data_path: Path to test.json
        output_path: Path to save results (optional)
        classifier: 'baseline' (filename heuristic) or 'content' (CLIP+OCR).
        min_support: Minimum actual-sample count for a class's per-class metrics
            to be reported and counted in the macro average. Classes below this
            are listed under `low_support_categories` instead.

    Returns:
        Evaluation results dictionary
    """
    print("Loading test data...")
    with open(test_data_path, 'r') as f:
        test_data = json.load(f)

    print(f"Loaded {len(test_data)} test samples")

    model = ContentClassifierModel() if classifier == 'content' else FileCategorizationModel()

    # Run predictions
    results = []
    correct = 0
    correct_subcategory = 0
    skipped_missing = 0

    category_metrics = defaultdict(lambda: {'tp': 0, 'fp': 0, 'fn': 0})
    confusion_matrix = defaultdict(lambda: defaultdict(int))
    confidence_scores = []

    print(f"Running predictions (classifier={classifier})...")
    for i, feature in enumerate(test_data):
        actual_category = feature.get('category', 'uncategorized')
        actual_subcategory = feature.get('subcategory', 'other')

        predicted_category, predicted_subcategory, confidence = model.predict_category(feature)

        # Content classifier reads real files; skip entries whose file is gone
        # so they do not distort metrics as false uncategorized predictions.
        if predicted_category == getattr(model, 'SKIP', None):
            skipped_missing += 1
            continue

        # Track results
        is_correct = predicted_category == actual_category
        is_subcategory_correct = predicted_subcategory == actual_subcategory

        if is_correct:
            correct += 1
            category_metrics[actual_category]['tp'] += 1
        else:
            category_metrics[actual_category]['fn'] += 1
            category_metrics[predicted_category]['fp'] += 1

        if is_subcategory_correct:
            correct_subcategory += 1

        confusion_matrix[actual_category][predicted_category] += 1
        confidence_scores.append(confidence)

        results.append({
            'filename': feature.get('filename'),
            'filepath': feature.get('filepath'),
            'actual_category': actual_category,
            'actual_subcategory': actual_subcategory,
            'predicted_category': predicted_category,
            'predicted_subcategory': predicted_subcategory,
            'confidence': confidence,
            'correct': is_correct,
            'subcategory_correct': is_subcategory_correct
        })

        if (i + 1) % 1000 == 0:
            print(f"  Processed {i + 1}/{len(test_data)}")

    # Calculate metrics over evaluated (non-skipped) samples only.
    evaluated = len(results)
    accuracy = correct / evaluated if evaluated else 0
    subcategory_accuracy = correct_subcategory / evaluated if evaluated else 0
    avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0

    # Per-category metrics. `support` is the count of actual samples of the
    # class (tp + fn); a class present only via false positives has support 0.
    # Classes with support < min_support are flagged unreported so their noisy
    # near-zero F1 does not distort the headline macro metric.
    per_category_metrics = {}
    low_support_categories = []
    for category in category_metrics:
        tp = category_metrics[category]['tp']
        fp = category_metrics[category]['fp']
        fn = category_metrics[category]['fn']

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        support = tp + fn
        reported = support >= min_support
        per_category_metrics[category] = {
            'precision': round(precision, 4),
            'recall': round(recall, 4),
            'f1_score': round(f1, 4),
            'support': support,
            'reported': reported,
        }
        if not reported:
            low_support_categories.append({'category': category, 'support': support})

    low_support_categories.sort(key=lambda c: -c['support'])

    # Macro average over adequately-supported classes only. Unweighted mean of
    # per-class precision/recall/F1 — excludes low-support classes so a 1-sample
    # class cannot swing it.
    reported_metrics = [m for m in per_category_metrics.values() if m['reported']]
    n_reported = len(reported_metrics)
    if n_reported:
        macro_precision = sum(m['precision'] for m in reported_metrics) / n_reported
        macro_recall = sum(m['recall'] for m in reported_metrics) / n_reported
        macro_f1 = sum(m['f1_score'] for m in reported_metrics) / n_reported
    else:
        macro_precision = macro_recall = macro_f1 = 0
    macro_avg = {
        'precision': round(macro_precision, 4),
        'recall': round(macro_recall, 4),
        'f1_score': round(macro_f1, 4),
        'min_support': min_support,
        'classes_reported': n_reported,
        'classes_excluded': len(low_support_categories),
    }

    # Find misclassifications
    misclassifications = [r for r in results if not r['correct']]
    misclassification_patterns = Counter(
        (r['actual_category'], r['predicted_category'])
        for r in misclassifications
    )

    # Build evaluation report
    evaluation = {
        'metadata': {
            'timestamp': datetime.now().isoformat(),
            'test_samples': len(test_data),
            'evaluated': evaluated,
            'skipped_missing': skipped_missing,
            'min_support': min_support,
            'model': ('ContentBasedFileOrganizer (CLIP+OCR)' if classifier == 'content'
                      else 'FileCategorizationModel v1.0')
        },
        'overall_metrics': {
            'accuracy': round(accuracy, 4),
            'subcategory_accuracy': round(subcategory_accuracy, 4),
            'avg_confidence': round(avg_confidence, 4),
            'total_correct': correct,
            'total_incorrect': evaluated - correct
        },
        'macro_avg_supported': macro_avg,
        'per_category_metrics': per_category_metrics,
        'low_support_categories': low_support_categories,
        'confusion_matrix': {k: dict(v) for k, v in confusion_matrix.items()},
        'top_misclassifications': [
            {
                'from': pattern[0],
                'to': pattern[1],
                'count': count
            }
            for pattern, count in misclassification_patterns.most_common(10)
        ],
        'sample_results': results[:100],  # Include sample of detailed results
        'all_predictions': results  # Full results
    }

    # Save results
    if output_path:
        print(f"Saving results to {output_path}")
        with open(output_path, 'w') as f:
            json.dump(evaluation, f, indent=2)

    return evaluation


def print_report(evaluation: Dict[str, Any]):
    """Print a formatted evaluation report."""
    print("\n" + "=" * 60)
    print("MODEL EVALUATION REPORT")
    print("=" * 60)

    meta = evaluation['metadata']
    print(f"\nTimestamp: {meta['timestamp']}")
    print(f"Model: {meta.get('model')}")
    print(f"Test Samples: {meta['test_samples']:,}")
    if meta.get('skipped_missing'):
        print(f"Evaluated: {meta.get('evaluated', 0):,} "
              f"(skipped {meta['skipped_missing']:,} missing files)")

    print("\n" + "-" * 40)
    print("OVERALL METRICS")
    print("-" * 40)
    metrics = evaluation['overall_metrics']
    print(f"  Category Accuracy:    {metrics['accuracy']:.2%}")
    print(f"  Subcategory Accuracy: {metrics['subcategory_accuracy']:.2%}")
    print(f"  Avg Confidence:       {metrics['avg_confidence']:.2%}")
    print(f"  Correct Predictions:  {metrics['total_correct']:,}")
    print(f"  Incorrect Predictions:{metrics['total_incorrect']:,}")

    min_support = meta.get('min_support', DEFAULT_MIN_SUPPORT)
    print("\n" + "-" * 40)
    print(f"PER-CATEGORY METRICS (support >= {min_support})")
    print("-" * 40)
    print(f"  {'Category':<25} {'Precision':>10} {'Recall':>10} {'F1':>10} {'Support':>10}")
    print("  " + "-" * 65)

    for category, m in sorted(evaluation['per_category_metrics'].items(),
                              key=lambda x: -x[1]['support']):
        if not m.get('reported', True):
            continue
        print(f"  {category:<25} {m['precision']:>10.2%} {m['recall']:>10.2%} "
              f"{m['f1_score']:>10.2%} {m['support']:>10,}")

    macro = evaluation.get('macro_avg_supported')
    if macro:
        print("  " + "-" * 65)
        print(f"  {'macro avg (' + str(macro['classes_reported']) + ' classes)':<25} "
              f"{macro['precision']:>10.2%} {macro['recall']:>10.2%} "
              f"{macro['f1_score']:>10.2%}")

    low_support = evaluation.get('low_support_categories', [])
    if low_support:
        print("\n" + "-" * 40)
        print(f"LOW-SUPPORT CATEGORIES (support < {min_support}, metrics not reported)")
        print("-" * 40)
        for c in low_support:
            print(f"  {c['category']:<25} support={c['support']:,}")

    print("\n" + "-" * 40)
    print("TOP MISCLASSIFICATIONS")
    print("-" * 40)
    for item in evaluation['top_misclassifications'][:5]:
        print(f"  {item['from']:>20} -> {item['to']:<20} ({item['count']:,} files)")

    print("\n" + "=" * 60)


def run(args) -> None:
    """Typed entry point: evaluate the classifier from a parsed namespace.

    The namespace must carry the attributes defined by
    ``src.cli.add_evaluate_arguments`` (the single source for this command's
    options, shared with the unified CLI). ``min_support=None`` resolves to
    DEFAULT_MIN_SUPPORT here so the constant stays single-homed.
    """
    min_support = args.min_support if args.min_support is not None else DEFAULT_MIN_SUPPORT

    evaluation = evaluate_model(args.test_data, args.output,
                                classifier=args.classifier,
                                min_support=min_support)

    print_report(evaluation)

    print(f"\nFull results saved to: {args.output}")


def main():
    """Standalone entry point (argument definitions shared with organize-files)."""
    import sys
    import argparse

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.cli import add_evaluate_arguments

    parser = argparse.ArgumentParser(description='Evaluate file categorization model')
    add_evaluate_arguments(parser)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
