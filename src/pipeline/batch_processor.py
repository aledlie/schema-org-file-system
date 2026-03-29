"""BatchProcessor: directory scanning and multi-directory batch orchestration."""

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

_SEPARATOR = "=" * 60

_IMAGE_EXTENSIONS = frozenset({
  ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tiff", ".tif",
})

try:
  from shared.clip_cache import get_cached_embeddings_batch, CLIP_CACHE_AVAILABLE
  from shared.constants import CLIP_CONTENT_LABELS, CLIP_BATCH_SIZE
  _BATCH_PREWARM_AVAILABLE = CLIP_CACHE_AVAILABLE
except ImportError:
  _BATCH_PREWARM_AVAILABLE = False


class BatchProcessor:
    """
    Orchestrates batch file organization across one or more directories.

    Args:
        file_processor: Injected FileProcessor (or compatible organizer) instance.
    """

    def __init__(self, file_processor: Any) -> None:
        self.file_processor = file_processor

    @property
    def _effective_organizer(self) -> Any:
        """Return the underlying organizer, unwrapping FileProcessor._organizer if set."""
        return getattr(self.file_processor, "_organizer", self.file_processor)

    def scan_directory(self, directory: Path) -> List[Path]:
        """Scan directory recursively for organizable files."""
        files: List[Path] = []
        should_skip = getattr(self._effective_organizer, "should_skip_file", lambda p: False)
        try:
            for item in directory.rglob("*"):
                if item.is_file() and not should_skip(item):
                    files.append(item)
        except PermissionError:
            print(f"Permission denied: {directory}")
        return files

    def organize_directories(
        self,
        source_dirs: List[str],
        dry_run: bool = False,
        limit: Optional[int] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Organize files from multiple source directories.

        Args:
            source_dirs: List of directory paths to organize.
            dry_run: If True, simulate organization without moving files.
            limit: Maximum number of files to process (for testing).
            force: If True, re-organize files even if already in correct location.

        Returns:
            Dictionary with organization results.
        """
        results: List[Dict[str, Any]] = []

        print(f"\n{_SEPARATOR}")
        print(f"Content-Based File Organization {'(DRY RUN)' if dry_run else ''}")
        print(f"{_SEPARATOR}\n")

        organizer = self._effective_organizer
        ocr_available = getattr(organizer, "ocr_available", True)
        stats = getattr(organizer, "stats", defaultdict(int))
        registry = getattr(organizer, "registry", None)

        if not ocr_available:
            print("WARNING: OCR libraries not available")
            print("   Install with: pip install pytesseract Pillow pypdf pdf2image")
            print("   Content classification will be limited to filenames\n")

        all_files: List[Path] = []
        for source_dir in source_dirs:
            source_path = Path(source_dir).expanduser()
            if source_path.exists():
                print(f"Scanning: {source_path}")
                files = self.scan_directory(source_path)
                all_files.extend(files)
                print(f"  Found {len(files)} files")
            else:
                print(f"Directory not found: {source_path}")

        if limit:
            all_files = all_files[:limit]
            print(f"\nWARNING: Processing limited to first {limit} files for testing\n")

        print(f"\nTotal files to process: {len(all_files)}\n")

        if _BATCH_PREWARM_AVAILABLE:
            image_paths = [p for p in all_files if p.suffix.lower() in _IMAGE_EXTENSIONS]
            if image_paths:
                print(f"\nPre-warming CLIP cache: {len(image_paths)} images (batch={CLIP_BATCH_SIZE})")
                for chunk_start in range(0, len(image_paths), CLIP_BATCH_SIZE):
                    chunk = image_paths[chunk_start : chunk_start + CLIP_BATCH_SIZE]
                    get_cached_embeddings_batch(chunk, CLIP_CONTENT_LABELS)
                print("CLIP cache pre-warm complete\n")

        for i, file_path in enumerate(all_files, 1):
            print(f"[{i}/{len(all_files)}] Processing: {file_path.name}")
            result = self.file_processor.organize_file(file_path, dry_run=dry_run, force=force)
            results.append(result)

            if result["status"] in ("organized", "would_organize"):
                print(f"  -> {result['destination']}")
            elif result["status"] == "error":
                print(f"  Error: {result['reason']}")

        summary: Dict[str, Any] = {
            "total_files": len(all_files),
            "organized": stats["organized"],
            "already_organized": stats["already_organized"],
            "skipped": stats["skipped"],
            "errors": stats["errors"],
            "dry_run": dry_run,
            "results": results,
            "registry_stats": registry.get_statistics() if registry and not dry_run else None,
        }

        return summary

    def print_summary(self, summary: Dict[str, Any]) -> None:
        """Print organization summary."""
        print(f"\n{_SEPARATOR}")
        print("Organization Summary")
        print(f"{_SEPARATOR}\n")

        print(f"Total files processed: {summary['total_files']}")
        print(f"Successfully organized: {summary['organized']}")
        print(f"Already organized: {summary['already_organized']}")
        print(f"Skipped: {summary['skipped']}")
        print(f"Errors: {summary['errors']}")

        if summary["dry_run"]:
            print("\nWARNING: This was a DRY RUN - no files were moved")

        print(f"\n{_SEPARATOR}")
        print("Category Breakdown")
        print(f"{_SEPARATOR}\n")

        category_stats: Dict[str, int] = defaultdict(int)
        for result in summary["results"]:
            if result.get("category"):
                category_stats[result["category"]] += 1

        for category, count in sorted(category_stats.items()):
            print(f"{category.capitalize()}: {count} files")

        ocr_count = sum(1 for r in summary["results"] if r.get("extracted_text_length", 0) > 0)
        print(f"\n{_SEPARATOR}")
        print("Content Extraction Stats")
        print(f"{_SEPARATOR}\n")
        print(f"Files with extracted text: {ocr_count}/{summary['total_files']}")

        company_files = [r for r in summary["results"] if r.get("company_name")]
        if company_files:
            print(f"\n{_SEPARATOR}")
            print("Detected Companies")
            print(f"{_SEPARATOR}\n")
            company_counts: Dict[str, int] = defaultdict(int)
            for result in company_files:
                company_counts[result["company_name"]] += 1

            print(f"Total files with detected companies: {len(company_files)}")
            print("\nCompanies found:")
            for company, count in sorted(company_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"  {company}: {count} files")

        if summary.get("registry_stats"):
            print(f"\n{_SEPARATOR}")
            print("Schema Registry")
            print(f"{_SEPARATOR}\n")
            stats = summary["registry_stats"]
            print(f"Total schemas: {stats['total_schemas']}")
            print(f"Types: {', '.join(stats['types'])}")
