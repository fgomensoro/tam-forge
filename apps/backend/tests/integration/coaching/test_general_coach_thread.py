"""The owner's general Coach thread on a real database: no activity, one per owner."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest


@pytest.mark.integration
def test_general_coach_thread_is_one_per_owner(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session
    from tamforge_backend.coaching.models import CoachThread
    from tamforge_backend.database import database_url_to_sync

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    try:
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        with sync_engine.begin() as connection:
            owner_id, other_owner_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (102269369, 'fgomensoro'), (1, 'someone') RETURNING id"
                )
            ).scalars()

        with Session(sync_engine) as session, session.begin():
            session.add(CoachThread(owner_id=owner_id, activity_instance_id=None))

        with Session(sync_engine) as session:
            general = session.scalars(
                select(CoachThread).where(CoachThread.owner_id == owner_id)
            ).one()
            assert general.activity_instance_id is None
            assert general.assistance_mode == "none"

        with Session(sync_engine) as session, pytest.raises(IntegrityError):
            with session.begin():
                session.add(CoachThread(owner_id=owner_id, activity_instance_id=None))

        with Session(sync_engine) as session, session.begin():
            session.add(CoachThread(owner_id=other_owner_id, activity_instance_id=None))

        with Session(sync_engine) as session:
            owners = session.scalars(
                select(CoachThread.owner_id)
                .where(CoachThread.activity_instance_id.is_(None))
                .order_by(CoachThread.owner_id)
            ).all()
            assert owners == sorted([owner_id, other_owner_id])
    finally:
        try:
            with sync_engine.begin() as connection:
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
        finally:
            sync_engine.dispose()


class FakeGeneralTransport:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def general_reply(self, request: Any) -> Mapping[str, object]:
        self.requests.append(request)
        return {"message": f"Reply {len(self.requests)} about {request.screen}."}


@pytest.mark.integration
def test_general_coach_routes_keep_one_thread_and_leave_activity_threads_alone(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
    from tamforge_backend.auth.schemas import AuthenticatedOwner
    from tamforge_backend.coaching.models import CoachMessage, CoachThread
    from tamforge_backend.config import Settings
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.main import create_app

    from apps.backend.tests.integration.workspaces.test_sql_execution_api import _seed_activity

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    try:
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        with sync_engine.begin() as connection:
            owner_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (102269369, 'fgomensoro') RETURNING id"
                )
            ).scalar_one()
            activity_id = _seed_activity(
                connection,
                owner_id=owner_id,
                suffix="general-coach",
                local_date=date(2026, 9, 25),
                stable_id="fixture.reading.task",
                block="technical_learning",
            )
        with Session(sync_engine) as session, session.begin():
            activity_thread = CoachThread(owner_id=owner_id, activity_instance_id=activity_id)
            session.add(activity_thread)
            session.flush()
            session.add(
                CoachMessage(
                    owner_id=owner_id, thread_id=activity_thread.id, speaker="learner", text="hi"
                )
            )
            activity_thread_id = activity_thread.id
            activity_updated_at = activity_thread.updated_at

        owner = AuthenticatedOwner(
            owner_id=owner_id,
            github_user_id=102269369,
            github_login="fgomensoro",
            session_id=1,
            csrf_hash=b"c" * 32,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        database_url = (
            make_url(test_database_url)
            .set(drivername="postgresql+asyncpg")
            .render_as_string(hide_password=False)
        )
        transport = FakeGeneralTransport()

        def client(*, claude_enabled: bool) -> TestClient:
            app = create_app(
                Settings(
                    environment="test",
                    database_url=database_url,
                    github_user_id=102269369,
                    secure_cookies=False,
                    claude_enabled=claude_enabled,
                    _env_file=None,
                )
            )
            app.dependency_overrides[get_authenticated_owner] = lambda: owner
            app.dependency_overrides[require_csrf_owner] = lambda: owner
            return TestClient(app)

        body = {"text": "que hago?", "context": {"screen": "Today", "summary": "- A (ready)"}}
        with client(claude_enabled=False) as disabled:
            disabled.app.state.coach_transport = transport  # type: ignore[attr-defined]
            refused = disabled.post("/api/v1/coach/messages", json=body)
            fresh = disabled.get("/api/v1/coach")
        assert refused.status_code == 503 and refused.json()["code"] == "coach_unavailable"
        assert fresh.status_code == 200 and fresh.json() == {"thread_id": None, "messages": []}
        assert transport.requests == []

        with client(claude_enabled=True) as enabled:
            enabled.app.state.coach_transport = transport  # type: ignore[attr-defined]
            first = enabled.post("/api/v1/coach/messages", json=body)
            second = enabled.post(
                "/api/v1/coach/messages",
                json={"text": "y despues?", "context": {"screen": "Roadmaps"}},
            )
            read = enabled.get("/api/v1/coach")

        assert first.status_code == 200 and second.status_code == 200
        thread = read.json()
        assert thread["thread_id"] == first.json()["thread_id"] == second.json()["thread_id"]
        assert [(m["speaker"], m["text"]) for m in thread["messages"]] == [
            ("learner", "que hago?"),
            ("coach", "Reply 1 about Today."),
            ("learner", "y despues?"),
            ("coach", "Reply 2 about Roadmaps."),
        ]
        assert all(
            m["next_step"] is None and m["proposed_evidence"] == [] for m in thread["messages"]
        )
        assert transport.requests[0].summary == "- A (ready)"
        assert transport.requests[1].summary == ""
        assert transport.requests[1].prior_messages == (
            ("learner", "que hago?"),
            ("coach", "Reply 1 about Today."),
        )

        with Session(sync_engine) as session:
            general = session.scalars(
                select(CoachThread).where(CoachThread.activity_instance_id.is_(None))
            ).all()
            assert [row.id for row in general] == [thread["thread_id"]]
            untouched = session.get(CoachThread, activity_thread_id)
            assert untouched is not None and untouched.updated_at == activity_updated_at
            activity_messages = session.scalar(
                select(func.count())
                .select_from(CoachMessage)
                .where(CoachMessage.thread_id == activity_thread_id)
            )
            assert activity_messages == 1
    finally:
        try:
            with sync_engine.begin() as connection:
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
        finally:
            sync_engine.dispose()
