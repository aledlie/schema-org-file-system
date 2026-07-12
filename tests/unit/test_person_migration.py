#!/usr/bin/env python3
"""
Unit tests for src/storage/person_migration.py - Option C phase 5 migration.

Covers:
- Filesystem-walk-driven plan building (NAME dir, Identity dir, Employment
  dir, and an unrecognized-subfolder fallback case)
- Dry run makes no filesystem or DB changes
- Apply moves files to Personal/{subcat}/ with collision-safety
- Manifest is written and complete
- Rollback reverses an apply run back to the original state exactly

Never touches a real ~/Documents path -- everything runs against tmp_path.
"""

from pathlib import Path

import pytest

from src.storage.graph_store import GraphStore
from src.storage.models import FileStatus
from src.storage.person_migration import (
    PERSONAL_SUBCAT_FOLDER,
    SUBCAT_CONTACTS,
    SUBCAT_EMPLOYMENT,
    SUBCAT_IDENTIFICATION,
    SUBCAT_OTHER,
    SUBCAT_SOURCE_FALLBACK,
    SUBCAT_SOURCE_SUBFOLDER,
    build_migration_plan,
    load_manifest,
    migrate_person_files,
    rollback_person_migration,
    write_manifest,
)


@pytest.fixture
def person_tree(tmp_path: Path) -> Path:
    """Build a fake ~/Documents/Person tree with the four required cases:
    a NAME subdir, an Identity subdir, an Employment subdir, and a file
    with no DB row sitting under an unrecognized subfolder name."""
    person_root = tmp_path / "Documents" / "Person"

    name_dir = person_root / "Alyshia Ledlie"
    name_dir.mkdir(parents=True)
    (name_dir / "resume.pdf").write_text("resume contents")

    identity_dir = person_root / "Identity"
    identity_dir.mkdir(parents=True)
    (identity_dir / "passport.jpg").write_text("passport contents")

    employment_dir = person_root / "Employment"
    employment_dir.mkdir(parents=True)
    (employment_dir / "offer_letter.pdf").write_text("offer letter contents")

    unrecognized_dir = person_root / "Misc"
    unrecognized_dir.mkdir(parents=True)
    (unrecognized_dir / "random_note.txt").write_text("random note contents")

    return person_root


@pytest.fixture
def documents_root(tmp_path: Path) -> Path:
    return tmp_path / "Documents"


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test.db")


class TestBuildMigrationPlan:
    def test_name_dir_maps_to_contacts(self, person_tree: Path, documents_root: Path) -> None:
        entries = build_migration_plan(person_tree, documents_root)
        entry = next(e for e in entries if Path(e.src).name == "resume.pdf")

        assert entry.subcat == SUBCAT_CONTACTS
        assert entry.subcat_source == SUBCAT_SOURCE_SUBFOLDER
        assert entry.flagged is False
        assert entry.dst == str(documents_root / PERSONAL_SUBCAT_FOLDER[SUBCAT_CONTACTS] / "resume.pdf")

    def test_identity_dir_maps_to_identification(self, person_tree: Path, documents_root: Path) -> None:
        entries = build_migration_plan(person_tree, documents_root)
        entry = next(e for e in entries if Path(e.src).name == "passport.jpg")

        assert entry.subcat == SUBCAT_IDENTIFICATION
        assert entry.subcat_source == SUBCAT_SOURCE_SUBFOLDER
        assert entry.flagged is False

    def test_employment_dir_maps_to_employment(self, person_tree: Path, documents_root: Path) -> None:
        entries = build_migration_plan(person_tree, documents_root)
        entry = next(e for e in entries if Path(e.src).name == "offer_letter.pdf")

        assert entry.subcat == SUBCAT_EMPLOYMENT
        assert entry.subcat_source == SUBCAT_SOURCE_SUBFOLDER
        assert entry.flagged is False

    def test_unrecognized_subfolder_falls_back_to_other_and_is_flagged(
        self, person_tree: Path, documents_root: Path
    ) -> None:
        entries = build_migration_plan(person_tree, documents_root)
        entry = next(e for e in entries if Path(e.src).name == "random_note.txt")

        assert entry.subcat == SUBCAT_OTHER
        assert entry.subcat_source == SUBCAT_SOURCE_FALLBACK
        assert entry.flagged is True

    def test_plan_covers_every_real_file(self, person_tree: Path, documents_root: Path) -> None:
        entries = build_migration_plan(person_tree, documents_root)
        assert len(entries) == 4

    def test_no_db_path_still_produces_full_plan(self, person_tree: Path, documents_root: Path) -> None:
        entries = build_migration_plan(person_tree, documents_root, db_path=None)
        assert len(entries) == 4
        assert all(entry.file_id is None for entry in entries)


class TestDryRun:
    def test_dry_run_does_not_touch_disk(
        self, person_tree: Path, documents_root: Path, db_path: str, tmp_path: Path
    ) -> None:
        manifest_path = tmp_path / "manifest.json"

        result = migrate_person_files(
            person_root=person_tree,
            documents_root=documents_root,
            db_path=db_path,
            manifest_path=manifest_path,
            apply=False,
            verbose=False,
        )

        assert result["dry_run"] is True
        assert result["planned"] == 4
        assert result["flagged"] == 1

        # Source files must remain untouched.
        assert (person_tree / "Alyshia Ledlie" / "resume.pdf").exists()
        assert (person_tree / "Identity" / "passport.jpg").exists()
        assert (person_tree / "Employment" / "offer_letter.pdf").exists()
        assert (person_tree / "Misc" / "random_note.txt").exists()

        # Destination tree must not have been created (Person/ itself lives
        # under documents_root in this fixture layout, so check Personal/
        # specifically rather than documents_root as a whole).
        assert not (documents_root / "Personal").exists()

        # Manifest is still written so it can be inspected before --apply.
        assert manifest_path.exists()


class TestApply:
    def test_apply_moves_files_to_correct_destinations(
        self, person_tree: Path, documents_root: Path, db_path: str, tmp_path: Path
    ) -> None:
        manifest_path = tmp_path / "manifest.json"

        result = migrate_person_files(
            person_root=person_tree,
            documents_root=documents_root,
            db_path=db_path,
            manifest_path=manifest_path,
            apply=True,
            verbose=False,
        )

        assert result["dry_run"] is False
        assert result["migrated"] == 4

        assert (documents_root / "Personal" / "Contacts" / "resume.pdf").exists()
        assert (documents_root / "Personal" / "Identification" / "passport.jpg").exists()
        assert (documents_root / "Personal" / "Employment" / "offer_letter.pdf").exists()
        assert (documents_root / "Personal" / "Other" / "random_note.txt").exists()

        # Person/ root must be fully emptied of real files.
        remaining_files = [p for p in person_tree.rglob("*") if p.is_file()]
        assert remaining_files == []

    def test_apply_uses_collision_safe_destination(
        self, person_tree: Path, documents_root: Path, db_path: str, tmp_path: Path
    ) -> None:
        # Pre-create a colliding file at the computed destination for resume.pdf.
        contacts_dir = documents_root / "Personal" / "Contacts"
        contacts_dir.mkdir(parents=True)
        (contacts_dir / "resume.pdf").write_text("pre-existing, different content")

        manifest_path = tmp_path / "manifest.json"
        result = migrate_person_files(
            person_root=person_tree,
            documents_root=documents_root,
            db_path=db_path,
            manifest_path=manifest_path,
            apply=True,
            verbose=False,
        )

        assert result["migrated"] == 4
        # Original collision target left untouched.
        assert (contacts_dir / "resume.pdf").read_text() == "pre-existing, different content"
        # Migrated file renamed out of the way by resolve_collision.
        assert (contacts_dir / "resume_1.pdf").exists()
        assert (contacts_dir / "resume_1.pdf").read_text() == "resume contents"

    def test_manifest_is_complete(
        self, person_tree: Path, documents_root: Path, db_path: str, tmp_path: Path
    ) -> None:
        manifest_path = tmp_path / "manifest.json"
        migrate_person_files(
            person_root=person_tree,
            documents_root=documents_root,
            db_path=db_path,
            manifest_path=manifest_path,
            apply=True,
            verbose=False,
        )

        entries = load_manifest(manifest_path)
        assert len(entries) == 4
        for entry in entries:
            assert entry.src
            assert entry.dst
            assert entry.subcat in PERSONAL_SUBCAT_FOLDER
            assert entry.subcat_source in {"db", "subfolder", "fallback"}


class TestRollback:
    def test_rollback_restores_original_state_exactly(
        self, person_tree: Path, documents_root: Path, db_path: str, tmp_path: Path
    ) -> None:
        manifest_path = tmp_path / "manifest.json"

        original_contents = {
            str(person_tree / "Alyshia Ledlie" / "resume.pdf"): "resume contents",
            str(person_tree / "Identity" / "passport.jpg"): "passport contents",
            str(person_tree / "Employment" / "offer_letter.pdf"): "offer letter contents",
            str(person_tree / "Misc" / "random_note.txt"): "random note contents",
        }

        migrate_person_files(
            person_root=person_tree,
            documents_root=documents_root,
            db_path=db_path,
            manifest_path=manifest_path,
            apply=True,
            verbose=False,
        )

        # Sanity: files really did move.
        assert not (person_tree / "Alyshia Ledlie" / "resume.pdf").exists()

        rollback_result = rollback_person_migration(manifest_path, db_path=db_path, verbose=False)
        assert rollback_result["restored"] == 4

        for original_path, contents in original_contents.items():
            path = Path(original_path)
            assert path.exists()
            assert path.read_text() == contents

        # Destination side (Personal/) should be empty again. Checked
        # specifically rather than all of documents_root, since Person/
        # itself lives under documents_root in this fixture layout.
        personal_root = documents_root / "Personal"
        remaining = [p for p in personal_root.rglob("*") if p.is_file()] if personal_root.exists() else []
        assert remaining == []

    def test_rollback_uses_recorded_dst_not_recomputed_path(
        self, person_tree: Path, documents_root: Path, db_path: str, tmp_path: Path
    ) -> None:
        # Force a collision so the actual dst differs from the naively
        # computed one; rollback must still find the file via the manifest.
        contacts_dir = documents_root / "Personal" / "Contacts"
        contacts_dir.mkdir(parents=True)
        (contacts_dir / "resume.pdf").write_text("pre-existing, different content")

        manifest_path = tmp_path / "manifest.json"
        migrate_person_files(
            person_root=person_tree,
            documents_root=documents_root,
            db_path=db_path,
            manifest_path=manifest_path,
            apply=True,
            verbose=False,
        )

        entries = load_manifest(manifest_path)
        moved_entry = next(e for e in entries if Path(e.src).name == "resume.pdf")
        assert moved_entry.dst == str(contacts_dir / "resume_1.pdf")

        rollback_person_migration(manifest_path, db_path=db_path, verbose=False)

        restored = person_tree / "Alyshia Ledlie" / "resume.pdf"
        assert restored.exists()
        assert restored.read_text() == "resume contents"
        # The pre-existing collision file must remain untouched by rollback.
        assert (contacts_dir / "resume.pdf").read_text() == "pre-existing, different content"


class TestDbHintPrecedence:
    def test_db_row_subcat_overrides_subfolder_mapping(
        self, person_tree: Path, documents_root: Path, db_path: str
    ) -> None:
        # Give the "random_note.txt" file (in the unrecognized Misc/ folder)
        # a DB row filed under person/employees -> should map to employment,
        # taking precedence over the Misc/ -> other fallback.
        store = GraphStore(db_path)
        misc_path = str(person_tree / "Misc" / "random_note.txt")

        # Keep one session open across these calls: add_file's own session
        # is committed-and-closed by the time it returns, which expires and
        # detaches the returned object (any later attribute access on it
        # would raise DetachedInstanceError).
        session = store.get_session()
        file_obj = store.add_file(
            original_path=misc_path, filename="random_note.txt", session=session
        )
        file_id = file_obj.id
        store.update_file_status(
            file_id, FileStatus.ORGANIZED, destination=misc_path, session=session
        )
        store.add_file_to_category(file_id, "person", "employees", session=session)
        session.commit()
        session.close()

        entries = build_migration_plan(person_tree, documents_root, db_path=db_path)
        entry = next(e for e in entries if Path(e.src).name == "random_note.txt")

        assert entry.subcat == SUBCAT_EMPLOYMENT
        assert entry.subcat_source == "db"
        assert entry.flagged is False
        assert entry.file_id == file_id
