"""Drift guard for the generated D1 schema.

``scripts/d1/schema.sql`` is rendered from ``Base.metadata`` by
``scripts/d1/generate_schema.py``, and its own header says the file is
authoritative and must not be hand-edited. Nothing enforced the other half of
that contract: editing ``src/storage/models.py`` without re-running the
generator left the committed SQL stale, silently.

It had drifted across three model changes before anyone noticed (2026-07-27):
the ``ix_categories_name`` UNIQUE index whose bug dropped category edges for
26% of rows, the four person-validation columns, and
``file_categories.signal_evidence``. A D1 load against that schema would have
failed on the missing columns or recreated the fixed UNIQUE bug in the mirror.

This regenerates in memory and compares against the committed file, so the
drift surfaces in CI on the commit that causes it rather than at deploy time.

Workflow when this test fails:
    python scripts/d1/generate_schema.py    # then commit the updated schema.sql

The generator is imported, never executed as a script — ``main()`` sits behind
an ``if __name__ == "__main__"`` guard, so importing it here cannot write to
the repo.
"""

from pathlib import Path

import pytest

from d1.generate_schema import _OUTPUT, generate

REGENERATE_HINT = "Run `python scripts/d1/generate_schema.py` and commit the result."


@pytest.fixture(scope="module")
def committed_schema() -> str:
    return _OUTPUT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def generated_schema() -> str:
    return generate()


def test_committed_schema_exists() -> None:
    """The generator's output path resolves to a real, non-empty file.

    Guards the case where _OUTPUT is repointed or the file is deleted: without
    this, the comparison below would fail with a bare FileNotFoundError from a
    fixture and read as an unrelated collection error.
    """
    assert _OUTPUT.is_file(), f"{_OUTPUT} is missing. {REGENERATE_HINT}"
    assert _OUTPUT.stat().st_size > 0, f"{_OUTPUT} is empty. {REGENERATE_HINT}"


def test_schema_sql_matches_models(committed_schema: str, generated_schema: str) -> None:
    """scripts/d1/schema.sql is what generate_schema.py currently emits.

    Byte-exact, deliberately: the generator's own output is the only thing that
    can satisfy it, so a hand-edit fails here too — which the file header
    already forbids.
    """
    if committed_schema == generated_schema:
        return

    # A plain assertEqual on two ~10 KB SQL blobs is unreadable, so report the
    # first differing line and the size delta instead.
    committed_lines = committed_schema.splitlines()
    generated_lines = generated_schema.splitlines()
    first_diff = next(
        (i for i, (a, b) in enumerate(zip(committed_lines, generated_lines), start=1) if a != b),
        min(len(committed_lines), len(generated_lines)) + 1,
    )

    def _line(lines: list[str]) -> str:
        return lines[first_diff - 1] if first_diff <= len(lines) else "<end of file>"

    pytest.fail(
        f"{_OUTPUT.name} is stale — it does not match src/storage/models.py.\n"
        f"{REGENERATE_HINT}\n"
        f"First difference at line {first_diff}:\n"
        f"  committed: {_line(committed_lines)}\n"
        f"  generated: {_line(generated_lines)}\n"
        f"({len(committed_lines)} committed lines vs {len(generated_lines)} generated)"
    )


def test_generate_is_deterministic() -> None:
    """Two calls agree.

    If they did not, the test above would fail at random and get deleted rather
    than fixed. The generator sorts tables and indexes for exactly this reason;
    this pins that ordering as a requirement.
    """
    assert generate() == generate()


def test_generator_does_not_write_on_import() -> None:
    """Importing the generator must not touch the committed file.

    Pins the `if __name__ == "__main__"` guard: without it, merely collecting
    this module would rewrite schema.sql, and the drift test above would pass
    by repairing the very thing it is meant to detect.
    """
    source = Path(_OUTPUT).parent / "generate_schema.py"
    assert 'if __name__ == "__main__":' in source.read_text(encoding="utf-8")
