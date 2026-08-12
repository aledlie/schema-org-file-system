"""Unit tests for scripts/shared/ utilities."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts/ is on sys.path so `from shared.x import y` resolves.
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from shared.clip_classification import CLIPResult  # noqa: E402
from shared.db_utils import db_connection, get_db_connection  # noqa: E402
from shared.file_ops import is_os_junk_file, resolve_collision  # noqa: E402

# ---------------------------------------------------------------------------
# is_os_junk_file
# ---------------------------------------------------------------------------


class TestIsOsJunkFile:
    @pytest.mark.parametrize(
        "name", [".DS_Store", "Thumbs.db", ".localized", "desktop.ini", "._resume.pdf"]
    )
    def test_junk_names_detected(self, name: str) -> None:
        assert is_os_junk_file(name) is True

    @pytest.mark.parametrize("name", ["resume.pdf", "passport.jpg", "notes.txt", "DS_Store"])
    def test_real_files_not_flagged(self, name: str) -> None:
        assert is_os_junk_file(name) is False


# ---------------------------------------------------------------------------
# resolve_collision
# ---------------------------------------------------------------------------


class TestResolveCollision:
    def test_no_collision_returns_path_unchanged(self, temp_dir: Path) -> None:
        target = temp_dir / "image.png"
        assert resolve_collision(target) == target

    def test_single_collision_appends_1(self, temp_dir: Path) -> None:
        existing = temp_dir / "image.png"
        existing.touch()
        result = resolve_collision(temp_dir / "image.png")
        assert result == temp_dir / "image_1.png"

    def test_multiple_collisions_increments_counter(self, temp_dir: Path) -> None:
        (temp_dir / "image.png").touch()
        (temp_dir / "image_1.png").touch()
        result = resolve_collision(temp_dir / "image.png")
        assert result == temp_dir / "image_2.png"

    def test_preserves_extension(self, temp_dir: Path) -> None:
        (temp_dir / "doc.pdf").touch()
        result = resolve_collision(temp_dir / "doc.pdf")
        assert result.suffix == ".pdf"
        assert result.stem == "doc_1"


# ---------------------------------------------------------------------------
# get_db_connection
# ---------------------------------------------------------------------------


class TestGetDbConnection:
    def test_returns_sqlite_connection(self, temp_db_path: str) -> None:
        conn = get_db_connection(temp_db_path)
        try:
            assert isinstance(conn, sqlite3.Connection)
        finally:
            conn.close()

    def test_row_factory_enabled_by_default(self, temp_db_path: str) -> None:
        conn = get_db_connection(temp_db_path)
        try:
            assert conn.row_factory is sqlite3.Row
        finally:
            conn.close()

    def test_row_factory_disabled(self, temp_db_path: str) -> None:
        conn = get_db_connection(temp_db_path, row_factory=False)
        try:
            assert conn.row_factory is None
        finally:
            conn.close()

    def test_creates_database_file(self, temp_db_path: str) -> None:
        conn = get_db_connection(temp_db_path)
        conn.close()
        assert Path(temp_db_path).exists()


# ---------------------------------------------------------------------------
# db_connection
# ---------------------------------------------------------------------------


class TestDbConnection:
    def test_yields_connection(self, temp_db_path: str) -> None:
        with db_connection(temp_db_path) as conn:
            assert isinstance(conn, sqlite3.Connection)

    def test_connection_closed_after_block(self, temp_db_path: str) -> None:
        with db_connection(temp_db_path) as conn:
            pass
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_write_requires_explicit_commit(self, temp_db_path: str) -> None:
        with db_connection(temp_db_path) as conn:
            conn.execute("CREATE TABLE t (v TEXT)")
            conn.execute("INSERT INTO t VALUES ('hello')")
            conn.commit()

        with db_connection(temp_db_path) as conn:
            row = conn.execute("SELECT v FROM t").fetchone()
            assert row["v"] == "hello"

    def test_no_auto_commit_on_exit(self, temp_db_path: str) -> None:
        """Verify that data written without commit is not persisted."""
        with db_connection(temp_db_path) as conn:
            conn.execute("CREATE TABLE t2 (v TEXT)")
            conn.commit()

        with db_connection(temp_db_path) as conn:
            conn.execute("INSERT INTO t2 VALUES ('uncommitted')")

        with db_connection(temp_db_path) as conn:
            rows = conn.execute("SELECT * FROM t2").fetchall()
            assert len(rows) == 0


# ---------------------------------------------------------------------------
# extract_ocr_text
# ---------------------------------------------------------------------------


class TestExtractOcrText:
    def test_returns_none_when_ocr_unavailable(self, sample_image_file: Path) -> None:
        from shared.ocr_classifier import OCR_AVAILABLE, extract_ocr_text

        if OCR_AVAILABLE:
            pytest.skip("doctr is installed; skipping unavailability test")
        result = extract_ocr_text(sample_image_file)
        assert result is None

    def test_returns_none_or_str_for_valid_image(self, sample_image_file: Path) -> None:
        from shared.ocr_classifier import extract_ocr_text

        result = extract_ocr_text(sample_image_file)
        assert result is None or isinstance(result, str)

    def test_truncates_to_max_chars(self, sample_image_file: Path) -> None:
        from shared.ocr_classifier import OCR_AVAILABLE, extract_ocr_text

        if not OCR_AVAILABLE:
            pytest.skip("doctr not installed")
        result = extract_ocr_text(sample_image_file, max_chars=10)
        if result is not None:
            assert len(result) <= 13  # 10 chars + "..."


# ---------------------------------------------------------------------------
# extract_ocr_with_confidence
# ---------------------------------------------------------------------------


class TestExtractOcrWithConfidence:
    def test_returns_none_when_ocr_unavailable(self, sample_image_file: Path) -> None:
        from shared.ocr_classifier import OCR_AVAILABLE, extract_ocr_with_confidence

        if OCR_AVAILABLE:
            pytest.skip("doctr is installed; skipping unavailability test")
        result = extract_ocr_with_confidence(sample_image_file)
        assert result is None

    def test_returns_ocr_result_or_none(self, sample_image_file: Path) -> None:
        from shared.ocr_classifier import OCRResult, extract_ocr_with_confidence

        result = extract_ocr_with_confidence(sample_image_file)
        assert result is None or isinstance(result, OCRResult)

    def test_result_has_confidence_and_metadata(self, sample_image_file: Path) -> None:
        from shared.ocr_classifier import OCR_AVAILABLE, extract_ocr_with_confidence

        if not OCR_AVAILABLE:
            pytest.skip("doctr not installed")
        result = extract_ocr_with_confidence(sample_image_file)
        if result is not None:
            assert 0.0 <= result.confidence <= 1.0
            assert result.word_count > 0
            assert isinstance(result.text, str)
            # language and orientation may be None for simple images


class TestDoctrFallbackGate:
    """Clean-negative gate in extract_ocr_with_confidence (P2) and its
    force_doctr_fallback override."""

    @pytest.fixture()
    def gated(self, monkeypatch: pytest.MonkeyPatch):
        """Force the easyocr-first path and record whether docTR ran."""
        from shared import ocr_classifier

        doctr_calls: list = []

        def fake_run_image_ocr(image_path):
            doctr_calls.append(image_path)
            return None

        monkeypatch.setattr(ocr_classifier, "EASYOCR_AVAILABLE", True)
        monkeypatch.setattr(ocr_classifier, "_run_image_ocr", fake_run_image_ocr)
        return ocr_classifier, doctr_calls

    def test_clean_negative_skips_doctr_by_default(
        self, gated, monkeypatch: pytest.MonkeyPatch, sample_image_file: Path
    ) -> None:
        ocr_classifier, doctr_calls = gated
        monkeypatch.setattr(
            ocr_classifier,
            "extract_text_easyocr_with_status",
            lambda path, max_chars=0: (None, False),
        )
        assert ocr_classifier.extract_ocr_with_confidence(sample_image_file) is None
        assert doctr_calls == []

    def test_force_doctr_fallback_runs_doctr_on_clean_negative(
        self, gated, monkeypatch: pytest.MonkeyPatch, sample_image_file: Path
    ) -> None:
        ocr_classifier, doctr_calls = gated
        monkeypatch.setattr(
            ocr_classifier,
            "extract_text_easyocr_with_status",
            lambda path, max_chars=0: (None, False),
        )
        result = ocr_classifier.extract_ocr_with_confidence(
            sample_image_file, force_doctr_fallback=True
        )
        assert result is None  # fake docTR found nothing
        assert doctr_calls == [sample_image_file]

    def test_easyocr_error_still_falls_back_to_doctr(
        self, gated, monkeypatch: pytest.MonkeyPatch, sample_image_file: Path
    ) -> None:
        ocr_classifier, doctr_calls = gated
        monkeypatch.setattr(
            ocr_classifier,
            "extract_text_easyocr_with_status",
            lambda path, max_chars=0: (None, True),
        )
        assert ocr_classifier.extract_ocr_with_confidence(sample_image_file) is None
        assert doctr_calls == [sample_image_file]

    def test_easyocr_hit_short_circuits(
        self, gated, monkeypatch: pytest.MonkeyPatch, sample_image_file: Path
    ) -> None:
        from shared.ocr_classifier import OCRResult

        ocr_classifier, doctr_calls = gated
        hit = OCRResult(text="hello", confidence=0.9, language="en", word_count=1, orientation=None)
        monkeypatch.setattr(
            ocr_classifier,
            "extract_text_easyocr_with_status",
            lambda path, max_chars=0: (hit, False),
        )
        result = ocr_classifier.extract_ocr_with_confidence(
            sample_image_file, force_doctr_fallback=True
        )
        assert result is hit
        assert doctr_calls == []


# ---------------------------------------------------------------------------
# title_snippet_from_lines
# ---------------------------------------------------------------------------


class TestTitleSnippetFromLines:
    def test_none_input(self) -> None:
        from shared.filename_utils import title_snippet_from_lines

        assert title_snippet_from_lines(None) is None
        assert title_snippet_from_lines([]) is None

    def test_picks_first_title_sized_line(self) -> None:
        from shared.filename_utils import title_snippet_from_lines

        lines = ["Order Confirmation - Amazon", "Thank you for your order"]
        assert title_snippet_from_lines(lines) == "Order_Confirmation_-_Amazon"

    def test_skips_short_ui_chrome(self) -> None:
        from shared.filename_utils import title_snippet_from_lines

        # "File Edit" style menu fragments are <= 10 chars and skipped
        lines = ["File Edit", "View Help", "Invoice from Acme Corp"]
        assert title_snippet_from_lines(lines) == "Invoice_from_Acme_Corp"

    def test_skips_long_body_text(self) -> None:
        from shared.filename_utils import title_snippet_from_lines

        long_line = "This is a very long body paragraph that clearly is not a window title"
        assert title_snippet_from_lines([long_line]) is None

    def test_only_first_three_lines_considered(self) -> None:
        from shared.filename_utils import title_snippet_from_lines

        lines = ["a", "b", "c", "A perfectly good title line"]
        assert title_snippet_from_lines(lines) is None

    def test_sanitizes_special_characters(self) -> None:
        from shared.filename_utils import title_snippet_from_lines

        assert title_snippet_from_lines(["Re: [URGENT] Q4 report!"]) == "Re_URGENT_Q4_report"

    def test_caps_length_at_40(self) -> None:
        from shared.filename_utils import title_snippet_from_lines

        line = "abcdefghij " * 4  # 43 chars stripped -> within (10, 50), caps to 40
        result = title_snippet_from_lines([line.strip()])
        assert result is not None
        assert len(result) <= 40

    def test_punctuation_only_line_rejected(self) -> None:
        from shared.filename_utils import title_snippet_from_lines

        assert title_snippet_from_lines(["--- ~~~ !!! ??? ***"]) is None


# ---------------------------------------------------------------------------
# extract_screenshot_lines
# ---------------------------------------------------------------------------


class TestExtractScreenshotLines:
    def test_returns_none_or_lines_for_valid_image(self, sample_image_file: Path) -> None:
        from shared.ocr_classifier import extract_screenshot_lines

        result = extract_screenshot_lines(sample_image_file)
        assert result is None or (
            isinstance(result, list) and all(isinstance(x, str) and x for x in result)
        )

    def test_doctr_fallback_splits_render_lines(self, sample_image_file: Path) -> None:
        from unittest.mock import MagicMock, patch

        import shared.ocr_classifier as oc

        fake_result = MagicMock()
        fake_result.render.return_value = "Title  Line\n\n  body   text here \n"
        with (
            patch.object(oc, "EASYOCR_AVAILABLE", False),
            patch.object(oc, "_run_image_ocr", return_value=fake_result),
        ):
            lines = oc.extract_screenshot_lines(sample_image_file)

        assert lines == ["Title Line", "body text here"]

    def test_easyocr_preferred_when_available(self, sample_image_file: Path) -> None:
        from unittest.mock import patch

        import shared.ocr_classifier as oc

        with (
            patch.object(oc, "EASYOCR_AVAILABLE", True),
            patch.object(oc, "extract_lines_easyocr", return_value=["From Easy"]) as easy,
            patch.object(oc, "_run_image_ocr") as doctr,
        ):
            lines = oc.extract_screenshot_lines(sample_image_file)

        assert lines == ["From Easy"]
        easy.assert_called_once()
        doctr.assert_not_called()

    def test_returns_none_when_no_backend_produces_text(self, sample_image_file: Path) -> None:
        from unittest.mock import patch

        import shared.ocr_classifier as oc

        with (
            patch.object(oc, "EASYOCR_AVAILABLE", False),
            patch.object(oc, "_run_image_ocr", return_value=None),
        ):
            assert oc.extract_screenshot_lines(sample_image_file) is None


# ---------------------------------------------------------------------------
# CLIPResult — decision_scores / raw_scores / all_scores (deprecated alias)
# ---------------------------------------------------------------------------


class TestCLIPResultScoreFields:
    """CLIPResult carries two named distributions and a deprecated alias.

    decision_scores — prefixed pass that chose the winner.
    raw_scores      — unprefixed pass (flatter distribution).
    all_scores      — deprecated alias for raw_scores; zero in-repo readers.
    """

    _DECISION = {"sofa": 0.0120, "chair": 0.0110}
    _RAW = {"sofa": 0.0115, "chair": 0.0118}

    def _make_result(self, margin: float | None = None) -> CLIPResult:
        return CLIPResult("sofa", 0.0120, self._DECISION, self._RAW, margin)

    def test_decision_scores_holds_prefixed_distribution(self) -> None:
        r = self._make_result()
        assert r.decision_scores == self._DECISION

    def test_raw_scores_holds_unprefixed_distribution(self) -> None:
        r = self._make_result()
        assert r.raw_scores == self._RAW

    def test_all_scores_is_alias_for_raw_scores(self) -> None:
        r = self._make_result()
        assert r.all_scores is r.raw_scores

    def test_decision_and_raw_can_differ(self) -> None:
        # The whole point: the two distributions rank differently.
        r = self._make_result()
        assert r.decision_scores["sofa"] > r.decision_scores["chair"]  # decision: sofa wins
        assert r.raw_scores["chair"] > r.raw_scores["sofa"]  # raw: chair leads

    def test_margin_field_survives_with_no_default(self) -> None:
        r = self._make_result(margin=1.09)
        assert r.margin == pytest.approx(1.09)

    def test_margin_defaults_to_none(self) -> None:
        r = self._make_result()
        assert r.margin is None

    def test_positional_and_keyword_construction_agree(self) -> None:
        pos = CLIPResult("sofa", 0.012, self._DECISION, self._RAW, 1.09)
        kw = CLIPResult(
            category="sofa",
            confidence=0.012,
            decision_scores=self._DECISION,
            raw_scores=self._RAW,
            margin=1.09,
        )
        assert pos == kw

    def test_classify_image_calls_score_embedding_twice(self, tmp_path: Path) -> None:
        """classify_image makes one prefixed call (decision) and one unprefixed (raw)."""
        import shared.clip_classification as cc

        fake_image = tmp_path / "test.jpg"
        fake_image.write_bytes(b"\xff\xd8")

        prefixed_results = [("sofa", 0.0120), ("chair", 0.0110)]
        raw_results = [("chair", 0.0118), ("sofa", 0.0115)]

        mock_clf = MagicMock()
        mock_clf.encode_image.return_value = MagicMock()  # fake embedding
        mock_clf.score_embedding.side_effect = [prefixed_results, raw_results]

        with (
            patch.object(cc, "CLIP_AVAILABLE", True),
            patch.object(cc, "get_clip_classifier", return_value=mock_clf),
            patch.object(cc, "CLIP_CACHE_AVAILABLE", False),
        ):
            result = cc.classify_image(fake_image, ["sofa", "chair"])

        assert result is not None
        assert result.category == "sofa"
        assert result.decision_scores == dict(prefixed_results)
        assert result.raw_scores == dict(raw_results)
        # Confirm they differ — decision picked sofa, raw would rank chair first.
        assert result.decision_scores["sofa"] > result.decision_scores["chair"]
        assert result.raw_scores["chair"] > result.raw_scores["sofa"]

        calls = mock_clf.score_embedding.call_args_list
        assert len(calls) == 2
        _, prefixed_kwargs = calls[0]
        _, raw_kwargs = calls[1]
        assert calls[0][0][2] == "a photo of "  # decision pass prefix
        assert calls[1][0][2] == ""  # raw pass prefix
