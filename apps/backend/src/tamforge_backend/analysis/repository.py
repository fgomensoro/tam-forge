"""Owner-scoped reads of gated feedback. Publication authority lives in the gate.

The public read translates a `SQLAlchemyError` into `FeedbackStorageUnavailable`,
because this is the only layer that can still recognise one for what it is. Above
it nothing catches a raw one: `api.register_routes` installs a handler per domain
error type and none for SQLAlchemy's, and `observability.middleware` re-raises, so
a dropped connection or a statement timeout used to reach Starlette's own
server-error handling as a plain-text 500 rather than the
`application/problem+json` the feedback route declares.

`raise ... from None` is deliberate. The `SQLAlchemyError` carries the rejected
statement and its bound parameters, which are owner data; the problem handler
renders whatever reaches it, so the chain must not ride along. The failure is
still logged with its own context by the layer that raised it.

`_released` stays untranslated on purpose: it touches no database and is only
ever called from inside the public read that already translates.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from tamforge_protocol.agents import (
    AnalysisVersions,
    EnglishAnalysisV1,
    FeedbackRead,
    PinnedRecord,
    TAMAnalysisV1,
)

from ..agents.models import AnalysisPublication, ModelRun
from ..agents.prompt_registry import verified
from ..learning.models import ActivityInstance, Attempt

RELEASED_KINDS = frozenset({"english_analysis", "tam_analysis"})


class FeedbackError(Exception):
    """Base safe feedback read error."""


class FeedbackNotFound(FeedbackError):
    """The owner has no such activity and attempt."""


class FeedbackUnreadable(FeedbackError):
    """Stored provenance did not satisfy the read contract."""


class FeedbackStorageUnavailable(FeedbackError):
    """The feedback store rejected the read and the caller may retry.

    Raised for a `SQLAlchemyError` and nothing else. It sits beside the other
    feedback errors so it is carried by the `FeedbackError` handler `api.py`
    already registers, which is why no handler registration had to change.
    """


@asynccontextmanager
async def _unavailable_on_database_error() -> AsyncIterator[None]:
    """Report a failed database call as an outage the caller may retry."""
    try:
        yield
    except SQLAlchemyError:
        raise FeedbackStorageUnavailable("feedback storage is unavailable") from None


class FeedbackRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def feedback(
        self, *, owner_id: int, activity_id: int, attempt_id: int
    ) -> FeedbackRead:
        async with _unavailable_on_database_error():
            attempt = await self.session.scalar(
                select(Attempt.id)
                .join(
                    ActivityInstance,
                    (ActivityInstance.owner_id == Attempt.owner_id)
                    & (ActivityInstance.id == Attempt.activity_instance_id),
                )
                .where(
                    Attempt.owner_id == owner_id,
                    Attempt.id == attempt_id,
                    Attempt.activity_instance_id == activity_id,
                )
            )
            if attempt is None:
                raise FeedbackNotFound()
            # Newest run first, but a later unpublished run must not retract feedback the
            # learner can already see, so the newest run holding BOTH analyses wins rather
            # than the newest run.
            rows = (
                await self.session.execute(
                    select(ModelRun, AnalysisPublication)
                    .join(
                        AnalysisPublication,
                        (AnalysisPublication.owner_id == ModelRun.owner_id)
                        & (AnalysisPublication.run_id == ModelRun.id),
                    )
                    .where(
                        ModelRun.owner_id == owner_id,
                        ModelRun.activity_id == activity_id,
                        ModelRun.attempt_id == attempt_id,
                    )
                    .order_by(ModelRun.id.desc())
                )
            ).all()
            by_run: dict[int, tuple[ModelRun, dict[str, object]]] = {}
            for run, publication in rows:
                analyses = by_run.setdefault(run.id, (run, {}))[1]
                analyses[publication.analysis_kind] = json.loads(
                    verified(publication).canonical_json
                )["analysis"]
            for run_id in sorted(by_run, reverse=True):
                run, published = by_run[run_id]
                if RELEASED_KINDS - published.keys():
                    continue
                return self._released(
                    run=run,
                    activity_id=activity_id,
                    attempt_id=attempt_id,
                    published=published,
                )
            return FeedbackRead(status="processing", activity_id=activity_id, attempt_id=attempt_id)

    def _released(
        self,
        *,
        run: ModelRun,
        activity_id: int,
        attempt_id: int,
        published: dict[str, object],
    ) -> FeedbackRead:
        header = json.loads(verified(run).canonical_json)
        try:
            return FeedbackRead(
                status="ready",
                activity_id=activity_id,
                attempt_id=attempt_id,
                versions=AnalysisVersions(
                    model_run=PinnedRecord(id=run.id, content_hash=run.content_hash.hex()),
                    prompt=PinnedRecord(**header["prompt"]),
                    output_schema=PinnedRecord(**header["schema_version"]),
                    rubric_binding=PinnedRecord(**header["rubric_binding"]),
                ),
                english=EnglishAnalysisV1.model_validate(published["english_analysis"]),
                tam=TAMAnalysisV1.model_validate(published["tam_analysis"]),
            )
        except (ValidationError, ValueError, KeyError, TypeError):
            # Stored rows that no longer satisfy the contract are a provenance fault, not a
            # crash. Never leak the offending payload into the response.
            raise FeedbackUnreadable() from None
