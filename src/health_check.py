"""
System Health Check Module

Validates dependencies and reports feature availability at startup.
"""

import sys
import shutil
from dataclasses import dataclass
from typing import Optional


@dataclass
class FeatureStatus:
    """Status of a single feature."""
    name: str
    available: bool
    version: Optional[str] = None
    error: Optional[str] = None
    impact: str = ""


class SystemHealthChecker:
    """
    Validates system dependencies and reports feature availability.

    Usage:
        checker = SystemHealthChecker()
        checker.run_all_checks()
        checker.print_status()

        # Or check specific feature
        if checker.is_available('clip_vision'):
            # Use CLIP model
    """

    def __init__(self):
        self.features: dict[str, FeatureStatus] = {}
        self._checked = False

    def run_all_checks(self) -> 'SystemHealthChecker':
        """Run all dependency checks."""
        self._check_python_version()
        self._check_pillow()
        self._check_heic_support()
        self._check_ocr()
        self._check_clip_vision()
        self._check_database()
        self._check_geocoding()
        self._check_error_tracking()
        self._check_document_processing()
        self._checked = True
        return self

    def _check_python_version(self) -> None:
        """Check Python version."""
        version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        min_version = (3, 8)
        available = sys.version_info >= min_version
        self.features['python'] = FeatureStatus(
            name="Python",
            available=available,
            version=version,
            error=None if available else f"Requires Python {min_version[0]}.{min_version[1]}+",
            impact="Core functionality"
        )

    def _check_pillow(self) -> None:
        """Check PIL/Pillow for image processing."""
        try:
            from PIL import Image
            import PIL
            self.features['pillow'] = FeatureStatus(
                name="Pillow (Image Processing)",
                available=True,
                version=PIL.__version__,
                impact="JPEG/PNG image loading, EXIF extraction"
            )
        except ImportError as e:
            self.features['pillow'] = FeatureStatus(
                name="Pillow (Image Processing)",
                available=False,
                error=str(e),
                impact="Cannot process images - pip install Pillow"
            )

    def _check_heic_support(self) -> None:
        """Check HEIC/HEIF image support."""
        try:
            import pillow_heif
            self.features['heic'] = FeatureStatus(
                name="HEIC Support",
                available=True,
                version=pillow_heif.__version__,
                impact="iPhone HEIC photos supported"
            )
        except ImportError:
            self.features['heic'] = FeatureStatus(
                name="HEIC Support",
                available=False,
                error="pillow-heif not installed",
                impact="HEIC files skipped - pip install pillow-heif"
            )

    def _check_ocr(self) -> None:
        """Check Tesseract OCR availability."""
        try:
            import pytesseract
            # Check if tesseract binary is available
            tesseract_path = shutil.which('tesseract')
            if tesseract_path:
                try:
                    version = pytesseract.get_tesseract_version()
                    self.features['ocr'] = FeatureStatus(
                        name="OCR (Tesseract)",
                        available=True,
                        version=str(version),
                        impact="Text extraction from images/screenshots"
                    )
                except Exception:
                    self.features['ocr'] = FeatureStatus(
                        name="OCR (Tesseract)",
                        available=True,
                        version="unknown",
                        impact="Text extraction from images/screenshots"
                    )
            else:
                self.features['ocr'] = FeatureStatus(
                    name="OCR (Tesseract)",
                    available=False,
                    error="tesseract binary not found",
                    impact="No OCR - brew install tesseract"
                )
        except ImportError:
            self.features['ocr'] = FeatureStatus(
                name="OCR (Tesseract)",
                available=False,
                error="pytesseract not installed",
                impact="No OCR - pip install pytesseract"
            )

    def _check_clip_vision(self) -> None:
        """Check CLIP model for AI vision classification."""
        try:
            import torch
            import transformers
            self.features['clip_vision'] = FeatureStatus(
                name="AI Vision (CLIP)",
                available=True,
                version=f"torch {torch.__version__}, transformers {transformers.__version__}",
                impact="AI-powered image content classification"
            )
        except ImportError as e:
            missing = []
            try:
                import torch
            except ImportError:
                missing.append("torch")
            try:
                import transformers
            except ImportError:
                missing.append("transformers")

            self.features['clip_vision'] = FeatureStatus(
                name="AI Vision (CLIP)",
                available=False,
                error=f"Missing: {', '.join(missing)}",
                impact="No AI classification - pip install torch transformers"
            )

    def _check_database(self) -> None:
        """Check SQLAlchemy for database storage."""
        try:
            import sqlalchemy
            self.features['database'] = FeatureStatus(
                name="Database (SQLAlchemy)",
                available=True,
                version=sqlalchemy.__version__,
                impact="Graph-based file storage, relationships"
            )
        except ImportError:
            self.features['database'] = FeatureStatus(
                name="Database (SQLAlchemy)",
                available=False,
                error="sqlalchemy not installed",
                impact="No DB storage - pip install sqlalchemy"
            )

    def _check_geocoding(self) -> None:
        """Check geopy for GPS coordinate lookup."""
        try:
            import geopy
            self.features['geocoding'] = FeatureStatus(
                name="Geocoding (geopy)",
                available=True,
                version=geopy.__version__,
                impact="GPS coordinates to location names"
            )
        except ImportError:
            self.features['geocoding'] = FeatureStatus(
                name="Geocoding (geopy)",
                available=False,
                error="geopy not installed",
                impact="No location lookup - pip install geopy"
            )

    def _check_error_tracking(self) -> None:
        """Check Sentry SDK for error tracking."""
        try:
            import sentry_sdk
            self.features['sentry'] = FeatureStatus(
                name="Error Tracking (Sentry)",
                available=True,
                version=sentry_sdk.VERSION,
                impact="Error monitoring and performance tracking"
            )
        except ImportError:
            self.features['sentry'] = FeatureStatus(
                name="Error Tracking (Sentry)",
                available=False,
                error="sentry-sdk not installed",
                impact="No error tracking - pip install sentry-sdk"
            )

    def _check_document_processing(self) -> None:
        """Check document processing libraries."""
        available_libs = []
        missing_libs = []

        # Check python-docx
        try:
            import docx
            available_libs.append("docx")
        except ImportError:
            missing_libs.append("python-docx")

        # Check pypdf
        try:
            import pypdf
            available_libs.append("pypdf")
        except ImportError:
            missing_libs.append("pypdf")

        # Check openpyxl
        try:
            import openpyxl
            available_libs.append("openpyxl")
        except ImportError:
            missing_libs.append("openpyxl")

        if available_libs:
            self.features['documents'] = FeatureStatus(
                name="Document Processing",
                available=True,
                version=", ".join(available_libs),
                impact=f"PDF/Word/Excel parsing ({len(available_libs)}/3 libs)"
            )
        else:
            self.features['documents'] = FeatureStatus(
                name="Document Processing",
                available=False,
                error=f"Missing: {', '.join(missing_libs)}",
                impact="No document parsing available"
            )

    def is_available(self, feature: str) -> bool:
        """Check if a specific feature is available."""
        if not self._checked:
            self.run_all_checks()
        return self.features.get(feature, FeatureStatus("unknown", False)).available

    def get_status(self, feature: str) -> Optional[FeatureStatus]:
        """Get detailed status for a feature."""
        if not self._checked:
            self.run_all_checks()
        return self.features.get(feature)

    def print_status(self, verbose: bool = False) -> None:
        """Print feature availability status."""
        if not self._checked:
            self.run_all_checks()

        available_count = sum(1 for f in self.features.values() if f.available)
        total_count = len(self.features)

        print("\n" + "=" * 60)
        print("SYSTEM HEALTH CHECK")
        print("=" * 60)

        for feature in self.features.values():
            status = "\033[92m[OK]\033[0m" if feature.available else "\033[91m[--]\033[0m"
            version = f" v{feature.version}" if feature.version and feature.available else ""
            print(f"  {status} {feature.name}{version}")

            if verbose or not feature.available:
                if feature.error:
                    print(f"       Error: {feature.error}")
                if not feature.available:
                    print(f"       Impact: {feature.impact}")

        print("-" * 60)
        print(f"Features available: {available_count}/{total_count}")

        if available_count == total_count:
            print("\033[92mAll features operational!\033[0m")
        else:
            missing = total_count - available_count
            print(f"\033[93m{missing} feature(s) unavailable - see above for install commands\033[0m")

        print("=" * 60 + "\n")

    def to_dict(self) -> dict:
        """Export status as dictionary."""
        if not self._checked:
            self.run_all_checks()
        return {
            name: {
                "available": f.available,
                "version": f.version,
                "error": f.error,
                "impact": f.impact
            }
            for name, f in self.features.items()
        }


# Singleton instance for easy access
_checker: Optional[SystemHealthChecker] = None


def get_health_checker() -> SystemHealthChecker:
    """Get or create the singleton health checker instance."""
    global _checker
    if _checker is None:
        _checker = SystemHealthChecker()
    return _checker


def check_system(verbose: bool = False) -> SystemHealthChecker:
    """Run health check and print status."""
    checker = get_health_checker()
    checker.run_all_checks()
    checker.print_status(verbose=verbose)
    return checker


def require_feature(feature: str) -> bool:
    """
    Check if a feature is available, print warning if not.

    Usage:
        if require_feature('clip_vision'):
            # Use CLIP model
        else:
            # Fallback behavior
    """
    checker = get_health_checker()
    if not checker._checked:
        checker.run_all_checks()

    status = checker.get_status(feature)
    if status and not status.available:
        print(f"\033[93mWarning: {status.name} unavailable - {status.impact}\033[0m")
        return False
    return status.available if status else False


if __name__ == "__main__":
    # Run standalone health check
    import argparse
    parser = argparse.ArgumentParser(description="Check system dependencies")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed output")
    args = parser.parse_args()

    check_system(verbose=args.verbose)
