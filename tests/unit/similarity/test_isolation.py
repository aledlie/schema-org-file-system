"""Guards on the faiss/torch process-isolation design.

faiss and torch each bundle their own libomp; whichever initialises second
aborts the process (`OMP: Error #15`), and `KMP_DUPLICATE_LIB_OK=TRUE`
segfaults rather than degrading. The feature therefore keeps faiss in a
subprocess, and several call sites must *probe* for faiss without importing it.

Those probes look like harmless simplifications — `importlib.util.find_spec`
reads as pointless next to a plain `import faiss` — so they are exactly the
thing a future cleanup removes. Each test below turns that cleanup red.
They run the check in a fresh interpreter, because a co-resident test may
already have imported either library into this one.
"""

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


def in_clean_interpreter(body: str) -> str:
    """Run `body` in a fresh process at the repo root; return its stdout."""
    completed = subprocess.run(
        [sys.executable, "-c", body],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert (
        completed.returncode == 0
    ), f"subprocess failed ({completed.returncode}):\n{completed.stderr}"
    return completed.stdout.strip()


class TestImportsStayApart:
    def test_importing_the_package_pulls_in_neither_torch_nor_faiss(self):
        """__init__ resolves attributes lazily (PEP 562) for this reason.

        An eager re-export would drag torch into the faiss child process and
        faiss into the torch parent — the exact co-load that aborts.
        """
        output = in_clean_interpreter(
            "import sys; import src.similarity;"
            "print('torch' in sys.modules, 'faiss' in sys.modules)"
        )

        assert output == "False False"

    def test_the_faiss_probe_does_not_import_faiss(self):
        """finder runs in the torch-side process."""
        pytest.importorskip("faiss")
        output = in_clean_interpreter(
            "import sys;"
            "from src.similarity.finder import _faiss_installed;"
            "found = _faiss_installed();"
            "print(found, 'faiss' in sys.modules)"
        )

        assert output == "True False"

    def test_unavailable_reason_does_not_import_faiss(self):
        output = in_clean_interpreter(
            "import sys;"
            "from src.similarity.finder import unavailable_reason;"
            "unavailable_reason();"
            "print('faiss' in sys.modules)"
        )

        assert output == "False"

    def test_health_check_reports_faiss_without_importing_it(self):
        """The health checker imports torch for the CLIP probe in the same run."""
        pytest.importorskip("faiss")
        output = in_clean_interpreter(
            "import sys; sys.path.insert(0, 'src');"
            "from health_check import SystemHealthChecker;"
            "c = SystemHealthChecker(); c._check_similarity();"
            "print(c.features['similarity'].available, 'faiss' in sys.modules)"
        )

        assert output == "True False"

    def test_the_worker_child_does_not_import_torch(self):
        """The child indexes with faiss; importing torch there would abort it."""
        output = in_clean_interpreter(
            "import sys; import src.similarity.worker;" "print('torch' in sys.modules)"
        )

        assert output == "False"


class TestHealthCheckReporting:
    def test_reports_unavailable_when_faiss_is_absent(self):
        output = in_clean_interpreter(
            "import importlib.util, sys; sys.path.insert(0, 'src');"
            "real = importlib.util.find_spec;"
            "importlib.util.find_spec = lambda n, *a, **k: "
            "(None if n == 'faiss' else real(n, *a, **k));"
            "from health_check import SystemHealthChecker;"
            "c = SystemHealthChecker(); c._check_similarity();"
            "s = c.features['similarity'];"
            "print(s.available, 'faiss-cpu' in (s.error or ''))"
        )

        assert output == "False True"
