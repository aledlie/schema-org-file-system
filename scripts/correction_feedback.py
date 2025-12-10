#!/usr/bin/env python3
"""
Correction Feedback System for File Organizer

Stores user corrections for miscategorized files in a persistent hashmap.
Uses file hashes to identify files and tracks correction patterns to improve
future categorization accuracy.

Structure:
{
    "corrections": {
        "<file_hash>": {
            "original_path": "/path/to/original/file.ext",
            "assigned_destination": "/path/to/wrong/destination/file.ext",
            "correct_destination": "/path/to/correct/destination/file.ext",
            "assigned_category": "wrong_category",
            "correct_category": "correct_category",
            "assigned_subcategory": "wrong_subcategory",
            "correct_subcategory": "correct_subcategory",
            "filename": "file.ext",
            "file_extension": ".ext",
            "correction_date": "2025-12-09T10:00:00",
            "correction_reason": "user description of why this was wrong",
            "filename_patterns": ["pattern1", "pattern2"],
            "content_hints": ["hint1", "hint2"]
        }
    },
    "category_rules": {
        "pattern -> category": count
    },
    "learned_patterns": {
        "filename_pattern": {
            "correct_category": "category",
            "correct_subcategory": "subcategory",
            "confidence": 0.95,
            "sample_count": 10
        }
    },
    "statistics": {
        "total_corrections": 100,
        "corrections_by_category": {"category": count},
        "most_common_mistakes": [{"from": "cat1", "to": "cat2", "count": 5}]
    }
}
"""

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from collections import defaultdict


class CorrectionFeedbackSystem:
    """Manages correction feedback for file categorization improvements."""

    def __init__(self, feedback_file: str = None):
        """Initialize the feedback system.

        Args:
            feedback_file: Path to the JSON file storing corrections.
                          Defaults to ~/.schema-org-file-system/corrections.json
        """
        if feedback_file is None:
            home = Path.home()
            config_dir = home / ".schema-org-file-system"
            config_dir.mkdir(exist_ok=True)
            feedback_file = str(config_dir / "corrections.json")

        self.feedback_file = feedback_file
        self.data = self._load_data()

    def _load_data(self) -> Dict:
        """Load existing corrections from file."""
        if os.path.exists(self.feedback_file):
            try:
                with open(self.feedback_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        return {
            "corrections": {},
            "category_rules": {},
            "learned_patterns": {},
            "statistics": {
                "total_corrections": 0,
                "corrections_by_category": {},
                "most_common_mistakes": []
            },
            "metadata": {
                "created": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "version": "1.0"
            }
        }

    def _save_data(self) -> None:
        """Save corrections to file."""
        self.data["metadata"]["last_updated"] = datetime.now().isoformat()
        with open(self.feedback_file, 'w') as f:
            json.dump(self.data, f, indent=2)

    @staticmethod
    def compute_file_hash(file_path: str) -> str:
        """Compute SHA-256 hash of a file.

        Args:
            file_path: Path to the file

        Returns:
            Hexadecimal hash string
        """
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                # Read in chunks for large files
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
        except (IOError, OSError):
            # Fallback to path-based hash if file can't be read
            return hashlib.sha256(file_path.encode()).hexdigest()

    @staticmethod
    def extract_filename_patterns(filename: str) -> List[str]:
        """Extract categorizable patterns from a filename.

        Args:
            filename: The filename to analyze

        Returns:
            List of patterns found
        """
        patterns = []
        name_lower = filename.lower()

        # Common patterns
        pattern_checks = [
            (r'^screenshot', 'screenshot_prefix'),
            (r'^img_', 'img_prefix'),
            (r'^pxl_', 'pixel_prefix'),
            (r'^dsc_', 'dsc_prefix'),
            (r'frame\d*', 'frame_pattern'),
            (r'sprite', 'sprite_keyword'),
            (r'texture', 'texture_keyword'),
            (r'audio|sound|sfx', 'audio_keyword'),
            (r'music|bgm|ost', 'music_keyword'),
            (r'icon', 'icon_keyword'),
            (r'button', 'button_keyword'),
            (r'tile', 'tile_keyword'),
            (r'wall|floor|door', 'environment_keyword'),
            (r'character|player|enemy', 'character_keyword'),
            (r'weapon|sword|bow|axe', 'weapon_keyword'),
            (r'item|potion|scroll', 'item_keyword'),
            (r'ui_|gui_|hud_', 'ui_prefix'),
            (r'\d{8}_\d{6}', 'timestamp_pattern'),
            (r'whatsapp', 'whatsapp_keyword'),
            (r'chatgpt', 'chatgpt_keyword'),
            (r'invoice|receipt', 'financial_keyword'),
            (r'contract|agreement', 'legal_keyword'),
            (r'resume|cv', 'employment_keyword'),
        ]

        for pattern, label in pattern_checks:
            if re.search(pattern, name_lower):
                patterns.append(label)

        # Extract file extension
        ext = Path(filename).suffix.lower()
        if ext:
            patterns.append(f"ext:{ext}")

        return patterns

    def add_correction(
        self,
        file_path: str,
        assigned_destination: str,
        correct_destination: str,
        assigned_category: str,
        correct_category: str,
        assigned_subcategory: str = None,
        correct_subcategory: str = None,
        correction_reason: str = None,
        content_hints: List[str] = None
    ) -> str:
        """Add a correction for a miscategorized file.

        Args:
            file_path: Original path of the file
            assigned_destination: Where the organizer put the file
            correct_destination: Where the file should have gone
            assigned_category: Category assigned by organizer
            correct_category: Correct category
            assigned_subcategory: Subcategory assigned by organizer
            correct_subcategory: Correct subcategory
            correction_reason: User's explanation of why this was wrong
            content_hints: Keywords from file content that should indicate correct category

        Returns:
            The file hash used as the key
        """
        # Compute file hash (use destination if original doesn't exist)
        if os.path.exists(assigned_destination):
            file_hash = self.compute_file_hash(assigned_destination)
        elif os.path.exists(file_path):
            file_hash = self.compute_file_hash(file_path)
        else:
            file_hash = hashlib.sha256(file_path.encode()).hexdigest()

        filename = os.path.basename(file_path)
        filename_patterns = self.extract_filename_patterns(filename)

        correction = {
            "original_path": file_path,
            "assigned_destination": assigned_destination,
            "correct_destination": correct_destination,
            "assigned_category": assigned_category,
            "correct_category": correct_category,
            "assigned_subcategory": assigned_subcategory,
            "correct_subcategory": correct_subcategory,
            "filename": filename,
            "file_extension": Path(filename).suffix.lower(),
            "correction_date": datetime.now().isoformat(),
            "correction_reason": correction_reason,
            "filename_patterns": filename_patterns,
            "content_hints": content_hints or []
        }

        self.data["corrections"][file_hash] = correction

        # Update statistics
        self._update_statistics(assigned_category, correct_category)

        # Update learned patterns
        self._update_learned_patterns(filename_patterns, correct_category, correct_subcategory)

        self._save_data()

        return file_hash

    def _update_statistics(self, assigned_category: str, correct_category: str) -> None:
        """Update correction statistics."""
        stats = self.data["statistics"]
        stats["total_corrections"] += 1

        # Track corrections by category
        if correct_category not in stats["corrections_by_category"]:
            stats["corrections_by_category"][correct_category] = 0
        stats["corrections_by_category"][correct_category] += 1

        # Track common mistakes
        mistake_key = f"{assigned_category} -> {correct_category}"
        found = False
        for mistake in stats["most_common_mistakes"]:
            if mistake["from"] == assigned_category and mistake["to"] == correct_category:
                mistake["count"] += 1
                found = True
                break

        if not found:
            stats["most_common_mistakes"].append({
                "from": assigned_category,
                "to": correct_category,
                "count": 1
            })

        # Sort by count
        stats["most_common_mistakes"].sort(key=lambda x: -x["count"])
        # Keep top 20
        stats["most_common_mistakes"] = stats["most_common_mistakes"][:20]

    def _update_learned_patterns(
        self,
        patterns: List[str],
        correct_category: str,
        correct_subcategory: str
    ) -> None:
        """Update learned patterns from corrections."""
        for pattern in patterns:
            if pattern not in self.data["learned_patterns"]:
                self.data["learned_patterns"][pattern] = {
                    "categories": {},
                    "subcategories": {}
                }

            learned = self.data["learned_patterns"][pattern]

            # Update category counts
            if correct_category not in learned["categories"]:
                learned["categories"][correct_category] = 0
            learned["categories"][correct_category] += 1

            # Update subcategory counts
            if correct_subcategory:
                if correct_subcategory not in learned["subcategories"]:
                    learned["subcategories"][correct_subcategory] = 0
                learned["subcategories"][correct_subcategory] += 1

    def get_suggestion(self, filename: str, current_category: str = None) -> Optional[Dict]:
        """Get a category suggestion based on learned patterns.

        Args:
            filename: The filename to check
            current_category: The currently assigned category

        Returns:
            Dictionary with suggested category and confidence, or None
        """
        patterns = self.extract_filename_patterns(filename)

        category_votes = defaultdict(float)
        subcategory_votes = defaultdict(float)

        for pattern in patterns:
            if pattern in self.data["learned_patterns"]:
                learned = self.data["learned_patterns"][pattern]

                # Weight by occurrence count
                for cat, count in learned["categories"].items():
                    category_votes[cat] += count

                for subcat, count in learned["subcategories"].items():
                    subcategory_votes[subcat] += count

        if not category_votes:
            return None

        # Find best category
        total_votes = sum(category_votes.values())
        best_category = max(category_votes.items(), key=lambda x: x[1])
        confidence = best_category[1] / total_votes if total_votes > 0 else 0

        # Find best subcategory
        best_subcategory = None
        if subcategory_votes:
            best_subcategory = max(subcategory_votes.items(), key=lambda x: x[1])[0]

        # Only suggest if confidence is above threshold and different from current
        if confidence >= 0.6 and best_category[0] != current_category:
            return {
                "suggested_category": best_category[0],
                "suggested_subcategory": best_subcategory,
                "confidence": round(confidence, 3),
                "matching_patterns": patterns,
                "sample_count": int(best_category[1])
            }

        return None

    def get_correction_by_hash(self, file_hash: str) -> Optional[Dict]:
        """Get a correction by file hash.

        Args:
            file_hash: The SHA-256 hash of the file

        Returns:
            The correction record or None
        """
        return self.data["corrections"].get(file_hash)

    def check_file(self, file_path: str) -> Optional[Dict]:
        """Check if a file has a correction recorded.

        Args:
            file_path: Path to the file

        Returns:
            The correction record if found, None otherwise
        """
        if os.path.exists(file_path):
            file_hash = self.compute_file_hash(file_path)
            return self.get_correction_by_hash(file_hash)
        return None

    def get_corrections_for_category(self, category: str) -> List[Dict]:
        """Get all corrections where files should have been in a category.

        Args:
            category: The correct category to filter by

        Returns:
            List of correction records
        """
        return [
            {**correction, "hash": hash_key}
            for hash_key, correction in self.data["corrections"].items()
            if correction["correct_category"] == category
        ]

    def get_mistake_patterns(self, from_category: str, to_category: str) -> List[Dict]:
        """Get corrections where files were miscategorized from one category to another.

        Args:
            from_category: The incorrectly assigned category
            to_category: The correct category

        Returns:
            List of correction records
        """
        return [
            {**correction, "hash": hash_key}
            for hash_key, correction in self.data["corrections"].items()
            if correction["assigned_category"] == from_category
            and correction["correct_category"] == to_category
        ]

    def export_rules(self) -> Dict:
        """Export learned rules for integration with the file organizer.

        Returns:
            Dictionary of rules that can be applied to improve categorization
        """
        rules = {
            "pattern_rules": [],
            "content_rules": [],
            "extension_rules": {}
        }

        # Extract high-confidence pattern rules
        for pattern, data in self.data["learned_patterns"].items():
            if data["categories"]:
                total = sum(data["categories"].values())
                best_cat = max(data["categories"].items(), key=lambda x: x[1])
                confidence = best_cat[1] / total

                if total >= 3 and confidence >= 0.7:
                    best_subcat = None
                    if data["subcategories"]:
                        best_subcat = max(data["subcategories"].items(), key=lambda x: x[1])[0]

                    rules["pattern_rules"].append({
                        "pattern": pattern,
                        "category": best_cat[0],
                        "subcategory": best_subcat,
                        "confidence": round(confidence, 3),
                        "sample_count": total
                    })

        # Sort by sample count
        rules["pattern_rules"].sort(key=lambda x: -x["sample_count"])

        # Extract content hint rules
        content_hints = defaultdict(lambda: defaultdict(int))
        for correction in self.data["corrections"].values():
            for hint in correction.get("content_hints", []):
                content_hints[hint][correction["correct_category"]] += 1

        for hint, categories in content_hints.items():
            total = sum(categories.values())
            best_cat = max(categories.items(), key=lambda x: x[1])
            confidence = best_cat[1] / total

            if total >= 2 and confidence >= 0.7:
                rules["content_rules"].append({
                    "hint": hint,
                    "category": best_cat[0],
                    "confidence": round(confidence, 3),
                    "sample_count": total
                })

        rules["content_rules"].sort(key=lambda x: -x["sample_count"])

        return rules

    def get_statistics(self) -> Dict:
        """Get correction statistics.

        Returns:
            Statistics dictionary
        """
        return {
            **self.data["statistics"],
            "total_patterns_learned": len(self.data["learned_patterns"]),
            "last_updated": self.data["metadata"]["last_updated"]
        }

    def remove_correction(self, file_hash: str) -> bool:
        """Remove a correction by hash.

        Args:
            file_hash: The hash of the correction to remove

        Returns:
            True if removed, False if not found
        """
        if file_hash in self.data["corrections"]:
            del self.data["corrections"][file_hash]
            self._save_data()
            return True
        return False

    def clear_all(self) -> None:
        """Clear all corrections (use with caution)."""
        self.data = {
            "corrections": {},
            "category_rules": {},
            "learned_patterns": {},
            "statistics": {
                "total_corrections": 0,
                "corrections_by_category": {},
                "most_common_mistakes": []
            },
            "metadata": {
                "created": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "version": "1.0"
            }
        }
        self._save_data()


# CLI Interface
def main():
    """Command-line interface for the correction feedback system."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Correction Feedback System for File Organizer"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Add correction
    add_parser = subparsers.add_parser("add", help="Add a correction")
    add_parser.add_argument("--file", required=True, help="Original file path")
    add_parser.add_argument("--assigned-dest", required=True, help="Where organizer put the file")
    add_parser.add_argument("--correct-dest", required=True, help="Correct destination")
    add_parser.add_argument("--assigned-cat", required=True, help="Assigned category")
    add_parser.add_argument("--correct-cat", required=True, help="Correct category")
    add_parser.add_argument("--assigned-subcat", help="Assigned subcategory")
    add_parser.add_argument("--correct-subcat", help="Correct subcategory")
    add_parser.add_argument("--reason", help="Why this was wrong")
    add_parser.add_argument("--hints", nargs="+", help="Content hints for correct category")

    # Check file
    check_parser = subparsers.add_parser("check", help="Check if a file has a correction")
    check_parser.add_argument("file", help="File path to check")

    # Get suggestion
    suggest_parser = subparsers.add_parser("suggest", help="Get category suggestion for a filename")
    suggest_parser.add_argument("filename", help="Filename to check")
    suggest_parser.add_argument("--current-cat", help="Current category")

    # Statistics
    subparsers.add_parser("stats", help="Show correction statistics")

    # Export rules
    subparsers.add_parser("export-rules", help="Export learned rules as JSON")

    # List corrections
    list_parser = subparsers.add_parser("list", help="List corrections")
    list_parser.add_argument("--category", help="Filter by correct category")
    list_parser.add_argument("--limit", type=int, default=20, help="Max results")

    args = parser.parse_args()

    system = CorrectionFeedbackSystem()

    if args.command == "add":
        file_hash = system.add_correction(
            file_path=args.file,
            assigned_destination=args.assigned_dest,
            correct_destination=args.correct_dest,
            assigned_category=args.assigned_cat,
            correct_category=args.correct_cat,
            assigned_subcategory=args.assigned_subcat,
            correct_subcategory=args.correct_subcat,
            correction_reason=args.reason,
            content_hints=args.hints
        )
        print(f"Correction added with hash: {file_hash}")

    elif args.command == "check":
        correction = system.check_file(args.file)
        if correction:
            print(json.dumps(correction, indent=2))
        else:
            print("No correction found for this file")

    elif args.command == "suggest":
        suggestion = system.get_suggestion(args.filename, args.current_cat)
        if suggestion:
            print(json.dumps(suggestion, indent=2))
        else:
            print("No suggestion available")

    elif args.command == "stats":
        stats = system.get_statistics()
        print(json.dumps(stats, indent=2))

    elif args.command == "export-rules":
        rules = system.export_rules()
        print(json.dumps(rules, indent=2))

    elif args.command == "list":
        if args.category:
            corrections = system.get_corrections_for_category(args.category)
        else:
            corrections = [
                {**c, "hash": h}
                for h, c in list(system.data["corrections"].items())[:args.limit]
            ]

        for c in corrections[:args.limit]:
            print(f"\n{c['hash'][:12]}...")
            print(f"  File: {c['filename']}")
            print(f"  {c['assigned_category']} -> {c['correct_category']}")
            if c.get('correction_reason'):
                print(f"  Reason: {c['correction_reason']}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
