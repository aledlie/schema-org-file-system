"""Unit tests for src.utils.tracking."""

import pytest

from src.utils.tracking import CostTracker, FileProcessingErrorTracker

# ---------------------------------------------------------------------------
# CostTracker tests
# ---------------------------------------------------------------------------


class TestCostTracker:
    def test_context_manager_returns_self(self) -> None:
        with CostTracker() as ct:
            assert isinstance(ct, CostTracker)

    def test_elapsed_seconds_is_non_negative(self) -> None:
        with CostTracker() as ct:
            pass
        assert ct.elapsed_seconds >= 0.0

    def test_elapsed_seconds_zero_before_exit(self) -> None:
        ct = CostTracker()
        assert ct.elapsed_seconds == 0.0
        with ct:
            assert ct.elapsed_seconds == 0.0

    def test_does_not_suppress_exceptions(self) -> None:
        with pytest.raises(ValueError):
            with CostTracker():
                raise ValueError("boom")

    def test_elapsed_recorded_even_on_exception(self) -> None:
        ct = CostTracker()
        try:
            with ct:
                raise RuntimeError("fail")
        except RuntimeError:
            pass
        assert ct.elapsed_seconds >= 0.0


# ---------------------------------------------------------------------------
# FileProcessingErrorTracker tests
# ---------------------------------------------------------------------------


class TestFileProcessingErrorTracker:
    def test_initial_counters_are_zero(self) -> None:
        tracker = FileProcessingErrorTracker()
        assert tracker.processed == 0
        assert tracker.succeeded == 0
        assert tracker.failed == 0
        assert tracker.errors == []

    def test_track_file_increments_processed_and_succeeded(self) -> None:
        tracker = FileProcessingErrorTracker()
        with tracker.track_file("/some/file.txt"):
            pass
        assert tracker.processed == 1
        assert tracker.succeeded == 1
        assert tracker.failed == 0

    def test_track_file_increments_failed_on_exception(self) -> None:
        tracker = FileProcessingErrorTracker()
        with tracker.track_file("/bad/file.txt"):
            raise OSError("read error")
        assert tracker.processed == 1
        assert tracker.succeeded == 0
        assert tracker.failed == 1

    def test_track_file_records_error_info(self) -> None:
        tracker = FileProcessingErrorTracker()
        with tracker.track_file("/bad/file.txt", category="images"):
            raise ValueError("bad value")
        assert len(tracker.errors) == 1
        err = tracker.errors[0]
        assert err["file_path"] == "/bad/file.txt"
        assert err["error_type"] == "ValueError"
        assert "bad value" in err["error_message"]
        assert err["category"] == "images"

    def test_track_file_does_not_reraise(self) -> None:
        tracker = FileProcessingErrorTracker()
        with tracker.track_file("/file.txt"):
            raise RuntimeError("suppressed")
        assert tracker.failed == 1

    def test_multiple_files_mixed_results(self) -> None:
        tracker = FileProcessingErrorTracker()
        with tracker.track_file("/ok1.txt"):
            pass
        with tracker.track_file("/ok2.txt"):
            pass
        with tracker.track_file("/bad.txt"):
            raise IOError("oops")
        assert tracker.processed == 3
        assert tracker.succeeded == 2
        assert tracker.failed == 1

    def test_get_stats_shape(self) -> None:
        tracker = FileProcessingErrorTracker()
        with tracker.track_file("/a.txt"):
            pass
        with tracker.track_file("/b.txt"):
            raise KeyError("missing")
        stats = tracker.get_stats()
        assert set(stats.keys()) == {"processed", "succeeded", "failed", "success_rate", "errors"}
        assert stats["processed"] == 2
        assert stats["succeeded"] == 1
        assert stats["failed"] == 1
        assert stats["success_rate"] == pytest.approx(0.5)

    def test_get_stats_success_rate_zero_processed(self) -> None:
        tracker = FileProcessingErrorTracker()
        stats = tracker.get_stats()
        assert stats["success_rate"] == pytest.approx(0.0)

    def test_print_summary_does_not_raise(self, capsys: pytest.CaptureFixture) -> None:
        tracker = FileProcessingErrorTracker()
        with tracker.track_file("/ok.txt"):
            pass
        with tracker.track_file("/bad.txt"):
            raise RuntimeError("fail")
        tracker.print_summary()
        captured = capsys.readouterr()
        assert "Processed" in captured.out
        assert "Succeeded" in captured.out
        assert "Failed" in captured.out

    def test_print_summary_empty_tracker(self, capsys: pytest.CaptureFixture) -> None:
        tracker = FileProcessingErrorTracker()
        tracker.print_summary()  # should not raise
        captured = capsys.readouterr()
        assert "Processed" in captured.out
