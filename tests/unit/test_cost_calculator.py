#!/usr/bin/env python3
"""
Unit tests for src/cost_roi_calculator.py - Cost and ROI calculator.

Priority: P1-5 (Medium - Cost tracking)
Coverage: 85%+ target

Tests cost tracking, ROI calculation, and reporting including:
- CostType enum
- ModelCostConfig dataclass
- UsageRecord dataclass
- CostROICalculator class
- CostTracker context manager
"""

import json
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pytest

from src.cost_roi_calculator import (
    CostType,
    ModelCostConfig,
    UsageRecord,
    CostSummary,
    ROIMetrics,
    CostROICalculator,
    CostTracker,
)


class TestCostTypeEnum:
    """Test CostType enum."""

    def test_all_cost_types_exist(self):
        """Should have all expected cost types."""
        expected_types = ["COMPUTE", "API_CALL", "STORAGE", "MEMORY"]
        for type_name in expected_types:
            assert hasattr(CostType, type_name)

    def test_cost_type_values(self):
        """Cost types should have correct string values."""
        assert CostType.COMPUTE.value == "compute"
        assert CostType.API_CALL.value == "api_call"
        assert CostType.STORAGE.value == "storage"
        assert CostType.MEMORY.value == "memory"


class TestModelCostConfig:
    """Test ModelCostConfig dataclass."""

    def test_create_basic_config(self):
        """Should create config with required fields."""
        config = ModelCostConfig(
            name="Test Model",
            cost_type=CostType.COMPUTE,
            cost_per_unit=0.001,
            unit_type="invocation",
            avg_processing_time_sec=1.5,
        )
        assert config.name == "Test Model"
        assert config.cost_type == CostType.COMPUTE
        assert config.cost_per_unit == 0.001
        assert config.unit_type == "invocation"
        assert config.avg_processing_time_sec == 1.5

    def test_default_values(self):
        """Should have correct default values."""
        config = ModelCostConfig(
            name="Test",
            cost_type=CostType.COMPUTE,
            cost_per_unit=0.001,
            unit_type="invocation",
            avg_processing_time_sec=1.0,
        )
        assert config.success_rate == 1.0
        assert config.description == ""
        assert config.files_correctly_classified == 0.0
        assert config.manual_time_saved_sec == 0.0

    def test_config_with_all_fields(self):
        """Should create config with all optional fields."""
        config = ModelCostConfig(
            name="Full Config",
            cost_type=CostType.API_CALL,
            cost_per_unit=0.01,
            unit_type="request",
            avg_processing_time_sec=2.0,
            success_rate=0.95,
            description="A full test config",
            files_correctly_classified=0.85,
            manual_time_saved_sec=30.0,
        )
        assert config.success_rate == 0.95
        assert config.description == "A full test config"
        assert config.files_correctly_classified == 0.85
        assert config.manual_time_saved_sec == 30.0


class TestUsageRecord:
    """Test UsageRecord dataclass."""

    def test_create_basic_record(self):
        """Should create record with required fields."""
        record = UsageRecord(
            feature_name="clip_vision",
            timestamp=datetime.now(),
            processing_time_sec=2.5,
            files_processed=1,
            success=True,
        )
        assert record.feature_name == "clip_vision"
        assert record.files_processed == 1
        assert record.success is True

    def test_default_values(self):
        """Should have correct default values."""
        record = UsageRecord(
            feature_name="test",
            timestamp=datetime.now(),
            processing_time_sec=1.0,
            files_processed=1,
            success=True,
        )
        assert record.error_message is None
        assert record.input_file_size_bytes == 0
        assert record.metadata == {}

    def test_record_with_error(self):
        """Should handle error records."""
        record = UsageRecord(
            feature_name="test",
            timestamp=datetime.now(),
            processing_time_sec=0.5,
            files_processed=0,
            success=False,
            error_message="File not found",
        )
        assert record.success is False
        assert record.error_message == "File not found"


class TestCostROICalculatorInit:
    """Test CostROICalculator initialization."""

    def test_init_loads_default_configs(self):
        """Should load default cost configurations."""
        calc = CostROICalculator()
        assert len(calc.cost_configs) > 0
        assert "clip_vision" in calc.cost_configs
        assert "tesseract_ocr" in calc.cost_configs
        assert "keyword_classifier" in calc.cost_configs

    def test_init_sets_session_start(self):
        """Should set session start time."""
        calc = CostROICalculator()
        assert isinstance(calc.session_start, datetime)

    def test_init_empty_usage_records(self):
        """Should start with empty usage records."""
        calc = CostROICalculator()
        assert calc.usage_records == []

    def test_init_with_custom_config(self):
        """Should load custom config from file."""
        custom_config = {
            "models": {
                "custom_model": {
                    "name": "Custom Model",
                    "cost_type": "compute",
                    "cost_per_unit": 0.05,
                    "unit_type": "invocation",
                    "avg_processing_time_sec": 5.0,
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(custom_config, f)
            config_path = f.name

        try:
            calc = CostROICalculator(config_path=config_path)
            assert "custom_model" in calc.cost_configs
            assert calc.cost_configs["custom_model"].cost_per_unit == 0.05
        finally:
            Path(config_path).unlink()


class TestRecordUsage:
    """Test record_usage method."""

    def test_record_usage_basic(self):
        """Should record basic usage."""
        calc = CostROICalculator()
        record = calc.record_usage(
            feature_name="clip_vision", processing_time_sec=2.5, files_processed=1, success=True
        )

        assert isinstance(record, UsageRecord)
        assert record.feature_name == "clip_vision"
        assert record.processing_time_sec == 2.5
        assert len(calc.usage_records) == 1

    def test_record_usage_with_error(self):
        """Should record failed usage."""
        calc = CostROICalculator()
        record = calc.record_usage(
            feature_name="tesseract_ocr",
            processing_time_sec=1.0,
            files_processed=0,
            success=False,
            error_message="OCR failed: corrupted image",
        )

        assert record.success is False
        assert "OCR failed" in record.error_message

    def test_record_usage_with_metadata(self):
        """Should record usage with metadata."""
        calc = CostROICalculator()
        record = calc.record_usage(
            feature_name="clip_vision",
            processing_time_sec=2.0,
            files_processed=1,
            success=True,
            metadata={"image_format": "JPEG", "dimensions": "1920x1080"},
        )

        assert record.metadata["image_format"] == "JPEG"

    def test_record_usage_multiple(self):
        """Should record multiple usage events."""
        calc = CostROICalculator()
        for i in range(10):
            calc.record_usage("clip_vision", 2.0 + i * 0.1, 1, True)

        assert len(calc.usage_records) == 10


class TestCalculateFeatureCost:
    """Test calculate_feature_cost method."""

    def test_calculate_cost_no_usage(self):
        """Should return zero costs when no usage."""
        calc = CostROICalculator()
        summary = calc.calculate_feature_cost("clip_vision")

        assert isinstance(summary, CostSummary)
        assert summary.total_invocations == 0
        assert summary.total_cost == 0.0

    def test_calculate_cost_with_usage(self):
        """Should calculate costs based on usage."""
        calc = CostROICalculator()

        # Record some usage
        for _ in range(10):
            calc.record_usage("clip_vision", 2.5, 1, True)

        summary = calc.calculate_feature_cost("clip_vision")

        assert summary.total_invocations == 10
        assert summary.total_files_processed == 10
        assert summary.total_cost > 0
        assert summary.avg_cost_per_file > 0

    def test_calculate_cost_success_rate(self):
        """Should calculate correct success rate."""
        calc = CostROICalculator()

        # 8 successful, 2 failed
        for _ in range(8):
            calc.record_usage("tesseract_ocr", 1.5, 1, True)
        for _ in range(2):
            calc.record_usage("tesseract_ocr", 0.5, 0, False)

        summary = calc.calculate_feature_cost("tesseract_ocr")

        assert summary.total_invocations == 10
        assert summary.success_rate == 0.8

    def test_calculate_cost_unknown_feature_raises(self):
        """Should raise for unknown feature."""
        calc = CostROICalculator()
        with pytest.raises(ValueError) as exc_info:
            calc.calculate_feature_cost("nonexistent_feature")
        assert "Unknown feature" in str(exc_info.value)


class TestCalculateROI:
    """Test calculate_roi method."""

    def test_calculate_roi_no_usage(self):
        """Should return zero ROI when no usage."""
        calc = CostROICalculator()
        roi = calc.calculate_roi("clip_vision")

        assert isinstance(roi, ROIMetrics)
        assert roi.total_cost == 0.0
        assert roi.total_value == 0.0
        assert roi.roi_percentage == 0.0

    def test_calculate_roi_with_usage(self):
        """Should calculate positive ROI for efficient features."""
        calc = CostROICalculator()

        # Record usage for a feature with high value
        for _ in range(100):
            calc.record_usage("schema_generation", 0.05, 1, True)

        roi = calc.calculate_roi("schema_generation")

        # schema_generation should have very high ROI (low cost, high value)
        assert roi.total_value > 0  # Use total_value instead of total_files_processed
        # Since schema_generation costs 0 and saves 5 min per file
        assert roi.roi_percentage == float("inf") or roi.roi_percentage > 1000

    def test_calculate_roi_manual_hours_saved(self):
        """Should calculate manual hours saved."""
        calc = CostROICalculator()

        # Record usage
        for _ in range(10):
            calc.record_usage("clip_vision", 2.5, 1, True)

        roi = calc.calculate_roi("clip_vision")

        # CLIP saves 30 sec per file, 10 files * 0.85 accuracy = 8.5 * 30 sec
        assert roi.manual_hours_saved > 0

    def test_calculate_roi_unknown_feature_raises(self):
        """Should raise for unknown feature."""
        calc = CostROICalculator()
        with pytest.raises(ValueError):
            calc.calculate_roi("unknown_feature")


class TestCalculateTotalCost:
    """Test calculate_total_cost method."""

    def test_calculate_total_cost_empty(self):
        """Should return zeros when no usage."""
        calc = CostROICalculator()
        total = calc.calculate_total_cost()

        assert total["total_cost"] == 0.0
        assert total["total_files_processed"] == 0
        assert total["feature_breakdown"] == {}

    def test_calculate_total_cost_with_usage(self):
        """Should sum costs across features."""
        calc = CostROICalculator()

        # Use multiple features
        for _ in range(10):
            calc.record_usage("clip_vision", 2.5, 1, True)
            calc.record_usage("tesseract_ocr", 1.5, 1, True)
            calc.record_usage("keyword_classifier", 0.001, 1, True)

        total = calc.calculate_total_cost()

        assert total["total_files_processed"] == 30
        assert total["total_processing_time_sec"] > 0
        assert len(total["feature_breakdown"]) == 3


class TestCalculateTotalROI:
    """Test calculate_total_roi method."""

    def test_calculate_total_roi_empty(self):
        """Should return zeros when no usage."""
        calc = CostROICalculator()
        total = calc.calculate_total_roi()

        assert total["total_cost"] == 0.0
        assert total["total_value"] == 0.0

    def test_calculate_total_roi_with_usage(self):
        """Should aggregate ROI across features."""
        calc = CostROICalculator()

        for _ in range(50):
            calc.record_usage("clip_vision", 2.5, 1, True)
            calc.record_usage("schema_generation", 0.05, 1, True)

        total = calc.calculate_total_roi()

        assert total["total_manual_hours_saved"] > 0
        assert "hourly_rate_used" in total


class TestOptimizationRecommendations:
    """Test get_optimization_recommendations method."""

    def test_recommendations_empty_when_no_issues(self):
        """Should return empty list when no issues."""
        calc = CostROICalculator()
        recommendations = calc.get_optimization_recommendations()
        # With no usage, no recommendations
        assert recommendations == []

    def test_recommendations_low_success_rate(self):
        """Should recommend when success rate is low."""
        calc = CostROICalculator()

        # Record mostly failures
        for _ in range(3):
            calc.record_usage("tesseract_ocr", 1.5, 1, True)
        for _ in range(7):
            calc.record_usage("tesseract_ocr", 0.5, 0, False)

        recommendations = calc.get_optimization_recommendations()

        # Should have recommendation about low success rate
        has_low_success = any(r["type"] == "low_success_rate" for r in recommendations)
        assert has_low_success

    def test_recommendations_slow_processing(self):
        """Should recommend when processing is slow."""
        calc = CostROICalculator()

        # Record with very slow processing (10x expected)
        config = calc.cost_configs["clip_vision"]
        slow_time = config.avg_processing_time_sec * 5  # 5x slower

        for _ in range(10):
            calc.record_usage("clip_vision", slow_time, 1, True)

        recommendations = calc.get_optimization_recommendations()

        has_slow_processing = any(r["type"] == "slow_processing" for r in recommendations)
        assert has_slow_processing


class TestEstimateCostForFiles:
    """Test estimate_cost_for_files method."""

    def test_estimate_for_1000_files(self):
        """Should estimate costs for 1000 files."""
        calc = CostROICalculator()
        estimate = calc.estimate_cost_for_files(1000)

        assert estimate["file_count"] == 1000
        assert estimate["total_estimated_cost"] >= 0
        assert estimate["total_estimated_time_sec"] > 0
        assert "feature_estimates" in estimate

    def test_estimate_for_specific_features(self):
        """Should estimate only for specified features."""
        calc = CostROICalculator()
        estimate = calc.estimate_cost_for_files(1000, features=["clip_vision", "tesseract_ocr"])

        assert len(estimate["feature_estimates"]) == 2
        assert "clip_vision" in estimate["feature_estimates"]
        assert "tesseract_ocr" in estimate["feature_estimates"]

    def test_estimate_includes_time_human_readable(self):
        """Should include human-readable time estimate."""
        calc = CostROICalculator()
        estimate = calc.estimate_cost_for_files(10000)

        assert "total_estimated_time_human" in estimate
        # Should be minutes or hours for 10000 files
        assert any(unit in estimate["total_estimated_time_human"] for unit in ["minutes", "hours"])


class TestFormatDuration:
    """Test _format_duration helper method."""

    def test_format_seconds(self):
        """Should format small durations in seconds."""
        calc = CostROICalculator()
        assert "seconds" in calc._format_duration(45)

    def test_format_minutes(self):
        """Should format medium durations in minutes."""
        calc = CostROICalculator()
        assert "minutes" in calc._format_duration(300)

    def test_format_hours(self):
        """Should format large durations in hours."""
        calc = CostROICalculator()
        assert "hours" in calc._format_duration(7200)


class TestGenerateReport:
    """Test generate_report method."""

    def test_generate_report_structure(self):
        """Should generate report with all sections."""
        calc = CostROICalculator()

        # Add some usage
        for _ in range(10):
            calc.record_usage("clip_vision", 2.5, 1, True)

        report = calc.generate_report()

        assert "metadata" in report
        assert "cost_summary" in report
        assert "roi_summary" in report
        assert "recommendations" in report
        assert "model_configs" in report
        assert "projections" in report

    def test_generate_report_saves_to_file(self):
        """Should save report to file when path provided."""
        calc = CostROICalculator()

        for _ in range(5):
            calc.record_usage("keyword_classifier", 0.001, 1, True)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            output_path = f.name

        try:
            calc.generate_report(output_path=output_path)

            # Verify file was created and contains valid JSON
            with open(output_path) as f:
                saved_report = json.load(f)

            assert "cost_summary" in saved_report
        finally:
            Path(output_path).unlink()

    def test_generate_report_metadata(self):
        """Should include session metadata."""
        calc = CostROICalculator()
        report = calc.generate_report()

        metadata = report["metadata"]
        assert "generated_at" in metadata
        assert "session_start" in metadata
        assert "session_duration_sec" in metadata
        assert "total_usage_records" in metadata


class TestCostTracker:
    """Test CostTracker context manager."""

    def test_cost_tracker_records_successful(self):
        """Should record successful usage on normal exit."""
        calc = CostROICalculator()

        with CostTracker(calc, "clip_vision", files_processed=1):
            time.sleep(0.01)  # Simulate some work

        assert len(calc.usage_records) == 1
        assert calc.usage_records[0].success is True
        assert calc.usage_records[0].processing_time_sec >= 0.01

    def test_cost_tracker_records_failure_on_exception(self):
        """Should record failed usage when exception occurs."""
        calc = CostROICalculator()

        try:
            with CostTracker(calc, "tesseract_ocr", files_processed=1):
                raise ValueError("Test error")
        except ValueError:
            pass

        assert len(calc.usage_records) == 1
        assert calc.usage_records[0].success is False
        assert "Test error" in calc.usage_records[0].error_message

    def test_cost_tracker_does_not_suppress_exceptions(self):
        """Should not suppress exceptions."""
        calc = CostROICalculator()

        with pytest.raises(RuntimeError):
            with CostTracker(calc, "clip_vision"):
                raise RuntimeError("Should propagate")

    def test_cost_tracker_with_metadata(self):
        """Should pass metadata to usage record."""
        calc = CostROICalculator()

        with CostTracker(
            calc,
            "clip_vision",
            files_processed=5,
            input_file_size_bytes=1024,
            metadata={"batch_id": "123"},
        ):
            pass

        record = calc.usage_records[0]
        assert record.files_processed == 5
        assert record.input_file_size_bytes == 1024
        assert record.metadata["batch_id"] == "123"


class TestDefaultCostConfigs:
    """Test that default cost configs are reasonable."""

    def test_clip_vision_config(self):
        """CLIP vision config should have expected values."""
        calc = CostROICalculator()
        config = calc.cost_configs["clip_vision"]

        assert config.cost_type == CostType.COMPUTE
        assert config.avg_processing_time_sec > 0
        assert config.success_rate > 0
        assert config.manual_time_saved_sec > 0

    def test_tesseract_ocr_config(self):
        """Tesseract OCR config should have expected values."""
        calc = CostROICalculator()
        config = calc.cost_configs["tesseract_ocr"]

        assert config.cost_type == CostType.COMPUTE
        assert config.cost_per_unit < 0.001  # Very low cost

    def test_nominatim_geocoding_config(self):
        """Nominatim config should be free API."""
        calc = CostROICalculator()
        config = calc.cost_configs["nominatim_geocoding"]

        assert config.cost_type == CostType.API_CALL
        assert config.cost_per_unit == 0.0  # Free

    def test_schema_generation_config(self):
        """Schema generation should be essentially free."""
        calc = CostROICalculator()
        config = calc.cost_configs["schema_generation"]

        assert config.cost_per_unit == 0.0
        assert config.success_rate > 0.95


class TestPrintSummary:
    """Test print_summary method (just verify it doesn't crash)."""

    def test_print_summary_empty(self, capsys):
        """Should print summary even with no usage."""
        calc = CostROICalculator()
        calc.print_summary()

        captured = capsys.readouterr()
        assert "COST & ROI SUMMARY" in captured.out

    def test_print_summary_with_usage(self, capsys):
        """Should print detailed summary with usage data."""
        calc = CostROICalculator()

        for _ in range(10):
            calc.record_usage("clip_vision", 2.5, 1, True)
            calc.record_usage("tesseract_ocr", 1.5, 1, True)

        calc.print_summary()

        captured = capsys.readouterr()
        assert "COST SUMMARY" in captured.out
        assert "ROI SUMMARY" in captured.out
        assert "clip_vision" in captured.out
