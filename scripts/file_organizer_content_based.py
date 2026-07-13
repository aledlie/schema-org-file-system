#!/usr/bin/env python3
"""
Content-Based Intelligent File Organizer using Schema.org metadata and OCR.

Organizes files based on their actual content rather than just file type.
Uses OCR to extract text from images and PDFs, then classifies by content.
"""

import json
import os
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

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
    from shared.file_ops import resolve_collision
    from shared.filename_utils import is_generic_filename
    from shared.ocr_classifier import is_ocr_available
    from shared.status import ProcessingStatus

    OCR_AVAILABLE = is_ocr_available()

    # HEIC support
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:
        pass
except ImportError:
    OCR_AVAILABLE = False
    print("Warning: OCR libraries not available. Install python-doctr[torch], Pillow, pypdf")

# KIE (Key Information Extraction) schema mapping (extraction itself lives in
# ContentOrganizer's classification layer).
try:
    from shared.kie_schema_mapping import kie_result_to_schema_org
except ImportError:
    kie_result_to_schema_org = None

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

if not DOCX_AVAILABLE:
    print("Warning: python-docx not available. Install python-docx")
if not EXCEL_AVAILABLE:
    print("Warning: openpyxl not available. Install openpyxl")
if not METADATA_AVAILABLE:
    print("Warning: Metadata libraries not available. Install piexif, geopy")

from rename_images import IMAGE_EXTENSIONS_WIDE, PHOTO_PROFILE, ImageAnalyzer  # noqa: E402

from analyzers.image_analyzer import ImageContentAnalyzer  # noqa: E402
from base import PropertyType  # noqa: E402
from enrichment import MetadataEnricher, cached_stat  # noqa: E402
from generators import DocumentGenerator, ImageGenerator  # noqa: E402
from integration import SchemaRegistry  # noqa: E402
from validator import SchemaValidator  # noqa: E402

# Graph storage imports
try:
    from storage.graph_store import GraphStore
    from storage.models import FileStatus

    GRAPH_STORE_AVAILABLE = True
except ImportError:
    GRAPH_STORE_AVAILABLE = False
    print("Warning: GraphStore not available. Database persistence disabled.")

# Cost tracking imports (optional - gracefully degrade if not available)
try:
    from cost_roi_calculator import CostROICalculator, CostTracker

    COST_TRACKING_AVAILABLE = True
except ImportError:
    COST_TRACKING_AVAILABLE = False

    # Provide stub implementations for graceful degradation
    class CostTracker:
        """Stub CostTracker when cost tracking is not available."""

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False


# Error tracking imports (optional - gracefully degrade if not available)
try:
    from error_tracking import (
        ErrorLevel,
        FileProcessingErrorTracker,
        capture_error,
        init_sentry,
        track_error,
        track_operation,
    )

    ERROR_TRACKING_AVAILABLE = True
except ImportError:
    ERROR_TRACKING_AVAILABLE = False

    # Stub implementations
    def init_sentry(*args, **kwargs):
        return False

    def capture_error(*args, **kwargs):
        pass

    def track_operation(*args, **kwargs):
        from contextlib import nullcontext

        return nullcontext()

    def track_error(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    class FileProcessingErrorTracker:
        def __init__(self):
            pass

        def track_file(self, *args, **kwargs):
            from contextlib import nullcontext

            return nullcontext()

        def print_summary(self):
            pass

        def get_stats(self):
            return {}

    class ErrorLevel:
        FATAL = "fatal"
        ERROR = "error"
        WARNING = "warning"
        INFO = "info"
        DEBUG = "debug"


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

        # Pipeline-specific state
        self.stats = defaultdict(int)

    def generate_schema(self, file_path: Path, schema_type: str, extracted_text: str = "") -> Dict:
        """Generate Schema.org metadata for a file with extracted content."""
        stats = cached_stat(str(file_path))
        mime_type = self.enricher.detect_mime_type(str(file_path))
        file_url = f"https://localhost/files/{quote(file_path.name)}"
        actual_path = str(file_path.absolute())

        # Create generator based on type
        if schema_type == "ImageObject":
            generator = ImageGenerator(schema_type)
            generator.set_property("name", file_path.name, PropertyType.TEXT)
            generator.set_property("contentUrl", file_url, PropertyType.URL)
            generator.set_property("encodingFormat", mime_type or "image/png", PropertyType.TEXT)
            generator.set_property("description", f"{file_path.name}", PropertyType.TEXT)
        elif schema_type in ["DigitalDocument", "Article", SCHOLARLY_ARTICLE_SCHEMA_TYPE, "Report"]:
            generator = DocumentGenerator(schema_type)
            generator.set_property("name", file_path.name, PropertyType.TEXT)
            generator.set_property("description", f"{file_path.name}", PropertyType.TEXT)
            generator.set_property(
                "encodingFormat", mime_type or "application/octet-stream", PropertyType.TEXT
            )
            generator.set_property("url", file_url, PropertyType.URL)
            generator.set_property("contentSize", f"{stats.st_size}B", PropertyType.TEXT)
            research = self._last_file_state.get("research")
            if schema_type == SCHOLARLY_ARTICLE_SCHEMA_TYPE and research:
                _publisher_key, identifier, publisher_name, canonical_url = research
                try:
                    generator.set_property("identifier", identifier, PropertyType.TEXT)
                    generator.set_property("sameAs", canonical_url, PropertyType.URL)
                    generator.set_property(
                        "publisher",
                        {"@type": "Organization", "name": publisher_name},
                        PropertyType.OBJECT,
                    )
                except Exception as e:
                    print(f"  Warning: could not attach scholarly metadata: {e}")
        else:
            generator = DocumentGenerator()
            generator.set_property("name", file_path.name, PropertyType.TEXT)
            generator.set_property("description", f"{file_path.name}", PropertyType.TEXT)

        # Set dates
        try:
            generator.set_dates(
                created=datetime.fromtimestamp(stats.st_ctime),
                modified=datetime.fromtimestamp(stats.st_mtime),
            )
        except Exception:
            pass

        # Add extracted text as abstract/text property
        if extracted_text:
            try:
                # Truncate to reasonable length for schema
                text_preview = extracted_text[:1000] + ("..." if len(extracted_text) > 1000 else "")
                generator.set_property("abstract", text_preview, PropertyType.TEXT)
                generator.set_property("text", extracted_text[:5000], PropertyType.TEXT)
            except Exception:
                pass

        # Add file path
        try:
            generator.set_property("filePath", actual_path, PropertyType.TEXT)
        except Exception:
            pass

        return generator.to_dict()

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
        """
        Persist file and its relationships to the graph store with canonical IDs.

        This method creates:
        - File record with canonical_id (urn:sha256:{hash})
        - Category record with canonical_id (UUID v5 from name)
        - Company record with canonical_id (UUID v5 from name)
        - Person records with canonical_id (UUID v5 from name)
        - Location record with canonical_id (UUID v5 from name)
        - Relationships between file and entities
        """
        try:
            session = self.graph_store.get_session()

            # Get file stats
            stat = (
                cached_stat(str(file_path)) if file_path.exists() else cached_stat(str(dest_path))
            )

            # Merge KIE-extracted Schema.org properties into schema dict.
            kie_fields_json = None
            if kie_result is not None:
                try:
                    kie_schema = kie_result_to_schema_org(kie_result)
                    # Merge KIE properties without overwriting existing keys.
                    for k, v in kie_schema.items():
                        if k not in schema or k == "@type":
                            schema[k] = v
                    # Serialize raw fields for debugging/reprocessing.
                    kie_fields_json = {
                        cls: [{"value": f.value, "confidence": f.confidence} for f in fields]
                        for cls, fields in kie_result.fields.items()
                    }
                except Exception:
                    pass  # KIE merge failure must not block persistence

            # Add file to store (generates canonical_id automatically)
            file_record = self.graph_store.add_file(
                original_path=str(file_path),
                filename=file_path.name,
                session=session,
                current_path=str(dest_path),
                file_size=stat.st_size,
                mime_type=schema.get("encodingFormat"),
                schema_type=schema.get("@type"),
                schema_data=schema,
                extracted_text=extracted_text[:10000] if extracted_text else None,
                extracted_text_length=len(extracted_text) if extracted_text else 0,
                ocr_confidence=ocr_confidence,
                detected_language=detected_language,
                kie_fields=kie_fields_json,
                status=FileStatus.ORGANIZED,
                organized_at=datetime.now(),
            )

            file_id = file_record.id

            # Add category relationship
            self.graph_store.add_file_to_category(
                file_id=file_id,
                category_name=category,
                subcategory_name=subcategory,
                session=session,
            )

            # Add company relationship if detected
            if company_name:
                self.graph_store.add_file_to_company(
                    file_id=file_id,
                    company_name=company_name,
                    context="content_analysis",
                    session=session,
                )

            # Add people relationships if detected
            if people_names:
                for person_name in people_names:
                    self.graph_store.add_file_to_person(
                        file_id=file_id, person_name=person_name, role="mentioned", session=session
                    )

            # Add location if available from image metadata
            if image_metadata and image_metadata.get("location"):
                location_info = image_metadata["location"]
                self.graph_store.add_file_to_location(
                    file_id=file_id,
                    location_name=location_info.get("display_name", "Unknown"),
                    latitude=location_info.get("latitude"),
                    longitude=location_info.get("longitude"),
                    city=location_info.get("city"),
                    state=location_info.get("state"),
                    country=location_info.get("country"),
                    location_type="captured_at",
                    session=session,
                )

            session.commit()
            session.close()

        except Exception as e:
            print(f"  ⚠ Graph store error (non-fatal): {e}")

    def _maybe_rename_image(self, file_path: Path, dry_run: bool) -> Path:
        """Rename generic image files using content analysis before sorting.

        When *not* dry-run, physically renames the file and returns the
        new path.  In dry-run mode the file stays on disk but the
        proposed new path is returned so that filename-pattern
        classification sees the descriptive name.  Callers that need to
        read file contents should use the original path stored in
        ``result['source']``.
        """
        if not is_generic_filename(file_path.name):
            return file_path

        if file_path.suffix.lower() not in IMAGE_EXTENSIONS_WIDE:
            return file_path

        result = self.rename_analyzer.analyze_image(file_path)

        new_name = result.get("new_name")
        if not new_name or result.get("status") != ProcessingStatus.PENDING:
            return file_path

        conf = result.get("confidence")
        conf_str = f" ({conf:.0%})" if conf is not None else ""
        new_path = resolve_collision(file_path.parent / new_name)

        if dry_run:
            print(f"  → Would rename: {file_path.name} → {new_path.name}{conf_str}")
            return new_path

        file_path.rename(new_path)
        print(f"  ✓ Renamed: {file_path.name} → {new_path.name}{conf_str}")
        return new_path

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
        result = {
            "source": str(file_path),
            "status": "skipped",
            "reason": None,
            "destination": None,
            "schema": None,
            "extracted_text_length": 0,
        }

        if self.should_skip_file(file_path):
            result["reason"] = "system_file"
            self.stats["skipped"] += 1
            return result

        if not file_path.is_file():
            result["reason"] = "not_file"
            self.stats["skipped"] += 1
            return result

        try:
            # Rename generic image files (screenshots, IMG_, etc.) before classification.
            # In dry-run the file stays on disk at file_path but renamed_path
            # carries the descriptive name for pattern matching.
            renamed_path = self._maybe_rename_image(file_path, dry_run)
            display_path = renamed_path if renamed_path != file_path else None
            physical_path = renamed_path if not dry_run else file_path

            # Detect category: physical_path for content reading,
            # display_path (renamed name) for filename-pattern matching.
            (
                category,
                subcategory,
                schema_type,
                extracted_text,
                company_name,
                people_names,
                image_metadata,
            ) = self.detect_file_category(physical_path, display_path=display_path)
            result["extracted_text_length"] = len(extracted_text)
            result["company_name"] = company_name
            result["people_names"] = people_names
            result["image_metadata"] = image_metadata

            # Handle skip category (duplicates, etc.)
            if category == "skip":
                result["status"] = "skipped"
                result["reason"] = subcategory  # e.g., 'duplicate'
                self.stats["skipped"] += 1
                return result

            # Generate schema with extracted content.
            # Use physical_path (current path on disk) since the file may have
            # been renamed by _maybe_rename_image before reaching this point.
            schema = self.generate_schema(physical_path, schema_type, extracted_text)

            # Validate schema
            validation_report = self.validator.validate(schema)

            # Get destination path (with optional date/location organization for images)
            # Use renamed_path so the destination carries the descriptive filename.
            dest_path = self.get_destination_path(
                renamed_path, category, subcategory, company_name, image_metadata, people_names
            )

            # Skip if already in the right place (unless force=True)
            if physical_path == dest_path and not force:
                result["status"] = "already_organized"
                result["destination"] = str(dest_path)
                result["schema"] = schema
                result["category"] = category
                result["subcategory"] = subcategory
                self.stats["already_organized"] += 1
                return result

            # Move file if not dry run
            if not dry_run:
                shutil.move(str(physical_path), str(dest_path))

                # Register schema
                schema["url"] = f"file://{dest_path.absolute()}"
                metadata = {
                    "category": category,
                    "subcategory": subcategory,
                    "organized_date": datetime.now().isoformat(),
                    "is_valid": validation_report.is_valid(),
                    "has_extracted_text": bool(extracted_text),
                }
                if company_name:
                    metadata["company_name"] = company_name

                self.registry.register(str(dest_path), schema, metadata=metadata)

                # Persist to database with canonical IDs
                if self.graph_store:
                    self._persist_to_graph_store(
                        file_path=file_path,
                        dest_path=dest_path,
                        category=category,
                        subcategory=subcategory,
                        schema=schema,
                        extracted_text=extracted_text,
                        company_name=company_name,
                        people_names=people_names,
                        image_metadata=image_metadata,
                        ocr_confidence=self._last_file_ocr_confidence,
                        detected_language=self._last_file_detected_language,
                        kie_result=self._last_file_state.get("kie_result"),
                    )

            result["status"] = "organized" if not dry_run else "would_organize"
            result["destination"] = str(dest_path)
            result["schema"] = schema
            result["category"] = category
            result["subcategory"] = subcategory
            result["is_valid"] = validation_report.is_valid()

            self.stats["organized"] += 1
            self.stats[f"{category}_{subcategory}"] += 1

        except Exception as e:
            result["status"] = "error"
            result["reason"] = str(e)
            self.stats["errors"] += 1
            print(f"  ✗ Error: {e}")

        return result

    def scan_directory(self, directory: Path) -> List[Path]:
        """Scan directory for files to organize."""
        files = []
        try:
            for item in directory.rglob("*"):
                if item.is_file() and not self.should_skip_file(item):
                    files.append(item)
        except PermissionError:
            print(f"Permission denied: {directory}")
        return files

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
        results = []

        print(f"\n{'='*60}")
        print(f"Content-Based File Organization {'(DRY RUN)' if dry_run else ''}")
        print(f"{'='*60}\n")

        if not self.ocr_available:
            print("⚠️  WARNING: OCR libraries not available")
            print("   Install with: pip install python-doctr[torch] Pillow pypdf")
            print("   Content classification will be limited to filenames\n")

        # Scan all directories
        all_files = []
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
            print(f"\n⚠️  Processing limited to first {limit} files for testing\n")

        print(f"\nTotal files to process: {len(all_files)}\n")

        # Organize each file
        for i, file_path in enumerate(all_files, 1):
            print(f"[{i}/{len(all_files)}] Processing: {file_path.name}")
            result = self.organize_file(file_path, dry_run=dry_run, force=force)
            results.append(result)

            if result["status"] == "organized" or result["status"] == "would_organize":
                print(f"  → {result['destination']}")
            elif result["status"] == "error":
                print(f"  ✗ Error: {result['reason']}")

        # Generate summary
        summary = {
            "total_files": len(all_files),
            "organized": self.stats["organized"],
            "already_organized": self.stats["already_organized"],
            "skipped": self.stats["skipped"],
            "errors": self.stats["errors"],
            "dry_run": dry_run,
            "results": results,
            "registry_stats": self.registry.get_statistics() if not dry_run else None,
        }

        return summary

    def print_summary(self, summary: Dict):
        """Print organization summary."""
        print(f"\n{'='*60}")
        print("Organization Summary")
        print(f"{'='*60}\n")

        print(f"Total files processed: {summary['total_files']}")
        print(f"Successfully organized: {summary['organized']}")
        print(f"Already organized: {summary['already_organized']}")
        print(f"Skipped: {summary['skipped']}")
        print(f"Errors: {summary['errors']}")

        if summary["dry_run"]:
            print("\n⚠️  This was a DRY RUN - no files were moved")

        # Category breakdown
        print(f"\n{'='*60}")
        print("Category Breakdown")
        print(f"{'='*60}\n")

        category_stats = defaultdict(int)
        for result in summary["results"]:
            if result.get("category"):
                category_stats[result["category"]] += 1

        for category, count in sorted(category_stats.items()):
            print(f"{category.capitalize()}: {count} files")

        # OCR stats
        ocr_count = sum(1 for r in summary["results"] if r.get("extracted_text_length", 0) > 0)
        print(f"\n{'='*60}")
        print("Content Extraction Stats")
        print(f"{'='*60}\n")
        print(f"Files with extracted text: {ocr_count}/{summary['total_files']}")

        # Company detection stats
        company_files = [r for r in summary["results"] if r.get("company_name")]
        if company_files:
            print(f"\n{'='*60}")
            print("Detected Companies")
            print(f"{'='*60}\n")
            company_counts = defaultdict(int)
            for result in company_files:
                company_counts[result["company_name"]] += 1

            print(f"Total files with detected companies: {len(company_files)}")
            print("\nCompanies found:")
            for company, count in sorted(company_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"  {company}: {count} files")

        if summary.get("registry_stats"):
            print(f"\n{'='*60}")
            print("Schema Registry")
            print(f"{'='*60}\n")
            stats = summary["registry_stats"]
            print(f"Total schemas: {stats['total_schemas']}")
            print(f"Types: {', '.join(stats['types'])}")

        # Cost tracking summary
        if self.cost_calculator:
            self._print_cost_summary()

    def _print_cost_summary(self):
        """Print cost and ROI summary from the cost calculator."""
        if not self.cost_calculator:
            return

        print(f"\n{'='*60}")
        print("Cost & ROI Analysis")
        print(f"{'='*60}\n")

        cost_summary = self.cost_calculator.calculate_total_cost()
        roi_summary = self.cost_calculator.calculate_total_roi()

        print(f"Total Processing Cost:     ${cost_summary['total_cost']:.4f}")
        print(f"Total Files Processed:     {cost_summary['total_files_processed']:,}")
        print(f"Avg Cost per File:         ${cost_summary['avg_cost_per_file']:.6f}")
        print(f"Total Processing Time:     {cost_summary['total_processing_time_sec']:.1f}s")

        print(f"\nEstimated Value Generated: ${roi_summary['total_value']:.2f}")
        roi_pct = roi_summary["overall_roi_percentage"]
        roi_str = f"{roi_pct:.0f}%" if roi_pct != float("inf") else "∞"
        print(f"Overall ROI:               {roi_str}")
        print(f"Manual Hours Saved:        {roi_summary['total_manual_hours_saved']:.1f} hours")

        # Per-feature breakdown (top 5 by usage)
        feature_costs = cost_summary.get("feature_breakdown", {})
        if feature_costs:
            print(f"\n{'Feature':<25} {'Cost':>10} {'Files':>10}")
            print("-" * 50)
            sorted_features = sorted(
                feature_costs.items(), key=lambda x: x[1]["total_files_processed"], reverse=True
            )
            for feature_name, data in sorted_features[:7]:
                if data["total_invocations"] > 0:
                    print(
                        f"{feature_name:<25} ${data['total_cost']:>9.4f} {data['total_files_processed']:>10,}"  # noqa: E501
                    )

        # Show recommendations if any critical issues
        recommendations = self.cost_calculator.get_optimization_recommendations()
        critical_recs = [r for r in recommendations if r["severity"] in ("critical", "high")]
        if critical_recs:
            print("\n⚠️  Optimization Recommendations:")
            for rec in critical_recs[:3]:
                print(f"   • {rec['message']}")

    def get_cost_report(self) -> Optional[Dict[str, Any]]:
        """
        Get the full cost and ROI report.

        Returns:
            Cost report dictionary or None if cost tracking is disabled
        """
        if not self.cost_calculator:
            return None
        return self.cost_calculator.generate_report()

    def save_cost_report(self, output_path: str = None):
        """
        Save the cost report to a JSON file.

        Args:
            output_path: Path to save the report (auto-generated if None)
        """
        if not self.cost_calculator:
            print("Cost tracking is not enabled")
            return

        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"results/cost_report_{timestamp}.json"

        self.cost_calculator.generate_report(output_path)
        print(f"Cost report saved to: {output_path}")

    def save_report(self, summary: Dict, output_path: str = None):
        """Save detailed organization report to JSON."""
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"results/content_organization_report_{timestamp}.json"

        with open(output_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)

        print(f"\nDetailed report saved to: {output_path}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Organize files by content using OCR and Schema.org metadata"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Simulate organization without moving files"
    )
    parser.add_argument(
        "--base-path",
        default="~/Documents",
        help="Base path for organized files (default: ~/Documents)",
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        default=["~/Desktop", "~/Downloads"],
        help="Source directories to organize (default: ~/Desktop ~/Downloads)",
    )
    parser.add_argument("--report", help="Path to save detailed JSON report")
    parser.add_argument("--limit", type=int, help="Limit number of files to process (for testing)")
    parser.add_argument(
        "--no-cost-tracking", action="store_true", help="Disable cost and ROI tracking"
    )
    parser.add_argument(
        "--cost-report",
        nargs="?",
        const="results/cost_report.json",
        default="results/cost_report.json",
        help=(
            "Path to save cost/ROI report (default: results/cost_report.json, "
            "use --no-cost-tracking to disable)"
        ),
    )
    parser.add_argument(
        "--check-deps",
        action="store_true",
        help="Run system health check and show feature availability",
    )
    parser.add_argument(
        "--skip-health-check", action="store_true", help="Skip startup health check"
    )
    parser.add_argument(
        "--sentry-dsn", help="Sentry DSN for error tracking (or set SENTRY_DSN env var)"
    )
    parser.add_argument("--no-sentry", action="store_true", help="Disable Sentry error tracking")
    parser.add_argument(
        "--db-path",
        default="results/file_organization.db",
        help=(
            "Path to SQLite database for persistent storage "
            "(default: results/file_organization.db)"
        ),
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Disable database persistence (use in-memory registry only)",
    )
    parser.add_argument(
        "--run-migration",
        action="store_true",
        help="Run database migration to add canonical_id columns to existing records",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-organization of all files, even if already in correct location",
    )

    args = parser.parse_args()

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


if __name__ == "__main__":
    main()
