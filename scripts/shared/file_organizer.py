"""Generic file organizer for managing file classification and movement."""

from pathlib import Path
from typing import Dict, List, Callable, Optional
from collections import defaultdict
import shutil
import json
from datetime import datetime

from shared.status import ProcessingStatus, update_stats_from_status
from shared.confidence_gate import check_confidence
from shared.file_ops import resolve_collision


class FileOrganizer:
    """
    Generic file organizer that works with any analyzer implementing
    analyze_image(image_path) -> dict with category, confidence, new_name, folder.

    Supports two organization modes:
    - 'folder': Move files to subdirectories based on category
    - 'in-place': Rename files in their original location
    """

    def __init__(
        self,
        analyzer,
        source_dir: Path,
        output_dir: Optional[Path] = None,
        dry_run: bool = True,
        find_images_fn: Optional[Callable] = None,
        mode: str = "folder",
    ):
        """
        Args:
            analyzer: Object with analyze_image(Path) -> dict method
            source_dir: Directory to scan for images
            output_dir: Directory for organized files (default: source_dir)
            dry_run: If True, simulate without moving files
            find_images_fn: Callable to find images (default: standard extensions)
            mode: 'folder' (default) moves to subdirs, 'in-place' renames in original location
        """
        self.analyzer = analyzer
        self.source_dir = Path(source_dir)
        self.output_dir = output_dir or self.source_dir
        self.dry_run = dry_run
        self.mode = mode
        self.results: List[Dict] = []
        self.stats: Dict[str, int] = defaultdict(int)

        if find_images_fn:
            self.find_images = find_images_fn
        else:
            self.find_images = self._default_find_images

    def _default_find_images(self) -> List[Path]:
        """Find all image files with standard extensions."""
        extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        images: list[Path] = []
        for ext in extensions:
            images.extend(self.source_dir.glob(f"*{ext}"))
            images.extend(self.source_dir.glob(f"*{ext.upper()}"))
        return sorted(images)

    def organize(self, limit: Optional[int] = None, min_confidence: float = 0.1) -> List[Dict]:
        """
        Organize all images by analyzing, gating, and moving.

        Args:
            limit: Maximum number of images to process
            min_confidence: Minimum confidence threshold for acceptance

        Returns:
            List of processing results
        """
        images = self.find_images()

        if limit:
            images = images[:limit]

        total = len(images)
        mode_str = "IN-PLACE" if self.mode == "in-place" else "FOLDER"
        print(f"\n{'='*60}")
        print(f"File Organizer ({mode_str})")
        print(f"{'='*60}")
        print(f"Source: {self.source_dir}")
        if self.mode == "folder":
            print(f"Output: {self.output_dir}")
        print(f"Images: {total}")
        print(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        print(f"{'='*60}\n")

        self.stats["total"] = total

        for i, image_path in enumerate(images, 1):
            print(f"[{i}/{total}] Processing: {image_path.name}")

            try:
                result = self.analyzer.analyze_image(image_path)

                # Check confidence gate
                gate = check_confidence(result["category"], result["confidence"], min_confidence)
                if not gate.accepted:
                    result["status"] = ProcessingStatus.LOW_CONFIDENCE
                    result["error"] = gate.reason
                    update_stats_from_status(self.stats, result["status"])
                    print(f"  ⊘ {gate.reason}")
                    self.results.append(result)
                    continue

                result["status"] = (
                    ProcessingStatus.RENAMED if not self.dry_run else ProcessingStatus.WOULD_RENAME
                )
                self.results.append(result)

                # Update stats
                self.stats["processed"] = self.stats.get("processed", 0) + 1
                if "folder" in result and self.mode == "folder":
                    self.stats[result["folder"]] = self.stats.get(result["folder"], 0) + 1

                # Show result
                conf_str = f"{result['confidence']*100:.1f}%"
                if self.mode == "folder":
                    folder = result.get("folder", "Uncategorized")
                    print(f"  → {folder}/{result['new_name']} ({conf_str})")
                else:
                    print(f"  → {result['new_name']} ({conf_str})")

                # Actually move/rename if not dry run
                if not self.dry_run:
                    if self.mode == "in-place":
                        self._rename_in_place(image_path, result)
                    else:
                        self._move_to_folder(image_path, result)

            except Exception as e:
                print(f"  ✗ Error: {e}")
                self.stats["errors"] = self.stats.get("errors", 0) + 1

        self.print_summary()
        return self.results

    def _rename_in_place(self, image_path: Path, result: Dict) -> None:
        """Rename file in its original location."""
        try:
            new_path = image_path.parent / result["new_name"]
            image_path.rename(new_path)
            self.stats["moved"] = self.stats.get("moved", 0) + 1
            update_stats_from_status(self.stats, result["status"])
        except FileExistsError:
            new_path = resolve_collision(new_path)
            result["new_name"] = new_path.name
            try:
                image_path.rename(new_path)
                self.stats["moved"] = self.stats.get("moved", 0) + 1
                update_stats_from_status(self.stats, result["status"])
            except Exception as e:
                result["error"] = str(e)
                result["status"] = ProcessingStatus.ERROR
                update_stats_from_status(self.stats, result["status"])
        except Exception as e:
            result["error"] = str(e)
            result["status"] = ProcessingStatus.ERROR
            update_stats_from_status(self.stats, result["status"])

    def _move_to_folder(self, image_path: Path, result: Dict) -> None:
        """Move file to folder-based organization."""
        try:
            dest_folder = Path(result["dest_folder"])
            dest_path = Path(result["dest_path"])
            dest_folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(image_path, dest_path)
            self.stats["moved"] = self.stats.get("moved", 0) + 1
            update_stats_from_status(self.stats, result["status"])
        except Exception as e:
            result["error"] = str(e)
            result["status"] = ProcessingStatus.ERROR
            update_stats_from_status(self.stats, result["status"])

    def print_summary(self):
        """Print organization summary."""
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        print(f"Total processed: {self.stats.get('processed', 0)}")

        if not self.dry_run:
            print(f"Files renamed: {self.stats.get('moved', 0)}")

        print(f"Errors: {self.stats.get('errors', 0)}")

        if self.mode == "folder":
            print("\nBy Category:")
            for key, count in sorted(self.stats.items()):
                if key not in ("processed", "moved", "errors", "total") and "/" in key:
                    print(f"  {key}: {count}")

    def save_results(self, output_file: Optional[Path] = None):
        """Save results to JSON file."""
        if output_file is None:
            output_file = self.output_dir / "organization_results.json"

        with open(output_file, "w") as f:
            json.dump(
                {
                    "timestamp": datetime.now().isoformat(),
                    "source_dir": str(self.source_dir),
                    "output_dir": str(self.output_dir),
                    "dry_run": self.dry_run,
                    "stats": dict(self.stats),
                    "results": self.results,
                },
                f,
                indent=2,
            )

        print(f"\nResults saved to: {output_file}")
