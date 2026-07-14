"""Unit tests for src/api/timeline_api.py (canonical timeline document).

Locks the ``_site/timeline_data.json`` contract that ``_site/run_timeline.html``
consumes: top-level ``{generated_at, cumulative, sessions, session_count}``,
sessions ordered ASC and filtered to ``total_files > 0``, and list-of-dict
shapes for categories (``name/color/icon/count/avg_confidence``), schema
types (``schema_type/count``), and extensions (``extension/count``). The
logic was folded into ``TimelineAPI`` from scripts/generate_timeline_data.py
(now a launcher); these shapes must not drift or the dashboard breaks.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is on sys.path so `from shared.x import y` resolves.
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from src.api import timeline_api  # noqa: E402
from src.api.timeline_api import TimelineAPI  # noqa: E402

SESSION_A = "aaaaaaaa-1111-2222-3333-444444444444"
SESSION_B = "bbbbbbbb-5555-6666-7777-888888888888"
SESSION_EMPTY = "cccccccc-9999-0000-1111-222222222222"


@pytest.fixture
def timeline_db(tmp_path: Path) -> Path:
    """Seed a DB covering ordering, filtering, JSON parsing, and NULL edges."""
    db = tmp_path / "timeline.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE organization_sessions (
            id TEXT PRIMARY KEY, started_at TEXT, completed_at TEXT,
            dry_run INTEGER, source_directories TEXT, base_path TEXT,
            file_limit INTEGER, total_files INTEGER, organized_count INTEGER,
            skipped_count INTEGER, error_count INTEGER, total_cost REAL,
            total_processing_time_sec REAL
        );
        CREATE TABLE files (
            id INTEGER PRIMARY KEY, session_id TEXT, status TEXT,
            processing_time_sec REAL, schema_type TEXT, file_extension TEXT
        );
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY, name TEXT, color TEXT, icon TEXT
        );
        CREATE TABLE file_categories (
            file_id INTEGER, category_id INTEGER, confidence REAL
        );
    """)
    conn.executemany(
        "INSERT INTO organization_sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (SESSION_A, "2026-01-01T10:00:00", "2026-01-01T10:05:00", 0,
             '["~/Desktop", "~/Downloads"]', "~/Documents", 100,
             10, 7, 2, 1, 0.5, 20.0),
            (SESSION_B, "2026-02-01T09:00:00", "2026-02-01T09:10:00", 1,
             "not-json", "~/Documents", None,
             20, 15, 4, 1, 1.25, 30.5),
            # total_files = 0 -> must be filtered out of the document
            (SESSION_EMPTY, "2026-03-01T08:00:00", None, 0,
             None, "~/Documents", None, 0, 0, 0, 0, 0.0, None),
        ],
    )
    conn.executemany(
        "INSERT INTO files VALUES (?,?,?,?,?,?)",
        [
            (1, SESSION_A, "organized", 1.5, "ImageObject", ".png"),
            (2, SESSION_A, "organized", 2.0, "ImageObject", ".PNG"),
            (3, SESSION_A, "skipped", 0.5, "DigitalDocument", ".pdf"),
            (4, SESSION_A, "error", None, None, None),
            (5, SESSION_B, "organized", 3.0, "DigitalDocument", ".pdf"),
            (6, SESSION_B, "organized", 1.0, "VideoObject", ".mp4"),
            (7, SESSION_B, "skipped", None, "ImageObject", ".jpg"),
            # orphan file: no session -> excluded from cumulative stats
            (8, None, "organized", 9.9, "ImageObject", ".gif"),
        ],
    )
    conn.executemany(
        "INSERT INTO categories VALUES (?,?,?,?)",
        [
            (1, "media", "#ff0000", "image"),
            (2, "documents", "#00ff00", "file-text"),
            (3, "empty-cat", "#0000ff", "box"),
        ],
    )
    conn.executemany(
        "INSERT INTO file_categories VALUES (?,?,?)",
        [(1, 1, 0.9), (2, 1, 0.8), (3, 2, 0.95),
         (5, 2, 0.7), (6, 1, 0.6), (7, 1, 0.85)],
    )
    conn.commit()
    conn.close()
    return db


class TestGetSessions:
    def test_filters_empty_and_orders_ascending(self, timeline_db):
        sessions = TimelineAPI(timeline_db).get_sessions()
        assert [s["id"] for s in sessions] == [SESSION_A, SESSION_B]

    def test_id_short_and_success_rate_rounding(self, timeline_db):
        first = TimelineAPI(timeline_db).get_sessions()[0]
        assert first["id_short"] == SESSION_A[:8]
        assert first["success_rate"] == 70.0  # 7/10, one decimal

    def test_source_directories_parsed_and_invalid_json_falls_back(self, timeline_db):
        sessions = TimelineAPI(timeline_db).get_sessions()
        assert sessions[0]["source_directories"] == ["~/Desktop", "~/Downloads"]
        assert sessions[1]["source_directories"] == []


class TestSessionBreakdowns:
    def test_categories_shape(self, timeline_db):
        cats = TimelineAPI(timeline_db).get_session_categories(SESSION_A)
        assert cats[0] == {
            "name": "media", "color": "#ff0000", "icon": "image",
            "count": 2, "avg_confidence": pytest.approx(0.85),
        }

    def test_schema_types_shape_and_null_excluded(self, timeline_db):
        types = TimelineAPI(timeline_db).get_session_schema_types(SESSION_A)
        assert types == [
            {"schema_type": "ImageObject", "count": 2},
            {"schema_type": "DigitalDocument", "count": 1},
        ]

    def test_extensions_lowercased_grouping(self, timeline_db):
        exts = TimelineAPI(timeline_db).get_session_extensions(SESSION_A)
        assert exts == [
            {"extension": ".png", "count": 2},
            {"extension": ".pdf", "count": 1},
        ]


class TestSessionChanges:
    def test_first_session_marker(self):
        changes = TimelineAPI.calculate_session_changes(
            {"total_files": 10, "organized_count": 7}, None
        )
        assert changes == {
            "is_first": True, "files_delta": 10, "organized_delta": 7,
            "new_categories": [], "category_changes": [],
        }

    def test_deltas_between_sessions(self, timeline_db):
        a, b = TimelineAPI(timeline_db).get_sessions()
        changes = TimelineAPI.calculate_session_changes(b, a)
        assert changes == {
            "is_first": False, "files_delta": 10, "organized_delta": 8,
            "success_rate_delta": 5.0, "cost_delta": 0.75, "time_delta": 10.5,
        }

    def test_none_processing_time_treated_as_zero(self):
        base = {"total_files": 1, "organized_count": 1, "success_rate": 100.0,
                "total_cost": 0.0, "total_processing_time_sec": None}
        changes = TimelineAPI.calculate_session_changes(dict(base), dict(base))
        assert changes["time_delta"] == 0


class TestCumulativeStats:
    def test_orphan_files_excluded(self, timeline_db):
        stats = TimelineAPI(timeline_db).get_cumulative_stats()
        assert stats["total_sessions"] == 2
        assert stats["total_files"] == 7  # file 8 has no session
        assert stats["total_organized"] == 4

    def test_top_categories_include_empty_category(self, timeline_db):
        stats = TimelineAPI(timeline_db).get_cumulative_stats()
        assert {"name": "empty-cat", "count": 0} in stats["top_categories"]


class TestDocument:
    def test_top_level_contract(self, timeline_db):
        data = TimelineAPI(timeline_db).generate_document()
        assert set(data) == {"generated_at", "cumulative", "sessions", "session_count"}
        assert data["session_count"] == 2

    def test_session_enrichment_keys(self, timeline_db):
        session = TimelineAPI(timeline_db).generate_document()["sessions"][0]
        assert {"categories", "schema_types", "extensions", "changes"} <= set(session)
        assert session["changes"]["is_first"] is True

    def test_module_convenience_delegates_to_class(self, timeline_db):
        assert timeline_api.generate_timeline_data(timeline_db)["session_count"] == 2

    def test_export_to_json_writes_and_returns_document(self, timeline_db, tmp_path):
        out = tmp_path / "_site" / "timeline_data.json"
        data = TimelineAPI(timeline_db).export_to_json(out)
        assert json.loads(out.read_text()) == data
        assert data["session_count"] == 2

    def test_run_writes_output_path(self, timeline_db, tmp_path, monkeypatch, capsys):
        from src.cli_inputs import TimelineInputs

        out = tmp_path / "_site" / "timeline_data.json"
        monkeypatch.setattr(timeline_api, "OUTPUT_PATH", out)
        timeline_api.run(TimelineInputs(db_path=str(timeline_db)))
        data = json.loads(out.read_text())
        assert data["session_count"] == 2
        assert "2 sessions" in capsys.readouterr().out
