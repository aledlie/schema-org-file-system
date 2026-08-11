"""The faiss subprocess boundary: failures surface, results round-trip.

The worker exists so faiss never shares a process with torch. That indirection
adds a failure mode the in-process version did not have — the child can die
without the parent noticing — so a silent failure here would read as "no
duplicates found" rather than as an error.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from src.similarity.types import DuplicateGroup, SimilarPair
from src.similarity.worker import IndexWorkerError, _group_from_dict

_REPO_ROOT = Path(__file__).resolve().parents[3]


class TestResultRoundTrip:
    def test_paths_and_similarities_survive_serialisation(self):
        payload = {
            "paths": ["/corpus/map.pdf", "/corpus/map_300dpi.png"],
            "pairs": [
                {
                    "left": "/corpus/map.pdf",
                    "right": "/corpus/map_300dpi.png",
                    "similarity": 0.9987,
                }
            ],
        }

        group = _group_from_dict(payload)

        assert group.paths == (Path("/corpus/map.pdf"), Path("/corpus/map_300dpi.png"))
        assert group.pairs[0].similarity == 0.9987
        assert isinstance(group.pairs[0].left, Path)

    def test_paths_with_spaces_and_unicode_survive(self):
        """Paths cross the boundary as JSON strings, not as shell arguments."""
        payload = {
            "paths": ["/corpus/Burning Flipside/Placement Map.pdf", "/corpus/café/map ①.png"],
            "pairs": [
                {
                    "left": "/corpus/Burning Flipside/Placement Map.pdf",
                    "right": "/corpus/café/map ①.png",
                    "similarity": 0.9,
                }
            ],
        }

        group = _group_from_dict(payload)

        assert group.paths[0].name == "Placement Map.pdf"
        assert group.paths[1].name == "map ①.png"


def run_worker(*argv: str) -> subprocess.CompletedProcess:
    """Invoke the child exactly as the parent does.

    Never call ``worker.main`` in-process: it runs a faiss search, and this
    pytest interpreter has torch loaded by sibling test modules, so an
    in-process call aborts the entire run with OMP: Error #15. (Learned the
    hard way — an earlier version of this file did exactly that and passed in
    isolation while killing the full suite.)
    """
    return subprocess.run(
        [sys.executable, "-m", "src.similarity.worker", *argv],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )


class TestChildEntryPoint:
    def test_writes_groups_for_a_valid_job(self, tmp_path):
        pytest.importorskip("faiss")
        descriptors = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype="float32")
        np.save(tmp_path / "descriptors.npy", descriptors)
        job = tmp_path / "job.json"
        job.write_text(
            json.dumps(
                {
                    "paths": ["/a.png", "/b.png", "/c.png"],
                    "threshold": 0.85,
                    "max_neighbors": 10,
                    "descriptors": "descriptors.npy",
                    "result": "result.json",
                }
            )
        )

        completed = run_worker(str(job))

        assert completed.returncode == 0, completed.stderr
        result = json.loads((tmp_path / "result.json").read_text())
        assert len(result["groups"]) == 1
        assert sorted(result["groups"][0]["paths"]) == ["/a.png", "/b.png"]

    def test_wrong_argument_count_is_a_usage_error(self, tmp_path):
        assert run_worker().returncode == 2
        assert run_worker("one.json", "two.json").returncode == 2


class TestParentSurfacesChildFailure:
    def test_missing_descriptor_file_raises_with_stderr(self, tmp_path, monkeypatch):
        """A child crash must raise, not quietly yield zero duplicates."""
        pytest.importorskip("faiss")
        from src.similarity import worker

        # Point the child at a job whose descriptor file was never written.
        original_save = np.save
        monkeypatch.setattr(np, "save", lambda *_a, **_k: None)
        try:
            with pytest.raises(IndexWorkerError) as exc:
                worker.group_near_duplicates_isolated(
                    [Path("/a.png"), Path("/b.png")],
                    np.array([[1.0, 0.0], [1.0, 0.0]], dtype="float32"),
                )
        finally:
            monkeypatch.setattr(np, "save", original_save)

        message = str(exc.value)
        assert "faiss index worker exited" in message
        # The child's traceback is carried through for diagnosis.
        assert "Error" in message or "error" in message

    def test_fewer_than_two_files_short_circuits_without_a_subprocess(self, monkeypatch):
        from src.similarity import worker

        def fail(*_args, **_kwargs):
            raise AssertionError("should not spawn a worker for a single file")

        monkeypatch.setattr(worker.subprocess, "run", fail)

        assert (
            worker.group_near_duplicates_isolated(
                [Path("/only.png")], np.array([[1.0, 0.0]], dtype="float32")
            )
            == []
        )


class TestTypes:
    def test_group_reports_its_similarity_range(self):
        left, middle, right = Path("/a"), Path("/b"), Path("/c")
        group = DuplicateGroup(
            paths=(left, middle, right),
            pairs=(
                SimilarPair(left, middle, 0.95),
                SimilarPair(middle, right, 0.88),
            ),
        )

        assert group.size == 3
        assert group.min_similarity == 0.88
        assert group.max_similarity == 0.95

    def test_types_module_imports_no_native_libraries(self):
        """It crosses the process boundary, so both sides must import it safely."""
        import sys

        import src.similarity.types  # noqa: F401

        # Nothing in types.py should have pulled these in on its own account.
        assert "src.similarity.types" in sys.modules
