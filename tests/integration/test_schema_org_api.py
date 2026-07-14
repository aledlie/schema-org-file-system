"""Integration tests for the schema.org FastAPI layer (src/api/).

Drives ``schema_org_api.app`` through Starlette's ``TestClient`` against a
real temp GraphStore database (``get_db`` overridden per test), plus a smoke
import of ``schema_org_models`` so both modules — which need fastapi/pydantic
and so were previously absent from the coverage denominator — are exercised.

The module uses bare ``from api.x import`` / ``from storage.x import``
statements resolved via the pytest ``pythonpath`` ([".", "src", "scripts"]);
importing it the same bare way here keeps ``app`` and its ``get_db``
dependency object identical to the ones the app registered, so the
dependency override binds to the right callable.
"""

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
for _p in (_PROJECT_ROOT, _PROJECT_ROOT / "src", _PROJECT_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi.testclient import TestClient  # noqa: E402

from api import schema_org_models  # noqa: E402
from api.schema_org_api import app, get_db  # noqa: E402
from storage.graph_store import GraphStore  # noqa: E402

FILE_PATH = "/inbox/globex_invoice.pdf"
COMPANY_NAME = "Globex"
PERSON_NAME = "Jane Roe"


@pytest.fixture
def client(tmp_path):
    """TestClient bound to a seeded temp DB via a get_db dependency override."""
    store = GraphStore(str(tmp_path / "api.db"))
    session = store.get_session()
    file = store.add_file(
        original_path=FILE_PATH,
        filename="globex_invoice.pdf",
        mime_type="application/pdf",
        session=session,
    )
    store.add_file_to_company(file.id, COMPANY_NAME, session=session)
    store.add_file_to_person(file.id, PERSON_NAME, session=session)
    session.commit()
    session.close()

    def override_get_db():
        db = store.get_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, store
    app.dependency_overrides.clear()


class TestSmokeImport:
    """Both modules load and expose their expected top-level surface."""

    def test_app_is_fastapi(self):
        from fastapi import FastAPI

        assert isinstance(app, FastAPI)

    def test_models_are_pydantic(self):
        from pydantic import BaseModel

        for name in ("FileSchemaOrg", "CompanySchemaOrg", "BulkExportParams",
                     "ErrorResponse", "PaginationParams"):
            model = getattr(schema_org_models, name)
            assert issubclass(model, BaseModel)


class TestDependencyFreeEndpoints:
    def test_health(self, client):
        test_client, _ = client
        resp = test_client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_context_document(self, client):
        test_client, _ = client
        resp = test_client.get("/schema/context")
        assert resp.status_code == 200
        assert "@context" in resp.json()


class TestEntityEndpoints:
    def _file_id(self, store):
        from storage.models import File

        return File.generate_id(FILE_PATH)

    def test_get_file_found(self, client):
        test_client, store = client
        resp = test_client.get(f"/api/files/{self._file_id(store)}/schema-org")
        assert resp.status_code == 200
        assert resp.json()["name"] == "globex_invoice.pdf"

    def test_get_file_404(self, client):
        test_client, _ = client
        resp = test_client.get("/api/files/does-not-exist/schema-org")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    def test_files_bulk_returns_graph(self, client):
        test_client, _ = client
        resp = test_client.get("/api/files/schema-org/bulk")
        assert resp.status_code == 200
        body = resp.json()
        assert "@context" in body
        assert len(body["@graph"]) == 1

    def test_files_bulk_mime_filter_excludes(self, client):
        test_client, _ = client
        resp = test_client.get("/api/files/schema-org/bulk", params={"mime_type": "image/png"})
        assert resp.status_code == 200
        assert resp.json()["@graph"] == []

    def test_company_by_name_found(self, client):
        test_client, _ = client
        resp = test_client.get(f"/api/companies/schema-org/by-name/{COMPANY_NAME}")
        assert resp.status_code == 200
        assert resp.json()["name"] == COMPANY_NAME

    def test_company_by_name_404(self, client):
        test_client, _ = client
        resp = test_client.get("/api/companies/schema-org/by-name/Nonesuch")
        assert resp.status_code == 404

    def test_person_by_name_found(self, client):
        test_client, _ = client
        resp = test_client.get(f"/api/people/schema-org/by-name/{PERSON_NAME}")
        assert resp.status_code == 200
        assert resp.json()["name"] == PERSON_NAME


class TestExportEndpoints:
    def test_export_all(self, client):
        test_client, _ = client
        resp = test_client.get("/api/schema-org/export")
        assert resp.status_code == 200
        assert "@graph" in resp.json()

    def test_export_files_only(self, client):
        test_client, _ = client
        resp = test_client.get("/api/schema-org/export", params={"entity_types": "file"})
        assert resp.status_code == 200
        assert "@graph" in resp.json()

    def test_full_graph(self, client):
        test_client, _ = client
        resp = test_client.get("/api/schema-org/graph")
        assert resp.status_code == 200
        assert "@graph" in resp.json()
