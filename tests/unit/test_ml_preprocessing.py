"""Unit tests for src.ml (feature extraction + preprocessing pipeline).

Covers the extraction of scripts/data_preprocessing.py into
src/ml/{feature_extractor,data_preprocessor}.py. sklearn-dependent methods
(split/vocabulary/label-encoder/export) are gated on sklearn availability —
they import it lazily so report-only flows must work without it.
"""

import json

import pytest

from src.ml import DataPreprocessor, FileFeatureExtractor
from src.ml.feature_extractor import GAME_ASSET_PATTERNS


def _record(filename, source="/inbox/x", category="media", subcategory="photos",
            **extra):
    rec = {
        "schema": {"name": filename},
        "source": f"{source}/{filename}",
        "category": category,
        "subcategory": subcategory,
    }
    rec.update(extra)
    return rec


class TestFileFeatureExtractor:
    @pytest.fixture
    def extractor(self):
        return FileFeatureExtractor()

    def test_extract_features_basic(self, extractor):
        features = extractor.extract_features(
            _record(
                "Screenshot_2024-01-05_invoice.png",
                extracted_text_length=120,
                company_name="Acme",
                people_names=["Ada"],
                image_metadata={"datetime": "2024:01:05", "gps_coordinates": None},
            )
        )

        assert features["extension"] == ".png"
        assert features["extension_category"] == "image"
        assert features["is_screenshot"] is True
        assert features["is_document"] is True  # 'invoice' is a document pattern
        assert features["has_extracted_text"] is True
        assert features["has_company_name"] is True
        assert features["people_count"] == 1
        assert features["has_datetime"] is True
        assert features["has_gps"] is False
        assert features["parent_folder"] == "x"
        assert len(features["filename_hash"]) == 8

    def test_tokenize_splits_camel_case_and_delimiters(self, extractor):
        features = extractor.extract_features(_record("myVacationPhoto_beach-2024.jpg"))
        tokens = features["filename_tokens"]
        assert "vacation" in tokens
        assert "photo" in tokens
        assert "beach" in tokens
        assert "2024" in tokens

    @pytest.mark.parametrize("filename,expected", [
        ("20240105_photo.jpg", True),
        ("2024-01-05 report.pdf", True),
        ("01-05-2024_scan.pdf", True),
        ("vacation_photo.jpg", False),
    ])
    def test_starts_with_date(self, extractor, filename, expected):
        features = extractor.extract_features(_record(filename))
        assert features["starts_with_date"] is expected

    def test_game_asset_pattern(self, extractor):
        features = extractor.extract_features(_record("player_sprite_idle.png"))
        assert features["is_game_asset"] is True
        assert any("sprite" in p for p in GAME_ASSET_PATTERNS)

    def test_unknown_extension_maps_to_other(self, extractor):
        features = extractor.extract_features(_record("archive.xyz"))
        assert features["extension_category"] == "other"


class TestDataPreprocessor:
    @pytest.fixture
    def report_file(self, tmp_path):
        report = {
            "results": [
                _record("Screenshot_001.png"),
                _record("invoice_acme.pdf", category="financial", subcategory="invoices"),
                _record("notes.txt", category="uncategorized", subcategory=""),
                _record("notes.txt", category="uncategorized", subcategory=""),
            ]
        }
        path = tmp_path / "report.json"
        path.write_text(json.dumps(report))
        return str(path)

    def test_requires_path(self):
        with pytest.raises(ValueError):
            DataPreprocessor().load_data()

    def test_requires_load_before_extract(self):
        with pytest.raises(ValueError):
            DataPreprocessor().extract_all_features()

    def test_pipeline_without_sklearn(self, report_file):
        """load -> features -> statistics -> quality -> report needs no sklearn."""
        pre = DataPreprocessor(report_file)
        pre.load_data()
        features = pre.extract_all_features()
        assert len(features) == 4

        stats = pre.compute_statistics()
        assert stats["total_records"] == 4
        assert stats["category_distribution"]["uncategorized"] == 2
        assert stats["pattern_counts"]["screenshots"] == 1

        quality = pre.validate_data_quality()
        assert quality["uncategorized_count"] == 2
        assert "notes.txt" in quality["issues_sample"]["duplicates"]
        assert 0 <= quality["quality_score"] <= 100

        report = pre.generate_report()
        assert "DATA QUALITY" in report
        assert "CATEGORY DISTRIBUTION" in report

    def test_export_for_training(self, report_file, tmp_path):
        pytest.importorskip("sklearn")
        pre = DataPreprocessor(report_file)
        pre.load_data()
        pre.extract_all_features()
        pre.compute_statistics()

        out = pre.export_for_training(str(tmp_path / "ml_out"))

        for key in ("features", "vocabulary", "labels", "train", "test", "statistics"):
            assert key in out
            assert json.loads(open(out[key]).read()) is not None


class TestScriptWrapper:
    def test_wrapper_reexports_src_ml(self):
        """scripts/data_preprocessing.py must expose the src.ml objects."""
        import data_preprocessing as wrapper

        from src.ml import data_preprocessor as canonical

        assert wrapper.DataPreprocessor is canonical.DataPreprocessor
        assert wrapper.run is canonical.run
        assert wrapper.FileFeatureExtractor is FileFeatureExtractor
