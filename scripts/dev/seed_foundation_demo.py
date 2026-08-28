"""Create the bounded test session used by the foundation browser journey."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import anyio
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tamforge_backend.auth.crypto import hash_secret
from tamforge_backend.auth.models import AuthSession, Owner
from tamforge_backend.config import APPROVED_GITHUB_USER_ID, Settings
from tamforge_backend.database import transaction_scope, validate_test_database_url
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.evidence.seed import seed_config
from tamforge_backend.learning.models import LearnerSetting
from tamforge_backend.notifications.models import Notification

ROOT = Path(__file__).parents[2]
SESSION_TOKEN = "s" * 43
CSRF_TOKEN = "c" * 43
TEST_LOGIN = "fgomensoro"


def load_test_settings() -> Settings:
    if os.environ.get("TAMFORGE_ENV") != "test":
        raise ValueError("foundation demo seeding requires TAMFORGE_ENV=test")
    raw_url = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
        "TAMFORGE_DATABASE_URL"
    )
    if raw_url is None:
        raise ValueError("foundation demo seeding requires TEST_DATABASE_URL")
    validated = validate_test_database_url(raw_url)
    settings = Settings(_env_file=None)
    if settings.database_url.get_secret_value() != validated:
        raise ValueError("TAMFORGE_DATABASE_URL must equal the isolated TEST_DATABASE_URL")
    if settings.github_user_id != APPROVED_GITHUB_USER_ID:
        raise ValueError("foundation demo seeding requires the exact configured owner")
    return settings


async def ensure_bucket(settings: Settings) -> None:
    def create() -> None:
        client = boto3.client(
            "s3",
            endpoint_url=settings.object_store_endpoint,
            region_name=settings.object_store_region,
            aws_access_key_id=settings.object_store_access_key.get_secret_value(),
            aws_secret_access_key=settings.object_store_secret_key.get_secret_value(),
            config=Config(s3={"addressing_style": settings.object_store_addressing_style}),
        )
        try:
            client.head_bucket(Bucket=settings.object_store_bucket)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            client.create_bucket(Bucket=settings.object_store_bucket)

    await anyio.to_thread.run_sync(create)


async def seed(settings: Settings, *, study_start_date: date) -> dict[str, object]:
    engine = create_async_engine(settings.database_url.get_secret_value())
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    now = datetime.now(UTC)
    try:
        async with factory() as session:
            async with transaction_scope(session):
                owner = await session.scalar(
                    select(Owner).where(Owner.github_user_id == APPROVED_GITHUB_USER_ID)
                )
                if owner is None:
                    owner = Owner(
                        github_user_id=APPROVED_GITHUB_USER_ID,
                        github_login=TEST_LOGIN,
                    )
                    session.add(owner)
                    await session.flush()
                else:
                    owner.github_login = TEST_LOGIN
                await session.execute(
                    delete(AuthSession).where(
                        AuthSession.token_hash == hash_secret(SESSION_TOKEN)
                    )
                )
                session.add(
                    AuthSession(
                        owner_id=owner.id,
                        token_hash=hash_secret(SESSION_TOKEN),
                        csrf_hash=hash_secret(CSRF_TOKEN),
                        created_at=now,
                        expires_at=now + timedelta(hours=2),
                    )
                )
                learner = await session.scalar(
                    select(LearnerSetting).where(LearnerSetting.owner_id == owner.id)
                )
                if learner is None:
                    session.add(
                        LearnerSetting(
                            owner_id=owner.id,
                            timezone="America/Los_Angeles",
                            study_start_date=study_start_date,
                            active_roadmap_version_id=None,
                        )
                    )
                else:
                    learner.timezone = "America/Los_Angeles"
                    learner.study_start_date = study_start_date
                await seed_config(
                    load_config_bundle(ROOT / "config"),
                    owner_id=owner.id,
                    session=session,
                    apply=True,
                )
                await session.execute(
                    delete(Notification).where(
                        Notification.owner_id == owner.id,
                        Notification.notification_type == "feedback_ready",
                        Notification.subject_kind == "activity",
                        Notification.subject_id == 1,
                    )
                )
                session.add(
                    Notification(
                        owner_id=owner.id,
                        notification_type="feedback_ready",
                        subject_kind="activity",
                        subject_id=1,
                        created_at=now,
                        read_at=None,
                    )
                )
        await ensure_bucket(settings)
        return {
            "base_url": "http://127.0.0.1:5173",
            "session_cookie": "tamforge_session",
            "session_token": SESSION_TOKEN,
            "csrf_cookie": "tamforge_csrf",
            "csrf_token": CSRF_TOKEN,
            "owner_github_id": APPROVED_GITHUB_USER_ID,
        }
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--study-start-date", type=date.fromisoformat, default=date(2026, 8, 24))
    arguments = parser.parse_args()
    try:
        settings = load_test_settings()
        result = asyncio.run(seed(settings, study_start_date=arguments.study_start_date))
    except (ValueError, RuntimeError, ClientError) as exc:
        raise SystemExit(f"seed_foundation_demo: {exc}") from None
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
