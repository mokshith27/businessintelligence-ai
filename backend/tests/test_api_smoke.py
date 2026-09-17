"""FastAPI smoke tests for the public API surface.

These tests boot the real FastAPI app in-process (TestClient) and verify
that the core routes are registered and respond correctly.

Design constraint: CI has no DuckDB warehouse or insight artifacts, so
data-backed endpoints are asserted *gracefully* — either they return 200
with the documented payload (local / deployed) or the documented
HTTPException status (500 "DuckDB database not found." / 404 "File not
found."). They must never crash with an unhandled traceback.
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ============================================================
# STATIC ENDPOINTS (deterministic, no data needed)
# ============================================================


def test_health(client):
    resp = client.get("/api/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "BusinessIntelligence.ai"


def test_root(client):
    resp = client.get("/")

    assert resp.status_code == 200
    body = resp.json()
    assert body["application"] == "BusinessIntelligence.ai"
    assert body["status"] == "running"
    assert body["documentation"] == "/docs"


def test_openapi_schema_served(client):
    resp = client.get("/openapi.json")

    assert resp.status_code == 200
    schema = resp.json()
    assert schema["info"]["title"]


def test_core_routes_registered(client):
    resp = client.get("/openapi.json")
    paths = resp.json()["paths"]

    for route in (
        "/api/health",
        "/api/kpis",
        "/api/events",
        "/api/insights/latest",
        "/api/insights/latest/executive",
        "/api/drivers",
        "/api/actions",
        "/api/roi/summary",
        "/api/auth/login",
        "/api/auth/me",
    ):
        assert route in paths, f"Core route missing from OpenAPI: {route}"


# ============================================================
# DATA-BACKED ENDPOINTS (graceful with or without artifacts)
# ============================================================


def test_kpis_endpoint_graceful(client):
    """200 + table list when the warehouse exists, 500 (never a crash) when not."""
    resp = client.get("/api/kpis")

    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        assert "available_tables" in resp.json()
        assert isinstance(resp.json()["available_tables"], list)
    else:
        assert "DuckDB" in resp.json()["detail"]


def test_latest_insight_graceful(client):
    """200 JSON when the insight artifact exists, 404 when not."""
    resp = client.get("/api/insights/latest")

    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert isinstance(resp.json(), dict)


def test_executive_insight_graceful(client):
    resp = client.get("/api/insights/latest/executive")

    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert isinstance(resp.json(), dict)


def test_events_endpoint_graceful(client):
    resp = client.get("/api/events?limit=5")

    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        assert isinstance(resp.json(), (list, dict))


def test_roi_summary_graceful(client):
    resp = client.get("/api/roi/summary")

    assert resp.status_code in (200, 404)


# ============================================================
# AUTH (deterministic: demo users are seeded in-code)
# ============================================================


def test_login_rejects_bad_credentials(client):
    resp = client.post(
        "/api/auth/login",
        json={"username": "maria.exec", "password": "wrong-password"},
    )

    assert resp.status_code == 401
    assert "Invalid username or password" in resp.json()["detail"]


def test_login_rejects_unknown_user(client):
    resp = client.post(
        "/api/auth/login",
        json={"username": "no.such.user", "password": "whatever"},
    )

    assert resp.status_code == 401


def test_login_issues_jwt_and_me_roundtrip(client):
    login = client.post(
        "/api/auth/login",
        json={"username": "maria.exec", "password": "demo-exec-2026"},
    )

    assert login.status_code == 200
    body = login.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )

    assert me.status_code == 200
    identity = me.json()
    assert identity["role"] in ("executive", "anonymous")
