"""
Tracking utilities: cost tracking context manager and file processing error tracker.

Re-exports error helper functions from src.error_tracking so callers can import
everything they need from a single place.
"""

import time
from contextlib import contextmanager
from typing import Any, Dict, Generator, Literal, Optional

try:
    from src.error_tracking import (
        ErrorLevel,
        FileProcessingErrorTracker,
        capture_error,
        init_sentry,
        track_error,
        track_operation,
    )
except ImportError:
    # Fallback stubs — keeps this module usable when src is not on sys.path

    class ErrorLevel:  # type: ignore[no-redef]
        """Stub error severity levels."""

        FATAL = "fatal"
        ERROR = "error"
        WARNING = "warning"
        INFO = "info"
        DEBUG = "debug"

    def init_sentry(*args: Any, **kwargs: Any) -> bool:
        """Stub: Sentry not available."""
        return False

    def capture_error(*args: Any, **kwargs: Any) -> None:
        """Stub: no-op capture."""

    @contextmanager
    def track_operation(
        operation_name: str, op_type: str = "task", **attributes: Any
    ) -> Generator[None, None, None]:
        """Stub: no-op context manager."""
        yield

    def track_error(
        operation: Optional[str] = None,
        level: str = "error",
        reraise: bool = True,
    ) -> Any:
        """Stub: identity decorator."""
        def decorator(func: Any) -> Any:
            return func
        return decorator

    class FileProcessingErrorTracker:  # type: ignore[no-redef]
        """
        Standalone file processing error tracker (stub — no Sentry).

        Usage::

            tracker = FileProcessingErrorTracker()
            with tracker.track_file("/path/to/file.txt"):
                process(file)
            tracker.print_summary()
        """

        def __init__(self) -> None:
            self.processed: int = 0
            self.succeeded: int = 0
            self.failed: int = 0
            self.errors: list[Dict[str, Any]] = []

        @contextmanager
        def track_file(
            self, file_path: str, category: Optional[str] = None
        ) -> Generator[None, None, None]:
            """Track processing of a single file."""
            self.processed += 1
            try:
                yield
                self.succeeded += 1
            except Exception as exc:
                self.failed += 1
                self.errors.append(
                    {
                        "file_path": file_path,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "category": category,
                    }
                )

        def get_stats(self) -> Dict[str, Any]:
            """Return processing statistics."""
            return {
                "processed": self.processed,
                "succeeded": self.succeeded,
                "failed": self.failed,
                "success_rate": self.succeeded / max(self.processed, 1),
                "errors": self.errors,
            }

        def print_summary(self) -> None:
            """Print a human-readable processing summary."""
            print("\nFile Processing Summary:")
            print(f"  Processed: {self.processed}")
            pct = self.succeeded / max(self.processed, 1) * 100
            print(f"  Succeeded: {self.succeeded} ({pct:.1f}%)")
            print(f"  Failed: {self.failed}")

            if self.errors:
                error_types: Dict[str, int] = {}
                for err in self.errors:
                    key = err["error_type"]
                    error_types[key] = error_types.get(key, 0) + 1

                print("\nError breakdown:")
                for error_type, count in sorted(
                    error_types.items(), key=lambda x: -x[1]
                ):
                    print(f"  {error_type}: {count}")


# ---------------------------------------------------------------------------
# CostTracker — lightweight context manager (no external deps)
# ---------------------------------------------------------------------------

class CostTracker:
    """
    Lightweight cost-tracking context manager.

    When the full ``cost_roi_calculator`` package is available, prefer that
    implementation.  This version provides a zero-dependency fallback that
    records wall-clock duration and exposes it as ``elapsed_seconds``.

    Usage::

        with CostTracker() as ct:
            do_expensive_work()
        print(ct.elapsed_seconds)
    """

    def __init__(self) -> None:
        self._start: Optional[float] = None
        self.elapsed_seconds: float = 0.0

    def __enter__(self) -> "CostTracker":
        self._start = time.monotonic()
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> Literal[False]:
        assert self._start is not None
        self.elapsed_seconds = time.monotonic() - self._start
        return False


__all__ = [
    "CostTracker",
    "ErrorLevel",
    "FileProcessingErrorTracker",
    "capture_error",
    "init_sentry",
    "track_error",
    "track_operation",
]
