"""Unit tests for scripts/backtest_scoring.py (UNIFIED_SCORING_PLAN §7.2).

Builds a tiny synthetic GraphStore SQLite DB (files with extracted_text /
mime_type / kie_fields spanning several categories plus one unbuildable row),
runs the replay pure functions over it, and asserts the distribution counts,
skip counting, stored-category agreement, labeled-set scoring, and the
weight-sensitivity loop shape. Golden-parity fixtures reuse the synthetic
texts from tests/integration/test_unified_scoring_golden.py so expected
decisions are already pinned by the golden suite.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

# Ensure scripts/ is on sys.path so `import backtest_scoring` (and its own
# `from shared.x import y`) resolve (mirrors tests/unit/test_relabel_test_set.py).
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import backtest_scoring as bs  # noqa: E402

from src.classifiers.content_classifier import ContentClassifier  # noqa: E402
from src.storage.graph_store import GraphStore  # noqa: E402

# --------------------------------------------------------------------------- #
# Synthetic corpus (texts mirror the golden integration fixtures)              #
# --------------------------------------------------------------------------- #

VENDOR_INVOICE_TEXT = (
    "INVOICE #2041 from Morning Train LLC. Purchase order PO-118 attached. "
    "Bill to: Integrity Studio. Payment terms net 30; supplier vendor id 88. "
    "Remit payment upon receipt of this invoice."
)

COURT_NOTICE_TEXT = (
    "NOTICE OF COURT SETTING. Cause No 2026-441 on the docket. "
    "Plaintiff: Mr. John Doe vs defendant. A hearing is set before the "
    "judicial officer. District Clerk contact info - phone: 512-555-0100, "
    "email: clerk@court.gov, address: 100 Main St. Contact the clerk."
)

INVOICE_OCR_TEXT = (
    "Invoice from Acme Corp. Total amount due $412.00 by invoice date "
    "2026-06-30. Billing statement and payment details enclosed."
)

# Two error_log keywords ("error:", "traceback") -> clears SCREENSHOT_MIN_HITS.
SCREENSHOT_ERROR_TEXT = "error: traceback follows fatal exception"

# The persisted kie_fields shape written by FileProcessor._persist_to_graph_store.
KIE_FIELDS_PERSISTED = {
    "vendor_name": [{"value": "Acme Corp", "confidence": 0.92}],
    "total_amount": [{"value": "$412.00", "confidence": 0.88}],
}

OCR_CONFIDENCE_STRONG = 0.9

VENDOR_PATH = "/data/in/morning-train-2041.pdf"
SPRITE_PATH = "/data/in/frame_12.png"
COURT_PATH = "/data/in/notice-of-ct-setting.pdf"
SCAN_PATH = "/data/in/scan_0021.png"
SCREENSHOT_PATH = "/data/in/Screenshot 2026-03-01 at 9.15.03 AM.png"

PDF_MIME = "application/pdf"
PNG_MIME = "image/png"
DOCUMENT_SCHEMA = "DigitalDocument"
IMAGE_SCHEMA = "ImageObject"

EXPECTED_TOTAL_ROWS = 6
EXPECTED_REPLAYED = 5
EXPECTED_UNBUILDABLE = 1
EXPECTED_AGREE = 4
EXPECTED_AGREEMENT_RATE = 0.8

SENSITIVITY_WEIGHTS_SUBSET = [
    ("W_FILENAME", bs.W_FILENAME, "filename_pattern"),
    ("W_MIME", bs.W_MIME, "mime_fallback"),
]


@pytest.fixture(scope="module")
def classifier() -> ContentClassifier:
    return ContentClassifier()


@pytest.fixture()
def synthetic_db(tmp_path: Path) -> Path:
    """A GraphStore DB with five classified files plus one unbuildable row."""
    db_path = tmp_path / "backtest.db"
    store = GraphStore(db_path=db_path)
    session = store.get_session()
    try:
        vendor = store.add_file(
            original_path=VENDOR_PATH,
            filename=Path(VENDOR_PATH).name,
            session=session,
            mime_type=PDF_MIME,
            schema_type=DOCUMENT_SCHEMA,
            extracted_text=VENDOR_INVOICE_TEXT,
        )
        store.add_file_to_category(vendor.id, "financial", "invoices", session=session)

        sprite = store.add_file(
            original_path=SPRITE_PATH,
            filename=Path(SPRITE_PATH).name,
            session=session,
            mime_type=PNG_MIME,
            schema_type=IMAGE_SCHEMA,
        )
        store.add_file_to_category(sprite.id, "game_assets", "sprites", session=session)

        court = store.add_file(
            original_path=COURT_PATH,
            filename=Path(COURT_PATH).name,
            session=session,
            mime_type=PDF_MIME,
            schema_type=DOCUMENT_SCHEMA,
            extracted_text=COURT_NOTICE_TEXT,
        )
        store.add_file_to_category(court.id, "legal", "litigation", session=session)

        scan = store.add_file(
            original_path=SCAN_PATH,
            filename=Path(SCAN_PATH).name,
            session=session,
            mime_type=PNG_MIME,
            schema_type=IMAGE_SCHEMA,
            extracted_text=INVOICE_OCR_TEXT,
            ocr_confidence=OCR_CONFIDENCE_STRONG,
            detected_language="en",
            kie_fields=KIE_FIELDS_PERSISTED,
        )
        store.add_file_to_category(scan.id, "financial", "invoices", session=session)

        screenshot = store.add_file(
            original_path=SCREENSHOT_PATH,
            filename=Path(SCREENSHOT_PATH).name,
            session=session,
            mime_type=PNG_MIME,
            schema_type=IMAGE_SCHEMA,
            extracted_text=SCREENSHOT_ERROR_TEXT,
            ocr_confidence=OCR_CONFIDENCE_STRONG,
            detected_language="en",
        )
        store.add_file_to_category(
            screenshot.id, "media", "photos_screenshots_error_log", session=session
        )

        # Unbuildable: no paths and no filename -> counted + skipped.
        store.add_file(original_path="", filename="", session=session)
    finally:
        session.close()
    return db_path


@pytest.fixture()
def replayed(synthetic_db: Path, classifier: ContentClassifier):
    """(rows, outcomes, skipped, report) for the synthetic corpus."""
    rows = bs.load_replay_rows(synthetic_db)
    lookup = bs.screenshot_text_lookup(rows)
    scorer = bs.build_replay_scorer(classifier, screenshot_text_by_path=lookup)
    outcomes, skipped = bs.replay_rows(rows, scorer)
    report = bs.summarize_replay(outcomes, skipped)
    return rows, outcomes, skipped, report


# --------------------------------------------------------------------------- #
# Row loading                                                                   #
# --------------------------------------------------------------------------- #


class TestLoadReplayRows:
    def test_snapshots_all_rows_with_stored_pairs(self, synthetic_db):
        rows = bs.load_replay_rows(synthetic_db)
        assert len(rows) == EXPECTED_TOTAL_ROWS

        by_name = {row.filename: row for row in rows}
        vendor = by_name[Path(VENDOR_PATH).name]
        assert (vendor.stored_category, vendor.stored_subcategory) == ("financial", "invoices")
        assert vendor.extracted_text == VENDOR_INVOICE_TEXT
        assert vendor.mime_type == PDF_MIME

        scan = by_name[Path(SCAN_PATH).name]
        assert scan.kie_fields == KIE_FIELDS_PERSISTED
        assert scan.ocr_confidence == OCR_CONFIDENCE_STRONG

        blank = by_name[""]
        assert blank.stored_category is None

    def test_limit_caps_rows(self, synthetic_db):
        assert len(bs.load_replay_rows(synthetic_db, limit=2)) == 2


# --------------------------------------------------------------------------- #
# Context reconstruction                                                        #
# --------------------------------------------------------------------------- #


class TestReconstruction:
    def test_reconstruct_kie_accepts_persisted_shape(self):
        kie = bs.reconstruct_kie(KIE_FIELDS_PERSISTED)
        assert kie is not None
        field = kie.fields["vendor_name"][0]
        assert (field.value, field.confidence) == ("Acme Corp", 0.92)

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            {},
            [1, 2],
            {"vendor_name": "not-a-list"},
            {"vendor_name": [{"confidence": 0.9}]},  # missing value
            {"vendor_name": [{"value": "x", "confidence": "high"}]},  # non-numeric
        ],
        ids=["none", "empty", "list", "scalar-entries", "missing-value", "bad-confidence"],
    )
    def test_reconstruct_kie_rejects_unreconstructable(self, raw):
        assert bs.reconstruct_kie(raw) is None

    def test_reconstruct_clip_accepts_numeric_dict(self):
        assert bs.reconstruct_clip({"photo": 0.6, "screenshot": 1}) == {
            "photo": 0.6,
            "screenshot": 1.0,
        }

    @pytest.mark.parametrize(
        "raw",
        [None, {}, ["photo"], {"photo": "high"}],
        ids=["none", "empty", "list", "non-numeric"],
    )
    def test_reconstruct_clip_rejects_unreplayable(self, raw):
        assert bs.reconstruct_clip(raw) is None

    @pytest.mark.parametrize(
        "mime_type,stored,expected",
        [
            (PNG_MIME, None, IMAGE_SCHEMA),
            ("video/mp4", None, "VideoObject"),
            ("audio/mpeg", None, "AudioObject"),
            (PDF_MIME, None, DOCUMENT_SCHEMA),
            (None, IMAGE_SCHEMA, IMAGE_SCHEMA),
            (None, "Photograph", DOCUMENT_SCHEMA),  # non-coarse stored type
            (None, None, DOCUMENT_SCHEMA),
        ],
    )
    def test_derive_schema_type(self, mime_type, stored, expected):
        assert bs.derive_schema_type(mime_type, stored) == expected

    def test_build_context_unbuildable_without_any_path(self):
        row = bs.ReplayRow(
            file_id="x",
            original_path="",
            current_path="",
            filename="",
            mime_type=None,
            schema_type=None,
            extracted_text="",
            ocr_confidence=None,
            detected_language=None,
            kie_fields=None,
            clip_scores=None,
            stored_category=None,
            stored_subcategory=None,
        )
        assert bs.build_context(row) is None

    def test_image_text_without_confidence_stays_filename_only(self):
        """Image rows with text but no stored OCR confidence get no OCR object."""
        row = bs.ReplayRow(
            file_id="y",
            original_path="/data/in/photo.png",
            current_path="",
            filename="photo.png",
            mime_type=PNG_MIME,
            schema_type=IMAGE_SCHEMA,
            extracted_text="some stored text",
            ocr_confidence=None,
            detected_language=None,
            kie_fields=None,
            clip_scores=None,
            stored_category=None,
            stored_subcategory=None,
        )
        context = bs.build_context(row)
        assert context is not None
        assert context.ensure_ocr() is None
        assert context.ensure_text() == ""  # image text routes via ensure_ocr


# --------------------------------------------------------------------------- #
# Replay + report                                                               #
# --------------------------------------------------------------------------- #


class TestReplay:
    def test_counts_and_skipping(self, replayed):
        _rows, outcomes, skipped, report = replayed
        assert len(outcomes) == EXPECTED_REPLAYED
        assert skipped == {
            bs.SKIP_UNBUILDABLE: EXPECTED_UNBUILDABLE,
            bs.SKIP_CLASSIFY_ERROR: 0,
        }
        assert report["total_rows"] == EXPECTED_TOTAL_ROWS
        assert report["replayed"] == EXPECTED_REPLAYED

    def test_decision_distribution(self, replayed):
        _rows, _outcomes, _skipped, report = replayed
        assert report["decision_distribution"] == {
            "financial/invoices": 1,
            "game_assets/sprites": 1,
            "legal/litigation": 1,
            "media/photos_screenshots_error_log": 1,
            "organization/vendors": 1,
        }
        assert report["decision_states"] == {"committed": EXPECTED_REPLAYED}

    def test_signal_win_participation(self, replayed):
        _rows, _outcomes, _skipped, report = replayed
        # KIE replay (persisted-shape reconstruction) and the stored-text
        # screenshot stub both participate in wins.
        assert report["signal_wins"]["kie_structured"] >= 1
        assert report["signal_wins"]["screenshot_ocr"] >= 1

    def test_stored_agreement(self, replayed):
        _rows, _outcomes, _skipped, report = replayed
        agreement = report["stored_agreement"]
        assert agreement["rows_with_stored_category"] == EXPECTED_REPLAYED
        assert agreement["agree_count"] == EXPECTED_AGREE
        assert agreement["agreement_rate"] == EXPECTED_AGREEMENT_RATE
        assert agreement["top_disagreements"] == [
            {
                "stored": "financial/invoices",
                "predicted": "organization/vendors",
                "count": 1,
            }
        ]

    def test_score_against_labels(self, replayed):
        _rows, outcomes, _skipped, _report = replayed
        labels = [
            {"filepath": SPRITE_PATH, "category": "game_assets", "subcategory": "sprites"},
            {"filepath": VENDOR_PATH, "category": "financial", "subcategory": "invoices"},
            {"filepath": "/data/in/unmatched.pdf", "category": "legal", "subcategory": "other"},
        ]
        scored = bs.score_against_labels(outcomes, labels)
        assert scored["labels_total"] == 3
        assert scored["matched"] == 2
        # sprite correct; vendor row predicted organization/vendors -> wrong.
        assert scored["category_accuracy"] == 0.5
        assert scored["subcategory_accuracy"] == 0.5

    def test_score_against_labels_no_matches(self, replayed):
        _rows, outcomes, _skipped, _report = replayed
        scored = bs.score_against_labels(outcomes, [{"filepath": "/elsewhere/x.pdf"}])
        assert scored["matched"] == 0
        assert scored["category_accuracy"] is None

    def test_classify_error_is_counted_not_raised(self, replayed):
        rows, _outcomes, _skipped, _report = replayed

        class ExplodingScorer:
            def classify(self, _context):
                raise RuntimeError("boom")

        outcomes, skipped = bs.replay_rows(rows, ExplodingScorer())
        assert outcomes == []
        assert skipped[bs.SKIP_CLASSIFY_ERROR] == EXPECTED_REPLAYED
        assert skipped[bs.SKIP_UNBUILDABLE] == EXPECTED_UNBUILDABLE


# --------------------------------------------------------------------------- #
# Weight sensitivity                                                            #
# --------------------------------------------------------------------------- #


class TestWeightSensitivity:
    def test_two_weight_subset_shape(self, replayed, classifier):
        rows, outcomes, _skipped, _report = replayed
        lookup = bs.screenshot_text_lookup(rows)
        report = bs.weight_sensitivity(
            rows,
            classifier,
            lookup,
            outcomes,
            weight_signals=SENSITIVITY_WEIGHTS_SUBSET,
        )
        assert list(report.keys()) == ["W_FILENAME", "W_MIME"]
        for constant_name, base_value, signal_name in SENSITIVITY_WEIGHTS_SUBSET:
            entry = report[constant_name]
            assert entry["signal"] == signal_name
            assert entry["base_weight"] == base_value
            assert isinstance(entry[bs.SENSITIVITY_DOWN_KEY], int)
            assert isinstance(entry[bs.SENSITIVITY_UP_KEY], int)
            assert entry[bs.SENSITIVITY_DOWN_KEY] >= 0
            assert entry[bs.SENSITIVITY_UP_KEY] >= 0

    def test_zero_delta_never_flips(self, replayed, classifier):
        """delta=0 reruns the identical scorer -> zero flips (determinism)."""
        rows, outcomes, _skipped, _report = replayed
        lookup = bs.screenshot_text_lookup(rows)
        report = bs.weight_sensitivity(
            rows,
            classifier,
            lookup,
            outcomes,
            weight_signals=SENSITIVITY_WEIGHTS_SUBSET,
            delta_fraction=0.0,
        )
        for entry in report.values():
            assert entry[bs.SENSITIVITY_DOWN_KEY] == 0
            assert entry[bs.SENSITIVITY_UP_KEY] == 0

    def test_declared_weight_list_covers_all_signals(self, classifier):
        """Every registered signal has a declared weight row and vice versa."""
        scorer = bs.build_replay_scorer(classifier)
        registered = {signal.name for signal in scorer._signals}
        declared = {signal_name for _, _, signal_name in bs.WEIGHT_SIGNALS}
        assert declared == registered


# --------------------------------------------------------------------------- #
# Screenshot-OCR stub                                                           #
# --------------------------------------------------------------------------- #


class TestScreenshotOcrStub:
    def test_stored_text_scores_error_log(self):
        result = bs.screenshot_ocr_from_text(SCREENSHOT_ERROR_TEXT)
        assert result is not None
        category, confidence, scores, text = result
        assert category == "error_log"
        assert confidence > 0
        assert "error_log" in scores
        assert text == SCREENSHOT_ERROR_TEXT

    @pytest.mark.parametrize("text", ["", "nothing relevant here"])
    def test_no_match_returns_none(self, text):
        assert bs.screenshot_ocr_from_text(text) is None

    def test_stub_looks_up_by_path(self):
        stub = bs.make_screenshot_ocr_stub({"/shots/a.png": SCREENSHOT_ERROR_TEXT})
        assert stub(Path("/shots/a.png")) is not None
        assert stub(Path("/shots/other.png")) is None

    def test_replay_scorer_swaps_in_stub(self, classifier):
        """The replay registry must not carry the disk-OCR classify callable."""
        scorer = bs.build_replay_scorer(classifier)
        screenshot_signal = next(
            signal for signal in scorer._signals if signal.name == bs.SCREENSHOT_OCR_SIGNAL_NAME
        )
        assert screenshot_signal._ocr_classify(Path("/nonexistent/Screenshot.png")) is None


# --------------------------------------------------------------------------- #
# Weight overrides                                                              #
# --------------------------------------------------------------------------- #


class TestWeightOverrides:
    def test_override_is_instance_local(self, classifier):
        scorer = bs.build_replay_scorer(classifier, weight_overrides={"mime_fallback": 0.9})
        overridden = next(signal for signal in scorer._signals if signal.name == "mime_fallback")
        assert overridden.weight == 0.9
        # A fresh registry is unaffected (weights.py constants untouched).
        fresh = bs.build_replay_scorer(classifier)
        untouched = next(signal for signal in fresh._signals if signal.name == "mime_fallback")
        assert untouched.weight == bs.W_MIME


# --------------------------------------------------------------------------- #
# CLI entry point                                                               #
# --------------------------------------------------------------------------- #


class TestMain:
    def test_missing_db_exits_nonzero(self, tmp_path):
        exit_code = bs.main(["--db-path", str(tmp_path / "missing.db")])
        assert exit_code == bs.EXIT_NO_DATA

    def test_empty_db_exits_nonzero(self, tmp_path):
        db_path = tmp_path / "empty.db"
        GraphStore(db_path=db_path)  # creates schema, no File rows
        exit_code = bs.main(["--db-path", str(db_path)])
        assert exit_code == bs.EXIT_NO_DATA

    def test_missing_labels_exits_nonzero(self, synthetic_db, tmp_path):
        exit_code = bs.main(
            [
                "--db-path",
                str(synthetic_db),
                "--labels",
                str(tmp_path / "missing-labels.json"),
            ]
        )
        assert exit_code == bs.EXIT_NO_DATA

    def test_full_run_writes_report(self, synthetic_db, tmp_path):
        output = tmp_path / "report.json"
        labels_path = tmp_path / "labels.json"
        labels_path.write_text(
            json.dumps(
                [{"filepath": SPRITE_PATH, "category": "game_assets", "subcategory": "sprites"}]
            ),
            encoding="utf-8",
        )
        exit_code = bs.main(
            [
                "--db-path",
                str(synthetic_db),
                "--labels",
                str(labels_path),
                "--output",
                str(output),
                "--limit",
                "10",
            ]
        )
        assert exit_code == bs.EXIT_OK
        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["replayed"] == EXPECTED_REPLAYED
        assert report["skipped"][bs.SKIP_UNBUILDABLE] == EXPECTED_UNBUILDABLE
        assert report["stored_agreement"]["agreement_rate"] == EXPECTED_AGREEMENT_RATE
        assert report["labels"]["matched"] == 1
        assert report["labels"]["category_accuracy"] == 1.0


# --------------------------------------------------------------------------- #
# Import-safety (repo convention: importing the module must not run the CLI)    #
# --------------------------------------------------------------------------- #


def test_module_import_does_not_execute_main():
    assert isinstance(bs, type(sys))
    assert isinstance(bs.WEIGHT_SIGNALS, list)
    assert isinstance(bs.SENSITIVITY_DEFAULT_LIMIT, int)


def test_replay_row_is_plain_snapshot():
    """ReplayRow carries values, not ORM handles (SimpleNamespace-safe)."""
    kie = bs.reconstruct_kie(KIE_FIELDS_PERSISTED)
    assert isinstance(kie, SimpleNamespace)


# --------------------------------------------------------------------------- #
# On-disk EXIF/GPS provider                                                    #
# --------------------------------------------------------------------------- #

JPEG_MIME = "image/jpeg"

# Written into the fixture EXIF; degrees-minutes-seconds so the expected
# decimals below are exact rather than rounded.
EXIF_CAPTURE_STAMP = "2024:04:04 18:44:35"
EXPECTED_CAPTURE = datetime(2024, 4, 4, 18, 44, 35)
EXPECTED_LATITUDE = 30.25  # 30 deg 15 min 0 sec N
EXPECTED_LONGITUDE = -97.5  # 97 deg 30 min 0 sec W

PNG_CREATION_STAMP = "2023-09-14T07:05:11"
EXPECTED_PNG_CREATION = datetime(2023, 9, 14, 7, 5, 11)


def _write_jpeg_with_exif(path: Path, *, stamp: str, with_gps: bool) -> Path:
    """A real 8x8 JPEG carrying EXIF capture time and (optionally) GPS."""
    import piexif
    from PIL import Image

    exif: dict = {"0th": {}, "Exif": {piexif.ExifIFD.DateTimeOriginal: stamp}, "GPS": {}}
    if with_gps:
        exif["GPS"] = {
            piexif.GPSIFD.GPSLatitudeRef: "N",
            piexif.GPSIFD.GPSLatitude: ((30, 1), (15, 1), (0, 1)),
            piexif.GPSIFD.GPSLongitudeRef: "W",
            piexif.GPSIFD.GPSLongitude: ((97, 1), (30, 1), (0, 1)),
        }
    Image.new("RGB", (8, 8), "blue").save(path, "JPEG", exif=piexif.dump(exif))
    return path


def _image_row(original_path: str, current_path: str, mime: str = JPEG_MIME) -> "bs.ReplayRow":
    return bs.ReplayRow(
        file_id="exif-row",
        original_path=original_path,
        current_path=current_path,
        filename=Path(original_path or current_path).name,
        mime_type=mime,
        schema_type=IMAGE_SCHEMA,
        extracted_text="",
        ocr_confidence=None,
        detected_language=None,
        kie_fields=None,
        clip_scores=None,
        stored_category=None,
        stored_subcategory=None,
    )


class TestOnDiskPath:
    """Which of the row's two paths the replay should read the file from."""

    def test_prefers_current_path_when_both_exist(self, tmp_path):
        original = tmp_path / "original.jpg"
        current = tmp_path / "filed.jpg"
        original.write_bytes(b"x")
        current.write_bytes(b"x")
        row = _image_row(str(original), str(current))
        assert bs.on_disk_path(row) == str(current)

    def test_falls_back_to_original_when_current_path_is_empty(self, tmp_path):
        original = tmp_path / "original.jpg"
        original.write_bytes(b"x")
        row = _image_row(str(original), "")
        assert bs.on_disk_path(row) == str(original)

    def test_falls_back_to_original_when_current_path_is_gone(self, tmp_path):
        """The reverted-move shape: the row claims a destination that never persisted."""
        original = tmp_path / "original.jpg"
        original.write_bytes(b"x")
        row = _image_row(str(original), str(tmp_path / "never_written.jpg"))
        assert bs.on_disk_path(row) == str(original)

    def test_returns_none_when_neither_path_resolves(self, tmp_path):
        row = _image_row(str(tmp_path / "gone_a.jpg"), str(tmp_path / "gone_b.jpg"))
        assert bs.on_disk_path(row) is None


class TestImageMetadataProvider:
    """EXIF/GPS read from disk, since no column persists it."""

    def test_returns_none_when_the_file_cannot_be_found(self, tmp_path):
        row = _image_row(str(tmp_path / "gone.jpg"), "")
        assert bs.make_image_metadata_provider(row) is None

    def test_reads_capture_time_and_gps(self, tmp_path):
        path = _write_jpeg_with_exif(
            tmp_path / "photo.jpg", stamp=EXIF_CAPTURE_STAMP, with_gps=True
        )
        provider = bs.make_image_metadata_provider(_image_row(str(path), ""))
        assert provider is not None
        metadata = provider(path)
        assert metadata[bs.DATETIME_METADATA_KEY] == EXPECTED_CAPTURE
        assert metadata[bs.GPS_METADATA_KEY] == (EXPECTED_LATITUDE, EXPECTED_LONGITUDE)

    def test_reads_the_resolved_file_not_the_path_it_is_handed(self, tmp_path):
        """The replay classifies under original_path (pre-move); the pixels are at current_path.

        Reading the handed path would find nothing and silently yield empty
        metadata — the exact failure this provider exists to prevent.
        """
        filed = _write_jpeg_with_exif(
            tmp_path / "filed.jpg", stamp=EXIF_CAPTURE_STAMP, with_gps=True
        )
        moved_from = tmp_path / "no_longer_here.jpg"
        provider = bs.make_image_metadata_provider(_image_row(str(moved_from), str(filed)))
        assert provider is not None

        metadata = provider(moved_from)

        assert metadata[bs.GPS_METADATA_KEY] == (EXPECTED_LATITUDE, EXPECTED_LONGITUDE)

    def test_reports_both_keys_as_none_when_the_image_has_no_exif(self, tmp_path):
        from PIL import Image

        path = tmp_path / "bare.jpg"
        Image.new("RGB", (8, 8), "red").save(path, "JPEG")
        provider = bs.make_image_metadata_provider(_image_row(str(path), ""))
        assert provider is not None
        metadata = provider(path)
        assert metadata[bs.DATETIME_METADATA_KEY] is None
        assert metadata[bs.GPS_METADATA_KEY] is None

    def test_falls_back_to_the_png_creation_time_chunk(self, tmp_path):
        """PNG carries no EXIF datetime, and .png is a PHOTO_EXTENSION."""
        from PIL import Image
        from PIL.PngImagePlugin import PngInfo

        info = PngInfo()
        info.add_text("Creation Time", PNG_CREATION_STAMP)
        path = tmp_path / "made.png"
        Image.new("RGB", (8, 8), "green").save(path, "PNG", pnginfo=info)

        provider = bs.make_image_metadata_provider(_image_row(str(path), "", mime=PNG_MIME))
        assert provider is not None
        assert provider(path)[bs.DATETIME_METADATA_KEY] == EXPECTED_PNG_CREATION


class TestBuildContextImageMetadata:
    """The wiring: without it every replayed row sees {} and GPS signals go dark."""

    def test_context_surfaces_exif_for_a_resolvable_image(self, tmp_path):
        path = _write_jpeg_with_exif(
            tmp_path / "photo.jpg", stamp=EXIF_CAPTURE_STAMP, with_gps=True
        )
        context = bs.build_context(_image_row(str(path), ""))
        assert context is not None
        assert context.ensure_image_metadata() == {
            bs.DATETIME_METADATA_KEY: EXPECTED_CAPTURE,
            bs.GPS_METADATA_KEY: (EXPECTED_LATITUDE, EXPECTED_LONGITUDE),
        }

    def test_context_is_empty_when_the_file_is_gone(self, tmp_path):
        context = bs.build_context(_image_row(str(tmp_path / "gone.jpg"), ""))
        assert context is not None
        assert context.ensure_image_metadata() == {}
