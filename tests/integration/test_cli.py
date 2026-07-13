"""Integration tests for the organize-files unified CLI (src/cli.py).

Drives ``main()`` through real argv parsing into the underlying subsystems:

- ``name`` and ``type`` run end-to-end against temp dirs (real file moves,
  including the multi-``--source`` forwarding that historically broke both
  inner parsers).
- ``prune-person`` runs against a real temp GraphStore database through the
  full parser path (Namespace-level behavior is covered in
  ``tests/unit/test_graph_store_prune.py``).
- Heavyweight subcommands (``content``, ``evaluate``, ``health``,
  ``migrate-ids``) are verified at the argv-translation boundary with the
  target entry point stubbed — their subsystems have their own suites and
  importing them pulls in torch/CLIP.
"""

import argparse
import sys
import types
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
for _p in (_PROJECT_ROOT, _PROJECT_ROOT / "src", _PROJECT_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from src.cli import _args_to_argv, main  # noqa: E402


def run_cli(monkeypatch, *argv: str) -> None:
    """Run the CLI main() with the given argv (excluding the prog name)."""
    monkeypatch.setattr(sys, "argv", ["organize-files", *argv])
    main()


ALL_SUBCOMMANDS = [
    "content",
    "name",
    "type",
    "preprocess",
    "evaluate",
    "migrate-ids",
    "person-view",
    "migrate-person",
    "index-people",
    "prune-person",
    "health",
    "update-site",
    "timeline",
]


class TestParser:
    def test_no_command_prints_help_and_exits_zero(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch)
        assert exc.value.code == 0
        assert "usage: organize-files" in capsys.readouterr().out

    def test_unknown_command_exits_two(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, "bogus")
        assert exc.value.code == 2
        assert "invalid choice" in capsys.readouterr().err

    def test_all_subcommands_registered(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, "--help")
        assert exc.value.code == 0
        help_text = capsys.readouterr().out
        for command in ALL_SUBCOMMANDS:
            assert command in help_text


class TestArgsToArgv:
    def test_translates_flags_lists_and_values(self):
        args = argparse.Namespace(
            func=None,
            command="content",
            sources=["/a", "/b"],
            base_path="~/Documents",
            dry_run=True,
            limit=5,
            report=None,
            no_db=False,
        )
        assert _args_to_argv(args) == [
            "--sources", "/a", "/b",
            "--base-path", "~/Documents",
            "--dry-run",
            "--limit", "5",
        ]


@pytest.fixture
def org_dirs(tmp_path):
    """Source dir with sample files plus an empty target base dir."""
    source = tmp_path / "inbox"
    source.mkdir()
    (source / "report.pdf").write_bytes(b"%PDF-1.4 test")
    (source / "script.py").write_text("print('hi')\n")
    target = tmp_path / "organized"
    target.mkdir()
    return source, target


class TestNameCommand:
    @pytest.fixture(autouse=True)
    def _no_repo_reports(self, monkeypatch):
        """Keep move-mode runs from writing reports into the repo results/."""
        from src.organizers.name_organizer import FileNameOrganizer

        monkeypatch.setattr(FileNameOrganizer, "save_report", lambda self: None)

    def test_dry_run_moves_nothing(self, monkeypatch, capsys, org_dirs):
        source, target = org_dirs
        run_cli(
            monkeypatch,
            "name", "--source", str(source), "--target", str(target), "--dry-run",
        )
        assert (source / "report.pdf").exists()
        assert (source / "script.py").exists()
        assert not [p for p in target.rglob("*") if p.is_file()]
        assert "report.pdf" in capsys.readouterr().out

    def test_moves_files_into_target(self, monkeypatch, org_dirs):
        source, target = org_dirs
        run_cli(monkeypatch, "name", "--source", str(source), "--target", str(target))
        assert not (source / "report.pdf").exists()
        moved = [p.name for p in target.rglob("*") if p.is_file()]
        assert "report.pdf" in moved
        assert "script.py" in moved

    def test_multiple_sources_all_processed(self, monkeypatch, capsys, tmp_path):
        source_a = tmp_path / "a"
        source_b = tmp_path / "b"
        source_a.mkdir()
        source_b.mkdir()
        (source_a / "alpha.txt").write_text("alpha")
        (source_b / "beta.txt").write_text("beta")
        target = tmp_path / "organized"

        run_cli(
            monkeypatch,
            "name",
            "--source", str(source_a), str(source_b),
            "--target", str(target),
            "--dry-run",
        )
        out = capsys.readouterr().out
        assert "alpha.txt" in out
        assert "beta.txt" in out


class TestTypeCommand:
    """Also the regression tests for --sources forwarding: the outer CLI
    always emits --sources, which the inner parser used to reject."""

    def test_moves_by_extension(self, monkeypatch, org_dirs):
        source, target = org_dirs
        run_cli(monkeypatch, "type", "--source", str(source), "--target", str(target))
        assert (target / "Documents" / "PDFs" / "report.pdf").exists()
        assert (target / "Code" / "Python" / "script.py").exists()
        assert not (source / "report.pdf").exists()

    def test_dry_run_moves_nothing(self, monkeypatch, org_dirs):
        source, target = org_dirs
        run_cli(
            monkeypatch,
            "type", "--source", str(source), "--target", str(target), "--dry-run",
        )
        assert (source / "report.pdf").exists()
        assert not (target / "Documents" / "PDFs" / "report.pdf").exists()

    def test_multiple_sources_all_processed(self, monkeypatch, tmp_path):
        source_a = tmp_path / "a"
        source_b = tmp_path / "b"
        source_a.mkdir()
        source_b.mkdir()
        (source_a / "one.pdf").write_bytes(b"%PDF-1.4")
        (source_b / "two.pdf").write_bytes(b"%PDF-1.4")
        target = tmp_path / "organized"

        run_cli(
            monkeypatch,
            "type", "--source", str(source_a), str(source_b), "--target", str(target),
        )
        assert (target / "Documents" / "PDFs" / "one.pdf").exists()
        assert (target / "Documents" / "PDFs" / "two.pdf").exists()


class TestPrunePersonCommand:
    @pytest.fixture
    def seeded_db(self, tmp_path):
        from src.storage.graph_store import GraphStore

        db_path = str(tmp_path / "graph.db")
        store = GraphStore(db_path)
        session = store.get_session()
        file = store.add_file(
            original_path="/tmp/jane_resume.pdf",
            filename="jane_resume.pdf",
            session=session,
        )
        store.add_file_to_person(file.id, "Jane Doe", session=session)
        session.commit()
        session.close()
        return db_path, store

    def _person_exists(self, store, name: str) -> bool:
        from src.storage.models import Person

        session = store.get_session()
        try:
            normalized = Person.normalize_name(name)
            return (
                session.query(Person)
                .filter(Person.normalized_name == normalized)
                .first()
                is not None
            )
        finally:
            session.close()

    def test_dry_run_reports_without_deleting(self, monkeypatch, capsys, seeded_db):
        db_path, store = seeded_db
        run_cli(monkeypatch, "prune-person", "Jane Doe", "--db-path", db_path)
        out = capsys.readouterr().out
        assert "[DRY RUN]" in out
        assert "Jane Doe" in out
        assert self._person_exists(store, "Jane Doe")

    def test_unknown_person_exits_nonzero(self, monkeypatch, capsys, seeded_db):
        db_path, _ = seeded_db
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, "prune-person", "Nobody Here", "--db-path", db_path)
        assert exc.value.code == 1
        assert "no matching person" in capsys.readouterr().out


class TestStubbedWiring:
    """Verify argv translation into heavyweight entry points without
    importing their torch/CLIP dependency stacks."""

    def _stub_module(self, monkeypatch, module_name: str, **attrs):
        captured = {}

        def fake_main():
            captured["argv"] = list(sys.argv)

        module = types.ModuleType(module_name)
        module.main = fake_main
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, module_name, module)
        return captured

    def test_content_argv_translation(self, monkeypatch):
        captured = self._stub_module(
            monkeypatch,
            "file_organizer_content_based",
            ContentBasedFileOrganizer=object,
        )
        run_cli(
            monkeypatch,
            "content",
            "--source", "/x", "/y",
            "--dry-run",
            "--limit", "5",
            "--no-db",
        )
        assert captured["argv"] == [
            "organize-files content",
            "--sources", "/x", "/y",
            "--base-path", "~/Documents",
            "--dry-run",
            "--limit", "5",
            "--db-path", "results/file_organization.db",
            "--no-db",
        ]

    def test_evaluate_argv_translation(self, monkeypatch):
        captured = self._stub_module(monkeypatch, "evaluate_model")
        run_cli(monkeypatch, "evaluate", "--classifier", "content")
        assert captured["argv"] == [
            "organize-files evaluate",
            "--classifier", "content",
        ]

    def test_health_calls_check_system(self, monkeypatch):
        calls = {}

        def fake_check_system(verbose=False):
            calls["verbose"] = verbose

        module = types.ModuleType("health_check")
        module.check_system = fake_check_system
        monkeypatch.setitem(sys.modules, "health_check", module)

        run_cli(monkeypatch, "health")
        assert calls == {"verbose": True}

    def test_migrate_ids_passes_db_path(self, monkeypatch, capsys, tmp_path):
        import storage.migration as migration_module

        calls = {}
        monkeypatch.setattr(
            migration_module,
            "run_migration",
            lambda db_path: calls.setdefault("db_path", db_path),
        )
        db_path = str(tmp_path / "migrate.db")
        run_cli(monkeypatch, "migrate-ids", "--db-path", db_path)
        assert calls["db_path"] == db_path
        assert "Migration complete" in capsys.readouterr().out
