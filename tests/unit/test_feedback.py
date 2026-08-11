"""Unit tests for src.feedback (correction tracker + feedback integration).

Covers the extraction of scripts/correction_feedback.py and
scripts/feedback_integration.py into
src/feedback/{correction_tracker,feedback_loop}.py. All state goes through a
tmp_path corrections file — never the real ~/.schema-org-file-system store.
"""

import json
from pathlib import Path

import pytest

from src.feedback import CorrectionFeedbackSystem, FeedbackIntegration


@pytest.fixture
def feedback_file(tmp_path):
    return str(tmp_path / "corrections.json")


@pytest.fixture
def system(feedback_file):
    return CorrectionFeedbackSystem(feedback_file)


def _add_sprite_correction(system, n=1, subcategory="sprites"):
    """Record n corrections moving sprite files media -> game_assets."""
    for i in range(n):
        system.add_correction(
            file_path=f"/inbox/player_sprite_{i}.png",
            assigned_destination=f"/Media/player_sprite_{i}.png",
            correct_destination=f"/GameAssets/player_sprite_{i}.png",
            assigned_category="media",
            correct_category="game_assets",
            correct_subcategory=subcategory,
        )


class TestCorrectionFeedbackSystem:
    def test_add_correction_persists_and_updates_stats(self, system, feedback_file):
        file_hash = system.add_correction(
            file_path="/inbox/invoice_acme.pdf",
            assigned_destination="/Media/invoice_acme.pdf",
            correct_destination="/Financial/invoice_acme.pdf",
            assigned_category="media",
            correct_category="financial",
            correction_reason="invoices are financial",
            content_hints=["total due"],
        )

        on_disk = json.loads(open(feedback_file).read())
        assert file_hash in on_disk["corrections"]
        assert on_disk["statistics"]["total_corrections"] == 1
        assert on_disk["statistics"]["corrections_by_category"]["financial"] == 1
        assert on_disk["statistics"]["most_common_mistakes"][0] == {
            "from": "media",
            "to": "financial",
            "count": 1,
        }
        # invoice keyword + extension both become learned patterns
        assert "financial_keyword" in on_disk["learned_patterns"]
        assert "ext:.pdf" in on_disk["learned_patterns"]

    def test_data_survives_reload(self, system, feedback_file):
        _add_sprite_correction(system)
        reloaded = CorrectionFeedbackSystem(feedback_file)
        assert reloaded.get_statistics()["total_corrections"] == 1

    def test_suggestion_from_learned_patterns(self, system):
        _add_sprite_correction(system, n=3)

        suggestion = system.get_suggestion("boss_sprite_walk.png", "media")
        assert suggestion is not None
        assert suggestion["suggested_category"] == "game_assets"
        assert suggestion["suggested_subcategory"] == "sprites"
        assert suggestion["confidence"] >= 0.6

    def test_no_suggestion_when_category_already_correct(self, system):
        _add_sprite_correction(system, n=3)
        assert system.get_suggestion("boss_sprite_walk.png", "game_assets") is None

    def test_no_suggestion_without_matching_patterns(self, system):
        _add_sprite_correction(system)
        assert system.get_suggestion("vacation_beach.heic", "media") is None

    def test_check_file_matches_by_content_hash(self, system, tmp_path):
        target = tmp_path / "doc.pdf"
        target.write_bytes(b"%PDF-1.4 fixture")
        system.add_correction(
            file_path=str(target),
            assigned_destination=str(target),
            correct_destination="/Financial/doc.pdf",
            assigned_category="media",
            correct_category="financial",
        )

        match = system.check_file(str(target))
        assert match is not None
        assert match["correct_category"] == "financial"
        assert system.check_file(str(tmp_path / "missing.pdf")) is None

    def test_export_rules_requires_support_and_confidence(self, system):
        # Two samples: below the >=3 sample threshold -> no pattern rule
        _add_sprite_correction(system, n=2)
        assert system.export_rules()["pattern_rules"] == []

        # Third sample crosses the threshold
        _add_sprite_correction(system, n=1)
        rules = system.export_rules()
        by_pattern = {r["pattern"]: r for r in rules["pattern_rules"]}
        assert by_pattern["sprite_keyword"]["category"] == "game_assets"
        assert by_pattern["sprite_keyword"]["confidence"] >= 0.7

    def test_remove_correction(self, system):
        file_hash = system.add_correction(
            file_path="/inbox/a.png",
            assigned_destination="/Media/a.png",
            correct_destination="/GameAssets/a.png",
            assigned_category="media",
            correct_category="game_assets",
        )
        assert system.remove_correction(file_hash) is True
        assert system.remove_correction(file_hash) is False
        assert system.get_correction_by_hash(file_hash) is None

    def test_get_corrections_for_category(self, system):
        _add_sprite_correction(system, n=2)
        corrections = system.get_corrections_for_category("game_assets")
        assert len(corrections) == 2
        assert all("hash" in c for c in corrections)

    def test_extract_filename_patterns(self):
        patterns = CorrectionFeedbackSystem.extract_filename_patterns(
            "Screenshot_20240105_093015.png"
        )
        assert "screenshot_prefix" in patterns
        assert "timestamp_pattern" in patterns
        assert "ext:.png" in patterns


class TestFeedbackIntegration:
    @pytest.fixture
    def integration(self, feedback_file):
        return FeedbackIntegration(feedback_file)

    def test_pre_categorize_check_exact_file_match(self, integration, tmp_path):
        target = tmp_path / "doc.pdf"
        target.write_bytes(b"%PDF-1.4 fixture")
        integration.feedback.add_correction(
            file_path=str(target),
            assigned_destination=str(target),
            correct_destination="/Financial/doc.pdf",
            assigned_category="media",
            correct_category="financial",
            correct_subcategory="invoices",
        )

        category, subcategory, confidence = integration.pre_categorize_check(
            str(target), "doc.pdf", "media", "photos"
        )
        assert (category, subcategory, confidence) == ("financial", "invoices", 1.0)

    def test_pre_categorize_check_pattern_suggestion(self, integration):
        _add_sprite_correction(integration.feedback, n=3)

        category, subcategory, confidence = integration.pre_categorize_check(
            "/nowhere/boss_sprite.png", "boss_sprite.png", "media", "photos"
        )
        assert category == "game_assets"
        assert subcategory == "sprites"
        # Unanimous vote history yields confidence 1.0; the suggestion gate is >=0.7
        assert confidence >= 0.7

    def test_pre_categorize_check_passthrough(self, integration):
        category, subcategory, confidence = integration.pre_categorize_check(
            "/nowhere/vacation.jpg", "vacation.jpg", "media", "photos"
        )
        assert (category, subcategory, confidence) == ("media", "photos", 1.0)

    def test_batch_apply_corrections(self, integration):
        _add_sprite_correction(integration.feedback, n=4)
        results = [
            {
                "schema": {"name": "enemy_sprite.png"},
                "source": "/inbox/enemy_sprite.png",
                "category": "media",
                "subcategory": "photos",
            },
            {
                "schema": {"name": "vacation.jpg"},
                "source": "/inbox/vacation.jpg",
                "category": "media",
                "subcategory": "photos",
            },
        ]

        modified, stats = integration.batch_apply_corrections(results)

        assert stats["total"] == 2
        assert stats["suggestions_made"] == 1
        assert stats["auto_applied"] == 1
        assert modified[0]["category"] == "game_assets"
        assert modified[0]["feedback_applied"] is True
        assert modified[1]["category"] == "media"
        # Inputs must not be mutated
        assert results[0]["category"] == "media"

    def test_get_pattern_keywords(self, integration):
        _add_sprite_correction(integration.feedback, n=3)
        keywords = integration.get_pattern_keywords()
        assert "game_assets" in keywords
        assert any(
            p == "sprite_keyword" or p.startswith("extension:")
            for p in keywords["game_assets"]["patterns"]
        )

    def test_generate_correction_report(self, integration):
        _add_sprite_correction(integration.feedback, n=3)
        report = integration.generate_correction_report(
            [
                {
                    "schema": {"name": "enemy_sprite.png"},
                    "source": "/inbox/enemy_sprite.png",
                    "category": "media",
                },
            ]
        )
        assert "enemy_sprite.png" in report
        assert "game_assets" in report


class TestScriptLaunchers:
    """The scripts are pure launchers for src.feedback — importing them does
    nothing; running them must reach the extracted implementations."""

    _SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"

    def _launch(self, script, *argv, env=None):
        import os
        import subprocess
        import sys

        return subprocess.run(
            [sys.executable, str(self._SCRIPTS_DIR / script), *argv],
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, **(env or {})},
        )

    def test_correction_feedback_cli_help(self):
        result = self._launch("correction_feedback.py", "--help")
        assert result.returncode == 0
        for subcommand in ("add", "suggest", "stats", "export-rules"):
            assert subcommand in result.stdout

    def test_feedback_integration_demo(self, tmp_path):
        # The demo opens the default store under $HOME — point it at tmp_path
        # so the test never touches the real ~/.schema-org-file-system.
        result = self._launch("feedback_integration.py", env={"HOME": str(tmp_path)})
        assert result.returncode == 0
        assert "Feedback Integration System" in result.stdout
        assert "Corrections recorded: 0" in result.stdout
