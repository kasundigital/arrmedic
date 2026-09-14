from pathlib import Path

from fastapi.testclient import TestClient

from app.bootstrap import app

client = TestClient(app)
EXPECTED_VERSION = Path("VERSION").read_text(encoding="utf-8").strip()


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["name"] == "ArrMedic"
    assert response.json()["version"] == EXPECTED_VERSION == "0.9.0"


def test_dashboard_loads():
    response = client.get("/")
    assert response.status_code == 200
    assert "ArrMedic" in response.text
    assert "runDiagnosticsButton" in response.text
    assert "exportDiagnosticsButton" in response.text
    assert "scanHistory" in response.text
    assert "fixSummary" in response.text
    assert "v0.9.0" in response.text
    assert "/static/path-doctor.html" in response.text
    assert "/static/hardlink-doctor.html" in response.text
    assert "/static/permission-doctor.html" in response.text
    assert "/static/queue-doctor.html" in response.text
    assert response.headers["cache-control"].startswith("no-store")


def test_doctor_pages_load():
    for path in ("path-doctor.html", "hardlink-doctor.html", "permission-doctor.html", "queue-doctor.html"):
        response = client.get(f"/static/{path}")
        assert response.status_code == 200
        assert "doctor.js?v=0.9.0" in response.text
