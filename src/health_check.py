"""
System Health Check Module

Validates dependencies and reports feature availability at startup.
"""

import sys
from dataclasses import dataclass
from typing import Dict, Optional, TypedDict

try:
    from .constants import SEPARATOR_WIDTH_MEDIUM
except ImportError:
    from constants import SEPARATOR_WIDTH_MEDIUM  # type: ignore[no-redef]


@dataclass
class FeatureStatus:
    """Status of a single feature."""

    name: str
    available: bool
    version: Optional[str] = None
    error: Optional[str] = None
    impact: str = ""


class FeatureStatusDict(TypedDict):
    """One feature's status as exported by SystemHealthChecker.to_dict."""

    available: bool
    version: Optional[str]
    error: Optional[str]
    impact: str


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

    def __init__(self) -> None:
        self.features: dict[str, FeatureStatus] = {}
        self._checked = False

    def run_all_checks(self) -> "SystemHealthChecker":
        """Run all dependency checks."""
        self._check_python_version()
        self._check_pillow()
        self._check_heic_support()
        self._check_ocr()
        self._check_clip_vision()
        self._check_scene_probe()
        self._check_similarity()
        self._check_database()
        self._check_geocoding()
        self._check_error_tracking()
        self._check_document_processing()
        self._check_name_validator()
        self._checked = True
        return self

    def _check_python_version(self) -> None:
        """Check Python version."""
        version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        min_version = (3, 8)
        available = sys.version_info >= min_version
        self.features["python"] = FeatureStatus(
            name="Python",
            available=available,
            version=version,
            error=None if available else f"Requires Python {min_version[0]}.{min_version[1]}+",
            impact="Core functionality",
        )

    def _check_pillow(self) -> None:
        """Check PIL/Pillow for image processing."""
        try:
            import PIL

            self.features["pillow"] = FeatureStatus(
                name="Pillow (Image Processing)",
                available=True,
                version=PIL.__version__,
                impact="JPEG/PNG image loading, EXIF extraction",
            )
        except ImportError as e:
            self.features["pillow"] = FeatureStatus(
                name="Pillow (Image Processing)",
                available=False,
                error=str(e),
                impact="Cannot process images - pip install Pillow",
            )

    def _check_heic_support(self) -> None:
        """Check HEIC/HEIF image support."""
        try:
            import pillow_heif

            self.features["heic"] = FeatureStatus(
                name="HEIC Support",
                available=True,
                version=pillow_heif.__version__,
                impact="iPhone HEIC photos supported",
            )
        except ImportError:
            self.features["heic"] = FeatureStatus(
                name="HEIC Support",
                available=False,
                error="pillow-heif not installed",
                impact="HEIC files skipped - pip install pillow-heif",
            )

    def _check_ocr(self) -> None:
        """Check docTR OCR availability."""
        try:
            import doctr

            self.features["ocr"] = FeatureStatus(
                name="OCR (docTR)",
                available=True,
                version=doctr.__version__,
                impact="Text extraction from images/screenshots",
            )
        except ImportError:
            self.features["ocr"] = FeatureStatus(
                name="OCR (docTR)",
                available=False,
                error="python-doctr not installed",
                impact="No OCR - pip install python-doctr[torch]",
            )

    def _check_clip_vision(self) -> None:
        """Check CLIP model for AI vision classification."""
        try:
            import torch
            import open_clip

            self.features["clip_vision"] = FeatureStatus(
                name="AI Vision (CLIP)",
                available=True,
                version=f"torch {torch.__version__}, open_clip {open_clip.__version__}",
                impact="AI-powered image content classification",
            )
        except ImportError:
            missing = []
            try:
                import torch
            except ImportError:
                missing.append("torch")
            try:
                import open_clip
            except ImportError:
                missing.append("open-clip-torch")

            self.features["clip_vision"] = FeatureStatus(
                name="AI Vision (CLIP)",
                available=False,
                error=f"Missing: {', '.join(missing)}",
                impact="No AI classification - pip install torch open-clip-torch",
            )

    def _check_similarity(self) -> None:
        """Check faiss for the near-duplicate index.

        Reports only on faiss: the SSCD descriptor half needs torch/torchvision,
        already covered by the CLIP check, and its checkpoint downloads on first
        use rather than at install time — so its absence is not a config error.

        Deliberately probes without importing faiss: this checker also imports
        torch, and the two abort the process when both initialise OpenMP
        (see src/similarity/worker.py).
        """
        import importlib.metadata
        import importlib.util

        if importlib.util.find_spec("faiss") is None:
            self.features["similarity"] = FeatureStatus(
                name="Near-duplicate index (faiss)",
                available=False,
                error="Missing: faiss-cpu",
                impact="No near-duplicate report - pip install -e '.[similarity]'",
            )
            return

        try:
            version = importlib.metadata.version("faiss-cpu")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        self.features["similarity"] = FeatureStatus(
            name="Near-duplicate index (faiss)",
            available=True,
            version=version,
            impact="organize-files find-duplicates",
        )

    def _check_database(self) -> None:
        """Check SQLAlchemy for database storage."""
        try:
            import sqlalchemy

            self.features["database"] = FeatureStatus(
                name="Database (SQLAlchemy)",
                available=True,
                version=sqlalchemy.__version__,
                impact="Graph-based file storage, relationships",
            )
        except ImportError:
            self.features["database"] = FeatureStatus(
                name="Database (SQLAlchemy)",
                available=False,
                error="sqlalchemy not installed",
                impact="No DB storage - pip install sqlalchemy",
            )

    def _check_geocoding(self) -> None:
        """Check geopy for GPS coordinate lookup."""
        try:
            import geopy

            self.features["geocoding"] = FeatureStatus(
                name="Geocoding (geopy)",
                available=True,
                # getattr: test suites stub geopy in sys.modules without __version__
                version=getattr(geopy, "__version__", "unknown"),
                impact="GPS coordinates to location names",
            )
        except ImportError:
            self.features["geocoding"] = FeatureStatus(
                name="Geocoding (geopy)",
                available=False,
                error="geopy not installed",
                impact="No location lookup - pip install geopy",
            )

    def _check_error_tracking(self) -> None:
        """Check Sentry SDK for error tracking."""
        try:
            import sentry_sdk

            self.features["sentry"] = FeatureStatus(
                name="Error Tracking (Sentry)",
                available=True,
                version=sentry_sdk.VERSION,
                impact="Error monitoring and performance tracking",
            )
        except ImportError:
            self.features["sentry"] = FeatureStatus(
                name="Error Tracking (Sentry)",
                available=False,
                error="sentry-sdk not installed",
                impact="No error tracking - pip install sentry-sdk",
            )

    def _check_document_processing(self) -> None:
        """Check document processing libraries."""
        available_libs = []
        missing_libs = []

        # Check python-docx
        try:
            import docx  # noqa: F401 — import IS the availability probe

            available_libs.append("docx")
        except ImportError:
            missing_libs.append("python-docx")

        # Check pypdf
        try:
            import pypdf  # noqa: F401 — import IS the availability probe

            available_libs.append("pypdf")
        except ImportError:
            missing_libs.append("pypdf")

        # Check openpyxl
        try:
            import openpyxl  # noqa: F401 — import IS the availability probe

            available_libs.append("openpyxl")
        except ImportError:
            missing_libs.append("openpyxl")

        if available_libs:
            self.features["documents"] = FeatureStatus(
                name="Document Processing",
                available=True,
                version=", ".join(available_libs),
                impact=f"PDF/Word/Excel parsing ({len(available_libs)}/3 libs)",
            )
        else:
            self.features["documents"] = FeatureStatus(
                name="Document Processing",
                available=False,
                error=f"Missing: {', '.join(missing_libs)}",
                impact="No document parsing available",
            )

    def _check_scene_probe(self) -> None:
        """Check the trained scene-probe artifact (``SceneSignal``)."""
        # Without the probe, no signal votes interiors/exteriors/places/opaque
        # graphics at all (the binary interior probe and photo_composition's
        # interior vote were retired with the SceneSignal swap) — those images
        # fall to weaker generic signals or the low-margin fallback.
        impact_when_missing = (
            "SceneSignal no-ops — interior/exterior/place/graphic scenes get "
            "no scene vote and fall to weaker generic signals or the "
            "low-margin fallback"
        )
        try:
            from scoring.signals import scene
        except ImportError:
            try:
                from src.scoring.signals import scene  # type: ignore[no-redef]
            except ImportError:
                self.features["scene_probe"] = FeatureStatus(
                    name="Scene Probe",
                    available=False,
                    error="scoring.signals.scene not importable",
                    impact=impact_when_missing,
                )
                return

        if not scene.PROBE_PATH.exists():
            self.features["scene_probe"] = FeatureStatus(
                name="Scene Probe",
                available=False,
                error=(
                    f"artifact missing: {scene.PROBE_PATH} — train with "
                    "'python scripts/prototype_scene_probe.py train'"
                ),
                impact=impact_when_missing,
            )
            return

        if scene.load_probe(scene.PROBE_PATH) is None:
            self.features["scene_probe"] = FeatureStatus(
                name="Scene Probe",
                available=False,
                error=(
                    f"artifact unreadable: {scene.PROBE_PATH} "
                    "(joblib/scikit-learn missing, or corrupt file — retrain)"
                ),
                impact=impact_when_missing,
            )
            return

        self.features["scene_probe"] = FeatureStatus(
            name="Scene Probe",
            available=True,
            version=str(scene.PROBE_PATH),
            impact="Trained CLIP-embedding scene classification active (SceneSignal)",
        )

    def _check_name_validator(self) -> None:
        """Check person-name validation layers (``names`` extra)."""
        try:
            from classifiers.person_name_validator import available_layers
        except ImportError:
            try:
                from src.classifiers.person_name_validator import (  # type: ignore[no-redef]
                    available_layers,
                )
            except ImportError:
                self.features["name_validator"] = FeatureStatus(
                    name="Person-Name Validator",
                    available=False,
                    error="person_name_validator module not found",
                    impact="No person-name validation — all detected names route to review",
                )
                return

        layers = available_layers()
        active = [name for name, ok in layers.items() if ok]
        missing = [name for name, ok in layers.items() if not ok]
        # denylist is always available; the optional layers add precision
        optional_ok = layers.get("shape", False) and layers.get("probablepeople", False)
        self.features["name_validator"] = FeatureStatus(
            name="Person-Name Validator",
            available=True,
            version=f"layers: {', '.join(active)}",
            error=(
                f"optional layers unavailable: {', '.join(missing)} "
                "(pip install nameparser probablepeople)"
                if missing and not optional_ok
                else None
            ),
            impact=(
                "Name validation active — precision increases with optional layers"
                if optional_ok
                else "Name validation degraded — optional layers missing; "
                "install nameparser probablepeople for higher precision"
            ),
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

        print("\n" + "=" * SEPARATOR_WIDTH_MEDIUM)
        print("SYSTEM HEALTH CHECK")
        print("=" * SEPARATOR_WIDTH_MEDIUM)

        for feature in self.features.values():
            status = "\033[92m[OK]\033[0m" if feature.available else "\033[91m[--]\033[0m"
            version = f" v{feature.version}" if feature.version and feature.available else ""
            print(f"  {status} {feature.name}{version}")

            if verbose or not feature.available:
                if feature.error:
                    print(f"       Error: {feature.error}")
                if not feature.available:
                    print(f"       Impact: {feature.impact}")

        print("-" * SEPARATOR_WIDTH_MEDIUM)
        print(f"Features available: {available_count}/{total_count}")

        if available_count == total_count:
            print("\033[92mAll features operational!\033[0m")
        else:
            missing = total_count - available_count
            print(
                f"\033[93m{missing} feature(s) unavailable - see above for install commands\033[0m"
            )

        print("=" * SEPARATOR_WIDTH_MEDIUM + "\n")

    def to_dict(self) -> Dict[str, FeatureStatusDict]:
        """Export status as dictionary."""
        if not self._checked:
            self.run_all_checks()
        return {
            name: {
                "available": f.available,
                "version": f.version,
                "error": f.error,
                "impact": f.impact,
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
