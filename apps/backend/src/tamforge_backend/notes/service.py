"""Study notes: drafted at the end of a block, edited by the learner, approved into evidence.

The Coach drafts only where the block allows coaching and only after the learner
committed; the learner can always write the note by hand. Approval renders the note as
Markdown, stores it in the object store under the learner's artifacts, records an
`Artifact` of class `recall_note` linked to the activity, and freezes the note. The
assistance recorded on the note comes from what happened (a coach draft, or a coaching
thread with coach messages), never from the Coach's own claim.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.roles.coach import (
    CoachBlock,
    CoachNoteDraft,
    CoachService,
    CoachUnavailable,
    NoteRequest,
    coaching_allowed,
)
from ..agents.roles.contracts import RoleContractError
from ..coaching.models import CoachEvidence, CoachMessage, CoachThread
from ..database import transaction_scope
from ..learning.artifacts import unencrypted_metadata
from ..learning.models import ActivityArtifactLink, ActivityInstance, Artifact, Attempt, StudyDay
from ..learning.service import _string_items
from ..models.base import utc_now
from ..roadmaps.models import TaskDefinition
from ..storage.models import ObjectStoreError, build_object_key
from ..storage.ports import ObjectStore
from .markdown import NoteDocument, note_filename, render_note_markdown
from .models import StudyNote
from .schemas import StudyNoteContent, StudyNoteResponse, StudyNoteSearchResponse, StudyNoteSummary

NOTE_CONTENT_TYPE = "text/markdown"
SEARCH_LIMIT = 50


class NotesError(Exception):
    """Base error safe to convert to a closed public problem response."""


class NoteNotFound(NotesError):
    """The owner-scoped activity or note does not exist."""


class NoteConflict(NotesError):
    """The note is frozen, the block forbids coaching, or nothing was committed yet."""


class NoteInvalidRequest(NotesError):
    """The command names something that is not there."""


class NotesUnavailable(NotesError):
    """The store, the object store or the Coach cannot answer right now."""


@dataclass(frozen=True, slots=True)
class _Loaded:
    activity: ActivityInstance
    definition: TaskDefinition
    local_date: date
    note: StudyNote | None


class StudyNoteService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        coach: CoachService,
        object_store: ObjectStore,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._coach = coach
        self._object_store = object_store
        self._clock = clock

    async def get(self, *, owner_id: int, activity_id: int) -> StudyNoteResponse:
        try:
            # The read is rolled back on every path, so a not-found answer never leaves a
            # transaction open on a session the caller reuses.
            try:
                loaded = await self._load(owner_id=owner_id, activity_id=activity_id, lock=False)
                if loaded.note is None:
                    raise NoteNotFound("there is no study note for this activity")
                return _response(loaded.note, loaded)
            finally:
                await self._session.rollback()
        except SQLAlchemyError:
            raise NotesUnavailable("the notes store is unavailable") from None

    async def draft(self, *, owner_id: int, activity_id: int) -> StudyNoteResponse:
        """Ask the Coach for a draft; the learner still edits and approves it."""
        try:
            async with transaction_scope(self._session):
                loaded = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
                if loaded.note is not None and loaded.note.status == "approved":
                    raise NoteConflict("an approved note is frozen; it cannot be redrafted")
                block = _block(loaded.definition)
                if not coaching_allowed(block):
                    raise NoteConflict("this block does not allow coaching")
                attempt = await self._committed_attempt(owner_id=owner_id, activity_id=activity_id)
                if not attempt:
                    raise NoteConflict("commit an attempt before asking for a note")
                messages, accepted = await self._coaching(
                    owner_id=owner_id, activity_id=activity_id
                )
                try:
                    draft = await self._coach.draft_note(
                        NoteRequest(
                            block=block,
                            committed_attempt=attempt,
                            coach_messages=messages,
                            accepted_evidence=accepted,
                        )
                    )
                except CoachUnavailable as exc:
                    raise NotesUnavailable(str(exc)) from None
                except RoleContractError as exc:
                    raise NoteConflict(str(exc)) from None
                note = loaded.note or StudyNote(
                    owner_id=owner_id,
                    activity_instance_id=activity_id,
                    drafted_by="coach",
                    assistance="coached",
                    assessment_status=loaded.activity.state,
                    title=draft.title,
                )
                _apply_draft(note, draft)
                note.drafted_by = "coach"
                note.assistance = "coached"
                note.assessment_status = loaded.activity.state
                note.updated_at = self._clock()
                if note.id is None:
                    self._session.add(note)
                await self._session.flush()
                return _response(note, loaded)
        except SQLAlchemyError:
            raise NotesUnavailable("the notes store is unavailable") from None

    async def save(
        self, *, owner_id: int, activity_id: int, content: StudyNoteContent
    ) -> StudyNoteResponse:
        """The learner's edit; creates the note by hand when the Coach never drafted one."""
        try:
            async with transaction_scope(self._session):
                loaded = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
                if loaded.note is not None and loaded.note.status == "approved":
                    raise NoteConflict("an approved note is frozen; it cannot be edited")
                note = loaded.note
                if note is None:
                    coached = await self._was_coached(owner_id=owner_id, activity_id=activity_id)
                    note = StudyNote(
                        owner_id=owner_id,
                        activity_instance_id=activity_id,
                        drafted_by="learner",
                        assistance="coached" if coached else "independent",
                        assessment_status=loaded.activity.state,
                        title=content.title,
                    )
                    self._session.add(note)
                _apply_content(note, content)
                note.assessment_status = loaded.activity.state
                note.updated_at = self._clock()
                await self._session.flush()
                return _response(note, loaded)
        except SQLAlchemyError:
            raise NotesUnavailable("the notes store is unavailable") from None

    async def approve(self, *, owner_id: int, activity_id: int) -> StudyNoteResponse:
        """Freeze the note as an evidence artifact in the database and the object store."""
        try:
            async with transaction_scope(self._session):
                loaded = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
                note = loaded.note
                if note is None:
                    raise NoteNotFound("there is no study note to approve")
                if note.status == "approved":
                    return _response(note, loaded)
                if not note.title.strip() or not note.rule.strip():
                    raise NoteConflict("a note needs at least a title and a rule to be approved")
                now = self._clock()
                note.assessment_status = loaded.activity.state
                # Render as approved, but flip the row only once the artifact exists: the
                # table forbids an approved note without one, and a flush can happen early.
                document = _document(note, loaded, status="approved")
                markdown = render_note_markdown(document).encode("utf-8")
                digest = hashlib.sha256(markdown).hexdigest()
                artifact = await self._session.scalar(
                    select(Artifact)
                    .where(Artifact.owner_id == owner_id)
                    .where(Artifact.content_hash == bytes.fromhex(digest))
                )
                if artifact is None:
                    key = build_object_key(
                        artifact_class="recall_note",
                        owner_id=str(owner_id),
                        logical_id=f"note-{note.id}",
                        sha256=digest,
                    )
                    try:
                        await self._object_store.put_immutable(
                            key=key,
                            body=_chunks(markdown),
                            sha256=digest,
                            content_type=NOTE_CONTENT_TYPE,
                            metadata={"tamforge-kind": "study-note", "tamforge-note": str(note.id)},
                        )
                    except ObjectStoreError:
                        raise NotesUnavailable("the object store refused the note") from None
                    artifact = Artifact(
                        owner_id=owner_id,
                        object_key=key,
                        content_hash=bytes.fromhex(digest),
                        content_type=NOTE_CONTENT_TYPE,
                        original_filename=note_filename(document),
                        byte_size=len(markdown),
                        artifact_class="recall_note",
                        encryption_metadata=unencrypted_metadata(),
                        derived_from_artifact_id=None,
                        immutable_version=1,
                        created_at=now,
                    )
                    self._session.add(artifact)
                    await self._session.flush()
                link = await self._session.scalar(
                    select(ActivityArtifactLink.id)
                    .where(ActivityArtifactLink.owner_id == owner_id)
                    .where(ActivityArtifactLink.activity_instance_id == activity_id)
                    .where(ActivityArtifactLink.artifact_id == artifact.id)
                )
                if link is None:
                    self._session.add(
                        ActivityArtifactLink(
                            owner_id=owner_id,
                            activity_instance_id=activity_id,
                            attempt_id=None,
                            artifact_id=artifact.id,
                            link_role="supporting",
                            created_at=now,
                        )
                    )
                note.artifact_id = artifact.id
                note.content_sha256 = digest
                note.status = "approved"
                note.approved_at = now
                note.updated_at = now
                await self._session.flush()
                return _response(note, loaded)
        except SQLAlchemyError:
            raise NotesUnavailable("the notes store is unavailable") from None

    async def search(self, *, owner_id: int, query: str) -> StudyNoteSearchResponse:
        text = query.strip()
        try:
            statement = (
                select(StudyNote, ActivityInstance.task_stable_id_snapshot, StudyDay.local_date)
                .join(
                    ActivityInstance,
                    (ActivityInstance.owner_id == StudyNote.owner_id)
                    & (ActivityInstance.id == StudyNote.activity_instance_id),
                )
                .join(
                    StudyDay,
                    (StudyDay.owner_id == ActivityInstance.owner_id)
                    & (StudyDay.id == ActivityInstance.study_day_id),
                )
                .where(StudyNote.owner_id == owner_id)
                .order_by(StudyNote.updated_at.desc(), StudyNote.id.desc())
                .limit(SEARCH_LIMIT)
            )
            if text:
                pattern = f"%{_escape_like(text)}%"
                statement = statement.where(
                    or_(
                        StudyNote.title.ilike(pattern, escape="\\"),
                        StudyNote.rule.ilike(pattern, escape="\\"),
                        StudyNote.explanation.ilike(pattern, escape="\\"),
                        StudyNote.example.ilike(pattern, escape="\\"),
                    )
                )
            rows = (await self._session.execute(statement)).all()
            items = [
                StudyNoteSummary(
                    id=note.id,
                    activity_id=note.activity_instance_id,
                    stable_id=str(stable_id),
                    local_date=local_date,
                    title=note.title,
                    status=cast(Any, note.status),
                    assistance=cast(Any, note.assistance),
                    flashcard_count=len(note.flashcards),
                    updated_at=note.updated_at,
                )
                for note, stable_id, local_date in rows
            ]
            await self._session.rollback()
            return StudyNoteSearchResponse(query=text, items=items)
        except SQLAlchemyError:
            raise NotesUnavailable("the notes store is unavailable") from None

    async def export(self, *, owner_id: int, since: date | None, until: date | None) -> bytes:
        """A zip of Markdown files, one per note, for backup or reading in Obsidian."""
        try:
            statement = (
                select(StudyNote, ActivityInstance.task_stable_id_snapshot, StudyDay.local_date)
                .join(
                    ActivityInstance,
                    (ActivityInstance.owner_id == StudyNote.owner_id)
                    & (ActivityInstance.id == StudyNote.activity_instance_id),
                )
                .join(
                    StudyDay,
                    (StudyDay.owner_id == ActivityInstance.owner_id)
                    & (StudyDay.id == ActivityInstance.study_day_id),
                )
                .where(StudyNote.owner_id == owner_id)
                .order_by(StudyDay.local_date, StudyNote.id)
            )
            if since is not None:
                statement = statement.where(StudyDay.local_date >= since)
            if until is not None:
                statement = statement.where(StudyDay.local_date <= until)
            rows = (await self._session.execute(statement)).all()
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                seen: set[str] = set()
                for note, stable_id, local_date in rows:
                    document = _document_from(note, str(stable_id), local_date)
                    name = note_filename(document)
                    if name in seen:
                        name = name[:-3] + f" ({note.id}).md"
                    seen.add(name)
                    archive.writestr(f"notes/{name}", render_note_markdown(document))
            await self._session.rollback()
            return buffer.getvalue()
        except SQLAlchemyError:
            raise NotesUnavailable("the notes store is unavailable") from None

    async def _load(self, *, owner_id: int, activity_id: int, lock: bool) -> _Loaded:
        statement = (
            select(ActivityInstance, TaskDefinition, StudyDay.local_date)
            .join(
                TaskDefinition,
                (TaskDefinition.owner_id == ActivityInstance.owner_id)
                & (TaskDefinition.id == ActivityInstance.task_definition_id),
            )
            .join(
                StudyDay,
                (StudyDay.owner_id == ActivityInstance.owner_id)
                & (StudyDay.id == ActivityInstance.study_day_id),
            )
            .where(ActivityInstance.owner_id == owner_id)
            .where(ActivityInstance.id == activity_id)
        )
        if lock:
            statement = statement.with_for_update(of=ActivityInstance)
        row = (await self._session.execute(statement)).first()
        if row is None:
            raise NoteNotFound("the activity was not found")
        activity, definition, local_date = row
        note = await self._session.scalar(
            select(StudyNote)
            .where(StudyNote.owner_id == owner_id)
            .where(StudyNote.activity_instance_id == activity_id)
        )
        return _Loaded(activity, definition, local_date, note)

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

    async def _coaching(
        self, *, owner_id: int, activity_id: int
    ) -> tuple[tuple[tuple[Any, str], ...], tuple[str, ...]]:
        thread_id = await self._session.scalar(
            select(CoachThread.id)
            .where(CoachThread.owner_id == owner_id)
            .where(CoachThread.activity_instance_id == activity_id)
        )
        if thread_id is None:
            return (), ()
        messages = tuple(
            (item.speaker, item.text)
            for item in await self._session.scalars(
                select(CoachMessage)
                .where(CoachMessage.owner_id == owner_id)
                .where(CoachMessage.thread_id == thread_id)
                .order_by(CoachMessage.id)
            )
        )
        accepted = tuple(
            item.text
            for item in await self._session.scalars(
                select(CoachEvidence)
                .where(CoachEvidence.owner_id == owner_id)
                .where(CoachEvidence.thread_id == thread_id)
                .order_by(CoachEvidence.id)
            )
        )
        return messages, accepted

    async def _was_coached(self, *, owner_id: int, activity_id: int) -> bool:
        found = await self._session.scalar(
            select(CoachMessage.id)
            .join(
                CoachThread,
                (CoachThread.owner_id == CoachMessage.owner_id)
                & (CoachThread.id == CoachMessage.thread_id),
            )
            .where(CoachThread.owner_id == owner_id)
            .where(CoachThread.activity_instance_id == activity_id)
            .where(CoachMessage.speaker == "coach")
            .limit(1)
        )
        return found is not None


async def _chunks(payload: bytes) -> AsyncIterator[bytes]:
    yield payload


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _block(definition: TaskDefinition) -> CoachBlock:
    return CoachBlock(
        stable_id=definition.stable_id,
        objective=definition.objective,
        allowed_ai_role=definition.allowed_ai_role,
        required_output=_string_items(definition.output_contract, "items"),
        pass_criteria=_string_items(definition.pass_contract, "items"),
    )


def _apply_draft(note: StudyNote, draft: CoachNoteDraft) -> None:
    note.title = draft.title
    note.rule = draft.rule
    note.explanation = draft.explanation
    note.example = draft.example
    note.misconceptions = list(draft.misconceptions)
    note.validated_queries = [item.model_dump() for item in draft.validated_queries]
    note.sources = list(draft.sources)
    note.flashcards = [item.model_dump() for item in draft.flashcards]


def _apply_content(note: StudyNote, content: StudyNoteContent) -> None:
    note.title = content.title
    note.rule = content.rule
    note.explanation = content.explanation
    note.example = content.example
    note.misconceptions = list(content.misconceptions)
    note.validated_queries = [item.model_dump() for item in content.validated_queries]
    note.sources = list(content.sources)
    note.flashcards = [item.model_dump() for item in content.flashcards]


def _document(note: StudyNote, loaded: _Loaded, *, status: str | None = None) -> NoteDocument:
    return _document_from(
        note, loaded.activity.task_stable_id_snapshot, loaded.local_date, status=status
    )


def _document_from(
    note: StudyNote, stable_id: str, local_date: date, *, status: str | None = None
) -> NoteDocument:
    return NoteDocument(
        title=note.title,
        stable_id=stable_id,
        local_date=local_date,
        status=status or note.status,
        assistance=note.assistance,
        assessment_status=note.assessment_status,
        drafted_by=note.drafted_by,
        rule=note.rule,
        explanation=note.explanation,
        example=note.example,
        misconceptions=list(note.misconceptions),
        validated_queries=list(note.validated_queries),
        sources=list(note.sources),
        flashcards=list(note.flashcards),
    )


def _response(note: StudyNote, loaded: _Loaded) -> StudyNoteResponse:
    return StudyNoteResponse(
        id=note.id,
        activity_id=note.activity_instance_id,
        stable_id=loaded.activity.task_stable_id_snapshot,
        local_date=loaded.local_date,
        status=cast(Any, note.status),
        drafted_by=cast(Any, note.drafted_by),
        assistance=cast(Any, note.assistance),
        assessment_status=note.assessment_status,
        title=note.title,
        rule=note.rule,
        explanation=note.explanation,
        example=note.example,
        misconceptions=list(note.misconceptions),
        validated_queries=cast(Any, list(note.validated_queries)),
        sources=list(note.sources),
        flashcards=cast(Any, list(note.flashcards)),
        artifact_id=note.artifact_id,
        content_sha256=note.content_sha256,
        updated_at=note.updated_at,
        approved_at=note.approved_at,
    )


__all__ = [
    "NoteConflict",
    "NoteInvalidRequest",
    "NoteNotFound",
    "NotesError",
    "NotesUnavailable",
    "StudyNoteService",
]
