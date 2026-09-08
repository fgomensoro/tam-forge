"""Owner-scoped reads of gated feedback. Publication authority lives in the gate."""

from __future__ import annotations

import json

from sqlalchemy import select
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


class FeedbackError(Exception):
    """Base safe feedback read error."""


class FeedbackNotFound(FeedbackError):
    """The owner has no such activity and attempt."""


class FeedbackRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def feedback(
        self, *, owner_id: int, activity_id: int, attempt_id: int
    ) -> FeedbackRead:
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
        run = await self.session.scalar(
            select(ModelRun)
            .where(
                ModelRun.owner_id == owner_id,
                ModelRun.activity_id == activity_id,
                ModelRun.attempt_id == attempt_id,
            )
            .order_by(ModelRun.id.desc())
            .limit(1)
        )
        if run is None:
            return FeedbackRead(
                status="processing", activity_id=activity_id, attempt_id=attempt_id
            )
        published = {
            row.analysis_kind: json.loads(verified(row).canonical_json)["analysis"]
            for row in (
                await self.session.scalars(
                    select(AnalysisPublication).where(
                        AnalysisPublication.owner_id == owner_id,
                        AnalysisPublication.run_id == run.id,
                    )
                )
            ).all()
        }
        if {"english_analysis", "tam_analysis"} - published.keys():
            return FeedbackRead(
                status="processing", activity_id=activity_id, attempt_id=attempt_id
            )
        header = json.loads(verified(run).canonical_json)
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
