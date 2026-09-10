"""Every Today repository call turns a database failure into TodayUnavailable."""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError
from tamforge_backend.learning.repository import StudyDayService, StudyDayUnavailable
from tamforge_backend.today.repository import SqlAlchemyTodayRepository
from tamforge_backend.today.schemas import DailyCloseCommand, EvidenceManifest
from tamforge_backend.today.service import TodayUnavailable

MONDAY = date(2026, 8, 31)
NOON_UTC = datetime(2026, 8, 31, 19, tzinfo=UTC)

CLOSE_COMMAND = DailyCloseCommand(
    evidence_confirmed=True,
    evidence_manifest=EvidenceManifest(activity_ids=(10,)),
    strongest_output="A concrete saved output.",
    repeated_mistake="One precise repeated mistake.",
    unfinished_classification="none",
    unfinished_requirement=None,
    correction_ids=(),
)

COMMANDS: dict[str, dict[str, object]] = {
    "load_today": {"owner_id": 1, "local_date": MONDAY},
    "close_day": {
        "owner_id": 1,
        "local_date": MONDAY,
        "command": CLOSE_COMMAND,
        "idempotency_key": "close-2026-08-31",
    },
}


class DroppedConnectionSession:
    """Just enough AsyncSession to fail every statement, transaction still working."""

    def begin(self):
        class Transaction:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, *exc: object) -> bool:
                return False

        return Transaction()

    async def execute(self, statement: object, *args: object, **values: object) -> object:
        del statement, args, values
        raise SQLAlchemyError("SELECT ... WHERE owner_id = %(owner_id)s", {"owner_id": 1})

    async def scalar(self, statement: object, *args: object, **values: object) -> object:
        return await self.execute(statement, *args, **values)

    async def scalars(self, statement: object, *args: object, **values: object) -> object:
        return await self.execute(statement, *args, **values)

    async def flush(self) -> None:
        await self.execute(None)

    async def rollback(self) -> None:
        await self.execute(None)

    def add(self, row: object) -> None:
        del row


class MaterializeFailureSession(DroppedConnectionSession):
    """Serve learner settings, then fail inside the study-day materialization."""

    async def scalar(self, statement: object, *args: object, **values: object) -> object:
        del statement, args, values
        return SimpleNamespace(
            active_roadmap_version_id=3,
            timezone="America/Los_Angeles",
            study_start_date=date(2026, 8, 24),
        )

    async def rollback(self) -> None:
        return None


def test_every_public_repository_call_is_covered() -> None:
    public = {
        name
        for name, _ in inspect.getmembers(SqlAlchemyTodayRepository, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public == set(COMMANDS)


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_a_database_failure_becomes_today_unavailable(command: str) -> None:
    repository = SqlAlchemyTodayRepository(DroppedConnectionSession())  # type: ignore[arg-type]
    with pytest.raises(TodayUnavailable) as caught:
        asyncio.run(getattr(repository, command)(**COMMANDS[command]))
    assert caught.value.__cause__ is None
    assert "owner_id" not in str(caught.value)


def test_a_study_day_failure_becomes_study_day_unavailable() -> None:
    service = StudyDayService(DroppedConnectionSession())  # type: ignore[arg-type]
    with pytest.raises(StudyDayUnavailable) as caught:
        asyncio.run(service.ensure_current_day(owner_id=1, at=NOON_UTC))
    assert caught.value.__cause__ is None
    assert "owner_id" not in str(caught.value)


def test_a_study_day_failure_reaches_today_as_unavailable() -> None:
    repository = SqlAlchemyTodayRepository(MaterializeFailureSession())  # type: ignore[arg-type]
    with pytest.raises(TodayUnavailable) as caught:
        asyncio.run(repository.load_today(owner_id=1, local_date=MONDAY))
    assert caught.value.__cause__ is None
    assert "owner_id" not in str(caught.value)
