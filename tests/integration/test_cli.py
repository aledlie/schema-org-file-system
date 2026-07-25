"""Integration tests for the organize-files unified CLI (src/cli.py).

Drives ``main()`` through real argv parsing into the underlying subsystems:

- ``name`` and ``type`` run end-to-end against temp dirs (real file moves,
  including the multi-``--source`` forwarding that historically broke both
  inner parsers).
- ``prune-person`` runs against a real temp GraphStore database through the
  full parser path (Namespace-level behavior is covered in
  ``tests/unit/test_graph_store_prune.py``).
- Heavyweight subcommands (``content``, ``evaluate``, ``health``,
  ``migrate-ids``, ``preprocess``, ``update-site``, ``timeline``) are
  verified at the parser→run(args) boundary with the target entry point
  stubbed — their subsystems have their own suites and importing them pulls
  in torch/CLIP.  The stub captures the typed inputs dataclass
  (src/cli_inputs.py) passed to run() so that tests can assert that every
  outer CLI flag lands on the right attribute without triggering real I/O.
  Parser <-> dataclass field parity is locked by
  ``tests/unit/test_cli_inputs.py``.
"""

import sys
import types
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
for _p in (_PROJECT_ROOT, _PROJECT_ROOT / "src", _PROJECT_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from src.cli import DEFAULT_COST_REPORT, main  # noqa: E402


def run_cli(monkeypatch, *argv: str) -> None:
    """Run the CLI main() with the given argv (excluding the prog name)."""
    # Python 3.14 argparse colorizes help/usage whenever FORCE_COLOR is set,
    # even under pytest capture; NO_COLOR takes precedence and keeps captured
    # output plain so substring assertions hold in any shell.
    monkeypatch.setenv("NO_COLOR", "1")
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
            "name",
            "--source",
            str(source),
            "--target",
            str(target),
            "--dry-run",
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
            "--source",
            str(source_a),
            str(source_b),
            "--target",
            str(target),
            "--dry-run",
        )
        out = capsys.readouterr().out
        assert "alpha.txt" in out
        assert "beta.txt" in out

    def test_recursive_flag_reaches_organizer(self, monkeypatch, capsys, tmp_path):
        """--recursive was defined only by the standalone parser before; the
        shared definition makes it reachable from organize-files."""
        source = tmp_path / "inbox"
        nested = source / "sub"
        nested.mkdir(parents=True)
        (nested / "deep.txt").write_text("deep")
        target = tmp_path / "organized"

        run_cli(
            monkeypatch,
            "name",
            "--source",
            str(source),
            "--target",
            str(target),
            "--recursive",
            "--dry-run",
        )
        assert "deep.txt" in capsys.readouterr().out


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
            "type",
            "--source",
            str(source),
            "--target",
            str(target),
            "--dry-run",
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
            "type",
            "--source",
            str(source_a),
            str(source_b),
            "--target",
            str(target),
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
                session.query(Person).filter(Person.normalized_name == normalized).first()
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
    """Verify that the outer parser converts argv into the correct typed
    inputs for each target's run() without importing the torch/CLIP
    dependency stacks."""

    def _stub_run(self, monkeypatch, module_name: str, **extra_attrs):
        """Inject a fake module that captures the typed inputs passed to run()."""
        captured = {}

        def fake_run(args):
            captured["args"] = args

        module = types.ModuleType(module_name)
        setattr(module, "run", fake_run)
        for key, value in extra_attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, module_name, module)
        return captured

    def test_content_passes_typed_inputs(self, monkeypatch):
        captured = self._stub_run(monkeypatch, "file_organizer_content_based")
        run_cli(
            monkeypatch,
            "content",
            "--source",
            "/x",
            "/y",
            "--dry-run",
            "--limit",
            "5",
            "--no-db",
        )
        args = captured["args"]
        assert args.sources == ["/x", "/y"]
        assert args.dry_run is True
        assert args.limit == 5
        assert args.no_db is True

    def test_evaluate_passes_typed_inputs(self, monkeypatch):
        captured = self._stub_run(monkeypatch, "evaluate_model")
        run_cli(monkeypatch, "evaluate", "--classifier", "content")
        assert captured["args"].classifier == "content"

    def test_evaluate_defaults(self, monkeypatch):
        """Default classifier reaches evaluate_model.run() correctly."""
        captured = self._stub_run(monkeypatch, "evaluate_model")
        run_cli(monkeypatch, "evaluate")
        assert captured["args"].classifier == "baseline"

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
            # run_migration_with_banner calls run_migration(db_path, dry_run=...),
            # so the stub must accept the dry_run kwarg the banner wrapper forwards.
            lambda db_path, dry_run=False: calls.update(db_path=db_path, dry_run=dry_run),
        )
        db_path = str(tmp_path / "migrate.db")
        run_cli(monkeypatch, "migrate-ids", "--db-path", db_path)
        assert calls["db_path"] == db_path
        assert calls["dry_run"] is False
        assert "Migration complete" in capsys.readouterr().out

    def test_migrate_ids_dry_run_forwards_flag(self, monkeypatch, capsys, tmp_path):
        import storage.migration as migration_module

        calls = {}
        monkeypatch.setattr(
            migration_module,
            "run_migration",
            lambda db_path, dry_run=False: calls.update(db_path=db_path, dry_run=dry_run),
        )
        db_path = str(tmp_path / "migrate.db")
        run_cli(monkeypatch, "migrate-ids", "--db-path", db_path, "--dry-run")
        assert calls["dry_run"] is True
        assert "[DRY RUN] No changes were made." in capsys.readouterr().out

    def test_preprocess_passes_typed_inputs(self, monkeypatch):
        """Verify preprocess flags land on the right typed-input attributes."""
        captured = self._stub_run(monkeypatch, "src.ml.data_preprocessor")
        run_cli(monkeypatch, "preprocess", "--input", "/data/in", "--output", "/data/out")
        args = captured["args"]
        assert args.input == "/data/in"
        assert args.output == "/data/out"

    def test_update_site_passes_typed_inputs(self, monkeypatch):
        """Verify update-site flags land on the right typed-input attributes."""
        captured = self._stub_run(monkeypatch, "update_site_data")
        run_cli(monkeypatch, "update-site", "--report", "/tmp/report.json")
        assert captured["args"].report == "/tmp/report.json"

    def test_update_site_defaults(self, monkeypatch):
        """Verify update-site defaults reach update_site_data.run()."""
        captured = self._stub_run(monkeypatch, "update_site_data")
        run_cli(monkeypatch, "update-site")
        assert captured["args"].report is None

    def test_timeline_passes_typed_inputs(self, monkeypatch):
        """Verify timeline flags land on the right typed-input attributes."""
        captured = self._stub_run(monkeypatch, "src.api.timeline_api")
        run_cli(monkeypatch, "timeline")
        # Default db_path is None (cli uses DEFAULT_DB_PATH as fallback in run())
        assert captured["args"].db_path is None

    def test_timeline_custom_db_path_reaches_run(self, monkeypatch):
        """--db-path was parsed and then silently ignored (the old main()
        never read argv); it now lands on the typed inputs run() honors."""
        captured = self._stub_run(monkeypatch, "src.api.timeline_api")
        run_cli(monkeypatch, "timeline", "--db-path", "/tmp/custom.db")
        assert captured["args"].db_path == "/tmp/custom.db"

    def test_content_formerly_inner_only_flags(self, monkeypatch):
        """Flags the standalone script accepted but organize-files dropped
        (--force, --skip-health-check, --sentry-dsn, --cost-report) are now
        reachable through the shared definition, with script defaults intact."""
        captured = self._stub_run(monkeypatch, "file_organizer_content_based")
        run_cli(
            monkeypatch,
            "content",
            "--force",
            "--skip-health-check",
            "--sentry-dsn",
            "dsn123",
        )
        args = captured["args"]
        assert args.force is True
        assert args.skip_health_check is True
        assert args.sentry_dsn == "dsn123"
        assert args.cost_report == DEFAULT_COST_REPORT
        assert args.check_deps is False
        assert args.run_migration is False

    def test_evaluate_rejects_removed_model_flag(self, monkeypatch):
        """--model never worked: the outer parser accepted it but the old
        inner re-parse rejected it. It is gone from the shared definition."""
        self._stub_run(monkeypatch, "evaluate_model")
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, "evaluate", "--model", "x")
        assert exc.value.code == 2

    def test_evaluate_min_support_default_is_none(self, monkeypatch):
        """None resolves to DEFAULT_MIN_SUPPORT inside evaluate_model.run(),
        keeping the constant single-homed in the script."""
        captured = self._stub_run(monkeypatch, "evaluate_model")
        run_cli(monkeypatch, "evaluate")
        assert captured["args"].min_support is None
        assert captured["args"].test_data == "results/ml_data/test.json"
        assert captured["args"].output == "results/model_evaluation.json"

    def test_preprocess_requires_input(self, monkeypatch):
        """--input is required by the shared definition, so organize-files
        fails fast instead of deep inside the script's old re-parse."""
        self._stub_run(monkeypatch, "src.ml.data_preprocessor")
        with pytest.raises(SystemExit) as exc:
            run_cli(monkeypatch, "preprocess")
        assert exc.value.code == 2

    def test_update_site_dir_defaults(self, monkeypatch):
        """results-dir/site-dir were formerly inner-parser-only; the shared
        definition carries their script defaults."""
        captured = self._stub_run(monkeypatch, "update_site_data")
        run_cli(monkeypatch, "update-site")
        assert captured["args"].results_dir == "results"
        assert captured["args"].site_dir == "_site"
