#!/usr/bin/env python3
"""
Content-Based Intelligent File Organizer using Schema.org metadata and OCR.

Organizes files based on their actual content rather than just file type.
Uses OCR to extract text from images and PDFs, then classifies by content.
"""

import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Shared filename-pattern classifier (single source of truth, lives in
# shared.filename_classifier and is consumed via ContentOrganizer). Re-export
# research helpers that the rest of this module and tests still reference by
# their original names.
from shared.filename_classifier import (  # noqa: E402,F401  (re-exported for tests)
    RESEARCH_CATEGORY,
    SCHOLARLY_ARTICLE_SCHEMA_TYPE,
    _detect_research_publisher,
)

# OCR (docTR via shared.ocr_classifier) and PDF imports.
# pypdf and PIL are imported here (even though extraction now lives in
# src.analyzers.text_extractor) so that OCR_AVAILABLE keeps gating the
# pipeline on the full dependency set, matching historical behavior.
try:
    import pypdf  # noqa: F401 — availability probe
    from PIL import Image  # noqa: F401 — availability probe
    from shared.file_ops import resolve_collision  # noqa: F401 — availability probe
    from shared.filename_utils import is_generic_filename  # noqa: F401 — availability probe
    from shared.ocr_classifier import OCR_AVAILABLE  # shared module-level flag; avoids duplicate probe
    from shared.status import ProcessingStatus  # noqa: F401 — availability probe

    # HEIC support
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:
        pass
except ImportError:
    OCR_AVAILABLE = False
    print("Warning: OCR libraries not available. Install python-doctr[torch], Pillow, pypdf")

# Add project root and src directory to path (portable)
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.analyzers.image_metadata import (  # noqa: E402
    METADATA_AVAILABLE,
    ImageMetadataParser,
)
from src.analyzers.text_extractor import (  # noqa: E402
    DOCX_AVAILABLE,
    EXCEL_AVAILABLE,
    TextExtractor,
)
from src.classifiers.content_classifier import ContentClassifier  # noqa: E402

# Classification layer (detect_file_category and friends) lives in
# ContentOrganizer; the thresholds are re-exported for tests that import them
# from this module.
from src.organizers.content_organizer import (  # noqa: E402,F401  (re-exported for tests)
    ContentOrganizer,
    _OCR_CONFIDENCE_THRESHOLD,
    _SCREENSHOT_OCR_KEYWORD_THRESHOLD,
)

# Pipeline layer (per-file processing + batch orchestration). Imported after
# the sys.path inserts above so the flat module aliases (storage.*, shared.*)
# resolve to the same module instances this script uses.
from src.pipeline import BatchProcessor, FileProcessor  # noqa: E402

if not DOCX_AVAILABLE:
    print("Warning: python-docx not available. Install python-docx")
if not EXCEL_AVAILABLE:
    print("Warning: openpyxl not available. Install openpyxl")
if not METADATA_AVAILABLE:
    print("Warning: Metadata libraries not available. Install piexif, geopy")

from rename_images import PHOTO_PROFILE, ImageAnalyzer  # noqa: E402

from analyzers.image_analyzer import ImageContentAnalyzer  # noqa: E402
from enrichment import MetadataEnricher  # noqa: E402
from integration import SchemaRegistry  # noqa: E402
from validator import SchemaValidator  # noqa: E402

# Graph storage imports
try:
    from storage.graph_store import GraphStore
    from storage.models import FileStatus  # noqa: F401 — availability probe

    GRAPH_STORE_AVAILABLE = True
except ImportError:
    GRAPH_STORE_AVAILABLE = False
    print("Warning: GraphStore not available. Database persistence disabled.")

# Cost tracking imports (optional - gracefully degrade if not available).
# CostTracker context managers live with the extraction/analysis code in
# src/analyzers; this module only needs the calculator itself.
try:
    from cost_roi_calculator import CostROICalculator

    COST_TRACKING_AVAILABLE = True
except ImportError:
    COST_TRACKING_AVAILABLE = False

# Error tracking imports (optional - gracefully degrade if not available).
# Only init_sentry is used (in main()); per-operation tracking helpers were
# never wired into the pipeline.
try:
    from error_tracking import init_sentry

    ERROR_TRACKING_AVAILABLE = True
except ImportError:
    ERROR_TRACKING_AVAILABLE = False

    def init_sentry(*args, **kwargs):
        return False


class ContentBasedFileOrganizer(ContentOrganizer):
    """Organize files based on content analysis using OCR.

    The classification layer (detect_file_category and its helper tiers,
    filename/filepath/game-asset/entity/media routing, unified CLIP+OCR
    scoring) is inherited from ``src.organizers.content_organizer
    .ContentOrganizer``; this subclass adds the production pipeline: schema
    generation/validation, graph-store persistence, image renaming, file
    moves, cost tracking, and reporting.
    """

    def __init__(
        self,
        base_path: str = None,
        organize_by_date: bool = False,
        organize_by_location: bool = False,
        enable_cost_tracking: bool = True,
        db_path: str = "results/file_organization.db",
    ):
        """
        Initialize the organizer.

        Args:
            base_path: Base path for organized files
            organize_by_date: If True, organize photos by date (Photos/2023/11/)
            organize_by_location: If True, organize photos by location when GPS data available
            enable_cost_tracking: If True, track costs and ROI for all features
            db_path: Path to SQLite database for persistent storage
        """
        base_path = Path(base_path or "~/Documents").expanduser()

        # Initialize cost tracking if available and enabled
        self.cost_calculator = None
        if enable_cost_tracking and COST_TRACKING_AVAILABLE:
            self.cost_calculator = CostROICalculator()
            print("✓ Cost tracking enabled")

        # Initialize graph store for persistent storage with canonical IDs
        self.graph_store = None
        if GRAPH_STORE_AVAILABLE and db_path:
            self.graph_store = GraphStore(db_path=db_path)
            print(f"✓ Graph store enabled ({db_path})")

        # Construct components in the historical order (their import-time and
        # construction side effects are load-bearing for stdout parity), then
        # hand the classification dependencies to ContentOrganizer.
        enricher = MetadataEnricher()
        self.validator = SchemaValidator()
        self.registry = SchemaRegistry()
        classifier = ContentClassifier()
        self.rename_analyzer = ImageAnalyzer(PHOTO_PROFILE)
        image_analyzer = ImageContentAnalyzer(cost_calculator=self.cost_calculator)
        metadata_parser = ImageMetadataParser(cost_calculator=self.cost_calculator)
        text_extractor = TextExtractor(cost_calculator=self.cost_calculator)

        # Classification layer (filepath patterns, category taxonomy,
        # game-asset keywords, per-file OCR/KIE state) is initialized by
        # ContentOrganizer.
        super().__init__(
            base_path=base_path,
            content_classifier=classifier,
            organize_by_date=organize_by_date,
            organize_by_location=organize_by_location,
            enable_cost_tracking=enable_cost_tracking,
            db_path=db_path,
            image_analyzer=image_analyzer,
            metadata_parser=metadata_parser,
            text_extractor=text_extractor,
            enricher=enricher,
            screenshot_content_classifier=self.rename_analyzer.content_classifier,
            ocr_available=OCR_AVAILABLE,
        )

        # Pipeline layer by composition: FileProcessor handles per-file schema
        # generation, moves, persistence, and reports; BatchProcessor handles
        # directory scanning and the batch loop (including CLIP/easyocr
        # pre-warm). Both call back into this organizer for classification
        # (should_skip_file, detect_file_category, get_destination_path,
        # generate_schema hooks) and the shared ``stats`` counter.
        self._file_processor = FileProcessor(
            base_path=base_path,
            db_path=None,  # graph_store is injected directly below
            cost_calculator=self.cost_calculator,
            graph_store=self.graph_store,
            enricher=enricher,
            validator=self.validator,
            registry=self.registry,
            rename_analyzer=self.rename_analyzer,
            organizer=self,
        )
        self._batch_processor = BatchProcessor(file_processor=self._file_processor)

        # Pipeline-specific state
        self.stats = defaultdict(int)

    def generate_schema(self, file_path: Path, schema_type: str, extracted_text: str = "") -> Dict:
        """Generate Schema.org metadata for a file with extracted content."""
        return self._file_processor.generate_schema(file_path, schema_type, extracted_text)

    def _persist_to_graph_store(
        self,
        file_path: Path,
        dest_path: Path,
        category: str,
        subcategory: str,
        schema: Dict,
        extracted_text: str,
        company_name: Optional[str],
        people_names: List[str],
        image_metadata: Optional[Dict],
        ocr_confidence: Optional[float] = None,
        detected_language: Optional[str] = None,
        kie_result=None,
    ) -> None:
        """Delegates to FileProcessor._persist_to_graph_store — see that method for parameter docs."""
        self._file_processor._persist_to_graph_store(
            file_path=file_path,
            dest_path=dest_path,
            category=category,
            subcategory=subcategory,
            schema=schema,
            extracted_text=extracted_text,
            company_name=company_name,
            people_names=people_names,
            image_metadata=image_metadata,
            ocr_confidence=ocr_confidence,
            detected_language=detected_language,
            kie_result=kie_result,
        )

    def _maybe_rename_image(self, file_path: Path, dry_run: bool) -> Path:
        """Rename generic image files using content analysis before sorting.

        When *not* dry-run, physically renames the file and returns the
        new path.  In dry-run mode the file stays on disk but the
        proposed new path is returned so that filename-pattern
        classification sees the descriptive name.  Callers that need to
        read file contents should use the original path stored in
        ``result['source']``.
        """
        return self._file_processor._maybe_rename_image(file_path, dry_run)

    def organize_file(self, file_path: Path, dry_run: bool = False, force: bool = False) -> Dict:
        """
        Organize a single file based on content.

        Args:
            file_path: Path to the file
            dry_run: If True, don't actually move files
            force: If True, re-organize even if already in correct location

        Returns:
            Dictionary with organization details
        """
        return self._file_processor.organize_file(file_path, dry_run=dry_run, force=force)

    def scan_directory(self, directory: Path) -> List[Path]:
        """Scan directory for files to organize."""
        return self._batch_processor.scan_directory(directory)

    def organize_directories(
        self, source_dirs: List[str], dry_run: bool = False, limit: int = None, force: bool = False
    ) -> Dict:
        """
        Organize files from multiple source directories.

        Args:
            source_dirs: List of directory paths to organize
            dry_run: If True, simulate organization without moving files
            limit: Maximum number of files to process (for testing)
            force: If True, re-organize files even if already in correct location

        Returns:
            Dictionary with organization results
        """
        return self._batch_processor.organize_directories(
            source_dirs, dry_run=dry_run, limit=limit, force=force
        )

    def print_summary(self, summary: Dict):
        """Print organization summary."""
        self._batch_processor.print_summary(summary)

    def _print_cost_summary(self):
        """Print cost and ROI summary from the cost calculator."""
        self._file_processor._print_cost_summary()

    def get_cost_report(self) -> Optional[Dict[str, Any]]:
        """
        Get the full cost and ROI report.

        Returns:
            Cost report dictionary or None if cost tracking is disabled
        """
        return self._file_processor.get_cost_report()

    def save_cost_report(self, output_path: str = None):
        """
        Save the cost report to a JSON file.

        Args:
            output_path: Path to save the report (auto-generated if None)
        """
        self._file_processor.save_cost_report(output_path)

    def save_report(self, summary: Dict, output_path: str = None):
        """Save detailed organization report to JSON."""
        self._file_processor.save_report(summary, output_path)


def run(args) -> None:
    """Typed entry point: organize by content from a parsed namespace.

    The namespace must carry the attributes defined by
    ``src.cli.add_content_arguments`` (the single source for this command's
    options, shared with the unified CLI).
    """
    # Initialize Sentry error tracking (before any other operations)
    if not args.no_sentry and ERROR_TRACKING_AVAILABLE:
        # Priority: CLI arg > FILE_SYSTEM_SENTRY_DSN > SENTRY_DSN
        sentry_dsn = (
            args.sentry_dsn
            or os.environ.get("FILE_SYSTEM_SENTRY_DSN")
            or os.environ.get("SENTRY_DSN")
        )
        if sentry_dsn:
            os.environ["SENTRY_DSN"] = sentry_dsn
        sentry_enabled = init_sentry()
        if sentry_enabled:
            print("✓ Sentry error tracking enabled")
    else:
        sentry_enabled = False

    # Run system health check
    if args.check_deps:
        from health_check import check_system

        check_system(verbose=True)
        return

    if not args.skip_health_check:
        from health_check import SystemHealthChecker

        checker = SystemHealthChecker().run_all_checks()
        checker.print_status()

    # Run migration if requested
    if args.run_migration:
        if GRAPH_STORE_AVAILABLE:
            from storage.migration import run_migration

            print(f"\n{'='*60}")
            print("Running ID Generation Migration")
            print(f"{'='*60}\n")
            run_migration(args.db_path)
            print("\nMigration complete. Canonical IDs have been generated for existing records.")
            return
        else:
            print("Error: GraphStore not available. Cannot run migration.")
            return

    # Create organizer with database path
    db_path = None if args.no_db else args.db_path
    organizer = ContentBasedFileOrganizer(
        base_path=args.base_path, enable_cost_tracking=not args.no_cost_tracking, db_path=db_path
    )

    # Organize directories
    summary = organizer.organize_directories(
        source_dirs=args.sources, dry_run=args.dry_run, limit=args.limit, force=args.force
    )

    # Print summary
    organizer.print_summary(summary)

    # Save reports
    if args.report or not args.dry_run:
        organizer.save_report(summary, args.report)

    # Save cost report if tracking was enabled
    if not args.no_cost_tracking and organizer.cost_calculator:
        organizer.save_cost_report(args.cost_report)

    # Update _site directory with latest HTML files
    if not args.dry_run:
        import subprocess
        from pathlib import Path

        script_path = Path(__file__).parent / "copy_to_site.sh"
        if script_path.exists():
            try:
                subprocess.run([str(script_path)], check=True, capture_output=True)
                print("\n✓ Updated _site directory with latest HTML files")
            except subprocess.CalledProcessError:
                print("\n⚠ Failed to update _site directory")


def main():
    """Standalone entry point (argument definitions shared with organize-files)."""
    import argparse

    from src.cli import add_content_arguments

    parser = argparse.ArgumentParser(
        description="Organize files by content using OCR and Schema.org metadata"
    )
    add_content_arguments(parser)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
