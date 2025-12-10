#!/usr/bin/env python3
"""
Integration module for applying correction feedback to the file organizer.

This module provides functions to:
1. Apply learned corrections before categorization
2. Integrate feedback patterns into the categorization logic
3. Generate correction suggestions from organization results
"""

import os
import json
from typing import Dict, List, Optional, Tuple
from correction_feedback import CorrectionFeedbackSystem


class FeedbackIntegration:
    """Integrates correction feedback with the file organizer."""

    def __init__(self, feedback_file: str = None):
        """Initialize the integration.

        Args:
            feedback_file: Path to corrections JSON file
        """
        self.feedback = CorrectionFeedbackSystem(feedback_file)
        self._cached_rules = None

    def get_cached_rules(self) -> Dict:
        """Get or compute cached rules."""
        if self._cached_rules is None:
            self._cached_rules = self.feedback.export_rules()
        return self._cached_rules

    def invalidate_cache(self):
        """Invalidate the cached rules (call after adding corrections)."""
        self._cached_rules = None

    def pre_categorize_check(
        self,
        file_path: str,
        filename: str,
        proposed_category: str,
        proposed_subcategory: str = None
    ) -> Tuple[str, str, float]:
        """Check if corrections suggest a different category.

        This should be called BEFORE final categorization to apply learned rules.

        Args:
            file_path: Path to the file
            filename: The filename
            proposed_category: Category the organizer wants to assign
            proposed_subcategory: Subcategory the organizer wants to assign

        Returns:
            Tuple of (final_category, final_subcategory, confidence)
            confidence is 1.0 for original proposal, <1.0 for suggestions
        """
        # First check if this exact file has a correction
        correction = self.feedback.check_file(file_path)
        if correction:
            return (
                correction["correct_category"],
                correction.get("correct_subcategory"),
                1.0  # Exact match has full confidence
            )

        # Check for pattern-based suggestions
        suggestion = self.feedback.get_suggestion(filename, proposed_category)
        if suggestion and suggestion["confidence"] >= 0.7:
            return (
                suggestion["suggested_category"],
                suggestion.get("suggested_subcategory") or proposed_subcategory,
                suggestion["confidence"]
            )

        # No correction needed
        return (proposed_category, proposed_subcategory, 1.0)

    def get_pattern_keywords(self) -> Dict[str, Dict]:
        """Get learned keyword patterns for each category.

        Returns keywords that should trigger specific categories based on
        correction feedback.

        Returns:
            Dictionary mapping categories to their learned keywords
        """
        rules = self.get_cached_rules()
        keywords = {}

        for rule in rules.get("pattern_rules", []):
            category = rule["category"]
            if category not in keywords:
                keywords[category] = {
                    "patterns": [],
                    "content_hints": []
                }

            pattern = rule["pattern"]
            # Convert pattern labels back to keywords
            if pattern.startswith("ext:"):
                keywords[category]["patterns"].append(f"extension:{pattern[4:]}")
            else:
                keywords[category]["patterns"].append(pattern)

        for rule in rules.get("content_rules", []):
            category = rule["category"]
            if category not in keywords:
                keywords[category] = {
                    "patterns": [],
                    "content_hints": []
                }
            keywords[category]["content_hints"].append(rule["hint"])

        return keywords

    def apply_to_organization_result(
        self,
        result: Dict,
        auto_apply: bool = False
    ) -> Dict:
        """Apply feedback suggestions to an organization result.

        Args:
            result: A single result from the organization report
            auto_apply: Whether to automatically apply high-confidence suggestions

        Returns:
            Modified result with feedback suggestions
        """
        filename = result.get("schema", {}).get("name") or os.path.basename(result.get("source", ""))
        current_category = result.get("category", "uncategorized")

        suggestion = self.feedback.get_suggestion(filename, current_category)

        if suggestion:
            result["feedback_suggestion"] = suggestion

            if auto_apply and suggestion["confidence"] >= 0.85:
                result["category"] = suggestion["suggested_category"]
                if suggestion.get("suggested_subcategory"):
                    result["subcategory"] = suggestion["suggested_subcategory"]
                result["feedback_applied"] = True

        return result

    def batch_apply_corrections(
        self,
        results: List[Dict],
        confidence_threshold: float = 0.85
    ) -> Tuple[List[Dict], Dict]:
        """Apply corrections to a batch of organization results.

        Args:
            results: List of organization results
            confidence_threshold: Minimum confidence to auto-apply

        Returns:
            Tuple of (modified_results, statistics)
        """
        modified = []
        stats = {
            "total": len(results),
            "suggestions_made": 0,
            "auto_applied": 0,
            "categories_changed": {}
        }

        for result in results:
            original_category = result.get("category")
            modified_result = self.apply_to_organization_result(
                result.copy(),
                auto_apply=confidence_threshold < 1.0
            )

            if "feedback_suggestion" in modified_result:
                stats["suggestions_made"] += 1

            if modified_result.get("feedback_applied"):
                stats["auto_applied"] += 1
                new_category = modified_result["category"]
                key = f"{original_category} -> {new_category}"
                stats["categories_changed"][key] = stats["categories_changed"].get(key, 0) + 1

            modified.append(modified_result)

        return modified, stats

    def generate_correction_report(self, results: List[Dict]) -> str:
        """Generate a report of suggested corrections from organization results.

        Args:
            results: List of organization results

        Returns:
            Markdown report string
        """
        suggestions = []

        for result in results:
            filename = result.get("schema", {}).get("name") or os.path.basename(result.get("source", ""))
            current_category = result.get("category", "uncategorized")

            suggestion = self.feedback.get_suggestion(filename, current_category)
            if suggestion:
                suggestions.append({
                    "filename": filename,
                    "current": current_category,
                    "suggested": suggestion["suggested_category"],
                    "confidence": suggestion["confidence"],
                    "patterns": suggestion["matching_patterns"]
                })

        if not suggestions:
            return "No correction suggestions based on learned patterns."

        report = "# Correction Suggestions Report\n\n"
        report += f"Found {len(suggestions)} files that may be miscategorized:\n\n"

        for s in sorted(suggestions, key=lambda x: -x["confidence"]):
            report += f"## {s['filename']}\n"
            report += f"- Current: `{s['current']}`\n"
            report += f"- Suggested: `{s['suggested']}`\n"
            report += f"- Confidence: {s['confidence']:.1%}\n"
            report += f"- Matching patterns: {', '.join(s['patterns'])}\n\n"

        return report


def integrate_with_organizer():
    """Print integration code for the file organizer."""
    print("""
# Add to scripts/file_organizer_content_based.py:

from feedback_integration import FeedbackIntegration

# Initialize at the top of the script
feedback_integration = FeedbackIntegration()

# In the categorize_file function, before returning:
def categorize_file_with_feedback(file_path, filename, category, subcategory):
    '''Apply feedback corrections to categorization.'''
    final_category, final_subcategory, confidence = feedback_integration.pre_categorize_check(
        file_path, filename, category, subcategory
    )

    if confidence < 1.0:
        print(f"  ℹ Feedback suggestion: {category} -> {final_category} ({confidence:.0%})")

    return final_category, final_subcategory

# Usage example:
# category, subcategory = determine_category(file_path, filename, content)
# category, subcategory = categorize_file_with_feedback(file_path, filename, category, subcategory)
""")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--integrate":
        integrate_with_organizer()
    else:
        # Demo
        integration = FeedbackIntegration()

        print("Feedback Integration System")
        print("=" * 50)

        stats = integration.feedback.get_statistics()
        print(f"\nCorrections recorded: {stats['total_corrections']}")
        print(f"Patterns learned: {stats['total_patterns_learned']}")

        rules = integration.get_cached_rules()
        if rules["pattern_rules"]:
            print(f"\nTop pattern rules:")
            for rule in rules["pattern_rules"][:5]:
                print(f"  {rule['pattern']} -> {rule['category']} ({rule['confidence']:.0%})")

        print("\nUsage:")
        print("  python scripts/feedback_integration.py --integrate  # Show integration code")
        print("  python scripts/correction_feedback.py add ...       # Add a correction")
        print("  python scripts/correction_feedback.py stats         # View statistics")
