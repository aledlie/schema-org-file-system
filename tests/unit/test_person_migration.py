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
    SUBCAT_EVENTS,
    SUBCAT_IDENTIFICATION,
    SUBCAT_JOURNAL,
    SUBCAT_LEGAL,
    SUBCAT_OTHER,
    SUBCAT_RECORDS,
    SUBCAT_SOURCE_FALLBACK,
    SUBCAT_SOURCE_SUBFOLDER,
    MigrationEntry,
    apply_person_index,
    build_migration_plan,
    build_person_index,
    index_person_files,
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

    def test_nested_docclass_folder_beats_name_dir(
        self, tmp_path: Path, documents_root: Path
    ) -> None:
        # A doc-class folder nested under a person NAME dir must win over the
        # name dir's contacts default (deepest-match wins).
        person_root = tmp_path / "Documents" / "Person"
        cases = {
            # Employment folder under a name dir beats the contacts default.
            "Alyshia Ledlie/Employment/offer.pdf": SUBCAT_EMPLOYMENT,
            # Journal/Personal get their own dedicated subcats (deepest wins).
            "Alyshia Ledlie/Personal/Journal/dream.docx": SUBCAT_JOURNAL,
            "Alyshia Ledlie/Personal/report.pdf": SUBCAT_RECORDS,
            "Alyshia Ledlie/Events/party.pdf": SUBCAT_EVENTS,
            "Alyshia Ledlie/DUI Docs/citation.pdf": SUBCAT_LEGAL,
            # Resumes stay in contacts (plan: resumes/CVs -> contacts).
            "Alyshia Ledlie/Resumes/cv.pdf": SUBCAT_CONTACTS,
            # A loose file directly under the name dir keeps the contacts default.
            "Alyshia Ledlie/loose_contact.pdf": SUBCAT_CONTACTS,
        }
        for rel, _ in cases.items():
            f = person_root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x")

        entries = build_migration_plan(person_root, documents_root)
        by_name = {Path(e.src).name: e for e in entries}
        for rel, expected in cases.items():
            name = Path(rel).name
            assert by_name[name].subcat == expected, rel
            assert by_name[name].subcat_source == SUBCAT_SOURCE_SUBFOLDER

    def test_docclass_ancestor_wins_over_nested_name_dir(
        self, tmp_path: Path, documents_root: Path
    ) -> None:
        # ".../Identity/Alyshia Ledlie/passport.jpg" is identification — the
        # name dir nested *under* a doc-class folder must not hijack it.
        person_root = tmp_path / "Documents" / "Person"
        f = person_root / "Identity" / "Alyshia Ledlie" / "passport.jpg"
        f.parent.mkdir(parents=True)
        f.write_text("x")

        entries = build_migration_plan(person_root, documents_root)
        entry = next(e for e in entries if Path(e.src).name == "passport.jpg")
        assert entry.subcat == SUBCAT_IDENTIFICATION
        assert entry.subcat_source == SUBCAT_SOURCE_SUBFOLDER

    def test_os_junk_files_are_excluded(
        self, tmp_path: Path, documents_root: Path
    ) -> None:
        person_root = tmp_path / "Documents" / "Person"
        name_dir = person_root / "Alyshia Ledlie"
        name_dir.mkdir(parents=True)
        (name_dir / "resume.pdf").write_text("resume contents")
        # OS/metadata junk that must never be migrated.
        (person_root / ".DS_Store").write_text("junk")
        (name_dir / ".DS_Store").write_text("junk")
        (name_dir / "._resume.pdf").write_text("appledouble")
        (name_dir / "Thumbs.db").write_text("junk")

        entries = build_migration_plan(person_root, documents_root)
        migrated_names = {Path(e.src).name for e in entries}

        assert migrated_names == {"resume.pdf"}

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


class TestPersonIndex:
    """index-people: attach person edges from the manifest without moving files."""

    def _manifest(self, tmp_path: Path, person_root: Path) -> Path:
        # src paths encode the person via the original Person/{Name}/ dir; one
        # entry sits under a doc-class dir with no name (must get no edge).
        entries = [
            MigrationEntry(
                src=str(person_root / "Jane Smith" / "resume.pdf"),
                dst=str(tmp_path / "Personal" / "Contacts" / "resume.pdf"),
                subcat="contacts",
                subcat_source="subfolder",
            ),
            MigrationEntry(
                src=str(person_root / "Identity" / "Jane Smith" / "passport.jpg"),
                dst=str(tmp_path / "Personal" / "Identification" / "passport.jpg"),
                subcat="identification",
                subcat_source="subfolder",
            ),
            MigrationEntry(
                src=str(person_root / "Employment" / "orphan.pdf"),
                dst=str(tmp_path / "Personal" / "Employment" / "orphan.pdf"),
                subcat="employment",
                subcat_source="subfolder",
            ),
        ]
        manifest_path = tmp_path / "manifest.json"
        write_manifest(entries, manifest_path)
        return manifest_path

    def test_build_index_attributes_by_name_dir(self, tmp_path: Path) -> None:
        person_root = tmp_path / "Documents" / "Person"
        manifest = self._manifest(tmp_path, person_root)

        index = build_person_index(manifest, person_root=person_root)
        people = {name for _dst, name in index}

        assert people == {"Jane Smith"}  # orphan.pdf excluded
        assert len(index) == 2  # resume + passport, both Jane Smith
        # the name dir nested under Identity/ is still attributed
        assert any("passport.jpg" in dst for dst, _ in index)

    def test_apply_creates_person_edges(self, tmp_path: Path, db_path: str) -> None:
        person_root = tmp_path / "Documents" / "Person"
        manifest = self._manifest(tmp_path, person_root)
        index = build_person_index(manifest, person_root=person_root)

        edges = apply_person_index(index, db_path)
        assert edges == 2

        store = GraphStore(db_path)
        session = store.get_session()
        try:
            people = store.get_all_people_with_files(session=session)
        finally:
            session.close()
        by_name = dict(people)
        assert "Jane Smith" in by_name
        assert len(by_name["Jane Smith"]) == 2  # current_paths recorded

    def test_dry_run_writes_nothing(self, tmp_path: Path, db_path: str) -> None:
        person_root = tmp_path / "Documents" / "Person"
        manifest = self._manifest(tmp_path, person_root)

        result = index_person_files(
            manifest_path=manifest, db_path=db_path,
            person_root=person_root, apply=False, verbose=False,
        )
        assert result["dry_run"] is True
        assert result["attributed"] == 2
        assert result["people"] == {"Jane Smith": 2}

        store = GraphStore(db_path)
        session = store.get_session()
        try:
            assert store.get_all_people_with_files(session=session) == []
        finally:
            session.close()

    def test_apply_is_idempotent(self, tmp_path: Path, db_path: str) -> None:
        person_root = tmp_path / "Documents" / "Person"
        manifest = self._manifest(tmp_path, person_root)
        index = build_person_index(manifest, person_root=person_root)

        apply_person_index(index, db_path)
        apply_person_index(index, db_path)  # second run must not duplicate edges

        store = GraphStore(db_path)
        session = store.get_session()
        try:
            people = dict(store.get_all_people_with_files(session=session))
        finally:
            session.close()
        assert len(people["Jane Smith"]) == 2
