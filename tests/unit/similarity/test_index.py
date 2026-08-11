"""Near-duplicate grouping.

Exercised through ``group_near_duplicates_isolated`` — the subprocess path that
production uses — rather than by importing ``src.similarity.index`` directly.
That is not indirection for its own sake: faiss aborts the interpreter if torch
has already initialised OpenMP in it, and torch is loaded by many other modules
in this suite, so an in-process faiss call here would kill the whole pytest run
depending on collection order. See src/similarity/worker.py.

Descriptors are synthetic unit-norm vectors: the grouping contract is
independent of where the vectors came from, and the SSCD model is a 94 MB
download.
"""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from src.similarity.worker import group_near_duplicates_isolated

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("faiss") is None, reason="faiss-cpu not installed"
)

DIMENSIONS = 8


def unit_vector(*components: float) -> np.ndarray:
    """A padded, L2-normalised descriptor — the shape SSCD emits."""
    vector = np.zeros(DIMENSIONS, dtype="float32")
    vector[: len(components)] = components
    return vector / np.linalg.norm(vector)


def paths(count: int) -> list:
    return [Path(f"/corpus/file_{index}.png") for index in range(count)]


class TestGrouping:
    def test_identical_descriptors_group(self):
        descriptors = np.vstack([unit_vector(1, 0), unit_vector(1, 0)])

        groups = group_near_duplicates_isolated(paths(2), descriptors, threshold=0.85)

        assert len(groups) == 1
        assert groups[0].size == 2
        assert groups[0].max_similarity == pytest.approx(1.0, abs=1e-5)

    def test_orthogonal_descriptors_do_not_group(self):
        descriptors = np.vstack([unit_vector(1, 0), unit_vector(0, 1)])

        assert group_near_duplicates_isolated(paths(2), descriptors, threshold=0.85) == []

    def test_distinct_clusters_become_distinct_groups(self):
        descriptors = np.vstack(
            [unit_vector(1, 0), unit_vector(1, 0), unit_vector(0, 1), unit_vector(0, 1)]
        )

        groups = group_near_duplicates_isolated(paths(4), descriptors, threshold=0.85)

        assert len(groups) == 2
        assert all(group.size == 2 for group in groups)

    def test_chained_similarity_forms_one_group(self):
        # A~B and B~C above threshold, A~C below: documented transitive grouping.
        a = unit_vector(1, 0)
        b = unit_vector(np.cos(np.pi / 8), np.sin(np.pi / 8))
        c = unit_vector(np.cos(np.pi / 4), np.sin(np.pi / 4))
        threshold = 0.85
        assert float(a @ c) < threshold < float(a @ b)

        groups = group_near_duplicates_isolated(paths(3), np.vstack([a, b, c]), threshold)

        assert len(groups) == 1
        assert groups[0].size == 3

    def test_unmatched_files_are_omitted(self):
        descriptors = np.vstack([unit_vector(1, 0), unit_vector(1, 0), unit_vector(0, 1)])

        groups = group_near_duplicates_isolated(paths(3), descriptors, threshold=0.85)

        assert len(groups) == 1
        assert Path("/corpus/file_2.png") not in groups[0].paths

    def test_groups_ordered_largest_first(self):
        descriptors = np.vstack([unit_vector(0, 1)] * 2 + [unit_vector(1, 0)] * 3)

        groups = group_near_duplicates_isolated(paths(5), descriptors, threshold=0.85)

        assert [group.size for group in groups] == [3, 2]

    def test_each_unordered_pair_reported_once(self):
        # Three mutually identical files: 3 unordered pairs, not 6 ordered ones.
        descriptors = np.vstack([unit_vector(1, 0)] * 3)

        group = group_near_duplicates_isolated(paths(3), descriptors, threshold=0.85)[0]

        assert len(group.pairs) == 3
        assert all(pair.left != pair.right for pair in group.pairs)

    def test_threshold_is_inclusive_lower_bound(self):
        # cos(60 degrees) = 0.5 exactly.
        descriptors = np.vstack([unit_vector(1, 0), unit_vector(0.5, np.sqrt(3) / 2)])

        assert group_near_duplicates_isolated(paths(2), descriptors, threshold=0.5)
        assert group_near_duplicates_isolated(paths(2), descriptors, threshold=0.51) == []

    def test_magnitude_is_ignored(self):
        # A 5x-scaled copy is the same image; cosine must score 1.0, not 5.0.
        descriptors = np.vstack([unit_vector(1, 0), unit_vector(1, 0) * 5])

        group = group_near_duplicates_isolated(paths(2), descriptors, threshold=0.85)[0]

        assert group.max_similarity == pytest.approx(1.0, abs=1e-5)

    def test_max_neighbors_does_not_truncate_below_group_size(self):
        descriptors = np.vstack([unit_vector(1, 0)] * 4)

        group = group_near_duplicates_isolated(
            paths(4), descriptors, threshold=0.85, max_neighbors=3
        )[0]

        assert group.size == 4

    def test_single_file_cannot_match_itself(self):
        assert group_near_duplicates_isolated(paths(1), np.vstack([unit_vector(1, 0)]), 0.0) == []

    def test_no_files_yields_no_groups(self):
        assert group_near_duplicates_isolated([], np.zeros((0, DIMENSIONS), "float32")) == []


class TestProcessIsolation:
    def test_runs_with_torch_already_loaded(self):
        """The regression this whole design exists for.

        An in-process faiss search after torch has initialised OpenMP aborts
        the interpreter (OMP: Error #15). If this test ever fails by killing
        the run rather than by assertion, the isolation has been undone.
        """
        pytest.importorskip("torch")
        import torch

        assert torch.randn(2, 2).shape == (2, 2)

        descriptors = np.vstack([unit_vector(1, 0), unit_vector(1, 0)])
        groups = group_near_duplicates_isolated(paths(2), descriptors, threshold=0.85)

        assert len(groups) == 1
