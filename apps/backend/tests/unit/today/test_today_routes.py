"""Authenticated Today reads, ETags, and CSRF-protected daily close."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app
from tamforge_backend.today.schemas import (
    DailyCloseResponse,
    TodayReadInput,
    TodayRoadmap,
)
from tamforge_backend.today.service import TodayConflict, build_today_response

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


class StubTodayService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.conflict = False

    async def get_today(self, **values):  # type: ignore[no-untyped-def]
        self.calls.append(("get", values))
        now = datetime(2026, 8, 30, 18, tzinfo=UTC)
        return build_today_response(
            TodayReadInput(
                local_date=values["local_date"],
                timezone="America/Los_Angeles",
                day_id=None,
                day_type="sunday",
                day_status="off",
                roadmap=TodayRoadmap(
                    version_id=4,
                    version_key="month-1-v1",
                    version_number=1,
                    month=1,
                    week=1,
                    day=7,
                ),
                planned_minutes=0,
                focused_minutes=0,
                tasks=(),
                corrections=(),
                interviews=(),
                awaiting_self_reviews=(),
                analyses=(),
                source_updated_at=now,
            )
        )

    async def close_day(self, **values):  # type: ignore[no-untyped-def]
        self.calls.append(("close", values))
        if self.conflict:
            raise TodayConflict("private repository detail")
        return DailyCloseResponse(
            daily_close_id=8,
            study_day_id=12,
            day_status="closed",
            closed_at=datetime(2026, 8, 27, 23, tzinfo=UTC),
            consequence="none",
            replayed=False,
        )


def _client() -> tuple[TestClient, StubTodayService]:
    from tamforge_backend.today.routes import get_today_service

    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            cors_origins=["https://app.example.test"],
            secure_cookies=False,
            _env_file=None,
        )
    )
    service = StubTodayService()
    app.dependency_overrides[get_today_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


def test_today_routes_are_owner_scoped_no_store_and_etagged() -> None:
    client, service = _client()
    close_body = {
        "evidence_confirmed": True,
        "evidence_manifest": {"schema_version": 1, "activity_ids": [10]},
        "strongest_output": "A concrete saved output.",
        "repeated_mistake": "One precise repeated mistake.",
        "unfinished_classification": "none",
        "unfinished_requirement": None,
        "correction_ids": [],
    }
    with client:
        today = client.get("/api/v1/today?date=2026-08-30")
        closed = client.post(
            "/api/v1/today/2026-08-27/close",
            json=close_body,
            headers={"Idempotency-Key": "close-2026-08-27"},
        )

    assert today.status_code == closed.status_code == 200
    assert today.headers["cache-control"] == "no-store"
    assert closed.headers["cache-control"] == "no-store"
    assert today.headers["etag"] == today.json()["etag"]
    assert service.calls[0] == (
        "get",
        {"owner_id": 1, "local_date": date(2026, 8, 30)},
    )
    assert service.calls[1][0] == "close"
    assert service.calls[1][1]["owner_id"] == 1
    assert service.calls[1][1]["local_date"] == date(2026, 8, 27)
    assert service.calls[1][1]["idempotency_key"] == "close-2026-08-27"


def test_today_conflict_is_safe_and_does_not_leak_details() -> None:
    client, service = _client()
    service.conflict = True
    with client:
        response = client.post(
            "/api/v1/today/2026-08-27/close",
            json={
                "evidence_confirmed": True,
                "evidence_manifest": {"schema_version": 1, "activity_ids": [10]},
                "strongest_output": "A concrete saved output.",
                "repeated_mistake": "One precise repeated mistake.",
                "unfinished_classification": "none",
                "unfinished_requirement": None,
                "correction_ids": [],
            },
            headers={"Idempotency-Key": "close-2026-08-27"},
        )

    assert response.status_code == 409
    assert response.json()["code"] == "today_conflict"
    assert "private repository detail" not in response.text
