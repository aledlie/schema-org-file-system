"""Tests for GraphStore review-queue methods and the organize-files review-people CLI."""

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from src.storage.graph_store import GraphStore, PERSON_REVIEW_STATUSES
from src.storage.models import Person, file_people


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "graph.db")


@pytest.fixture
def store(db_path: str) -> GraphStore:
    return GraphStore(db_path)


def _create_person(store: GraphStore, name: str, **kwargs) -> Person:
    """Create a Person row (bypasses the validator via validate=False for seeding)."""
    session = store.get_session()
    person = store.get_or_create_person(name, session=session, validate=False)
    assert person is not None, f"seeding {name!r} must create a Person row"
    for key, val in kwargs.items():
        setattr(person, key, val)
    session.commit()
    person_id = person.id
    session.close()
    session = store.get_session()
    try:
        return session.query(Person).filter(Person.id == person_id).one()
    finally:
        session.close()


def _add_person_with_files(store: GraphStore, name: str, paths: list) -> None:
    """Attach name to files at paths; bypasses the validator (trusted test seed).

    Files are marked ORGANIZED with current_path set so they satisfy the
    get_all_people_with_files(min_files=1) filter.
    """
    from src.storage.models import FileStatus

    session = store.get_session()
    file_ids = []
    for path in paths:
        f = store.add_file(original_path=path, filename=Path(path).name, session=session)
        file_ids.append(f.id)
        store.add_file_to_person(f.id, name, session=session, validate=False)
    session.commit()
    session.close()
    for fid, path in zip(file_ids, paths):
        store.update_file_status(fid, FileStatus.ORGANIZED, destination=path)


class TestListPeopleByStatus:
    def test_returns_all_when_status_none(self, store: GraphStore) -> None:
        _create_person(store, "Alice Smith", review_status="auto_accepted")
        _create_person(store, "Bob Jones", review_status="pending_review")
        rows = store.list_people_by_status(status=None)
        names = {r["name"] for r in rows}
        assert "Alice Smith" in names
        assert "Bob Jones" in names

    def test_filters_by_pending_review(self, store: GraphStore) -> None:
        _create_person(store, "Alice Smith", review_status="auto_accepted")
        _create_person(store, "Pending Person", review_status="pending_review")
        rows = store.list_people_by_status(status="pending_review")
        assert len(rows) == 1
        assert rows[0]["name"] == "Pending Person"

    def test_filters_by_rejected(self, store: GraphStore) -> None:
        _create_person(store, "Alice Smith", review_status="auto_accepted")
        _create_person(store, "Bad Name Llc", review_status="rejected")
        rows = store.list_people_by_status(status="rejected")
        assert len(rows) == 1
        assert rows[0]["name"] == "Bad Name Llc"

    def test_raises_on_unknown_status(self, store: GraphStore) -> None:
        with pytest.raises(ValueError, match="unknown review_status"):
            store.list_people_by_status(status="bogus")

    def test_returns_ordered_by_name(self, store: GraphStore) -> None:
        _create_person(store, "Zara White", review_status="auto_accepted")
        _create_person(store, "Aaron Black", review_status="auto_accepted")
        rows = store.list_people_by_status(status="auto_accepted")
        names = [r["name"] for r in rows]
        assert names == sorted(names)

    def test_summary_includes_paths(self, store: GraphStore) -> None:
        _add_person_with_files(store, "Alice Smith", ["/tmp/a.pdf"])
        rows = store.list_people_by_status(status=None)
        alice = next(r for r in rows if r["name"] == "Alice Smith")
        assert "paths" in alice
        assert "person_id" in alice
        assert "review_status" in alice


class TestSetPersonReviewStatus:
    def test_accept_sets_confirmed(self, store: GraphStore) -> None:
        _create_person(store, "Pending Person", review_status="pending_review")
        result = store.set_person_review_status("Pending Person", "confirmed")
        assert result is not None
        assert result["new_status"] == "confirmed"
        assert result["old_status"] == "pending_review"
        rows = store.list_people_by_status(status="confirmed")
        assert rows[0]["name"] == "Pending Person"

    def test_reject_sets_rejected_tombstone(self, store: GraphStore) -> None:
        _create_person(store, "Bad Corp Name", review_status="pending_review")
        result = store.set_person_review_status("Bad Corp Name", "rejected")
        assert result is not None
        assert result["new_status"] == "rejected"

    def test_returns_none_for_unknown_person(self, store: GraphStore) -> None:
        result = store.set_person_review_status("Nobody At All", "confirmed")
        assert result is None

    def test_raises_on_invalid_status(self, store: GraphStore) -> None:
        _create_person(store, "Alice Smith", review_status="pending_review")
        with pytest.raises(ValueError, match="unknown review_status"):
            store.set_person_review_status("Alice Smith", "not_a_status")

    def test_accepts_integer_id(self, store: GraphStore) -> None:
        session = store.get_session()
        person = store.get_or_create_person("Alice Smith", session=session, validate=False)
        assert person is not None
        session.commit()
        pid = person.id
        session.close()
        result = store.set_person_review_status(pid, "confirmed")
        assert result is not None
        assert result["name"] == "Alice Smith"


class TestRevalidatePeople:
    def test_dry_run_does_not_write(self, store: GraphStore) -> None:
        _create_person(
            store, "Pending Person", review_status="pending_review", validation_scores={}
        )
        rows = store.revalidate_people(apply=False)
        assert isinstance(rows, list)
        # status in DB unchanged (dry run)
        db_rows = store.list_people_by_status(status="pending_review")
        assert len(db_rows) == 1

    def test_skips_confirmed_and_rejected(self, store: GraphStore) -> None:
        _create_person(store, "Confirmed Person", review_status="confirmed", validation_scores={})
        _create_person(store, "Rejected Name", review_status="rejected", validation_scores={})
        rows = store.revalidate_people(apply=True)
        # Neither row should be touched
        names = {r["name"] for r in rows}
        assert "Confirmed Person" not in names
        assert "Rejected Name" not in names

    def test_skips_already_validated_auto_accepted(self, store: GraphStore) -> None:
        _create_person(
            store,
            "Alice Smith",
            review_status="auto_accepted",
            validation_scores={"shape": 1.0, "gazetteer": 1.0},
        )
        rows = store.revalidate_people(apply=True)
        # Has validation_scores, so not a legacy row — should be skipped
        names = {r["name"] for r in rows}
        assert "Alice Smith" not in names

    def test_rescores_legacy_auto_accepted(self, store: GraphStore) -> None:
        # A legacy row has empty validation_scores
        _create_person(store, "Alice Smith", review_status="auto_accepted", validation_scores={})
        rows = store.revalidate_people(apply=True)
        names = {r["name"] for r in rows}
        assert "Alice Smith" in names

    def test_changed_flag_accurate(self, store: GraphStore) -> None:
        _create_person(
            store, "Pending Person", review_status="pending_review", validation_scores={}
        )
        rows = store.revalidate_people(apply=True)
        assert isinstance(rows, list)
        for row in rows:
            assert "changed" in row
            assert "old_status" in row
            assert "new_status" in row


class TestGetAllPeopleWithFilesNoDenylist:
    """After Phase 3 the denylist no longer guards get_all_people_with_files.
    Status filter is now the sole gate."""

    def test_rejected_excluded(self, store: GraphStore) -> None:
        _add_person_with_files(store, "Alice Smith", ["/tmp/a.pdf"])
        _create_person(store, "Bad Corp Inc", review_status="rejected")
        results = store.get_all_people_with_files()
        names = {name for name, _ in results}
        assert "Alice Smith" in names
        assert "Bad Corp Inc" not in names

    def test_pending_excluded(self, store: GraphStore) -> None:
        _add_person_with_files(store, "Alice Smith", ["/tmp/a.pdf"])
        _create_person(store, "Ambiguous Camp Name", review_status="pending_review")
        results = store.get_all_people_with_files()
        names = {name for name, _ in results}
        assert "Alice Smith" in names
        assert "Ambiguous Camp Name" not in names

    def test_auto_accepted_visible(self, store: GraphStore) -> None:
        _add_person_with_files(store, "Alice Smith", ["/tmp/a.pdf"])
        session = store.get_session()
        alice_norm = Person.normalize_name("Alice Smith")
        person = session.query(Person).filter(Person.normalized_name == alice_norm).first()
        assert person is not None
        person.review_status = "auto_accepted"
        session.commit()
        session.close()
        results = store.get_all_people_with_files()
        names = {name for name, _ in results}
        assert "Alice Smith" in names


class TestReviewPeopleCli:
    def _run(self, db_path: str, **kwargs) -> None:
        from src.cli import cmd_review_people

        defaults = {
            "db_path": db_path,
            "apply": False,
            "status": "pending_review",
            "accept": None,
            "reject": None,
            "revalidate": False,
        }
        defaults.update(kwargs)
        cmd_review_people(argparse.Namespace(**defaults))

    def test_list_pending_empty(self, store: GraphStore, db_path: str, capsys) -> None:
        self._run(db_path)
        out = capsys.readouterr().out
        assert "No people" in out or "pending_review" in out

    def test_list_pending_shows_person(self, store: GraphStore, db_path: str, capsys) -> None:
        _create_person(
            store, "Pending Person", review_status="pending_review", detection_confidence=0.55
        )
        self._run(db_path, status="pending_review")
        out = capsys.readouterr().out
        assert "Pending Person" in out

    def test_revalidate_dry_run_no_writes(self, store: GraphStore, db_path: str, capsys) -> None:
        _create_person(
            store, "Pending Person", review_status="pending_review", validation_scores={}
        )
        self._run(db_path, revalidate=True, apply=False)
        out = capsys.readouterr().out
        assert "DRY RUN" in out
        # DB unchanged
        rows = store.list_people_by_status(status="pending_review")
        assert len(rows) == 1

    def test_accept_dry_run_no_writes(self, store: GraphStore, db_path: str, capsys) -> None:
        _create_person(store, "Pending Person", review_status="pending_review")
        self._run(db_path, accept=["Pending Person"], apply=False)
        # dry-run: status not changed
        rows = store.list_people_by_status(status="pending_review")
        assert len(rows) == 1

    def test_reject_apply_sets_tombstone(self, store: GraphStore, db_path: str, capsys) -> None:
        _create_person(store, "Bad Corp Inc", review_status="pending_review")
        self._run(db_path, reject=["Bad Corp Inc"], apply=True)
        rows = store.list_people_by_status(status="rejected")
        assert any(r["name"] == "Bad Corp Inc" for r in rows)

    def test_unknown_status_exits(self, store: GraphStore, db_path: str, capsys) -> None:
        with pytest.raises(SystemExit) as excinfo:
            self._run(db_path, status="bogus_status")
        assert excinfo.value.code == 2

    def test_apply_backs_up_on_accept(self, store: GraphStore, db_path: str, capsys) -> None:
        _create_person(store, "Pending Person", review_status="pending_review")
        self._run(db_path, accept=["Pending Person"], apply=True)
        out = capsys.readouterr().out
        assert "Backed up database" in out


class TestBuildPersonJsonldAdditionalProperty:
    def test_sidecar_present_when_columns_set(self) -> None:
        from src.storage.models import build_person_jsonld

        class FakePerson:
            canonical_id = "00000000-0000-0000-0000-000000000001"
            name = "Alice Smith"
            email = None
            role = None
            first_seen = None
            last_seen = None
            file_count = 2
            review_status = "auto_accepted"
            detection_confidence = 0.82
            validation_scores = {"shape": 1.0, "gazetteer": 1.0}

        result = build_person_jsonld(FakePerson())
        assert "additionalProperty" in result
        props = {p["propertyID"]: p["value"] for p in result["additionalProperty"]}
        assert props["ml:reviewStatus"] == "auto_accepted"
        assert props["ml:detectionConfidence"] == 0.82
        assert "shape" in props["ml:validationScores"]

    def test_sidecar_absent_for_legacy_row(self) -> None:
        from src.storage.models import build_person_jsonld

        class FakeLegacyPerson:
            canonical_id = "00000000-0000-0000-0000-000000000002"
            name = "Bob Jones"
            email = None
            role = None
            first_seen = None
            last_seen = None
            file_count = 1
            review_status = None
            detection_confidence = None
            validation_scores = None

        result = build_person_jsonld(FakeLegacyPerson())
        assert "additionalProperty" not in result

    def test_sidecar_absent_when_no_attribute(self) -> None:
        from src.storage.models import build_person_jsonld

        class PreMigrationPerson:
            canonical_id = "00000000-0000-0000-0000-000000000003"
            name = "Carol White"
            email = None
            role = None
            first_seen = None
            last_seen = None
            file_count = 0
            # deliberately no review_status / detection_confidence / validation_scores

        result = build_person_jsonld(PreMigrationPerson())
        assert "additionalProperty" not in result

    def test_empty_validation_scores_no_sidecar_entry(self) -> None:
        from src.storage.models import build_person_jsonld

        class PersonWithEmptyScores:
            canonical_id = "00000000-0000-0000-0000-000000000004"
            name = "Dan Brown"
            email = None
            role = None
            first_seen = None
            last_seen = None
            file_count = 1
            review_status = "auto_accepted"
            detection_confidence = None
            validation_scores: dict[str, float] = {}

        result = build_person_jsonld(PersonWithEmptyScores())
        # review_status present but no confidence or scores
        props = {p["propertyID"] for p in result.get("additionalProperty", [])}
        assert "ml:reviewStatus" in props
        assert "ml:detectionConfidence" not in props
        assert "ml:validationScores" not in props
