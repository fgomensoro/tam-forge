"""The owner's general Coach thread: the Coach outside any activity, one thread per owner.

Every learner message and every Coach reply is a row, as in an activity thread. The
screen context rides along with one turn only; it is never stored and never evidence.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.roles.coach import CoachUnavailable
from ..agents.roles.contracts import RoleContractError
from ..agents.roles.general_coach import GeneralCoachRequest, GeneralCoachService
from ..database import transaction_scope
from ..models.base import utc_now
from .models import CoachMessage, CoachThread
from .schemas import CoachMessageResponse, GeneralCoachContext, GeneralCoachThreadResponse
from .service import PRIOR_MESSAGE_LIMIT, CoachingInvalidRequest, CoachingUnavailable


def _general(owner_id: int) -> Select[tuple[CoachThread]]:
    return (
        select(CoachThread)
        .where(CoachThread.owner_id == owner_id)
        .where(CoachThread.activity_instance_id.is_(None))
    )


class GeneralCoachThreadService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        coach: GeneralCoachService,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._coach = coach
        self._clock = clock

    async def thread(self, *, owner_id: int) -> GeneralCoachThreadResponse:
        try:
            thread = await self._session.scalar(_general(owner_id))
            response = await self._response(owner_id, thread)
            await self._session.rollback()
            return response
        except SQLAlchemyError:
            raise CoachingUnavailable("the coaching store is unavailable") from None

    async def send(
        self, *, owner_id: int, text: str, context: GeneralCoachContext
    ) -> GeneralCoachThreadResponse:
        try:
            async with transaction_scope(self._session):
                # Created on the first send. A concurrent first send waits for the other to
                # commit instead of failing on the unique index; the row lock orders sends.
                await self._session.execute(
                    insert(CoachThread)
                    .values(owner_id=owner_id, activity_instance_id=None)
                    .on_conflict_do_nothing(
                        index_elements=[CoachThread.owner_id],
                        index_where=CoachThread.activity_instance_id.is_(None),
                    )
                )
                thread = (
                    await self._session.execute(_general(owner_id).with_for_update())
                ).scalar_one()
                prior = await self._messages(owner_id, thread.id)
                learner_message = text.strip()
                request = GeneralCoachRequest(
                    screen=context.screen,
                    summary=context.summary,
                    learner_message=learner_message,
                    prior_messages=tuple(
                        (cast(Any, item.speaker), item.text)
                        for item in prior[-PRIOR_MESSAGE_LIMIT:]
                    ),
                )
                try:
                    turn = await self._coach.reply(request)
                except CoachUnavailable as exc:
                    raise CoachingUnavailable(str(exc)) from None
                except RoleContractError as exc:
                    raise CoachingInvalidRequest(str(exc)) from None
                self._session.add_all(
                    [
                        CoachMessage(
                            owner_id=owner_id,
                            thread_id=thread.id,
                            speaker="learner",
                            text=learner_message,
                        ),
                        CoachMessage(
                            owner_id=owner_id,
                            thread_id=thread.id,
                            speaker="coach",
                            text=turn.message,
                        ),
                    ]
                )
                thread.updated_at = self._clock()
                await self._session.flush()
                return await self._response(owner_id, thread)
        except SQLAlchemyError:
            raise CoachingUnavailable("the coaching store is unavailable") from None

    async def _messages(self, owner_id: int, thread_id: int) -> list[CoachMessage]:
        rows = await self._session.scalars(
            select(CoachMessage)
            .where(CoachMessage.owner_id == owner_id)
            .where(CoachMessage.thread_id == thread_id)
            .order_by(CoachMessage.id)
        )
        return list(rows)

    async def _response(
        self, owner_id: int, thread: CoachThread | None
    ) -> GeneralCoachThreadResponse:
        if thread is None:
            return GeneralCoachThreadResponse(thread_id=None, messages=[])
        return GeneralCoachThreadResponse(
            thread_id=thread.id,
            messages=[
                CoachMessageResponse(
                    id=item.id,
                    speaker=cast(Any, item.speaker),
                    text=item.text,
                    next_step=None,
                    proposed_evidence=[],
                    created_at=item.created_at,
                )
                for item in await self._messages(owner_id, thread.id)
            ],
        )


__all__ = ["GeneralCoachThreadService"]
