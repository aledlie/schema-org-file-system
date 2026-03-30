"""FileProcessor: single-file organization and schema generation."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from src.generators import DocumentGenerator, ImageGenerator
from src.base import PropertyType
from src.enrichment import MetadataEnricher
from src.validator import SchemaValidator
from src.integration import SchemaRegistry

try:
    from src.storage.graph_store import GraphStore
    from src.storage.models import FileStatus
    GRAPH_STORE_AVAILABLE = True
except ImportError:
    GRAPH_STORE_AVAILABLE = False
    GraphStore = None  # type: ignore[assignment,misc]
    FileStatus = None  # type: ignore[assignment]

try:
    from src.cost_roi_calculator import CostROICalculator
    COST_TRACKING_AVAILABLE = True
except ImportError:
    COST_TRACKING_AVAILABLE = False
    CostROICalculator = None  # type: ignore[assignment,misc]


class FileProcessor:
    """
    Handles single-file organization, schema generation, DB persistence,
    and cost/report utilities.

    Args:
        base_path: Base path for organized files.
        dry_run: Default dry-run mode (can be overridden per call).
        db_path: SQLite DB path for GraphStore persistence.
        cost_calculator: Injected CostROICalculator instance (optional).
        graph_store: Injected GraphStore instance (optional).
        enricher: Injected MetadataEnricher (optional, created if None).
        validator: Injected SchemaValidator (optional, created if None).
        registry: Injected SchemaRegistry (optional, created if None).
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
    ) -> None:
        self.base_path = Path(base_path).expanduser()
        self.dry_run = dry_run

        self.cost_calculator = cost_calculator
        if self.cost_calculator is None and COST_TRACKING_AVAILABLE and CostROICalculator is not None:
            self.cost_calculator = CostROICalculator()

        self.graph_store = graph_store
        if self.graph_store is None and GRAPH_STORE_AVAILABLE and GraphStore is not None and db_path:
            self.graph_store = GraphStore(db_path=db_path)

        self.enricher = enricher if enricher is not None else MetadataEnricher()
        self.validator = validator if validator is not None else SchemaValidator()
        self.registry = registry if registry is not None else SchemaRegistry()

    def generate_schema(
        self,
        file_path: Path,
        schema_type: str,
        extracted_text: str = "",
    ) -> Dict[str, Any]:
        """Generate Schema.org metadata for a file with extracted content."""
        stats = file_path.stat()
        mime_type = self.enricher.detect_mime_type(str(file_path))
        file_url = f"https://localhost/files/{quote(file_path.name)}"
        actual_path = str(file_path.absolute())

        if schema_type == "ImageObject":
            generator: Any = ImageGenerator(schema_type)
            generator.set_basic_info(
                name=file_path.name,
                content_url=file_url,
                encoding_format=mime_type or "image/png",
                description=file_path.name,
            )
        elif schema_type in ("DigitalDocument", "Article"):
            generator = DocumentGenerator(schema_type)
            generator.set_basic_info(
                name=file_path.name,
                description=file_path.name,
            )
            generator.set_file_info(
                encoding_format=mime_type or "application/octet-stream",
                url=file_url,
                content_size=stats.st_size,
            )
        else:
            generator = DocumentGenerator()
            generator.set_basic_info(
                name=file_path.name,
                description=file_path.name,
            )

        try:
            generator.set_dates(
                created=datetime.fromtimestamp(stats.st_ctime),
                modified=datetime.fromtimestamp(stats.st_mtime),
            )
        except Exception:
            pass

        if extracted_text:
            try:
                text_preview = extracted_text[:1000] + ("..." if len(extracted_text) > 1000 else "")
                generator.set_property("abstract", text_preview, PropertyType.TEXT)
                generator.set_property("text", extracted_text[:5000], PropertyType.TEXT)
            except Exception:
                pass

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
    ) -> None:
        """Persist file and its entity relationships to the graph store."""
        if not self.graph_store:
            return
        try:
            session = self.graph_store.get_session()

            stat = file_path.stat() if file_path.exists() else dest_path.stat()

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
                status=FileStatus.ORGANIZED,
                organized_at=datetime.now(),
            )

            file_id = file_record.id

            self.graph_store.add_file_to_category(
                file_id=file_id,
                category_name=category,
                subcategory_name=subcategory,
                session=session,
            )

            if company_name:
                self.graph_store.add_file_to_company(
                    file_id=file_id,
                    company_name=company_name,
                    context="content_analysis",
                    session=session,
                )

            if people_names:
                for person_name in people_names:
                    self.graph_store.add_file_to_person(
                        file_id=file_id,
                        person_name=person_name,
                        role="mentioned",
                        session=session,
                    )

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
            print(f"  Warning: Graph store error (non-fatal): {e}")

    def organize_file(
        self,
        file_path: Path,
        dry_run: bool = False,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Organize a single file based on content.

        Requires ``_organizer`` to be set to a ContentBasedFileOrganizer instance.

        Args:
            file_path: Path to the file.
            dry_run: If True, don't actually move files.
            force: If True, re-organize even if already in correct location.

        Returns:
            Dictionary with organization details.
        """
        organizer = getattr(self, "_organizer", None)
        if organizer is None:
            raise RuntimeError(
                "FileProcessor._organizer is not set. "
                "Attach a ContentBasedFileOrganizer instance to _organizer before calling organize_file."
            )
        return organizer.organize_file(file_path, dry_run=dry_run, force=force)

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
