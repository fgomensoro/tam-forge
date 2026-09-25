"""The owner's general Coach thread on a real database: no activity, one per owner."""

from __future__ import annotations

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
