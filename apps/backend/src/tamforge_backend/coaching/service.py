"""Coaching threads: the learner writes after committing, the Coach answers in shape.

The thread is the durable record: every learner message and every Coach turn is a
row, and a proposed evidence note becomes evidence only when the learner accepts
it. Nothing here scores, completes or reschedules anything.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.roles.coach import (
    CoachBlock,
    CoachRequest,
    CoachService,
    CoachUnavailable,
    coaching_allowed,
)
from ..agents.roles.contracts import RoleContractError
from ..database import transaction_scope
from ..learning.models import ActivityInstance, Attempt, StudyDay
from ..learning.service import _string_items
from ..models.base import utc_now
from ..roadmaps.models import TaskDefinition
from ..today.handoff import render_handoff
from ..today.models import DailyHandoff
from .models import CoachEvidence, CoachMessage, CoachThread
from .schemas import CoachEvidenceProposal, CoachMessageResponse, CoachThreadResponse

PRIOR_MESSAGE_LIMIT = 10


class CoachingError(Exception):
    """Base coaching error safe to convert to a closed public problem response."""


class CoachingNotFound(CoachingError):
    """The owner-scoped activity, thread or message does not exist."""


class CoachingConflict(CoachingError):
    """Coaching is not allowed here, or the learner has not committed yet."""


class CoachingInvalidRequest(CoachingError):
    """The command names something that is not there."""


class CoachingUnavailable(CoachingError):
    """The store or the Coach cannot answer right now."""


@dataclass(frozen=True, slots=True)
class _Loaded:
    activity: ActivityInstance
    definition: TaskDefinition
    thread: CoachThread | None


def next_step_for(activity: ActivityInstance) -> str:
    """The plan's next step, derived from state; the Coach repeats it, never invents it."""
    if activity.output_committed_at is None:
        return "Commit your attempt for this block, then the coach can respond."
    if activity.state == "output_committed":
        return "Submit the mandatory self-review for this block."
    if activity.state in {"correction_due", "needs_work"}:
        return "Complete the due correction before moving on."
    return "Continue with the next block of the day."


class CoachThreadService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        coach: CoachService,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._coach = coach
        self._clock = clock

    async def thread(self, *, owner_id: int, activity_id: int) -> CoachThreadResponse:
        try:
            loaded = await self._load(owner_id=owner_id, activity_id=activity_id, lock=False)
            response = await self._response(loaded)
            await self._session.rollback()
            return response
        except SQLAlchemyError:
            raise CoachingUnavailable("the coaching store is unavailable") from None

    async def send(self, *, owner_id: int, activity_id: int, text: str) -> CoachThreadResponse:
        try:
            async with transaction_scope(self._session):
                loaded = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
                block = _block(loaded.definition)
                if not coaching_allowed(block):
                    raise CoachingConflict("this block does not allow coaching")
                if loaded.activity.output_committed_at is None:
                    raise CoachingConflict("commit an attempt before asking the coach")
                thread = loaded.thread or CoachThread(
                    owner_id=owner_id, activity_instance_id=activity_id
                )
                if thread.id is None:
                    self._session.add(thread)
                    await self._session.flush()
                prior = await self._messages(owner_id=owner_id, thread_id=thread.id)
                request = CoachRequest(
                    block=block,
                    committed_attempt=await self._committed_attempt(
                        owner_id=owner_id, activity_id=activity_id
                    ),
                    learner_message=text.strip(),
                    next_step=next_step_for(loaded.activity),
                    prior_messages=tuple(
                        (cast(Any, item.speaker), item.text)
                        for item in prior[-PRIOR_MESSAGE_LIMIT:]
                    ),
                    handoff=await self._handoff(owner_id=owner_id, activity=loaded.activity),
                )
                try:
                    turn = await self._coach.turn(request)
                except CoachUnavailable as exc:
                    raise CoachingUnavailable(str(exc)) from None
                except RoleContractError as exc:
                    raise CoachingConflict(str(exc)) from None
                self._session.add(
                    CoachMessage(
                        owner_id=owner_id, thread_id=thread.id, speaker="learner", text=text.strip()
                    )
                )
                self._session.add(
                    CoachMessage(
                        owner_id=owner_id,
                        thread_id=thread.id,
                        speaker="coach",
                        text=turn.message,
                        next_step=turn.next_step,
                        proposed_evidence=[
                            {"kind": item.kind, "text": item.text}
                            for item in turn.proposed_evidence
                        ],
                    )
                )
                thread.updated_at = self._clock()
                await self._session.flush()
                loaded = _Loaded(loaded.activity, loaded.definition, thread)
                return await self._response(loaded)
        except SQLAlchemyError:
            raise CoachingUnavailable("the coaching store is unavailable") from None

    async def accept_evidence(
        self, *, owner_id: int, activity_id: int, message_id: int, index: int
    ) -> CoachThreadResponse:
        try:
            async with transaction_scope(self._session):
                loaded = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
                if loaded.thread is None:
                    raise CoachingNotFound("there is no coaching thread for this activity")
                message = await self._session.scalar(
                    select(CoachMessage)
                    .where(CoachMessage.owner_id == owner_id)
                    .where(CoachMessage.thread_id == loaded.thread.id)
                    .where(CoachMessage.id == message_id)
                )
                if message is None or message.speaker != "coach":
                    raise CoachingNotFound("the coach message was not found")
                proposals = message.proposed_evidence
                if index >= len(proposals):
                    raise CoachingInvalidRequest("the proposal index is out of range")
                existing = await self._session.scalar(
                    select(CoachEvidence.id)
                    .where(CoachEvidence.owner_id == owner_id)
                    .where(CoachEvidence.message_id == message_id)
                    .where(CoachEvidence.proposal_index == index)
                )
                if existing is None:
                    proposal = proposals[index]
                    self._session.add(
                        CoachEvidence(
                            owner_id=owner_id,
                            thread_id=loaded.thread.id,
                            message_id=message_id,
                            proposal_index=index,
                            kind=str(proposal["kind"]),
                            text=str(proposal["text"]),
                        )
                    )
                    await self._session.flush()
                return await self._response(loaded)
        except SQLAlchemyError:
            raise CoachingUnavailable("the coaching store is unavailable") from None

    async def _load(self, *, owner_id: int, activity_id: int, lock: bool) -> _Loaded:
        statement = (
            select(ActivityInstance, TaskDefinition)
            .join(
                TaskDefinition,
                (TaskDefinition.owner_id == ActivityInstance.owner_id)
                & (TaskDefinition.id == ActivityInstance.task_definition_id),
            )
            .where(ActivityInstance.owner_id == owner_id)
            .where(ActivityInstance.id == activity_id)
        )
        if lock:
            statement = statement.with_for_update(of=ActivityInstance)
        row = (await self._session.execute(statement)).first()
        if row is None:
            raise CoachingNotFound("the activity was not found")
        activity, definition = row
        thread = await self._session.scalar(
            select(CoachThread)
            .where(CoachThread.owner_id == owner_id)
            .where(CoachThread.activity_instance_id == activity_id)
        )
        return _Loaded(activity, definition, thread)

    async def _messages(self, *, owner_id: int, thread_id: int) -> list[CoachMessage]:
        rows = await self._session.scalars(
            select(CoachMessage)
            .where(CoachMessage.owner_id == owner_id)
            .where(CoachMessage.thread_id == thread_id)
            .order_by(CoachMessage.id)
        )
        return list(rows)

    async def _handoff(self, *, owner_id: int, activity: ActivityInstance) -> str | None:
        """The previous closed day's next action and gaps, so the Coach opens with them."""
        local_date = await self._session.scalar(
            select(StudyDay.local_date)
            .where(StudyDay.owner_id == owner_id)
            .where(StudyDay.id == activity.study_day_id)
        )
        if local_date is None:
            return None
        row = await self._session.scalar(
            select(DailyHandoff)
            .where(DailyHandoff.owner_id == owner_id)
            .where(DailyHandoff.local_date < local_date)
            .order_by(DailyHandoff.local_date.desc(), DailyHandoff.id.desc())
            .limit(1)
        )
        if row is None:
            return None
        return render_handoff(
            local_date=row.local_date.isoformat(),
            next_action=row.next_action,
            gaps=tuple(str(gap) for gap in row.gaps),
        )

    async def _committed_attempt(self, *, owner_id: int, activity_id: int) -> str:
        attempt = await self._session.scalar(
            select(Attempt)
            .where(Attempt.owner_id == owner_id)
            .where(Attempt.activity_instance_id == activity_id)
            .order_by(Attempt.id.desc())
            .limit(1)
        )
        if attempt is None:
            return ""
        return (
            attempt.original_markdown or attempt.original_text or attempt.original_sql or ""
        ).strip()

    async def _response(self, loaded: _Loaded) -> CoachThreadResponse:
        messages: list[CoachMessageResponse] = []
        if loaded.thread is not None:
            accepted = {
                (row.message_id, row.proposal_index)
                for row in await self._session.scalars(
                    select(CoachEvidence)
                    .where(CoachEvidence.owner_id == loaded.thread.owner_id)
                    .where(CoachEvidence.thread_id == loaded.thread.id)
                )
            }
            for item in await self._messages(
                owner_id=loaded.thread.owner_id, thread_id=loaded.thread.id
            ):
                messages.append(
                    CoachMessageResponse(
                        id=item.id,
                        speaker=cast(Any, item.speaker),
                        text=item.text,
                        next_step=item.next_step,
                        proposed_evidence=[
                            CoachEvidenceProposal(
                                index=index,
                                kind=cast(Any, proposal["kind"]),
                                text=str(proposal["text"]),
                                accepted=(item.id, index) in accepted,
                            )
                            for index, proposal in enumerate(item.proposed_evidence)
                        ],
                        created_at=item.created_at,
                    )
                )
        return CoachThreadResponse(
            activity_id=loaded.activity.id,
            thread_id=None if loaded.thread is None else loaded.thread.id,
            coaching_allowed=coaching_allowed(_block(loaded.definition)),
            committed=loaded.activity.output_committed_at is not None,
            next_step=next_step_for(loaded.activity),
            messages=messages,
        )


def _block(definition: TaskDefinition) -> CoachBlock:
    return CoachBlock(
        stable_id=definition.stable_id,
        objective=definition.objective,
        allowed_ai_role=definition.allowed_ai_role,
        required_output=_string_items(definition.output_contract, "items"),
        pass_criteria=_string_items(definition.pass_contract, "items"),
    )


__all__ = [
    "CoachThreadService",
    "CoachingConflict",
    "CoachingError",
    "CoachingInvalidRequest",
    "CoachingNotFound",
    "CoachingUnavailable",
    "next_step_for",
]
