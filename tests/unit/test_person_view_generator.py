"""
Unit tests for PersonViewGenerator.

Uses a lightweight fake GraphStore (matching GraphStore.get_all_people_with_
files' signature/return shape) rather than a real GraphStore + tmp SQLite DB:
this worktree's src/storage/graph_store.py does not yet carry the Phase 3
`get_all_people_with_files`/`get_files_by_person` query methods (in-progress,
uncommitted, in a sibling agent's checkout), so a real GraphStore can't be
exercised here without editing that file, which is out of scope for this task.

All filesystem fixtures use pytest's `tmp_path`, so nothing ever touches a
real ~/Documents path.
"""

import os
from typing import Dict, List, Tuple

import pytest

from src.storage.person_view_generator import (
    PersonViewGenerator,
    PersonViewRealFileError,
)


class FakeGraphStore:
    """Mirrors GraphStore.get_all_people_with_files' signature/return shape."""

    def __init__(self, people_files: Dict[str, List[str]]):
        self._people_files = people_files

    def get_all_people_with_files(
        self, session=None, min_files: int = 1
    ) -> List[Tuple[str, List[str]]]:
        return [
            (name, paths)
            for name, paths in self._people_files.items()
            if len(paths) >= min_files
        ]


@pytest.fixture
def real_files_dir(tmp_path):
    real_dir = tmp_path / "Personal" / "Employment"
    real_dir.mkdir(parents=True)
    return real_dir


@pytest.fixture
def view_root(tmp_path):
    return tmp_path / "Person"


def test_dry_run_computes_without_touching_disk(real_files_dir, view_root):
    resume = real_files_dir / "resume.pdf"
    resume.write_text("resume contents")

    store = FakeGraphStore({"Jane Smith": [str(resume)]})
    generator = PersonViewGenerator(store, view_root=view_root)
    summary = generator.generate(dry_run=True, apply=False)

    assert summary == {
        "people": 1,
        "symlinks_created": 1,
        "removed_stale": 0,
        "dry_run": True,
        "errors": [],
    }
    assert not view_root.exists()


def test_apply_creates_expected_symlink_tree(real_files_dir, view_root):
    resume = real_files_dir / "resume.pdf"
    resume.write_text("resume contents")
    passport = real_files_dir.parent / "Identification" / "passport.pdf"
    passport.parent.mkdir(parents=True)
    passport.write_text("passport contents")

    store = FakeGraphStore({"Jane Smith": [str(resume), str(passport)]})
    generator = PersonViewGenerator(store, view_root=view_root)
    summary = generator.generate(dry_run=False, apply=True)

    assert summary["people"] == 1
    assert summary["symlinks_created"] == 2
    assert summary["errors"] == []

    person_dir = view_root / "Jane Smith"
    assert person_dir.is_dir()

    resume_link = person_dir / "resume.pdf"
    passport_link = person_dir / "passport.pdf"
    assert os.path.islink(resume_link)
    assert os.path.islink(passport_link)
    assert resume_link.resolve() == resume.resolve()
    assert passport_link.resolve() == passport.resolve()


def test_generate_requires_both_apply_and_not_dry_run(real_files_dir, view_root):
    resume = real_files_dir / "resume.pdf"
    resume.write_text("resume contents")

    store = FakeGraphStore({"Jane Smith": [str(resume)]})
    generator = PersonViewGenerator(store, view_root=view_root)

    # dry_run defaults True; apply=True alone must not write anything.
    summary = generator.generate(apply=True)

    assert summary["dry_run"] is True
    assert not view_root.exists()


def test_apply_is_idempotent_on_rerun(real_files_dir, view_root):
    resume = real_files_dir / "resume.pdf"
    resume.write_text("resume contents")

    store = FakeGraphStore({"Jane Smith": [str(resume)]})
    generator = PersonViewGenerator(store, view_root=view_root)
    first = generator.generate(dry_run=False, apply=True)
    second = generator.generate(dry_run=False, apply=True)

    assert first["symlinks_created"] == 1
    assert second["symlinks_created"] == 1
    assert second["removed_stale"] == 1
    assert second["errors"] == []

    person_dir = view_root / "Jane Smith"
    links = list(person_dir.iterdir())
    assert len(links) == 1
    assert os.path.islink(links[0])
    assert links[0].resolve() == resume.resolve()


def test_apply_aborts_on_real_file_under_view_root(real_files_dir, view_root):
    resume = real_files_dir / "resume.pdf"
    resume.write_text("resume contents")

    store = FakeGraphStore({"Jane Smith": [str(resume)]})
    generator = PersonViewGenerator(store, view_root=view_root)
    generator.generate(dry_run=False, apply=True)

    intruder = view_root / "Jane Smith" / "do_not_delete.txt"
    intruder.write_text("this is a real file, not a symlink")

    with pytest.raises(PersonViewRealFileError) as excinfo:
        generator.generate(dry_run=False, apply=True)

    assert str(intruder) in str(excinfo.value)
    assert intruder.exists()
    assert not os.path.islink(intruder)


def test_dry_run_reports_real_file_blocker_without_raising(real_files_dir, view_root):
    resume = real_files_dir / "resume.pdf"
    resume.write_text("resume contents")

    view_root.mkdir(parents=True)
    intruder = view_root / "stray.txt"
    intruder.write_text("real file")

    store = FakeGraphStore({"Jane Smith": [str(resume)]})
    generator = PersonViewGenerator(store, view_root=view_root)
    summary = generator.generate(dry_run=True, apply=False)

    assert summary["dry_run"] is True
    assert len(summary["errors"]) == 1
    assert str(intruder) in summary["errors"][0]
    assert intruder.exists()


def test_folder_name_collision_disambiguated(real_files_dir, view_root):
    file_a = real_files_dir / "a.pdf"
    file_b = real_files_dir / "b.pdf"
    file_a.write_text("a")
    file_b.write_text("b")

    # Two distinct person records that sanitize to the identical folder name.
    store = FakeGraphStore({"Jane Smith": [str(file_a)], "Jane  Smith": [str(file_b)]})
    generator = PersonViewGenerator(store, view_root=view_root)
    summary = generator.generate(dry_run=False, apply=True)

    assert summary["errors"] == []
    dirs = sorted(p.name for p in view_root.iterdir())
    assert dirs == ["Jane Smith", "Jane Smith_1"]


def test_symlink_basename_collision_disambiguated(real_files_dir, view_root):
    dir_one = real_files_dir / "one"
    dir_two = real_files_dir / "two"
    dir_one.mkdir()
    dir_two.mkdir()
    file_one = dir_one / "id.pdf"
    file_two = dir_two / "id.pdf"
    file_one.write_text("one")
    file_two.write_text("two")

    store = FakeGraphStore({"Jane Smith": [str(file_one), str(file_two)]})
    generator = PersonViewGenerator(store, view_root=view_root)
    summary = generator.generate(dry_run=False, apply=True)

    assert summary["errors"] == []
    person_dir = view_root / "Jane Smith"
    names = sorted(p.name for p in person_dir.iterdir())
    assert names == ["id.pdf", "id_1.pdf"]


def test_min_files_filters_people_with_too_few_files(real_files_dir, view_root):
    resume = real_files_dir / "resume.pdf"
    resume.write_text("resume contents")

    store = FakeGraphStore({"Jane Smith": [str(resume)]})
    generator = PersonViewGenerator(store, view_root=view_root)
    summary = generator.generate(dry_run=True, apply=False, min_files=2)

    assert summary["people"] == 0
    assert summary["symlinks_created"] == 0
