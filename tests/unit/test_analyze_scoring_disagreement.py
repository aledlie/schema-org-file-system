"""Unit tests for scripts/analyze_scoring_disagreement.py.

Feeds synthetic shadow-log JSONL (agreeing, disagreeing, malformed lines)
through parse_records/summarize and asserts the summary numbers, the
descending grouping order, and the example-path capping.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional, Tuple

# Ensure scripts/ is on sys.path so `import analyze_scoring_disagreement`
# resolves (mirrors tests/unit/test_relabel_test_set.py).
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import analyze_scoring_disagreement as asd  # noqa: E402


def _record_line(
    legacy: Tuple[str, str] = ("financial", "invoices"),
    unified: Tuple[str, str] = ("financial", "invoices"),
    path: str = "/tmp/a.pdf",
    decision_state: str = "committed",
    agrees: Optional[bool] = None,
    include_agrees: bool = True,
) -> str:
    """One shadow-log JSONL line in the §7.1 shape Phase 0 writes."""
    record = {
        "ts": "2026-07-16T00:00:00+00:00",
        "path": path,
        "scorer": "shadow",
        "decision": {
            "category": unified[0],
            "subcategory": unified[1],
            "schema_type": "DigitalDocument",
            "confidence": 0.8,
            "margin": 0.2,
            "decision_state": decision_state,
        },
        "winning_signals": ["TextContentSignal"],
        "all_scores": [],
        "legacy_decision": {
            "category": legacy[0],
            "subcategory": legacy[1],
            "schema_type": "DigitalDocument",
        },
    }
    if include_agrees:
        record["agrees"] = (legacy == unified) if agrees is None else agrees
    return json.dumps(record)


class TestParseRecords:
    def test_parses_valid_lines(self) -> None:
        lines = [_record_line(), _record_line(path="/tmp/b.pdf")]
        records, malformed = asd.parse_records(lines)
        assert len(records) == 2
        assert malformed == 0

    def test_counts_and_skips_malformed_lines(self) -> None:
        lines = [
            _record_line(),
            "not json at all {",
            '"a bare json string"',
            "42",
            _record_line(path="/tmp/b.pdf"),
        ]
        records, malformed = asd.parse_records(lines)
        assert len(records) == 2
        assert malformed == 3

    def test_blank_lines_ignored_without_counting(self) -> None:
        lines = ["", "   ", "\n", _record_line()]
        records, malformed = asd.parse_records(lines)
        assert len(records) == 1
        assert malformed == 0


class TestSummarize:
    def _summary(self, lines, top: int = asd.DEFAULT_TOP):
        records, malformed = asd.parse_records(lines)
        return asd.summarize(records, malformed=malformed, top=top)

    def test_summary_numbers(self) -> None:
        lines = [
            _record_line(),  # agrees
            _record_line(path="/tmp/b.pdf"),  # agrees
            _record_line(
                legacy=("media", "photos"), unified=("personal", "events"), path="/tmp/c.jpg"
            ),
            "garbage line",
        ]
        report = self._summary(lines)

        assert report["total_records"] == 3
        assert report["malformed_lines"] == 1
        assert report["agree_count"] == 2
        assert report["disagree_count"] == 1
        assert report["agreement_rate"] == round(2 / 3, asd.RATE_PRECISION)

    def test_empty_input_has_null_rate(self) -> None:
        report = self._summary([])
        assert report["total_records"] == 0
        assert report["agreement_rate"] is None
        assert report["disagreements"] == []

    def test_decision_state_counts(self) -> None:
        lines = [
            _record_line(decision_state="committed"),
            _record_line(decision_state="committed", path="/tmp/b.pdf"),
            _record_line(decision_state="low_confidence", path="/tmp/c.pdf"),
            _record_line(decision_state="low_margin", path="/tmp/d.pdf"),
        ]
        report = self._summary(lines)
        assert report["decision_states"] == {
            "committed": 2,
            "low_confidence": 1,
            "low_margin": 1,
        }

    def test_agrees_derived_from_decisions_when_absent(self) -> None:
        lines = [
            _record_line(include_agrees=False),  # same pair -> agrees
            _record_line(
                legacy=("media", "photos"),
                unified=("personal", "events"),
                include_agrees=False,
            ),
        ]
        report = self._summary(lines)
        assert report["agree_count"] == 1
        assert report["disagree_count"] == 1

    def test_disagreements_grouped_and_sorted_desc(self) -> None:
        frequent = {"legacy": ("media", "photos"), "unified": ("personal", "events")}
        rare = {"legacy": ("technical", "other"), "unified": ("financial", "invoices")}
        lines = [
            _record_line(path="/tmp/1.jpg", **frequent),
            _record_line(path="/tmp/2.jpg", **frequent),
            _record_line(path="/tmp/3.jpg", **frequent),
            _record_line(path="/tmp/4.pdf", **rare),
        ]
        report = self._summary(lines)

        assert [d["count"] for d in report["disagreements"]] == [3, 1]
        top_pair = report["disagreements"][0]
        assert top_pair["legacy"] == "media/photos"
        assert top_pair["unified"] == "personal/events"
        assert top_pair["examples"] == ["/tmp/1.jpg", "/tmp/2.jpg", "/tmp/3.jpg"]

    def test_top_caps_pairs_and_examples(self) -> None:
        pair_a = {"legacy": ("media", "photos"), "unified": ("personal", "events")}
        pair_b = {"legacy": ("technical", "other"), "unified": ("financial", "invoices")}
        pair_c = {"legacy": ("games", "sprites"), "unified": ("media", "photos")}
        lines = (
            [_record_line(path=f"/tmp/a{i}.jpg", **pair_a) for i in range(4)]
            + [_record_line(path=f"/tmp/b{i}.pdf", **pair_b) for i in range(3)]
            + [_record_line(path="/tmp/c0.png", **pair_c)]
        )
        report = self._summary(lines, top=2)

        # Only the top 2 pairs survive, each capped to 2 example paths.
        assert len(report["disagreements"]) == 2
        assert [d["count"] for d in report["disagreements"]] == [4, 3]
        assert report["disagreements"][0]["examples"] == ["/tmp/a0.jpg", "/tmp/a1.jpg"]
        assert report["disagreements"][1]["examples"] == ["/tmp/b0.pdf", "/tmp/b1.pdf"]


class TestFormatReport:
    def test_renders_counts_and_pairs(self) -> None:
        lines = [
            _record_line(),
            _record_line(
                legacy=("media", "photos"), unified=("personal", "events"), path="/tmp/c.jpg"
            ),
        ]
        records, malformed = asd.parse_records(lines)
        text = asd.format_report(asd.summarize(records, malformed=malformed))

        assert "Total records:   2" in text
        assert "media/photos -> personal/events" in text
        assert "- /tmp/c.jpg" in text

    def test_no_disagreements_renders_none(self) -> None:
        text = asd.format_report(asd.summarize([], malformed=0))
        assert "(none)" in text
        assert "n/a" in text


class TestMain:
    def test_main_reads_log_and_writes_json(self, tmp_path: Path, capsys) -> None:
        log = tmp_path / "shadow.jsonl"
        log.write_text(
            "\n".join(
                [
                    _record_line(),
                    _record_line(
                        legacy=("media", "photos"),
                        unified=("personal", "events"),
                        path="/tmp/c.jpg",
                    ),
                    "malformed {",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        json_out = tmp_path / "report.json"

        exit_code = asd.main(["--log", str(log), "--json", str(json_out), "--top", "5"])

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "Shadow scoring disagreement report" in out

        report = json.loads(json_out.read_text(encoding="utf-8"))
        assert report["total_records"] == 2
        assert report["malformed_lines"] == 1
        assert report["disagreements"][0]["unified"] == "personal/events"

    def test_main_missing_log_returns_error(self, tmp_path: Path, capsys) -> None:
        exit_code = asd.main(["--log", str(tmp_path / "absent.jsonl")])
        assert exit_code == 1
        assert "not found" in capsys.readouterr().out
