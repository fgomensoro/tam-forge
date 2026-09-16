from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.cards.routes import get_card_service
from tamforge_backend.cards.schemas import (
    CardCommand,
    CardPage,
    CardResponse,
    CardReviewResponse,
    CardReviewResult,
    CardsExport,
    DueCardsResponse,
)
from tamforge_backend.cards.service import CardInvalid, CardNotFound
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)
NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


def _card(command: CardCommand, card_id: int = 7) -> CardResponse:
    return CardResponse(
        id=card_id,
        question=command.question,
        answer=command.answer,
        skill_slug=command.skill_slug,
        source_kind=command.source_kind,
        source_ref=command.source_ref,
        assistance=command.assistance,
        status="active",
        scheduler_version="sm2-v1",
        easiness=Decimal("2.50"),
        interval_days=0,
        repetitions=0,
        due_on=date(2026, 9, 16),
        created_at=NOW,
        updated_at=NOW,
    )


class StubService:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.command = CardCommand(
            question="What does a 200 from the ingest endpoint mean?",
            answer="Durably accepted, not yet processed.",
            skill_slug="api_contracts",
            source_kind="study_note",
            source_ref="note:12",
            assistance="coached",
        )

    async def list(self, *, owner_id: int) -> CardPage:
        self.calls.append(("list", {"owner_id": owner_id}))
        return CardPage(items=(_card(self.command),))

    async def create(self, *, owner_id: int, command: CardCommand) -> CardResponse:
        self.calls.append(("create", {"owner_id": owner_id, "command": command}))
        return _card(command)

    async def due(self, *, owner_id: int, local_date: date) -> DueCardsResponse:
        self.calls.append(("due", {"owner_id": owner_id, "local_date": local_date}))
        return DueCardsResponse(local_date=local_date, items=(_card(self.command),))

    async def review(self, *, owner_id: int, card_id: int, **values: object) -> CardReviewResult:
        self.calls.append(("review", {"owner_id": owner_id, "card_id": card_id, **values}))
        if self.error is not None:
            raise self.error
        card = _card(self.command, card_id).model_copy(
            update={"interval_days": 1, "repetitions": 1, "due_on": date(2026, 9, 17)}
        )
        return CardReviewResult(
            card=card,
            review=CardReviewResponse(
                id=1,
                card_id=card_id,
                grade=4,
                mode="written",
                reviewed_on=date(2026, 9, 16),
                interval_before=0,
                interval_after=1,
                easiness_after=Decimal("2.50"),
                due_after=date(2026, 9, 17),
                created_at=NOW,
            ),
        )

    async def export(self, *, owner_id: int) -> CardsExport:
        self.calls.append(("export", {"owner_id": owner_id}))
        return CardsExport(scheduler_version="sm2-v1", cards=(_card(self.command),), reviews=())


def _client() -> tuple[TestClient, StubService]:
    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            cors_origins=["https://app.example.test"],
            secure_cookies=False,
            _env_file=None,
        )
    )
    service = StubService()
    app.dependency_overrides[get_card_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


def test_create_due_review_and_export_round_trip() -> None:
    client, service = _client()
    with client:
        created = client.post("/api/v1/cards", json=service.command.model_dump())
        due = client.get("/api/v1/cards/due?date=2026-09-16")
        reviewed = client.post(
            "/api/v1/cards/7/reviews", json={"grade": 4, "reviewed_on": "2026-09-16"}
        )
        exported = client.get("/api/v1/cards/export")
        listed = client.get("/api/v1/cards")

    assert created.status_code == 201, created.text
    assert created.json()["assistance"] == "coached"
    assert created.json()["source_ref"] == "note:12"
    assert created.headers["cache-control"] == "no-store"
    assert due.status_code == 200 and due.json()["local_date"] == "2026-09-16"
    assert due.json()["items"][0]["due_on"] == "2026-09-16"
    assert reviewed.status_code == 201
    assert reviewed.json()["card"]["due_on"] == "2026-09-17"
    assert reviewed.json()["review"]["interval_after"] == 1
    assert exported.status_code == 200 and exported.json()["scheduler_version"] == "sm2-v1"
    assert listed.status_code == 200 and len(listed.json()["items"]) == 1
    assert [name for name, _ in service.calls] == ["create", "due", "review", "export", "list"]
    review_call = service.calls[2][1]
    assert review_call["grade"] == 4 and review_call["mode"] == "written"
    assert review_call["recording_id"] is None


def test_invalid_commands_never_reach_the_service() -> None:
    client, service = _client()
    with client:
        blank = client.post("/api/v1/cards", json={**service.command.model_dump(), "question": ""})
        grade = client.post(
            "/api/v1/cards/7/reviews", json={"grade": 6, "reviewed_on": "2026-09-16"}
        )
        undated = client.get("/api/v1/cards/due")
        extra = client.post("/api/v1/cards", json={**service.command.model_dump(), "x": 1})

    assert {blank.status_code, grade.status_code, undated.status_code, extra.status_code} == {422}
    assert service.calls == []


def test_spoken_reviews_carry_the_recording_and_errors_are_closed_problems() -> None:
    client, service = _client()
    recording = UUID("22222222-2222-4222-8222-222222222222")
    with client:
        spoken = client.post(
            "/api/v1/cards/7/reviews",
            json={
                "grade": 3,
                "reviewed_on": "2026-09-16",
                "mode": "spoken",
                "recording_id": str(recording),
            },
        )
        service.error = CardNotFound("internal card detail")
        missing = client.post(
            "/api/v1/cards/9/reviews", json={"grade": 3, "reviewed_on": "2026-09-16"}
        )
        service.error = CardInvalid("internal card detail")
        invalid = client.post(
            "/api/v1/cards/9/reviews", json={"grade": 3, "reviewed_on": "2026-09-16"}
        )

    assert spoken.status_code == 201
    assert service.calls[0][1]["recording_id"] == recording
    assert service.calls[0][1]["mode"] == "spoken"
    assert missing.status_code == 404 and missing.json()["code"] == "card_not_found"
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert invalid.status_code == 422 and invalid.json()["code"] == "invalid_card_command"
    assert "internal card detail" not in missing.text + invalid.text
