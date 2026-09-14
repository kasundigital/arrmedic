from fastapi.testclient import TestClient

from app.main import APP_VERSION, app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["name"] == "ArrMedic"
    assert response.json()["version"] == APP_VERSION == "0.5.0"


def test_dashboard_loads():
    response = client.get("/")
    assert response.status_code == 200
    assert "ArrMedic" in response.text
    assert "runDiagnosticsButton" in response.text
    assert "v0.5.0" in response.text
    assert response.headers["cache-control"].startswith("no-store")
