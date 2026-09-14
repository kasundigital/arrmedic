from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["name"] == "ArrMedic"


def test_dashboard_loads():
    response = client.get("/")
    assert response.status_code == 200
    assert "ArrMedic" in response.text
