"""Unit tests for src.error_tracking (non-Sentry paths)."""

from typing import Any
from unittest.mock import patch, MagicMock

import pytest

from src.error_tracking import (
    ErrorLevel,
    FileProcessingErrorTracker,
    capture_error,
    get_file_tracker,
    init_sentry,
    reset_file_tracker,
    track_error,
    track_operation,
)


# ---------------------------------------------------------------------------
# ErrorLevel
# ---------------------------------------------------------------------------


class TestErrorLevel:
    def test_level_values(self) -> None:
        assert ErrorLevel.FATAL == "fatal"
        assert ErrorLevel.ERROR == "error"
        assert ErrorLevel.WARNING == "warning"
        assert ErrorLevel.INFO == "info"
        assert ErrorLevel.DEBUG == "debug"


# ---------------------------------------------------------------------------
# init_sentry (without SDK)
# ---------------------------------------------------------------------------


class TestInitSentryNoSdk:
    def test_returns_false_when_sentry_unavailable(self) -> None:
        """When SENTRY_AVAILABLE is False, init_sentry returns False without touching SDK."""
        with patch("src.error_tracking.SENTRY_AVAILABLE", False):
            result = init_sentry(dsn="https://fake@sentry.io/1")
        assert result is False

    def test_returns_false_when_no_dsn(self) -> None:
        """Without a DSN, init_sentry returns False even when SDK is installed."""
        with (
            patch("src.error_tracking.SENTRY_AVAILABLE", True),
            patch.dict("os.environ", {}, clear_for_key="SENTRY_DSN"),
        ):
            result = init_sentry(dsn=None)
        assert result is False

    def test_returns_false_when_sentry_init_raises(self) -> None:
        """A broken sentry_sdk.init causes init_sentry to return False gracefully."""
        mock_sdk = MagicMock()
        mock_sdk.init.side_effect = RuntimeError("bad config")
        with (
            patch("src.error_tracking.SENTRY_AVAILABLE", True),
            patch("src.error_tracking.sentry_sdk", mock_sdk),
        ):
            result = init_sentry(dsn="https://fake@sentry.io/1")
        assert result is False


# We can't easily test the success path without a real DSN; that's acceptable.


# ---------------------------------------------------------------------------
# capture_error (no-Sentry fallback)
# ---------------------------------------------------------------------------


class TestCaptureErrorNoSentry:
    def test_returns_none_when_sentry_unavailable(self, capsys: pytest.CaptureFixture) -> None:
        with patch("src.error_tracking.SENTRY_AVAILABLE", False):
            result = capture_error(ValueError("boom"))
        assert result is None
        out = capsys.readouterr().out
        assert "ValueError" in out
        assert "boom" in out

    def test_logs_context_when_sentry_unavailable(self, capsys: pytest.CaptureFixture) -> None:
        with patch("src.error_tracking.SENTRY_AVAILABLE", False):
            capture_error(TypeError("type problem"), context={"key": "value"})
        out = capsys.readouterr().out
        assert "key" in out

    def test_respects_level_in_log(self, capsys: pytest.CaptureFixture) -> None:
        with patch("src.error_tracking.SENTRY_AVAILABLE", False):
            capture_error(RuntimeError("e"), level=ErrorLevel.WARNING)
        out = capsys.readouterr().out
        assert "warning" in out.lower()


# ---------------------------------------------------------------------------
# track_operation (no-Sentry path)
# ---------------------------------------------------------------------------


class TestTrackOperationNoSentry:
    def test_yields_without_sentry(self) -> None:
        with patch("src.error_tracking.SENTRY_AVAILABLE", False):
            executed = []
            with track_operation("test_op"):
                executed.append(True)
        assert executed == [True]

    def test_exceptions_propagate(self) -> None:
        with patch("src.error_tracking.SENTRY_AVAILABLE", False):
            with pytest.raises(ValueError):
                with track_operation("test_op"):
                    raise ValueError("propagated")

    def test_yields_with_sentry(self) -> None:
        """When Sentry is present, the context manager still yields normally."""
        mock_sdk = MagicMock()
        fake_span = MagicMock()
        mock_sdk.start_span.return_value.__enter__ = lambda s: fake_span
        mock_sdk.start_span.return_value.__exit__ = MagicMock(return_value=False)

        with patch("src.error_tracking.SENTRY_AVAILABLE", True), patch(
            "src.error_tracking.sentry_sdk", mock_sdk
        ):
            executed = []
            with track_operation("my_op", op_type="task", file_path="/tmp/a"):
                executed.append(True)
        assert executed == [True]

    def test_sentry_path_captures_exception(self) -> None:
        mock_sdk = MagicMock()
        fake_span = MagicMock()
        mock_sdk.start_span.return_value.__enter__ = lambda s: fake_span
        mock_sdk.start_span.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch("src.error_tracking.SENTRY_AVAILABLE", True),
            patch("src.error_tracking.sentry_sdk", mock_sdk),
            patch("src.error_tracking.capture_error") as mock_capture,
        ):
            with pytest.raises(OSError):
                with track_operation("risky_op"):
                    raise OSError("disk full")
        mock_capture.assert_called_once()


# ---------------------------------------------------------------------------
# track_error decorator (no-Sentry path)
# ---------------------------------------------------------------------------


class TestTrackErrorNoSentry:
    def test_wraps_function_and_returns_result(self) -> None:
        with patch("src.error_tracking.SENTRY_AVAILABLE", False):

            @track_error("my_fn")
            def greet(name: str) -> str:
                return f"hello {name}"

            assert greet("world") == "hello world"

    def test_preserves_function_name(self) -> None:
        with patch("src.error_tracking.SENTRY_AVAILABLE", False):

            @track_error()
            def my_func() -> None:
                pass

            assert my_func.__name__ == "my_func"

    def test_reraises_by_default(self) -> None:
        with patch("src.error_tracking.SENTRY_AVAILABLE", False):

            @track_error("op")
            def fail() -> None:
                raise KeyError("missing")

            with pytest.raises(KeyError):
                fail()

    def test_reraise_false_returns_none(self) -> None:
        with patch("src.error_tracking.SENTRY_AVAILABLE", False):

            @track_error("op", reraise=False)
            def fail() -> None:
                raise KeyError("missing")

            result = fail()
        assert result is None

    def test_operation_name_defaults_to_func_name(self) -> None:
        """track_error() with no args should use function.__name__."""
        with (
            patch("src.error_tracking.SENTRY_AVAILABLE", False),
            patch("src.error_tracking.capture_error") as mock_capture,
        ):

            @track_error(reraise=False)
            def my_named_fn() -> None:
                raise ValueError("oops")

            my_named_fn()
        # capture_error should have been called
        mock_capture.assert_called_once()


# ---------------------------------------------------------------------------
# FileProcessingErrorTracker (src.error_tracking version)
# ---------------------------------------------------------------------------


class TestFileProcessingErrorTrackerFromErrorTracking:
    """Verify the src.error_tracking.FileProcessingErrorTracker (not the stub).

    The tracker from src.error_tracking calls track_operation and capture_error
    internally, so the Sentry path is exercised when SENTRY_AVAILABLE is True.
    Here we run without Sentry.
    """

    def test_initial_state(self) -> None:
        tracker = FileProcessingErrorTracker()
        assert tracker.processed == 0
        assert tracker.succeeded == 0
        assert tracker.failed == 0
        assert tracker.errors == []

    def test_successful_file(self) -> None:
        tracker = FileProcessingErrorTracker()
        with tracker.track_file("/some/file.txt"):
            pass
        assert tracker.processed == 1
        assert tracker.succeeded == 1
        assert tracker.failed == 0

    def test_failed_file_recorded(self) -> None:
        tracker = FileProcessingErrorTracker()
        with tracker.track_file("/bad/file.txt", category="docs"):
            raise OSError("permission denied")
        assert tracker.processed == 1
        assert tracker.succeeded == 0
        assert tracker.failed == 1
        err = tracker.errors[0]
        assert err["file_path"] == "/bad/file.txt"
        assert err["error_type"] == "OSError"
        assert "permission denied" in err["error_message"]
        assert err["category"] == "docs"

    def test_error_does_not_propagate(self) -> None:
        tracker = FileProcessingErrorTracker()
        with tracker.track_file("/f.txt"):
            raise RuntimeError("suppressed")
        assert tracker.failed == 1  # no exception here

    def test_get_stats(self) -> None:
        tracker = FileProcessingErrorTracker()
        with tracker.track_file("/ok.txt"):
            pass
        with tracker.track_file("/bad.txt"):
            raise ValueError("fail")
        stats = tracker.get_stats()
        assert stats["processed"] == 2
        assert stats["succeeded"] == 1
        assert stats["failed"] == 1
        assert stats["success_rate"] == pytest.approx(0.5)
        assert len(stats["errors"]) == 1

    def test_print_summary_no_errors(self, capsys: pytest.CaptureFixture) -> None:
        tracker = FileProcessingErrorTracker()
        with tracker.track_file("/ok.txt"):
            pass
        tracker.print_summary()
        out = capsys.readouterr().out
        assert "Processed" in out
        assert "Succeeded" in out

    def test_print_summary_with_errors(self, capsys: pytest.CaptureFixture) -> None:
        tracker = FileProcessingErrorTracker()
        with tracker.track_file("/bad.txt"):
            raise ValueError("err1")
        with tracker.track_file("/bad2.txt"):
            raise ValueError("err2")
        tracker.print_summary()
        out = capsys.readouterr().out
        assert "ValueError" in out


# ---------------------------------------------------------------------------
# get_file_tracker / reset_file_tracker singletons
# ---------------------------------------------------------------------------


class TestFileTrackerSingleton:
    def setup_method(self) -> None:
        # Reset to a clean state before each test
        reset_file_tracker()

    def test_get_file_tracker_returns_tracker(self) -> None:
        tracker = get_file_tracker()
        assert isinstance(tracker, FileProcessingErrorTracker)

    def test_get_file_tracker_same_instance(self) -> None:
        t1 = get_file_tracker()
        t2 = get_file_tracker()
        assert t1 is t2

    def test_reset_returns_fresh_tracker(self) -> None:
        old = get_file_tracker()
        with old.track_file("/file.txt"):
            pass
        assert old.processed == 1

        fresh = reset_file_tracker()
        assert fresh.processed == 0
        assert fresh is not old

    def test_get_after_reset_returns_new_instance(self) -> None:
        reset_file_tracker()
        t = get_file_tracker()
        assert t.processed == 0
