from fastapi.testclient import TestClient
from tamforge_backend.main import create_app


def test_health_is_explicit_and_contains_no_secret_data() -> None:
    response = TestClient(create_app()).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "tam-forge-backend"}
