"""Tests for GraphStore.remove_person_edge / prune_person and the
organize-files prune-person CLI command."""

import argparse
from pathlib import Path

import pytest

from src.storage.graph_store import GraphStore
from src.storage.models import Person, file_people


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "graph.db")


@pytest.fixture
def store(db_path: str) -> GraphStore:
    return GraphStore(db_path)


def _add_person_with_files(store: GraphStore, name: str, paths: list) -> list:
    """Attach `name` to files at `paths`; returns the file ids."""
    session = store.get_session()
    file_ids = []
    for path in paths:
        file = store.add_file(original_path=path, filename=Path(path).name, session=session)
        file_ids.append(file.id)
        store.add_file_to_person(file.id, name, session=session)
    session.commit()
    session.close()
    return file_ids


def _person(store: GraphStore, name: str):
    session = store.get_session()
    try:
        normalized = Person.normalize_name(name)
        return session.query(Person).filter(Person.normalized_name == normalized).first()
    finally:
        session.close()


def _edge_count(store: GraphStore) -> int:
    session = store.get_session()
    try:
        return session.execute(file_people.select()).fetchall().__len__()
    finally:
        session.close()


class TestRemovePersonEdge:
    def test_removes_edge_and_keeps_both_rows(self, store: GraphStore) -> None:
        (file_id,) = _add_person_with_files(store, "Jane Doe", ["/tmp/a.pdf"])

        assert store.remove_person_edge(file_id, "Jane Doe") is True

        assert _edge_count(store) == 0
        person = _person(store, "Jane Doe")
        assert person is not None
        assert person.file_count == 0
        assert store.get_file(file_id=file_id) is not None

    def test_accepts_person_primary_key(self, store: GraphStore) -> None:
        (file_id,) = _add_person_with_files(store, "Jane Doe", ["/tmp/a.pdf"])
        person_id = _person(store, "Jane Doe").id

        assert store.remove_person_edge(file_id, person_id) is True
        assert _edge_count(store) == 0

    def test_returns_false_when_no_edge(self, store: GraphStore) -> None:
        (file_id,) = _add_person_with_files(store, "Jane Doe", ["/tmp/a.pdf"])
        session = store.get_session()
        store.get_or_create_person("Other Person", session=session)
        session.commit()
        session.close()

        assert store.remove_person_edge(file_id, "Other Person") is False
        assert store.remove_person_edge("no-such-file", "Jane Doe") is False
        assert store.remove_person_edge(file_id, "No Such Person") is False
        assert _edge_count(store) == 1

    def test_file_count_never_goes_negative(self, store: GraphStore) -> None:
        (file_id,) = _add_person_with_files(store, "Jane Doe", ["/tmp/a.pdf"])
        session = store.get_session()
        person = session.query(Person).first()
        assert person is not None
        person.file_count = 0
        session.commit()
        session.close()

        assert store.remove_person_edge(file_id, "Jane Doe") is True
        assert _person(store, "Jane Doe").file_count == 0


class TestPrunePerson:
    def test_deletes_person_and_edges_keeps_files(self, store: GraphStore) -> None:
        file_ids = _add_person_with_files(store, "Morning Train", ["/tmp/a.pdf", "/tmp/b.pdf"])

        summary = store.prune_person("Morning Train")
        assert summary is not None

        assert summary == {
            "name": "Morning Train",
            "person_id": summary["person_id"],
            "edges_removed": 2,
            "paths": ["/tmp/a.pdf", "/tmp/b.pdf"],
        }
        assert _person(store, "Morning Train") is None
        assert _edge_count(store) == 0
        for file_id in file_ids:
            assert store.get_file(file_id=file_id) is not None

    def test_dry_run_reports_without_deleting(self, store: GraphStore) -> None:
        _add_person_with_files(store, "Morning Train", ["/tmp/a.pdf"])

        summary = store.prune_person("Morning Train", dry_run=True)
        assert summary is not None

        assert summary["edges_removed"] == 1
        assert _person(store, "Morning Train") is not None
        assert _edge_count(store) == 1

    def test_paths_prefer_current_path(self, store: GraphStore) -> None:
        from src.storage.models import FileStatus

        (file_id,) = _add_person_with_files(store, "Jane Doe", ["/tmp/a.pdf"])
        store.update_file_status(file_id, FileStatus.ORGANIZED, destination="/docs/a.pdf")

        summary = store.prune_person("Jane Doe", dry_run=True)
        assert summary is not None
        assert summary["paths"] == ["/docs/a.pdf"]

    def test_returns_none_for_unknown_person(self, store: GraphStore) -> None:
        assert store.prune_person("Nobody") is None
        assert store.prune_person(9999) is None

    def test_clears_merge_pointers_of_dependents(self, store: GraphStore) -> None:
        _add_person_with_files(store, "Jane Doe", ["/tmp/a.pdf"])
        session = store.get_session()
        target = session.query(Person).first()
        assert target is not None
        dependent = store.get_or_create_person("J. Doe", session=session)
        assert dependent is not None
        dependent.merged_into_id = target.id
        dependent_id = dependent.id
        session.commit()
        session.close()

        store.prune_person("Jane Doe")

        session = store.get_session()
        try:
            survivor = session.query(Person).filter(Person.id == dependent_id).one()
            assert survivor.merged_into_id is None
        finally:
            session.close()


class TestPruneMissingPersonEdges:
    def test_drops_only_dead_path_edges(self, store: GraphStore, tmp_path: Path) -> None:
        real_file = tmp_path / "real.pdf"
        real_file.write_text("x")
        _add_person_with_files(store, "Jane Doe", [str(real_file), "/nonexistent/gone.pdf"])

        result = store.prune_missing_person_edges()

        assert result["edges_removed"] == 1
        assert result["edges"][0]["path"] == "/nonexistent/gone.pdf"
        assert result["edges"][0]["person"] == "Jane Doe"
        assert _edge_count(store) == 1
        person = _person(store, "Jane Doe")
        assert person is not None
        assert person.file_count == 1

    def test_keeps_file_and_person_rows(self, store: GraphStore) -> None:
        (file_id,) = _add_person_with_files(store, "Jane Doe", ["/nonexistent/a.pdf"])

        store.prune_missing_person_edges()

        assert store.get_file(file_id=file_id) is not None
        assert _person(store, "Jane Doe") is not None
        assert _edge_count(store) == 0

    def test_prefers_current_path_over_original(self, store: GraphStore, tmp_path: Path) -> None:
        from src.storage.models import FileStatus

        organized = tmp_path / "organized.pdf"
        organized.write_text("x")
        (file_id,) = _add_person_with_files(store, "Jane Doe", ["/nonexistent/orig.pdf"])
        store.update_file_status(file_id, FileStatus.ORGANIZED, destination=str(organized))

        result = store.prune_missing_person_edges()

        assert result["edges_removed"] == 0
        assert _edge_count(store) == 1

    def test_dry_run_reports_without_deleting(self, store: GraphStore) -> None:
        _add_person_with_files(store, "Jane Doe", ["/nonexistent/a.pdf"])

        result = store.prune_missing_person_edges(dry_run=True)

        assert result["edges_removed"] == 1
        assert _edge_count(store) == 1
        assert _person(store, "Jane Doe").file_count == 1


class TestPruneMissingCliFlag:
    def test_person_view_prune_missing_dry_run(
        self, store: GraphStore, db_path: str, tmp_path: Path, capsys
    ) -> None:
        from src.cli import cmd_person_view

        _add_person_with_files(store, "Jane Doe", ["/nonexistent/a.pdf"])

        cmd_person_view(
            argparse.Namespace(
                view_root=str(tmp_path / "view"),
                db_path=db_path,
                apply=False,
                prune_missing=True,
            )
        )

        out = capsys.readouterr().out
        assert "[DRY RUN] Dead-path person edges pruned: 1" in out
        assert "Jane Doe: /nonexistent/a.pdf" in out
        assert _edge_count(store) == 1

    def test_person_view_prune_missing_apply(
        self, store: GraphStore, db_path: str, tmp_path: Path, capsys
    ) -> None:
        from src.cli import cmd_person_view

        _add_person_with_files(store, "Jane Doe", ["/nonexistent/a.pdf"])

        cmd_person_view(
            argparse.Namespace(
                view_root=str(tmp_path / "view"),
                db_path=db_path,
                apply=True,
                prune_missing=True,
            )
        )

        out = capsys.readouterr().out
        assert "[APPLIED] Dead-path person edges pruned: 1" in out
        assert _edge_count(store) == 0


class TestPrunePersonCli:
    def _run(self, db_path: str, people: list, apply: bool) -> None:
        from src.cli import cmd_prune_person

        cmd_prune_person(argparse.Namespace(people=people, db_path=db_path, apply=apply))

    def test_dry_run_leaves_db_untouched(self, store: GraphStore, db_path: str, capsys) -> None:
        _add_person_with_files(store, "Morning Train", ["/tmp/a.pdf"])

        self._run(db_path, ["Morning Train"], apply=False)

        out = capsys.readouterr().out
        assert "[DRY RUN] Morning Train" in out
        assert _person(store, "Morning Train") is not None

    def test_apply_deletes_and_backs_up(self, store: GraphStore, db_path: str, capsys) -> None:
        _add_person_with_files(store, "Morning Train", ["/tmp/a.pdf"])

        self._run(db_path, ["Morning Train"], apply=True)

        out = capsys.readouterr().out
        assert "[APPLIED] Morning Train" in out
        assert "Backed up database" in out
        assert _person(store, "Morning Train") is None
        backups = list(Path(db_path).parent.glob("graph.db.bak-*"))
        assert backups, "expected a timestamped .bak file next to the db"

    def test_unknown_person_exits_nonzero(self, store: GraphStore, db_path: str, capsys) -> None:
        with pytest.raises(SystemExit) as excinfo:
            self._run(db_path, ["Nobody"], apply=False)
        assert excinfo.value.code == 1
        assert "no matching person" in capsys.readouterr().out
