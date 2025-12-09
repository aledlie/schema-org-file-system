#!/usr/bin/env python3
"""
Cost and ROI Calculator for Schema.org File Organization System

Calculates per-feature and per-model costs with ROI metrics.
Tracks usage, estimates costs, and provides optimization recommendations.
"""

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import defaultdict


class CostType(Enum):
    """Types of costs tracked."""
    COMPUTE = "compute"      # CPU/GPU processing time
    API_CALL = "api_call"    # External API calls
    STORAGE = "storage"      # File storage costs
    MEMORY = "memory"        # RAM usage


@dataclass
class ModelCostConfig:
    """Cost configuration for a specific model/feature."""
    name: str
    cost_type: CostType
    cost_per_unit: float           # Cost per invocation or per second
    unit_type: str                 # "invocation", "second", "mb", etc.
    avg_processing_time_sec: float # Average time per file
    success_rate: float = 1.0      # Expected success rate (0-1)
    description: str = ""

    # Value metrics (for ROI calculation)
    files_correctly_classified: float = 0.0  # Average files correctly classified per use
    manual_time_saved_sec: float = 0.0       # Manual time saved per use


@dataclass
class UsageRecord:
    """Record of a single feature/model usage."""
    feature_name: str
    timestamp: datetime
    processing_time_sec: float
    files_processed: int
    success: bool
    error_message: Optional[str] = None
    input_file_size_bytes: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CostSummary:
    """Summary of costs for a feature."""
    feature_name: str
    total_invocations: int
    total_processing_time_sec: float
    total_cost: float
    avg_cost_per_file: float
    success_rate: float
    total_files_processed: int


@dataclass
class ROIMetrics:
    """ROI metrics for a feature."""
    feature_name: str
    total_cost: float
    total_value: float  # Estimated value generated
    roi_percentage: float
    manual_hours_saved: float
    cost_per_file: float
    value_per_file: float
    break_even_files: int  # Files needed to break even


class CostROICalculator:
    """
    Calculates costs and ROI for the file organization system.

    Tracks usage of each feature/model and provides cost analysis
    with ROI calculations based on manual time saved.
    """

    # Default cost configurations based on 2024/2025 pricing
    DEFAULT_COST_CONFIGS = {
        # AI Vision (CLIP Model)
        "clip_vision": ModelCostConfig(
            name="CLIP Vision Model",
            cost_type=CostType.COMPUTE,
            cost_per_unit=0.0001,          # ~$0.0001 per inference (local GPU)
            unit_type="invocation",
            avg_processing_time_sec=2.5,   # 2-3 seconds per image
            success_rate=0.95,
            description="OpenAI CLIP model for image content classification",
            files_correctly_classified=0.85,
            manual_time_saved_sec=30.0     # 30 sec to manually classify an image
        ),

        # OCR (Tesseract)
        "tesseract_ocr": ModelCostConfig(
            name="Tesseract OCR",
            cost_type=CostType.COMPUTE,
            cost_per_unit=0.00001,         # Very low cost (local processing)
            unit_type="invocation",
            avg_processing_time_sec=1.5,   # 1-2 seconds per image
            success_rate=0.90,
            description="Tesseract OCR for text extraction",
            files_correctly_classified=0.75,
            manual_time_saved_sec=60.0     # 1 min to manually read/transcribe
        ),

        # Face Detection (OpenCV)
        "face_detection": ModelCostConfig(
            name="OpenCV Face Detection",
            cost_type=CostType.COMPUTE,
            cost_per_unit=0.000005,        # Very low cost
            unit_type="invocation",
            avg_processing_time_sec=0.5,   # Very fast
            success_rate=0.85,
            description="Haar cascade face detection",
            files_correctly_classified=0.80,
            manual_time_saved_sec=5.0      # Quick manual check
        ),

        # Geocoding (Nominatim API)
        "nominatim_geocoding": ModelCostConfig(
            name="Nominatim Geocoding",
            cost_type=CostType.API_CALL,
            cost_per_unit=0.0,             # Free API (rate limited)
            unit_type="invocation",
            avg_processing_time_sec=1.0,   # Network latency
            success_rate=0.75,             # May timeout or fail
            description="OpenStreetMap reverse geocoding",
            files_correctly_classified=0.90,
            manual_time_saved_sec=120.0    # 2 min to manually look up location
        ),

        # Keyword Classification (Rule-based)
        "keyword_classifier": ModelCostConfig(
            name="Keyword Classification",
            cost_type=CostType.COMPUTE,
            cost_per_unit=0.0,             # Essentially free
            unit_type="invocation",
            avg_processing_time_sec=0.001, # Instant
            success_rate=0.98,
            description="Rule-based keyword matching",
            files_correctly_classified=0.70,
            manual_time_saved_sec=15.0     # Quick manual categorization
        ),

        # PDF Processing
        "pdf_extraction": ModelCostConfig(
            name="PDF Text Extraction",
            cost_type=CostType.COMPUTE,
            cost_per_unit=0.00005,
            unit_type="invocation",
            avg_processing_time_sec=3.0,
            success_rate=0.85,
            description="pypdf + pdf2image for PDF processing",
            files_correctly_classified=0.80,
            manual_time_saved_sec=120.0    # 2 min to manually read PDF
        ),

        # Word Document Processing
        "docx_extraction": ModelCostConfig(
            name="Word Document Extraction",
            cost_type=CostType.COMPUTE,
            cost_per_unit=0.00001,
            unit_type="invocation",
            avg_processing_time_sec=0.5,
            success_rate=0.95,
            description="python-docx for DOCX processing",
            files_correctly_classified=0.85,
            manual_time_saved_sec=90.0     # 1.5 min to manually read
        ),

        # Excel Processing
        "xlsx_extraction": ModelCostConfig(
            name="Excel Extraction",
            cost_type=CostType.COMPUTE,
            cost_per_unit=0.00002,
            unit_type="invocation",
            avg_processing_time_sec=1.0,
            success_rate=0.90,
            description="openpyxl for Excel processing",
            files_correctly_classified=0.80,
            manual_time_saved_sec=180.0    # 3 min to manually review spreadsheet
        ),

        # EXIF Metadata Extraction
        "exif_extraction": ModelCostConfig(
            name="EXIF Metadata Extraction",
            cost_type=CostType.COMPUTE,
            cost_per_unit=0.0,             # Free
            unit_type="invocation",
            avg_processing_time_sec=0.1,
            success_rate=0.70,             # Many images lack EXIF
            description="PIL/piexif for image metadata",
            files_correctly_classified=0.95,
            manual_time_saved_sec=45.0     # Time to manually check image properties
        ),

        # Schema.org Generation
        "schema_generation": ModelCostConfig(
            name="Schema.org Generation",
            cost_type=CostType.COMPUTE,
            cost_per_unit=0.0,
            unit_type="invocation",
            avg_processing_time_sec=0.05,
            success_rate=0.99,
            description="Structured data generation",
            files_correctly_classified=0.99,
            manual_time_saved_sec=300.0    # 5 min to manually create JSON-LD
        ),

        # Game Asset Detection
        "game_asset_detection": ModelCostConfig(
            name="Game Asset Detection",
            cost_type=CostType.COMPUTE,
            cost_per_unit=0.0,
            unit_type="invocation",
            avg_processing_time_sec=0.001,
            success_rate=0.95,
            description="Keyword-based game asset classification",
            files_correctly_classified=0.90,
            manual_time_saved_sec=20.0
        ),
    }

    # Hourly rate for manual work (for ROI calculation)
    MANUAL_HOURLY_RATE = 25.0  # $25/hour for manual file organization

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the cost calculator.

        Args:
            config_path: Optional path to custom cost configuration JSON
        """
        self.cost_configs: Dict[str, ModelCostConfig] = {}
        self.usage_records: List[UsageRecord] = []
        self.session_start = datetime.now()

        # Load default configs
        for name, config in self.DEFAULT_COST_CONFIGS.items():
            self.cost_configs[name] = config

        # Load custom config if provided
        if config_path and Path(config_path).exists():
            self._load_custom_config(config_path)

    def _load_custom_config(self, config_path: str):
        """Load custom cost configuration from JSON."""
        with open(config_path, 'r') as f:
            custom_config = json.load(f)

        for name, config_dict in custom_config.get('models', {}).items():
            self.cost_configs[name] = ModelCostConfig(
                name=config_dict.get('name', name),
                cost_type=CostType(config_dict.get('cost_type', 'compute')),
                cost_per_unit=config_dict.get('cost_per_unit', 0.0),
                unit_type=config_dict.get('unit_type', 'invocation'),
                avg_processing_time_sec=config_dict.get('avg_processing_time_sec', 1.0),
                success_rate=config_dict.get('success_rate', 1.0),
                description=config_dict.get('description', ''),
                files_correctly_classified=config_dict.get('files_correctly_classified', 0.0),
                manual_time_saved_sec=config_dict.get('manual_time_saved_sec', 0.0)
            )

    def record_usage(
        self,
        feature_name: str,
        processing_time_sec: float,
        files_processed: int = 1,
        success: bool = True,
        error_message: Optional[str] = None,
        input_file_size_bytes: int = 0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> UsageRecord:
        """
        Record a usage event for a feature/model.

        Args:
            feature_name: Name of the feature (must match cost_configs key)
            processing_time_sec: Time taken for processing
            files_processed: Number of files processed
            success: Whether the processing succeeded
            error_message: Error message if failed
            input_file_size_bytes: Size of input file
            metadata: Additional metadata

        Returns:
            The created UsageRecord
        """
        record = UsageRecord(
            feature_name=feature_name,
            timestamp=datetime.now(),
            processing_time_sec=processing_time_sec,
            files_processed=files_processed,
            success=success,
            error_message=error_message,
            input_file_size_bytes=input_file_size_bytes,
            metadata=metadata or {}
        )
        self.usage_records.append(record)
        return record

    def calculate_feature_cost(self, feature_name: str) -> CostSummary:
        """
        Calculate total cost for a specific feature.

        Args:
            feature_name: Name of the feature

        Returns:
            CostSummary for the feature
        """
        config = self.cost_configs.get(feature_name)
        if not config:
            raise ValueError(f"Unknown feature: {feature_name}")

        # Filter records for this feature
        records = [r for r in self.usage_records if r.feature_name == feature_name]

        if not records:
            return CostSummary(
                feature_name=feature_name,
                total_invocations=0,
                total_processing_time_sec=0.0,
                total_cost=0.0,
                avg_cost_per_file=0.0,
                success_rate=0.0,
                total_files_processed=0
            )

        total_invocations = len(records)
        total_processing_time = sum(r.processing_time_sec for r in records)
        total_files = sum(r.files_processed for r in records)
        successful = sum(1 for r in records if r.success)

        # Calculate cost based on cost type
        if config.cost_type == CostType.COMPUTE:
            # Cost based on invocations
            total_cost = total_invocations * config.cost_per_unit
        elif config.cost_type == CostType.API_CALL:
            total_cost = total_invocations * config.cost_per_unit
        else:
            total_cost = total_invocations * config.cost_per_unit

        avg_cost_per_file = total_cost / total_files if total_files > 0 else 0.0
        success_rate = successful / total_invocations if total_invocations > 0 else 0.0

        return CostSummary(
            feature_name=feature_name,
            total_invocations=total_invocations,
            total_processing_time_sec=total_processing_time,
            total_cost=total_cost,
            avg_cost_per_file=avg_cost_per_file,
            success_rate=success_rate,
            total_files_processed=total_files
        )

    def calculate_roi(self, feature_name: str) -> ROIMetrics:
        """
        Calculate ROI for a specific feature.

        ROI = (Value Generated - Cost) / Cost * 100

        Value is calculated as:
        - Manual time saved * hourly rate * success rate

        Args:
            feature_name: Name of the feature

        Returns:
            ROIMetrics for the feature
        """
        config = self.cost_configs.get(feature_name)
        if not config:
            raise ValueError(f"Unknown feature: {feature_name}")

        cost_summary = self.calculate_feature_cost(feature_name)

        if cost_summary.total_files_processed == 0:
            return ROIMetrics(
                feature_name=feature_name,
                total_cost=0.0,
                total_value=0.0,
                roi_percentage=0.0,
                manual_hours_saved=0.0,
                cost_per_file=0.0,
                value_per_file=0.0,
                break_even_files=0
            )

        # Calculate value generated
        # Value = (manual time saved * files classified correctly) * hourly rate
        files_classified = cost_summary.total_files_processed * config.files_correctly_classified
        total_time_saved_sec = files_classified * config.manual_time_saved_sec
        total_time_saved_hours = total_time_saved_sec / 3600
        total_value = total_time_saved_hours * self.MANUAL_HOURLY_RATE

        # Calculate ROI
        if cost_summary.total_cost > 0:
            roi_percentage = ((total_value - cost_summary.total_cost) / cost_summary.total_cost) * 100
        else:
            roi_percentage = float('inf') if total_value > 0 else 0.0

        # Calculate break-even point
        cost_per_file = cost_summary.avg_cost_per_file
        value_per_file = (config.manual_time_saved_sec / 3600) * self.MANUAL_HOURLY_RATE * config.files_correctly_classified

        if cost_per_file > 0 and value_per_file > cost_per_file:
            break_even_files = 1  # Already profitable per file
        elif cost_per_file > 0:
            # Need multiple files to break even
            break_even_files = int(cost_summary.total_cost / value_per_file) + 1 if value_per_file > 0 else float('inf')
        else:
            break_even_files = 0  # No cost

        return ROIMetrics(
            feature_name=feature_name,
            total_cost=cost_summary.total_cost,
            total_value=total_value,
            roi_percentage=roi_percentage,
            manual_hours_saved=total_time_saved_hours,
            cost_per_file=cost_per_file,
            value_per_file=value_per_file,
            break_even_files=break_even_files
        )

    def calculate_total_cost(self) -> Dict[str, Any]:
        """
        Calculate total cost across all features.

        Returns:
            Dictionary with total cost breakdown
        """
        total_cost = 0.0
        total_files = 0
        total_time = 0.0
        feature_costs = {}

        for feature_name in self.cost_configs.keys():
            summary = self.calculate_feature_cost(feature_name)
            if summary.total_invocations > 0:
                feature_costs[feature_name] = asdict(summary)
                total_cost += summary.total_cost
                total_files += summary.total_files_processed
                total_time += summary.total_processing_time_sec

        return {
            'total_cost': total_cost,
            'total_files_processed': total_files,
            'total_processing_time_sec': total_time,
            'avg_cost_per_file': total_cost / total_files if total_files > 0 else 0.0,
            'feature_breakdown': feature_costs
        }

    def calculate_total_roi(self) -> Dict[str, Any]:
        """
        Calculate total ROI across all features.

        Returns:
            Dictionary with total ROI breakdown
        """
        total_cost = 0.0
        total_value = 0.0
        total_hours_saved = 0.0
        feature_rois = {}

        for feature_name in self.cost_configs.keys():
            roi = self.calculate_roi(feature_name)
            if roi.total_cost > 0 or roi.total_value > 0:
                feature_rois[feature_name] = asdict(roi)
                total_cost += roi.total_cost
                total_value += roi.total_value
                total_hours_saved += roi.manual_hours_saved

        overall_roi = ((total_value - total_cost) / total_cost * 100) if total_cost > 0 else float('inf')

        return {
            'total_cost': total_cost,
            'total_value': total_value,
            'overall_roi_percentage': overall_roi,
            'total_manual_hours_saved': total_hours_saved,
            'hourly_rate_used': self.MANUAL_HOURLY_RATE,
            'feature_breakdown': feature_rois
        }

    def get_optimization_recommendations(self) -> List[Dict[str, Any]]:
        """
        Analyze usage and provide cost optimization recommendations.

        Returns:
            List of recommendations
        """
        recommendations = []

        for feature_name in self.cost_configs.keys():
            summary = self.calculate_feature_cost(feature_name)
            roi = self.calculate_roi(feature_name)
            config = self.cost_configs[feature_name]

            if summary.total_invocations == 0:
                continue

            # Check for low success rate
            if summary.success_rate < 0.7:
                recommendations.append({
                    'feature': feature_name,
                    'type': 'low_success_rate',
                    'severity': 'high',
                    'message': f"{config.name} has a {summary.success_rate:.1%} success rate. "
                              f"Consider improving error handling or fallback mechanisms.",
                    'potential_savings': summary.total_cost * (1 - summary.success_rate)
                })

            # Check for negative ROI
            if roi.roi_percentage < 0:
                recommendations.append({
                    'feature': feature_name,
                    'type': 'negative_roi',
                    'severity': 'critical',
                    'message': f"{config.name} has negative ROI ({roi.roi_percentage:.1f}%). "
                              f"Cost (${roi.total_cost:.4f}) exceeds value (${roi.total_value:.4f}).",
                    'potential_savings': roi.total_cost - roi.total_value
                })

            # Check for high processing time
            avg_time = summary.total_processing_time_sec / summary.total_invocations
            if avg_time > config.avg_processing_time_sec * 2:
                recommendations.append({
                    'feature': feature_name,
                    'type': 'slow_processing',
                    'severity': 'medium',
                    'message': f"{config.name} is taking {avg_time:.2f}s per invocation "
                              f"(expected {config.avg_processing_time_sec:.2f}s). Consider optimization.",
                    'potential_savings': 0.0  # Time savings, not cost
                })

            # Check if feature is underutilized
            total_files = sum(r.files_processed for r in self.usage_records)
            feature_files = summary.total_files_processed
            if total_files > 100 and feature_files / total_files < 0.05 and roi.roi_percentage > 100:
                recommendations.append({
                    'feature': feature_name,
                    'type': 'underutilized',
                    'severity': 'low',
                    'message': f"{config.name} is only used for {feature_files/total_files:.1%} of files "
                              f"but has {roi.roi_percentage:.0f}% ROI. Consider expanding usage.",
                    'potential_savings': 0.0  # Opportunity cost
                })

        # Sort by severity and potential savings
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        recommendations.sort(key=lambda x: (severity_order.get(x['severity'], 4), -x['potential_savings']))

        return recommendations

    def estimate_cost_for_files(self, file_count: int, features: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Estimate cost for processing a given number of files.

        Args:
            file_count: Number of files to estimate
            features: List of features to use (None for all)

        Returns:
            Cost estimate breakdown
        """
        features = features or list(self.cost_configs.keys())
        estimates = {}
        total_cost = 0.0
        total_time = 0.0
        total_value = 0.0

        for feature_name in features:
            config = self.cost_configs.get(feature_name)
            if not config:
                continue

            # Estimate cost
            cost = file_count * config.cost_per_unit
            time_sec = file_count * config.avg_processing_time_sec

            # Estimate value
            files_classified = file_count * config.files_correctly_classified * config.success_rate
            value = (files_classified * config.manual_time_saved_sec / 3600) * self.MANUAL_HOURLY_RATE

            estimates[feature_name] = {
                'estimated_cost': cost,
                'estimated_time_sec': time_sec,
                'estimated_time_human': self._format_duration(time_sec),
                'estimated_value': value,
                'estimated_roi': ((value - cost) / cost * 100) if cost > 0 else float('inf')
            }

            total_cost += cost
            total_time += time_sec
            total_value += value

        return {
            'file_count': file_count,
            'total_estimated_cost': total_cost,
            'total_estimated_time_sec': total_time,
            'total_estimated_time_human': self._format_duration(total_time),
            'total_estimated_value': total_value,
            'estimated_roi': ((total_value - total_cost) / total_cost * 100) if total_cost > 0 else float('inf'),
            'feature_estimates': estimates
        }

    def _format_duration(self, seconds: float) -> str:
        """Format seconds into human-readable duration."""
        if seconds < 60:
            return f"{seconds:.1f} seconds"
        elif seconds < 3600:
            return f"{seconds/60:.1f} minutes"
        else:
            return f"{seconds/3600:.1f} hours"

    def generate_report(self, output_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate a comprehensive cost and ROI report.

        Args:
            output_path: Optional path to save report JSON

        Returns:
            Complete report dictionary
        """
        report = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'session_start': self.session_start.isoformat(),
                'session_duration_sec': (datetime.now() - self.session_start).total_seconds(),
                'total_usage_records': len(self.usage_records)
            },
            'cost_summary': self.calculate_total_cost(),
            'roi_summary': self.calculate_total_roi(),
            'recommendations': self.get_optimization_recommendations(),
            'model_configs': {name: asdict(config) for name, config in self.cost_configs.items()},
        }

        # Add projections for common file counts
        report['projections'] = {
            '1000_files': self.estimate_cost_for_files(1000),
            '10000_files': self.estimate_cost_for_files(10000),
            '100000_files': self.estimate_cost_for_files(100000)
        }

        if output_path:
            with open(output_path, 'w') as f:
                json.dump(report, f, indent=2, default=str)

        return report

    def print_summary(self):
        """Print a formatted summary of costs and ROI."""
        print("\n" + "=" * 70)
        print("COST & ROI SUMMARY REPORT")
        print("=" * 70)

        # Overall costs
        cost_summary = self.calculate_total_cost()
        print(f"\n{'COST SUMMARY':=^70}")
        print(f"  Total Cost:              ${cost_summary['total_cost']:.4f}")
        print(f"  Total Files Processed:   {cost_summary['total_files_processed']:,}")
        print(f"  Avg Cost per File:       ${cost_summary['avg_cost_per_file']:.6f}")
        print(f"  Total Processing Time:   {self._format_duration(cost_summary['total_processing_time_sec'])}")

        # ROI summary
        roi_summary = self.calculate_total_roi()
        print(f"\n{'ROI SUMMARY':=^70}")
        print(f"  Total Value Generated:   ${roi_summary['total_value']:.2f}")
        print(f"  Overall ROI:             {roi_summary['overall_roi_percentage']:.0f}%")
        print(f"  Manual Hours Saved:      {roi_summary['total_manual_hours_saved']:.1f} hours")
        print(f"  (at ${roi_summary['hourly_rate_used']:.2f}/hour)")

        # Per-feature breakdown
        print(f"\n{'PER-FEATURE BREAKDOWN':=^70}")
        print(f"{'Feature':<25} {'Cost':>10} {'Value':>10} {'ROI':>10} {'Files':>10}")
        print("-" * 70)

        for feature_name in sorted(self.cost_configs.keys()):
            cost = self.calculate_feature_cost(feature_name)
            roi = self.calculate_roi(feature_name)

            if cost.total_invocations > 0:
                roi_str = f"{roi.roi_percentage:.0f}%" if roi.roi_percentage != float('inf') else "∞"
                print(f"{feature_name:<25} ${cost.total_cost:>9.4f} ${roi.total_value:>9.2f} {roi_str:>10} {cost.total_files_processed:>10,}")

        # Recommendations
        recommendations = self.get_optimization_recommendations()
        if recommendations:
            print(f"\n{'RECOMMENDATIONS':=^70}")
            for i, rec in enumerate(recommendations[:5], 1):
                print(f"  {i}. [{rec['severity'].upper()}] {rec['message']}")

        print("\n" + "=" * 70)


class CostTracker:
    """
    Context manager for tracking feature usage costs.

    Usage:
        calculator = CostROICalculator()
        with CostTracker(calculator, 'clip_vision', files_processed=1) as tracker:
            # Do the work
            result = analyze_image(image_path)
        # Cost is automatically recorded
    """

    def __init__(
        self,
        calculator: CostROICalculator,
        feature_name: str,
        files_processed: int = 1,
        input_file_size_bytes: int = 0,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.calculator = calculator
        self.feature_name = feature_name
        self.files_processed = files_processed
        self.input_file_size_bytes = input_file_size_bytes
        self.metadata = metadata or {}
        self.start_time = None
        self.success = True
        self.error_message = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        processing_time = time.time() - self.start_time

        if exc_type is not None:
            self.success = False
            self.error_message = str(exc_val)

        self.calculator.record_usage(
            feature_name=self.feature_name,
            processing_time_sec=processing_time,
            files_processed=self.files_processed,
            success=self.success,
            error_message=self.error_message,
            input_file_size_bytes=self.input_file_size_bytes,
            metadata=self.metadata
        )

        return False  # Don't suppress exceptions


def main():
    """Demo the cost calculator with sample data."""
    import random

    print("Schema.org File Organization System - Cost & ROI Calculator Demo")
    print("=" * 70)

    # Create calculator
    calculator = CostROICalculator()

    # Simulate processing 1000 files with various features
    print("\nSimulating processing of 1000 files...")

    for i in range(1000):
        # Simulate different feature usage patterns
        file_type = random.choice(['image', 'pdf', 'docx', 'xlsx', 'game_asset'])

        if file_type == 'image':
            # Image processing uses CLIP, OCR, face detection
            calculator.record_usage('clip_vision', random.uniform(2.0, 3.5), 1, random.random() > 0.05)
            calculator.record_usage('tesseract_ocr', random.uniform(1.0, 2.0), 1, random.random() > 0.10)
            calculator.record_usage('face_detection', random.uniform(0.3, 0.8), 1, random.random() > 0.15)
            calculator.record_usage('exif_extraction', random.uniform(0.05, 0.15), 1, random.random() > 0.30)
            if random.random() > 0.5:
                calculator.record_usage('nominatim_geocoding', random.uniform(0.5, 1.5), 1, random.random() > 0.25)

        elif file_type == 'pdf':
            calculator.record_usage('pdf_extraction', random.uniform(2.0, 5.0), 1, random.random() > 0.15)
            calculator.record_usage('keyword_classifier', random.uniform(0.001, 0.002), 1, True)

        elif file_type == 'docx':
            calculator.record_usage('docx_extraction', random.uniform(0.3, 0.8), 1, random.random() > 0.05)
            calculator.record_usage('keyword_classifier', random.uniform(0.001, 0.002), 1, True)

        elif file_type == 'xlsx':
            calculator.record_usage('xlsx_extraction', random.uniform(0.5, 1.5), 1, random.random() > 0.10)
            calculator.record_usage('keyword_classifier', random.uniform(0.001, 0.002), 1, True)

        elif file_type == 'game_asset':
            calculator.record_usage('game_asset_detection', random.uniform(0.001, 0.002), 1, True)

        # Schema generation for all files
        calculator.record_usage('schema_generation', random.uniform(0.03, 0.08), 1, True)

    # Print summary
    calculator.print_summary()

    # Generate and save report
    report = calculator.generate_report('results/cost_roi_report.json')
    print(f"\nFull report saved to: results/cost_roi_report.json")

    # Show projection for larger runs
    print(f"\n{'COST PROJECTIONS':=^70}")
    for file_count in [1000, 10000, 100000]:
        estimate = calculator.estimate_cost_for_files(file_count)
        print(f"\n{file_count:,} files:")
        print(f"  Estimated Cost:  ${estimate['total_estimated_cost']:.2f}")
        print(f"  Estimated Value: ${estimate['total_estimated_value']:.2f}")
        print(f"  Estimated Time:  {estimate['total_estimated_time_human']}")
        print(f"  Projected ROI:   {estimate['estimated_roi']:.0f}%")


if __name__ == '__main__':
    main()
