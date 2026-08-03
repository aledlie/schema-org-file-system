"""
Tracking utilities: cost tracking context manager and file processing error tracker.

Re-exports error helper functions from src.error_tracking so callers can import
everything they need from a single place.
"""

import time
from contextlib import contextmanager
from types import TracebackType
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    List,
    Literal,
    Optional,
    ParamSpec,
    TYPE_CHECKING,
    TypedDict,
    TypeVar,
)

if TYPE_CHECKING:
    from sentry_sdk.tracing import Span

P = ParamSpec("P")
R = TypeVar("R")


class FileErrorInfo(TypedDict):
    """One failed file's error record (structural mirror of
    src.error_tracking.FileErrorInfo, usable when that import fails)."""
    file_path: str
    error_type: str
    error_message: str
    category: Optional[str]


class ProcessingStats(TypedDict):
    """Aggregate counters (structural mirror of
    src.error_tracking.ProcessingStats)."""
    processed: int
    succeeded: int
    failed: int
    success_rate: float
    errors: List[FileErrorInfo]


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

    def init_sentry(
        dsn: Optional[str] = None,
        environment: Optional[str] = None,
        traces_sample_rate: float = 0.0,
        profiles_sample_rate: float = 0.0,
        enable_logs: bool = True,
    ) -> bool:
        """Stub: Sentry not available."""
        return False

    def capture_error(
        error: Exception,
        level: str = ErrorLevel.ERROR,
        context: Optional[Dict[str, Any]] = None,
        tags: Optional[Dict[str, str]] = None,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """Stub: no-op capture."""
        return None

    @contextmanager
    def track_operation(
        operation_name: str, op_type: str = "task", **attributes: Any
    ) -> Generator[Optional["Span"], None, None]:
        """Stub: no-op context manager."""
        yield None

    def track_error(
        operation: Optional[str] = None,
        level: str = ErrorLevel.ERROR,
        reraise: bool = True,
    ) -> Callable[[Callable[P, R]], Callable[P, Optional[R]]]:
        """Stub: identity decorator."""
        def decorator(func: Callable[P, R]) -> Callable[P, Optional[R]]:
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
            self.errors: list[FileErrorInfo] = []

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

        def get_stats(self) -> ProcessingStats:
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
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
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
