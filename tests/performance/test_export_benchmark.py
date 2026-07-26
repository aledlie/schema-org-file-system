"""
Performance benchmarks for SchemaOrgExporter.

Measures throughput of all four export methods across three data sizes.
10k tests are marked ``slow`` and skipped in normal CI runs.

Exporter benchmarks run *cold*: the ORM identity map is expunged before each
round (see ``_bench_cold``) so every timed call rebuilds ORM objects from
scratch. Without this, pytest-benchmark reuses warm identity-map objects across
rounds and reports times that never occur for a real one-shot export from a
fresh session.

Run benchmarks:
    pytest tests/performance/ -v --benchmark-only
    pytest tests/performance/ -v --benchmark-only -m "not slow"  # skip 10k

Save and compare baselines:
    pytest tests/performance/ --benchmark-save=baseline -m "not slow"
    pytest tests/performance/ --benchmark-compare=baseline -m "not slow"

Benchmark output files are stored under .benchmarks/ (add to .gitignore if desired).
"""

import sys
from pathlib import Path
from uuid import uuid4

from typing import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

_SRC_DIR = Path(__file__).parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from storage.models import Base, Category, File, file_categories
from storage.schema_org_exporter import SchemaOrgExporter

# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


def _hex64(i: int) -> str:
    """Return a 64-character hex string deterministically derived from i."""
    return format(i, "064x")


def _uuid_str(prefix: str, i: int) -> str:
    """Produce a stable UUID-formatted canonical ID for entity i."""
    # Use a short tag so IDs are unique across entity types in the same DB
    raw = f"{prefix}-{i}"
    # Pad to UUID format (8-4-4-4-12)
    h = format(hash(raw) & 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF, "032x")
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _seed_session(n: int) -> Session:
    """Create an in-memory SQLite session seeded with n Files and n Categories.

    No relationships are created so that seeding cost is O(n), not O(n²).
    Returns the open session; caller is responsible for closing it.
    """
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    files = [
        File(
            id=_hex64(i),
            filename=f"file_{i}.pdf",
            original_path=f"/docs/file_{i}.pdf",
            mime_type="application/pdf",
            file_size=1024 * (i % 100 + 1),
            canonical_id=f"urn:sha256:{_hex64(i)}",
        )
        for i in range(n)
    ]

    categories = [
        Category(
            name=f"Category_{i}",
            canonical_id=_uuid_str("cat", i),
            full_path=f"Category_{i}",
            level=0,
        )
        for i in range(n)
    ]

    session.bulk_save_objects(files)
    session.bulk_save_objects(categories)
    session.commit()
    return session


# ---------------------------------------------------------------------------
# Parametrized size fixture
# ---------------------------------------------------------------------------

_SIZES = [
    pytest.param(100, id="100"),
    pytest.param(1_000, id="1k"),
    pytest.param(10_000, id="10k", marks=pytest.mark.slow),
]


@pytest.fixture(params=_SIZES)
def seeded(request) -> Iterator[tuple[Session, int]]:
    """Yields (session, n) for the given entity count."""
    n: int = request.param
    session = _seed_session(n)
    yield session, n
    session.close()


# ---------------------------------------------------------------------------
# Cold-measurement helper
# ---------------------------------------------------------------------------

_COLD_ROUNDS = 5


def _bench_cold(benchmark, session, target, *args):
    """Benchmark ``target(*args)`` with a fresh (cold) ORM identity map per round.

    ``session.expunge_all()`` runs in pedantic ``setup`` before each timed round,
    dropping all instances from the identity map so every call rebuilds ORM
    objects from scratch — the real one-shot export cost. (``expire_all`` is
    insufficient: it keeps object shells and only refreshes attributes, leaving
    the measurement "semi-warm".) Returns the target's value.
    """

    def setup():
        session.expunge_all()
        return args, {}

    return benchmark.pedantic(target, setup=setup, rounds=_COLD_ROUNDS, iterations=1)


# ---------------------------------------------------------------------------
# Benchmark: get_graph_document (in-memory, no I/O)
# ---------------------------------------------------------------------------


def test_bench_get_graph_document(benchmark, seeded):
    session, n = seeded
    exporter = SchemaOrgExporter(session)
    result = _bench_cold(benchmark, session, exporter.get_graph_document, [File, Category])
    assert len(result["@graph"]) == n * 2


# ---------------------------------------------------------------------------
# Benchmark: export_to_file (JSON, pretty=False for pure serialization speed)
# ---------------------------------------------------------------------------


def test_bench_export_to_file(benchmark, seeded, tmp_path):
    session, n = seeded
    exporter = SchemaOrgExporter(session)
    out = tmp_path / "export.json"
    count = _bench_cold(benchmark, session, exporter.export_to_file, out, [File, Category], False)
    assert count == n * 2


# ---------------------------------------------------------------------------
# Benchmark: export_to_ndjson (streaming format)
# ---------------------------------------------------------------------------


def test_bench_export_to_ndjson(benchmark, seeded, tmp_path):
    session, n = seeded
    exporter = SchemaOrgExporter(session)
    out = tmp_path / "export.ndjson"
    count = _bench_cold(benchmark, session, exporter.export_to_ndjson, out, [File, Category])
    assert count == n * 2


# ---------------------------------------------------------------------------
# Benchmark: export_with_graph (@graph format)
# ---------------------------------------------------------------------------


def test_bench_export_with_graph(benchmark, seeded, tmp_path):
    session, n = seeded
    exporter = SchemaOrgExporter(session)
    out = tmp_path / "export_graph.json"
    count = _bench_cold(
        benchmark, session, exporter.export_with_graph, out, [File, Category], False
    )
    assert count == n * 2


# ---------------------------------------------------------------------------
# Per-entity to_schema_org() serialization cost
# ---------------------------------------------------------------------------


def test_bench_file_to_schema_org(benchmark, seeded):
    """Measures raw File.to_schema_org() cost without exporter overhead."""
    session, n = seeded
    files = session.query(File).all()
    result = benchmark(lambda: [f.to_schema_org() for f in files])
    assert len(result) == n


def test_bench_category_to_schema_org(benchmark, seeded):
    """Measures raw Category.to_schema_org() cost without exporter overhead."""
    session, n = seeded
    categories = session.query(Category).all()
    result = benchmark(lambda: [c.to_schema_org() for c in categories])
    assert len(result) == n


# ---------------------------------------------------------------------------
# Relationship-building overhead
# ---------------------------------------------------------------------------


def _seed_session_with_relations(n: int) -> Session:
    """Create a seeded session with n Files, n Categories, and n file-category associations.

    Each file is linked to one category (file i → category i % n).
    """
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    files = [
        File(
            id=_hex64(i),
            filename=f"file_{i}.pdf",
            original_path=f"/docs/file_{i}.pdf",
            mime_type="application/pdf",
            file_size=1024 * (i % 100 + 1),
            canonical_id=f"urn:sha256:{_hex64(i)}",
        )
        for i in range(n)
    ]
    categories = [
        Category(
            name=f"Category_{i}",
            canonical_id=_uuid_str("cat", i),
            full_path=f"Category_{i}",
            level=0,
        )
        for i in range(n)
    ]
    session.bulk_save_objects(files)
    session.bulk_save_objects(categories)
    session.commit()

    cat_ids = [
        row[0] for row in session.execute(text("SELECT id FROM categories ORDER BY id")).fetchall()
    ]
    associations = [
        {"file_id": _hex64(i), "category_id": cat_ids[i % n], "confidence": 1.0} for i in range(n)
    ]
    session.execute(file_categories.insert(), associations)
    session.commit()
    return session


@pytest.fixture(params=_SIZES)
def seeded_with_relations(request) -> Iterator[tuple[Session, int]]:
    """Yields (session, n) with file-category relationships populated."""
    n: int = request.param
    session = _seed_session_with_relations(n)
    yield session, n
    session.close()


def test_bench_get_graph_document_with_relations(benchmark, seeded_with_relations):
    """Measures get_graph_document overhead when file-category relationships are populated."""
    session, n = seeded_with_relations
    exporter = SchemaOrgExporter(session)
    result = _bench_cold(benchmark, session, exporter.get_graph_document, [File, Category])
    assert len(result["@graph"]) == n * 2
