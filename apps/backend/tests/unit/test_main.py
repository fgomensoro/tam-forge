from __future__ import annotations

from fastapi.testclient import TestClient
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app


class FakeDatabaseResources:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


def test_app_lifespan_stores_one_settings_instance_and_disposes_database(
    monkeypatch,
) -> None:
    settings = Settings()
    resources = FakeDatabaseResources()
    monkeypatch.setattr(
        "tamforge_backend.main.create_database_resources",
        lambda configured: resources,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        assert app.state.settings is settings
        assert app.state.database is resources
        assert client.get("/healthz").json() == {
            "status": "ok",
            "service": "tam-forge-backend",
        }

    assert resources.disposed is True
