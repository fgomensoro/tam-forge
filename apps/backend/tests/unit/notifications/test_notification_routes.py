"""Authenticated notification route and safe-error tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app
from tamforge_backend.notifications.routes import get_notification_service
from tamforge_backend.notifications.schemas import (
    NotificationPage,
    NotificationResponse,
)
from tamforge_backend.notifications.service import NotificationNotFound

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


class StubNotificationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.missing = False

    @staticmethod
    def _item() -> NotificationResponse:
        return NotificationResponse(
            id=5,
            notification_type="feedback_ready",
            subject_kind="activity",
            subject_id=7,
            created_at=datetime(2026, 8, 29, 12, tzinfo=UTC),
            read_at=None,
        )

    async def list_notifications(self, **values: object) -> NotificationPage:
        self.calls.append(("list", values))
        return NotificationPage(items=(self._item(),), next_cursor=None)

    async def mark_read(self, **values: object) -> NotificationResponse:
        self.calls.append(("read", values))
        if self.missing:
            raise NotificationNotFound("private detail")
        return self._item().model_copy(
            update={"read_at": datetime(2026, 8, 29, 12, 1, tzinfo=UTC)}
        )


def _client() -> tuple[TestClient, StubNotificationService]:
    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            cors_origins=["https://app.example.test"],
            secure_cookies=False,
            _env_file=None,
        )
    )
    service = StubNotificationService()
    app.dependency_overrides[get_notification_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


def test_notification_routes_are_owner_scoped_no_store_and_bounded() -> None:
    client, service = _client()
    with client:
        listed = client.get("/api/v1/notifications?cursor=20&limit=10")
        read = client.post("/api/v1/notifications/5/read")
        invalid_events = client.get(
            "/api/v1/events",
            headers={"Last-Event-ID": "not-a-number"},
        )

    assert listed.status_code == 200
    assert read.status_code == 200
    assert invalid_events.status_code == 422
    assert listed.headers["cache-control"] == "no-store"
    assert read.headers["cache-control"] == "no-store"
    assert invalid_events.headers["cache-control"] == "no-store"
    assert service.calls == [
        ("list", {"owner_id": 1, "cursor": 20, "limit": 10}),
        ("read", {"owner_id": 1, "notification_id": 5}),
    ]


def test_notification_errors_do_not_leak_repository_details() -> None:
    client, service = _client()
    service.missing = True
    with client:
        response = client.post("/api/v1/notifications/5/read")

    assert response.status_code == 404
    assert response.json()["code"] == "notification_not_found"
    assert "private detail" not in response.text
