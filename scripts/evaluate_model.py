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


class FileCategorizationModel:
    """Simulates the categorization logic from file_organizer_content_based.py"""

    # Game asset keywords (from file_organizer_content_based.py)
    GAME_AUDIO_KEYWORDS = [
        'bolt', 'spell', 'magic', 'sword', 'dagger', 'arrow', 'attack', 'damage',
        'lightning', 'fire', 'ice', 'acid', 'poison', 'heal', 'summon', 'dispel',
        'door', 'chest', 'coin', 'pickup', 'unlock', 'lock', 'fiddle', 'lute',
        'mandoline', 'glockenspiel', 'sfx', 'sound', 'effect', 'ambient'
    ]

    GAME_MUSIC_KEYWORDS = [
        'battle', 'boss', 'dungeon', 'castle', 'forest', 'town', 'cave', 'temple',
        'victory', 'defeat', 'chaos', 'hope', 'despair', 'triumph', 'mysterious',
        'drakalor', 'altar', 'dwarven', 'elven', 'clockwork', 'theme', 'bgm',
        'soundtrack', 'music', 'loop'
    ]

    GAME_SPRITE_KEYWORDS = [
        'frame', 'leg', 'arm', 'head', 'torso', 'wing', 'tail', 'face', 'hand',
        'wall', 'floor', 'door', 'window', 'tree', 'rock', 'grass', 'sprite',
        'sword', 'shield', 'armor', 'potion', 'scroll', 'coin', 'gem', 'item',
        'icon', 'button', 'menu', 'cursor', 'bar', 'container', 'tile',
        'character', 'enemy', 'npc', 'player', 'walk', 'run', 'idle', 'attack',
        'hurt', 'dead', 'angry', 'happy', 'sad', 'shoulder', 'body', 'feet'
    ]

    SCREENSHOT_PATTERNS = [
        r'screenshot',
        r'screen\s*shot',
        r'screen_\d+',
        r'capture',
        r'snip',
    ]

    DOCUMENT_PATTERNS = [
        r'invoice', r'receipt', r'contract',
        r'report', r'statement', r'tax',
        r'resume', r'cv', r'letter',
    ]

    def __init__(self):
        self.all_game_keywords = set(
            self.GAME_AUDIO_KEYWORDS +
            self.GAME_MUSIC_KEYWORDS +
            self.GAME_SPRITE_KEYWORDS
        )

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

        # Check for screenshots first
        if self._matches_patterns(filename, self.SCREENSHOT_PATTERNS):
            if extension in ['.png', '.jpg', '.jpeg']:
                return ('media', 'photos_screenshots', 0.95)

        # Check for game assets
        game_score = self._calculate_game_asset_score(filename_tokens, extension)
        if game_score > 0.5:
            subcategory = self._determine_game_subcategory(filename_tokens, extension)
            return ('game_assets', subcategory, game_score)

        # Check for documents
        if self._matches_patterns(filename, self.DOCUMENT_PATTERNS):
            return ('legal', 'other', 0.7)

        # Media files
        if extension_category == 'image':
            return ('media', 'photos_other', 0.6)
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

    def _matches_patterns(self, text: str, patterns: List[str]) -> bool:
        """Check if text matches any patterns."""
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def _calculate_game_asset_score(self, tokens: List[str], extension: str) -> float:
        """Calculate likelihood of being a game asset."""
        if not tokens:
            return 0.0

        # Count matching keywords
        matches = sum(1 for t in tokens if t.lower() in self.all_game_keywords)

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
            music_matches = sum(1 for t in tokens_lower if t in self.GAME_MUSIC_KEYWORDS)
            audio_matches = sum(1 for t in tokens_lower if t in self.GAME_AUDIO_KEYWORDS)

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


def evaluate_model(test_data_path: str, output_path: str = None) -> Dict[str, Any]:
    """
    Evaluate the categorization model on test data.

    Args:
        test_data_path: Path to test.json
        output_path: Path to save results (optional)

    Returns:
        Evaluation results dictionary
    """
    print("Loading test data...")
    with open(test_data_path, 'r') as f:
        test_data = json.load(f)

    print(f"Loaded {len(test_data)} test samples")

    model = FileCategorizationModel()

    # Run predictions
    results = []
    correct = 0
    correct_subcategory = 0

    category_metrics = defaultdict(lambda: {'tp': 0, 'fp': 0, 'fn': 0})
    confusion_matrix = defaultdict(lambda: defaultdict(int))
    confidence_scores = []

    print("Running predictions...")
    for i, feature in enumerate(test_data):
        actual_category = feature.get('category', 'uncategorized')
        actual_subcategory = feature.get('subcategory', 'other')

        predicted_category, predicted_subcategory, confidence = model.predict_category(feature)

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

    # Calculate metrics
    accuracy = correct / len(test_data) if test_data else 0
    subcategory_accuracy = correct_subcategory / len(test_data) if test_data else 0
    avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0

    # Per-category metrics
    per_category_metrics = {}
    for category in category_metrics:
        tp = category_metrics[category]['tp']
        fp = category_metrics[category]['fp']
        fn = category_metrics[category]['fn']

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        per_category_metrics[category] = {
            'precision': round(precision, 4),
            'recall': round(recall, 4),
            'f1_score': round(f1, 4),
            'support': tp + fn
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
            'model': 'FileCategorizationModel v1.0'
        },
        'overall_metrics': {
            'accuracy': round(accuracy, 4),
            'subcategory_accuracy': round(subcategory_accuracy, 4),
            'avg_confidence': round(avg_confidence, 4),
            'total_correct': correct,
            'total_incorrect': len(test_data) - correct
        },
        'per_category_metrics': per_category_metrics,
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

    print(f"\nTimestamp: {evaluation['metadata']['timestamp']}")
    print(f"Test Samples: {evaluation['metadata']['test_samples']:,}")

    print("\n" + "-" * 40)
    print("OVERALL METRICS")
    print("-" * 40)
    metrics = evaluation['overall_metrics']
    print(f"  Category Accuracy:    {metrics['accuracy']:.2%}")
    print(f"  Subcategory Accuracy: {metrics['subcategory_accuracy']:.2%}")
    print(f"  Avg Confidence:       {metrics['avg_confidence']:.2%}")
    print(f"  Correct Predictions:  {metrics['total_correct']:,}")
    print(f"  Incorrect Predictions:{metrics['total_incorrect']:,}")

    print("\n" + "-" * 40)
    print("PER-CATEGORY METRICS")
    print("-" * 40)
    print(f"  {'Category':<25} {'Precision':>10} {'Recall':>10} {'F1':>10} {'Support':>10}")
    print("  " + "-" * 65)

    for category, m in sorted(evaluation['per_category_metrics'].items(),
                              key=lambda x: -x[1]['support']):
        print(f"  {category:<25} {m['precision']:>10.2%} {m['recall']:>10.2%} "
              f"{m['f1_score']:>10.2%} {m['support']:>10,}")

    print("\n" + "-" * 40)
    print("TOP MISCLASSIFICATIONS")
    print("-" * 40)
    for item in evaluation['top_misclassifications'][:5]:
        print(f"  {item['from']:>20} -> {item['to']:<20} ({item['count']:,} files)")

    print("\n" + "=" * 60)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Evaluate file categorization model')
    parser.add_argument('--test-data', '-t',
                        default='results/ml_data/test.json',
                        help='Path to test.json')
    parser.add_argument('--output', '-o',
                        default='results/model_evaluation.json',
                        help='Output path for results JSON')

    args = parser.parse_args()

    # Run evaluation
    evaluation = evaluate_model(args.test_data, args.output)

    # Print report
    print_report(evaluation)

    print(f"\nFull results saved to: {args.output}")


if __name__ == "__main__":
    main()
