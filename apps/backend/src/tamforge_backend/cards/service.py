"""Cards: created from notes, evidence or by hand; due by date; graded and rescheduled."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import transaction_scope
from ..models.base import utc_now
from ..recordings.models import Recording
from .importing import package_card_commands
from .models import Card, CardReview
from .scheduling import SM2_VERSION, CardState, new_card_state, schedule
from .schemas import (
    CardCommand,
    CardImportResponse,
    CardPage,
    CardResponse,
    CardReviewResponse,
    CardReviewResult,
    CardsExport,
    DueCardsResponse,
)

DUE_LIMIT = 200


class CardsError(Exception):
    """Base error safe to convert to a closed public problem response."""


class CardNotFound(CardsError):
    """The owner-scoped card or recording does not exist."""


class CardInvalid(CardsError):
    """The command names something that is not there."""


class CardsUnavailable(CardsError):
    """The store cannot answer right now."""


def card_content_hash(question: str, answer: str) -> bytes:
    """Cards are the same card when their normalized question and answer match."""
    normalized = f"{' '.join(question.split()).casefold()}\n{' '.join(answer.split()).casefold()}"
    return hashlib.sha256(normalized.encode("utf-8")).digest()


class CardService:
    def __init__(self, session: AsyncSession, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._session = session
        self._clock = clock

    async def create(self, *, owner_id: int, command: CardCommand) -> CardResponse:
        """Create the card, or return the one with the same content: re-imports do not duplicate."""
        try:
            async with transaction_scope(self._session):
                card, _ = await self._upsert(owner_id=owner_id, command=command)
                return _card(card)
        except SQLAlchemyError:
            raise CardsUnavailable("the card store is unavailable") from None

    async def create_many(
        self, *, owner_id: int, commands: Sequence[CardCommand]
    ) -> tuple[CardResponse, ...]:
        try:
            async with transaction_scope(self._session):
                created = [
                    _card((await self._upsert(owner_id=owner_id, command=command))[0])
                    for command in commands
                ]
                return tuple(created)
        except SQLAlchemyError:
            raise CardsUnavailable("the card store is unavailable") from None

    async def upsert_many(
        self, *, owner_id: int, commands: Sequence[CardCommand]
    ) -> tuple[tuple[Card, bool], ...]:
        """Create or find each card inside the caller's transaction: (row, created) pairs."""
        return tuple([await self._upsert(owner_id=owner_id, command=c) for c in commands])

    async def import_package(
        self, *, owner_id: int, source_ref: str, files: Mapping[str, bytes]
    ) -> CardImportResponse:
        """Cards from every opted-in vault note in a package; a second import adds nothing."""
        commands = package_card_commands(files)
        try:
            async with transaction_scope(self._session):
                results = await self.upsert_many(owner_id=owner_id, commands=commands)
                return CardImportResponse(
                    source_ref=source_ref,
                    created=sum(1 for _, created in results if created),
                    existing=sum(1 for _, created in results if not created),
                    cards=tuple(_card(card) for card, _ in results),
                )
        except SQLAlchemyError:
            raise CardsUnavailable("the card store is unavailable") from None

    async def list(self, *, owner_id: int) -> CardPage:
        try:
            rows = (
                await self._session.scalars(
                    select(Card).where(Card.owner_id == owner_id).order_by(Card.due_on, Card.id)
                )
            ).all()
            page = CardPage(items=tuple(_card(item) for item in rows))
            await self._session.rollback()
            return page
        except SQLAlchemyError:
            raise CardsUnavailable("the card store is unavailable") from None

    async def due(self, *, owner_id: int, local_date: date) -> DueCardsResponse:
        """The cards due on or before a date: one query, oldest due first."""
        try:
            rows = (
                await self._session.scalars(
                    select(Card)
                    .where(Card.owner_id == owner_id)
                    .where(Card.status == "active")
                    .where(Card.due_on <= local_date)
                    .order_by(Card.due_on, Card.id)
                    .limit(DUE_LIMIT)
                )
            ).all()
            due = DueCardsResponse(local_date=local_date, items=tuple(_card(i) for i in rows))
            await self._session.rollback()
            return due
        except SQLAlchemyError:
            raise CardsUnavailable("the card store is unavailable") from None

    async def review(
        self,
        *,
        owner_id: int,
        card_id: int,
        grade: int,
        reviewed_on: date,
        mode: str = "written",
        recording_id: UUID | None = None,
    ) -> CardReviewResult:
        """Record the grade and reschedule the card under the pinned algorithm."""
        try:
            async with transaction_scope(self._session):
                card = await self._session.scalar(
                    select(Card)
                    .where(Card.owner_id == owner_id)
                    .where(Card.id == card_id)
                    .with_for_update()
                )
                if card is None:
                    raise CardNotFound("the card was not found")
                recording_pk: int | None = None
                if recording_id is not None:
                    recording_pk = await self._session.scalar(
                        select(Recording.id)
                        .where(Recording.owner_id == owner_id)
                        .where(Recording.client_recording_id == recording_id)
                    )
                    if recording_pk is None:
                        raise CardNotFound("the recording was not found")
                if mode == "spoken" and recording_pk is None:
                    raise CardInvalid("a spoken review needs its recording")
                outcome = schedule(
                    CardState(
                        easiness=card.easiness,
                        interval_days=card.interval_days,
                        repetitions=card.repetitions,
                        due_on=card.due_on,
                    ),
                    grade=grade,
                    reviewed_on=reviewed_on,
                )
                now = self._clock()
                card.easiness = outcome.after.easiness
                card.interval_days = outcome.after.interval_days
                card.repetitions = outcome.after.repetitions
                card.due_on = outcome.after.due_on
                card.scheduler_version = SM2_VERSION
                card.updated_at = now
                review = CardReview(
                    owner_id=owner_id,
                    card_id=card.id,
                    grade=grade,
                    mode=mode,
                    reviewed_on=reviewed_on,
                    interval_before=outcome.before.interval_days,
                    interval_after=outcome.after.interval_days,
                    easiness_after=outcome.after.easiness,
                    due_after=outcome.after.due_on,
                    recording_id=recording_pk,
                    created_at=now,
                )
                self._session.add(review)
                await self._session.flush()
                return CardReviewResult(card=_card(card), review=_review(review))
        except SQLAlchemyError:
            raise CardsUnavailable("the card store is unavailable") from None

    async def export(self, *, owner_id: int) -> CardsExport:
        """Every card and every review, for the owner's data export."""
        try:
            cards = (
                await self._session.scalars(
                    select(Card).where(Card.owner_id == owner_id).order_by(Card.id)
                )
            ).all()
            reviews = (
                await self._session.scalars(
                    select(CardReview)
                    .where(CardReview.owner_id == owner_id)
                    .order_by(CardReview.id)
                )
            ).all()
            export = CardsExport(
                scheduler_version=SM2_VERSION,
                cards=tuple(_card(item) for item in cards),
                reviews=tuple(_review(item) for item in reviews),
            )
            await self._session.rollback()
            return export
        except SQLAlchemyError:
            raise CardsUnavailable("the card store is unavailable") from None

    async def _upsert(self, *, owner_id: int, command: CardCommand) -> tuple[Card, bool]:
        digest = card_content_hash(command.question, command.answer)
        existing = await self._session.scalar(
            select(Card).where(Card.owner_id == owner_id).where(Card.content_hash == digest)
        )
        if existing is not None:
            return existing, False
        now = self._clock()
        card = Card(
            owner_id=owner_id,
            question=command.question.strip(),
            answer=command.answer.strip(),
            content_hash=digest,
            source_kind=command.source_kind,
            source_ref=command.source_ref,
            skill_slug=command.skill_slug,
            assistance=command.assistance,
            status="active",
            scheduler_version=SM2_VERSION,
            **_state_columns(new_card_state(due_on=now.date())),
            created_at=now,
            updated_at=now,
        )
        self._session.add(card)
        await self._session.flush()
        return card, True


def _state_columns(state: CardState) -> dict[str, Any]:
    return {
        "easiness": state.easiness,
        "interval_days": state.interval_days,
        "repetitions": state.repetitions,
        "due_on": state.due_on,
    }


def _card(card: Card) -> CardResponse:
    return CardResponse(
        id=card.id,
        question=card.question,
        answer=card.answer,
        skill_slug=card.skill_slug,
        source_kind=cast(Any, card.source_kind),
        source_ref=card.source_ref,
        assistance=cast(Any, card.assistance),
        status=cast(Any, card.status),
        scheduler_version=card.scheduler_version,
        easiness=card.easiness,
        interval_days=card.interval_days,
        repetitions=card.repetitions,
        due_on=card.due_on,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


def _review(review: CardReview) -> CardReviewResponse:
    return CardReviewResponse(
        id=review.id,
        card_id=review.card_id,
        grade=review.grade,
        mode=cast(Any, review.mode),
        reviewed_on=review.reviewed_on,
        interval_before=review.interval_before,
        interval_after=review.interval_after,
        easiness_after=review.easiness_after,
        due_after=review.due_after,
        created_at=review.created_at,
    )


__all__ = [
    "CardInvalid",
    "CardNotFound",
    "CardService",
    "CardsError",
    "CardsUnavailable",
    "card_content_hash",
]
