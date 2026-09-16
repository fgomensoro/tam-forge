"""The interview debrief: one bounded read of a real interview, from its transcript.

The debrief names what was strong and what was missing with verbatim quotes, says which
TAM skills the interview touched and in which direction, and proposes practice for the
next week. It never changes the plan and never claims to have recorded or scheduled
anything: those are the learner's decisions, made in the app.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..runtime import (
    AgentOutputInvalid,
    AgentRuntimeError,
    BoundedClaudeRuntime,
    PreparedAgentRun,
    TransportResult,
)
from ..tools.registry import AgentRole
from .contracts import (
    COMMITTED_ATTEMPT,
    SPEECH_METRICS,
    TASK_BRIEF,
    RoleContractError,
    prepare_role_prompt,
)

DEBRIEF_SCHEMA_ID = "urn:tamforge:schema:debrief-v1"
DEBRIEF_JOB_TYPE = "claude.debrief"
DEBRIEF_MAX_TURNS = 4
DEBRIEF_WALL_TIME_SECONDS = 300.0
DEBRIEF_PROMPT_VERSION = "v1"
MAX_TRANSCRIPT_CHARS = 200_000
PLAN_CHANGE_MARKERS = (
    "i changed the plan",
    "i updated the plan",
    "i rescheduled",
    "i moved the block",
    "i added a block",
    "i removed the block",
    "i marked",
    "i recorded",
    "i scheduled",
    "i completed",
)


class DebriefUnavailable(RoleContractError):
    """Claude is disabled or the runtime failed; the interview stays without a debrief."""


@dataclass(frozen=True, slots=True)
class DebriefInterview:
    company: str
    role: str
    stage: str
    starts_at: datetime
    status: str


@dataclass(frozen=True, slots=True)
class DebriefSkill:
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class DebriefRequest:
    interview: DebriefInterview
    transcript: str
    skills: tuple[DebriefSkill, ...]
    transcript_source: Literal["recording", "transcript_only"] = "recording"
    reference: tuple[str, ...] = ()
    repair_errors: tuple[str, ...] = ()


# Frank's Interview Progress Tracker compares every interview on the same four dimensions;
# hiring progression is reported apart because advancing is not proof of better communication.
TRACKER_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("answer_clarity", "Answer clarity and structure"),
    ("technical_examples", "Technical examples and supporting evidence"),
    ("english_accuracy", "English accuracy visible in the transcript"),
    ("follow_up_handling", "Handling of follow-up questions"),
)
DIMENSION_MAXIMUM = Decimal("4")


class ScoredTrackerDimension(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slug: str = Field(min_length=1, max_length=64)
    score: Decimal = Field(ge=0, le=4)
    rationale: str = Field(min_length=1, max_length=400)


class DebriefFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    statement: str = Field(min_length=1, max_length=500)
    evidence: str = Field(min_length=1, max_length=400)
    skill_slug: str = Field(min_length=1, max_length=64)


class SkillEffect(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    skill_slug: str = Field(min_length=1, max_length=64)
    direction: Literal["up", "flat", "down"]
    evidence: str = Field(min_length=1, max_length=400)


class PracticeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = Field(min_length=1, max_length=500)
    skill_slug: str = Field(min_length=1, max_length=64)
    minutes: int = Field(ge=5, le=90)


class DebriefOutcome(BaseModel):
    """The only shape a debrief may take."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1, max_length=1500)
    dimensions: tuple[ScoredTrackerDimension, ...] = Field(min_length=4, max_length=4)
    strengths: tuple[DebriefFinding, ...] = Field(min_length=2, max_length=4)
    gaps: tuple[DebriefFinding, ...] = Field(min_length=2, max_length=4)
    skills_affected: tuple[SkillEffect, ...] = Field(min_length=1, max_length=6)
    next_week_practice: tuple[PracticeProposal, ...] = Field(min_length=1, max_length=3)
    hiring_progression: str = Field(min_length=1, max_length=500)


class DebriefTransport(Protocol):
    async def debrief(self, request: DebriefRequest) -> Mapping[str, object]: ...


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def validate_debrief(
    payload: Mapping[str, object], *, transcript: str, skills: Sequence[DebriefSkill]
) -> tuple[str, ...]:
    """Issues by name; empty means the debrief may be stored."""
    try:
        outcome = DebriefOutcome.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "debrief"
        return (f"debrief {location}: {first['msg']}",)
    known = {skill.slug for skill in skills}
    haystack = _normalize(transcript)
    expected = [slug for slug, _ in TRACKER_DIMENSIONS]
    if sorted(d.slug for d in outcome.dimensions) != sorted(expected):
        return ("the debrief must score exactly the tracker dimensions: " + ", ".join(expected),)
    for dimension in outcome.dimensions:
        if dimension.score != dimension.score.quantize(Decimal("0.5")):
            return (f"dimension {dimension.slug} must be scored in half points",)
    for group, items in (("strengths", outcome.strengths), ("gaps", outcome.gaps)):
        for item in items:
            if item.skill_slug not in known:
                return (f"{group} names a skill outside the catalog: {item.skill_slug}",)
            if _normalize(item.evidence) not in haystack:
                return (f"{group} evidence must be a verbatim quote from the transcript",)
    for effect in outcome.skills_affected:
        if effect.skill_slug not in known:
            return (f"skills_affected names a skill outside the catalog: {effect.skill_slug}",)
        if _normalize(effect.evidence) not in haystack:
            return ("skills_affected evidence must be a verbatim quote from the transcript",)
    if len({e.skill_slug for e in outcome.skills_affected}) != len(outcome.skills_affected):
        return ("each affected skill appears once",)
    for practice in outcome.next_week_practice:
        if practice.skill_slug not in known:
            return (f"practice names a skill outside the catalog: {practice.skill_slug}",)
    lowered = " ".join(
        [outcome.summary, outcome.hiring_progression]
        + [f.statement for f in outcome.strengths + outcome.gaps]
        + [p.description for p in outcome.next_week_practice]
    ).lower()
    for marker in PLAN_CHANGE_MARKERS:
        if marker in lowered:
            return ("the debrief cannot change the plan or claim to have recorded anything",)
    return ()


@dataclass
class _DebriefRuntimeAdapter:
    transport: DebriefTransport
    request: DebriefRequest

    async def invoke(
        self, run: PreparedAgentRun, *, repair_errors: tuple[str, ...] = ()
    ) -> TransportResult:
        del run
        request = DebriefRequest(
            interview=self.request.interview,
            transcript=self.request.transcript,
            skills=self.request.skills,
            transcript_source=self.request.transcript_source,
            reference=self.request.reference,
            repair_errors=repair_errors,
        )
        payload = await self.transport.debrief(request)
        return TransportResult(payload=payload, turns=1)


class DebriefService:
    def __init__(self, transport: DebriefTransport | None, *, model: str) -> None:
        self._transport = transport
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def debrief(self, request: DebriefRequest) -> DebriefOutcome:
        """One bounded debrief, or a contract error the caller renders as such."""
        if not request.transcript.strip():
            raise RoleContractError("the debrief reads a transcript; there is none")
        if len(request.transcript) > MAX_TRANSCRIPT_CHARS:
            raise RoleContractError("the transcript is longer than the debrief may read")
        if not request.skills:
            raise RoleContractError("the debrief needs the skill catalog")
        prepare_role_prompt(
            AgentRole.REVIEWER,
            committed=True,
            requested_context=(TASK_BRIEF, COMMITTED_ATTEMPT, SPEECH_METRICS),
        )
        if self._transport is None:
            raise DebriefUnavailable("the debrief needs Claude enabled on the server")
        runtime = BoundedClaudeRuntime(
            _DebriefRuntimeAdapter(self._transport, request),
            validate=lambda payload: validate_debrief(
                payload, transcript=request.transcript, skills=request.skills
            ),
        )
        digest = hashlib.sha256(
            f"{request.interview.company}:{request.interview.starts_at.isoformat()}:"
            f"{request.transcript}".encode()
        ).hexdigest()[:24]
        prepared = PreparedAgentRun(
            run_key=f"debrief:{digest}",
            job_type=DEBRIEF_JOB_TYPE,
            model=self._model,
            schema_id=DEBRIEF_SCHEMA_ID,
            prompt_version=DEBRIEF_PROMPT_VERSION,
            max_turns=DEBRIEF_MAX_TURNS,
            wall_time_seconds=DEBRIEF_WALL_TIME_SECONDS,
        )
        try:
            result = await runtime.run(prepared)
        except AgentOutputInvalid:
            raise DebriefUnavailable("the debrief did not return a valid outcome") from None
        except AgentRuntimeError as exc:
            raise DebriefUnavailable(str(exc)) from None
        return DebriefOutcome.model_validate(result.payload)


def debrief_schema() -> dict[str, object]:
    return DebriefOutcome.model_json_schema()


def render_debrief_prompt(request: DebriefRequest) -> str:
    """The prompt the SDK transport sends: the record, the catalog, the transcript."""
    interview = request.interview
    lines: list[str] = [
        f"Interview: {interview.company}, {interview.role}, stage {interview.stage}, "
        f"{interview.starts_at.date().isoformat()}, status {interview.status}.",
        "TAM skills you may name (use the slug):\n"
        + "\n".join(f"- {skill.slug}: {skill.name}" for skill in request.skills),
        (
            "This transcript was pasted without audio: judge only the words. Never comment on "
            "pronunciation, fluency, pace or pauses."
            if request.transcript_source == "transcript_only"
            else "This transcript comes from a recording; timestamps are in milliseconds."
        ),
        "Transcript (learner and interviewer):\n" + request.transcript,
    ]
    if request.reference:
        lines.append(
            "Reference material the learner wrote earlier (readiness labels are unverified):\n"
            + "\n".join(f"- {item}" for item in request.reference)
        )
    lines.append(
        "Score these four comparison dimensions in half points from 0 to 4, each with a "
        "rationale:\n" + "\n".join(f"- {slug}: {name}" for slug, name in TRACKER_DIMENSIONS)
    )
    lines.append(
        "Return a summary; two to four strengths and two to four gaps, each with a verbatim "
        "quote from the transcript as evidence and the skill it concerns; the skills affected "
        "with a direction (up, flat, down) and a quote; one to three practice proposals for "
        "next week with the skill and minutes; and the hiring progression as a separate fact. "
        "Do not change the plan and do not claim to have recorded or scheduled anything."
    )
    if request.repair_errors:
        lines.append(
            "Your previous answer was refused; fix these:\n"
            + "\n".join(f"- {error}" for error in request.repair_errors)
        )
    return "\n\n".join(lines)


__all__ = [
    "DEBRIEF_JOB_TYPE",
    "DEBRIEF_PROMPT_VERSION",
    "DEBRIEF_SCHEMA_ID",
    "DIMENSION_MAXIMUM",
    "TRACKER_DIMENSIONS",
    "DebriefFinding",
    "DebriefInterview",
    "DebriefOutcome",
    "DebriefRequest",
    "DebriefService",
    "DebriefSkill",
    "DebriefTransport",
    "DebriefUnavailable",
    "PracticeProposal",
    "ScoredTrackerDimension",
    "SkillEffect",
    "debrief_schema",
    "render_debrief_prompt",
    "validate_debrief",
]
