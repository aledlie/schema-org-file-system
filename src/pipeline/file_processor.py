"""FileProcessor: single-file organization and schema generation."""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from src.generators import DocumentGenerator, ImageGenerator
from src.base import PropertyType
from src.enrichment import MetadataEnricher, cached_stat
from src.validator import SchemaValidator
from src.integration import SchemaRegistry

# Storage imports: prefer the flat modules (``storage.*``) so that, when driven
# by the production script (which puts both the project root and ``src/`` on
# sys.path and builds its GraphStore from the flat module), the FileStatus enum
# passed to ``GraphStore.add_file`` is the *same class* the store's SQLEnum
# column was declared with. Fall back to the package-qualified path for
# contexts that only have the project root on sys.path.
try:
    from storage.graph_store import GraphStore
    from storage.models import FileStatus
    GRAPH_STORE_AVAILABLE = True
except ImportError:
    try:
        from src.storage.graph_store import GraphStore
        from src.storage.models import FileStatus
        GRAPH_STORE_AVAILABLE = True
    except ImportError:
        GRAPH_STORE_AVAILABLE = False
        GraphStore = None  # type: ignore[assignment,misc]
        FileStatus = None  # type: ignore[assignment]

# Research-paper schema type (shared with the filename classifier). Falls back
# to the literal when scripts/shared is not importable.
try:
    from shared.filename_classifier import SCHOLARLY_ARTICLE_SCHEMA_TYPE
except ImportError:
    SCHOLARLY_ARTICLE_SCHEMA_TYPE = "ScholarlyArticle"

# KIE (Key Information Extraction) schema mapping for graph-store persistence.
try:
    from shared.kie_schema_mapping import kie_result_to_schema_org
except ImportError:
    kie_result_to_schema_org = None  # type: ignore[assignment]

# Image-rename support (generic screenshot/IMG_ filenames renamed by content
# analysis before classification). Requires scripts/shared on sys.path.
try:
    from shared.constants import IMAGE_EXTENSIONS_WIDE
    from shared.file_ops import resolve_collision
    from shared.filename_utils import is_generic_filename
    from shared.status import ProcessingStatus
    _RENAME_SUPPORT_AVAILABLE = True
except ImportError:
    _RENAME_SUPPORT_AVAILABLE = False


class FileProcessor:
    """
    Handles single-file organization, schema generation, DB persistence,
    and cost/report utilities.

    Classification is delegated back to the injected ``organizer`` (a
    ``ContentOrganizer``/``ContentBasedFileOrganizer``): ``should_skip_file``,
    ``detect_file_category``, ``get_destination_path``, ``generate_schema``,
    per-file OCR/KIE state, and the ``stats`` counter all live there.

    Args:
        base_path: Base path for organized files.
        dry_run: Default dry-run mode (can be overridden per call).
        db_path: SQLite DB path for GraphStore persistence (used only when no
            graph_store instance is injected).
        cost_calculator: Injected CostROICalculator instance (optional).
        graph_store: Injected GraphStore instance (optional).
        enricher: Injected MetadataEnricher (optional, created if None).
        validator: Injected SchemaValidator (optional, created if None).
        registry: Injected SchemaRegistry (optional, created if None).
        rename_analyzer: Injected ImageAnalyzer used by ``_maybe_rename_image``
            (optional; renaming is skipped when None).
        organizer: The organizer this processor calls back into for
            classification. May also be attached later via ``_organizer``.
    """

    def __init__(
        self,
        base_path: Path,
        dry_run: bool = False,
        db_path: Optional[str] = None,
        cost_calculator: Optional[Any] = None,
        graph_store: Optional[Any] = None,
        enricher: Optional[Any] = None,
        validator: Optional[Any] = None,
        registry: Optional[Any] = None,
        rename_analyzer: Optional[Any] = None,
        organizer: Optional[Any] = None,
    ) -> None:
        self.base_path = Path(base_path).expanduser()
        self.dry_run = dry_run

        self.cost_calculator = cost_calculator

        self.graph_store = graph_store
        if self.graph_store is None and GRAPH_STORE_AVAILABLE and GraphStore is not None and db_path:
            self.graph_store = GraphStore(db_path=db_path)

        self.enricher = enricher if enricher is not None else MetadataEnricher()
        self.validator = validator if validator is not None else SchemaValidator()
        self.registry = registry if registry is not None else SchemaRegistry()
        self.rename_analyzer = rename_analyzer
        self._organizer = organizer

    def generate_schema(
        self,
        file_path: Path,
        schema_type: str,
        extracted_text: str = "",
    ) -> Dict[str, Any]:
        """Generate Schema.org metadata for a file with extracted content."""
        stats = cached_stat(str(file_path))
        mime_type = self.enricher.detect_mime_type(str(file_path))
        file_url = f"https://localhost/files/{quote(file_path.name)}"
        actual_path = str(file_path.absolute())

        # Create generator based on type
        if schema_type == "ImageObject":
            generator: Any = ImageGenerator(schema_type)
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
            research = None
            if self._organizer is not None:
                research = getattr(self._organizer, "_last_file_state", {}).get("research")
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
        schema: Dict[str, Any],
        extracted_text: str,
        company_name: Optional[str],
        people_names: List[str],
        image_metadata: Optional[Dict[str, Any]],
        ocr_confidence: Optional[float] = None,
        detected_language: Optional[str] = None,
        kie_result: Any = None,
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
        if not self.graph_store:
            return
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
        if self.rename_analyzer is None or not _RENAME_SUPPORT_AVAILABLE:
            return file_path

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

    def organize_file(
        self,
        file_path: Path,
        dry_run: bool = False,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Organize a single file based on content.

        Requires ``_organizer`` to be set (constructor ``organizer=`` or
        attached afterwards): classification and destination routing are
        delegated to it.

        Args:
            file_path: Path to the file.
            dry_run: If True, don't actually move files.
            force: If True, re-organize even if already in correct location.

        Returns:
            Dictionary with organization details.
        """
        organizer = self._organizer
        if organizer is None:
            raise RuntimeError(
                "FileProcessor._organizer is not set. "
                "Attach a ContentBasedFileOrganizer instance to _organizer before calling organize_file."
            )

        result = {
            "source": str(file_path),
            "status": "skipped",
            "reason": None,
            "destination": None,
            "schema": None,
            "extracted_text_length": 0,
        }

        if organizer.should_skip_file(file_path):
            result["reason"] = "system_file"
            organizer.stats["skipped"] += 1
            return result

        if not file_path.is_file():
            result["reason"] = "not_file"
            organizer.stats["skipped"] += 1
            return result

        try:
            # Rename generic image files (screenshots, IMG_, etc.) before classification.
            # In dry-run the file stays on disk at file_path but renamed_path
            # carries the descriptive name for pattern matching.
            renamed_path = organizer._maybe_rename_image(file_path, dry_run)
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
            ) = organizer.detect_file_category(physical_path, display_path=display_path)
            result["extracted_text_length"] = len(extracted_text)
            result["company_name"] = company_name
            result["people_names"] = people_names
            result["image_metadata"] = image_metadata

            # Handle skip category (duplicates, etc.)
            if category == "skip":
                result["status"] = "skipped"
                result["reason"] = subcategory  # e.g., 'duplicate'
                organizer.stats["skipped"] += 1
                return result

            # Generate schema with extracted content.
            # Use physical_path (current path on disk) since the file may have
            # been renamed by _maybe_rename_image before reaching this point.
            schema = organizer.generate_schema(physical_path, schema_type, extracted_text)

            # Validate schema
            validation_report = self.validator.validate(schema)

            # Get destination path (with optional date/location organization for images)
            # Use renamed_path so the destination carries the descriptive filename.
            dest_path = organizer.get_destination_path(
                renamed_path, category, subcategory, company_name, image_metadata, people_names
            )

            # Skip if already in the right place (unless force=True)
            if physical_path == dest_path and not force:
                result["status"] = "already_organized"
                result["destination"] = str(dest_path)
                result["schema"] = schema
                result["category"] = category
                result["subcategory"] = subcategory
                organizer.stats["already_organized"] += 1
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
                    organizer._persist_to_graph_store(
                        file_path=file_path,
                        dest_path=dest_path,
                        category=category,
                        subcategory=subcategory,
                        schema=schema,
                        extracted_text=extracted_text,
                        company_name=company_name,
                        people_names=people_names,
                        image_metadata=image_metadata,
                        ocr_confidence=organizer._last_file_ocr_confidence,
                        detected_language=organizer._last_file_detected_language,
                        kie_result=organizer._last_file_state.get("kie_result"),
                    )

            result["status"] = "organized" if not dry_run else "would_organize"
            result["destination"] = str(dest_path)
            result["schema"] = schema
            result["category"] = category
            result["subcategory"] = subcategory
            result["is_valid"] = validation_report.is_valid()

            organizer.stats["organized"] += 1
            organizer.stats[f"{category}_{subcategory}"] += 1

        except Exception as e:
            result["status"] = "error"
            result["reason"] = str(e)
            organizer.stats["errors"] += 1
            print(f"  ✗ Error: {e}")

        return result

    def _print_cost_summary(self) -> None:
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
            Cost report dictionary or None if cost tracking is disabled.
        """
        if not self.cost_calculator:
            return None
        return self.cost_calculator.generate_report()

    def save_cost_report(self, output_path: Optional[str] = None) -> None:
        """
        Save the cost report to a JSON file.

        Args:
            output_path: Path to save the report (auto-generated if None).
        """
        if not self.cost_calculator:
            print("Cost tracking is not enabled")
            return

        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"results/cost_report_{timestamp}.json"

        self.cost_calculator.generate_report(output_path)
        print(f"Cost report saved to: {output_path}")

    def save_report(self, summary: Dict[str, Any], output_path: Optional[str] = None) -> None:
        """Save detailed organization report to JSON."""
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"results/content_organization_report_{timestamp}.json"

        with open(output_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)

        print(f"\nDetailed report saved to: {output_path}")
