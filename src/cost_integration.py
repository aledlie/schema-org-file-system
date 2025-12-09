#!/usr/bin/env python3
"""
Cost Tracking Integration for File Organizer

Provides integration between the cost calculator and the existing
file organization system with minimal code changes required.
"""

import time
from functools import wraps
from typing import Callable, Optional, Dict, Any
from pathlib import Path
from contextlib import contextmanager

from cost_roi_calculator import CostROICalculator, CostTracker


# Global calculator instance for easy integration
_global_calculator: Optional[CostROICalculator] = None


def get_calculator() -> CostROICalculator:
    """Get or create the global cost calculator instance."""
    global _global_calculator
    if _global_calculator is None:
        _global_calculator = CostROICalculator()
    return _global_calculator


def reset_calculator():
    """Reset the global calculator (useful for testing)."""
    global _global_calculator
    _global_calculator = None


def track_cost(feature_name: str, files_processed: int = 1):
    """
    Decorator to track costs for a function.

    Usage:
        @track_cost('clip_vision')
        def analyze_image(image_path):
            # ... do analysis ...
            return result

    Args:
        feature_name: Name of the feature being tracked
        files_processed: Number of files processed per call
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            calculator = get_calculator()
            with CostTracker(calculator, feature_name, files_processed):
                return func(*args, **kwargs)
        return wrapper
    return decorator


@contextmanager
def track_feature(
    feature_name: str,
    files_processed: int = 1,
    file_path: Optional[Path] = None
):
    """
    Context manager for tracking feature costs.

    Usage:
        with track_feature('tesseract_ocr', file_path=image_path):
            text = pytesseract.image_to_string(image)

    Args:
        feature_name: Name of the feature
        files_processed: Number of files
        file_path: Optional path for file size tracking
    """
    calculator = get_calculator()
    file_size = 0
    if file_path and Path(file_path).exists():
        file_size = Path(file_path).stat().st_size

    with CostTracker(
        calculator,
        feature_name,
        files_processed=files_processed,
        input_file_size_bytes=file_size
    ):
        yield


def record_feature_usage(
    feature_name: str,
    processing_time_sec: float,
    files_processed: int = 1,
    success: bool = True,
    error_message: Optional[str] = None
):
    """
    Manually record feature usage.

    Use this when the context manager or decorator approach isn't suitable.

    Args:
        feature_name: Name of the feature
        processing_time_sec: Time taken
        files_processed: Number of files processed
        success: Whether it succeeded
        error_message: Error message if failed
    """
    calculator = get_calculator()
    calculator.record_usage(
        feature_name=feature_name,
        processing_time_sec=processing_time_sec,
        files_processed=files_processed,
        success=success,
        error_message=error_message
    )


def get_cost_report() -> Dict[str, Any]:
    """Get the current cost report."""
    return get_calculator().generate_report()


def print_cost_summary():
    """Print the cost summary."""
    get_calculator().print_summary()


def save_cost_report(output_path: str):
    """Save the cost report to a file."""
    get_calculator().generate_report(output_path)


def estimate_processing_cost(
    file_count: int,
    features: Optional[list] = None
) -> Dict[str, Any]:
    """
    Estimate cost for processing a number of files.

    Args:
        file_count: Number of files to estimate
        features: List of features to use (None for all)

    Returns:
        Cost estimate dictionary
    """
    return get_calculator().estimate_cost_for_files(file_count, features)


class FeatureTracker:
    """
    Helper class for tracking multiple features in a processing pipeline.

    Usage:
        tracker = FeatureTracker()

        # Track CLIP analysis
        with tracker.track('clip_vision'):
            scores = model.classify(image)

        # Track OCR
        with tracker.track('tesseract_ocr'):
            text = pytesseract.image_to_string(image)

        # Get summary
        print(tracker.summary())
    """

    def __init__(self):
        self.timings = {}
        self.successes = {}
        self.errors = {}

    @contextmanager
    def track(self, feature_name: str, files: int = 1):
        """Track a specific feature."""
        start = time.time()
        success = True
        error_msg = None

        try:
            yield
        except Exception as e:
            success = False
            error_msg = str(e)
            raise
        finally:
            elapsed = time.time() - start
            self.timings[feature_name] = self.timings.get(feature_name, 0) + elapsed
            self.successes[feature_name] = self.successes.get(feature_name, 0) + (1 if success else 0)
            if error_msg:
                self.errors[feature_name] = error_msg

            # Record to global calculator
            record_feature_usage(
                feature_name=feature_name,
                processing_time_sec=elapsed,
                files_processed=files,
                success=success,
                error_message=error_msg
            )

    def summary(self) -> Dict[str, Any]:
        """Get tracking summary."""
        return {
            'timings': self.timings,
            'successes': self.successes,
            'errors': self.errors,
            'total_time': sum(self.timings.values())
        }


# Example integration showing how to modify file_organizer_content_based.py
INTEGRATION_EXAMPLE = '''
# Add to file_organizer_content_based.py:

# At top of file, add import:
from src.cost_integration import track_feature, print_cost_summary, save_cost_report

# In ImageContentAnalyzer.classify_image_content():
def classify_image_content(self, image_path: Path) -> Dict[str, float]:
    """Classify image content using CLIP zero-shot classification."""
    if not self.vision_available or self.model is None:
        return {}

    with track_feature('clip_vision', file_path=image_path):  # ADD THIS
        try:
            image = Image.open(image_path)
            # ... rest of classification code ...
            return scores
        except Exception as e:
            print(f"  Image classification error: {e}")
            return {}

# In ContentBasedFileOrganizer.extract_text_from_image():
def extract_text_from_image(self, image_path: Path) -> str:
    """Extract text from image using OCR."""
    if not self.ocr_available:
        return ""

    with track_feature('tesseract_ocr', file_path=image_path):  # ADD THIS
        try:
            image = Image.open(image_path)
            text = pytesseract.image_to_string(image)
            return text.strip()
        except Exception as e:
            print(f"  OCR error: {e}")
            return ""

# At end of organize_directories():
def organize_directories(self, source_dirs: List[str], dry_run: bool = False, limit: int = None) -> Dict:
    """Organize files from multiple source directories."""
    # ... existing code ...

    # At end, add cost summary
    if not dry_run:
        print_cost_summary()  # ADD THIS
        save_cost_report(f"results/cost_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    return summary
'''


def print_integration_guide():
    """Print guide for integrating cost tracking."""
    print("=" * 70)
    print("COST TRACKING INTEGRATION GUIDE")
    print("=" * 70)
    print("""
To add cost tracking to your file organizer, you have several options:

1. DECORATOR APPROACH (for standalone functions):
   -----------------------------------------------
   from src.cost_integration import track_cost

   @track_cost('clip_vision')
   def classify_image(image_path):
       # ... your code ...
       return result

2. CONTEXT MANAGER APPROACH (for code blocks):
   -------------------------------------------
   from src.cost_integration import track_feature

   with track_feature('tesseract_ocr', file_path=image_path):
       text = pytesseract.image_to_string(image)

3. MANUAL RECORDING (for complex cases):
   -------------------------------------
   from src.cost_integration import record_feature_usage

   start = time.time()
   try:
       result = do_processing()
       record_feature_usage('my_feature', time.time() - start, success=True)
   except Exception as e:
       record_feature_usage('my_feature', time.time() - start, success=False, error_message=str(e))

4. FEATURE TRACKER CLASS (for pipelines):
   --------------------------------------
   from src.cost_integration import FeatureTracker

   tracker = FeatureTracker()
   with tracker.track('clip_vision'):
       scores = analyze_image(path)
   with tracker.track('tesseract_ocr'):
       text = extract_text(path)

   print(tracker.summary())

Available Features:
-------------------
- clip_vision         : CLIP model image classification
- tesseract_ocr       : OCR text extraction
- face_detection      : OpenCV face detection
- nominatim_geocoding : GPS reverse geocoding
- keyword_classifier  : Rule-based keyword matching
- pdf_extraction      : PDF text extraction
- docx_extraction     : Word document extraction
- xlsx_extraction     : Excel extraction
- exif_extraction     : Image metadata extraction
- schema_generation   : Schema.org JSON-LD generation
- game_asset_detection: Game asset classification

Reporting:
----------
from src.cost_integration import print_cost_summary, save_cost_report, get_cost_report

# Print summary to console
print_cost_summary()

# Save detailed report to JSON
save_cost_report('results/cost_report.json')

# Get report as dictionary
report = get_cost_report()

Cost Estimation:
----------------
from src.cost_integration import estimate_processing_cost

# Estimate cost for processing 10,000 files
estimate = estimate_processing_cost(10000)
print(f"Estimated cost: ${estimate['total_estimated_cost']:.2f}")
print(f"Estimated time: {estimate['total_estimated_time_human']}")
print(f"Estimated ROI: {estimate['estimated_roi']:.0f}%")
""")
    print("=" * 70)


if __name__ == '__main__':
    print_integration_guide()
