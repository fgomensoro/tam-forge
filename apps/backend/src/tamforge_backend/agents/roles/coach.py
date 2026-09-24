"""The Coach: hints before the learner commits, corrects after, writes only evidence and notes.

Three rules, all enforced by shape rather than by discipline at the call site:

- It never runs in a block whose `allowed_ai_role` forbids it (`none`, or a role
  other than coach, tutor or interviewer). An interviewer block forbids coaching
  during Attempt A, so there it answers only after the commit, and never in the
  sealed final mock. Elsewhere, before the learner commits it asks a recall question
  and gives hints on request; a hint is reported in `hint_given` and the caller
  records it as assistance on the attempt. After the commit it corrects.
- Its output is a message, the next step taken from the plan the caller hands it
  (never invented), and proposed evidence the learner still has to accept. There is
  no field through which it could mark anything done.
- Every turn goes through the bounded runtime with a validator, so a malformed or
  over-long answer is refused, never rendered.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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
    SELF_REVIEW,
    TASK_BRIEF,
    RoleContractError,
    prepare_role_prompt,
)

COACH_SCHEMA_ID = "urn:tamforge:schema:coach-v2"
NOTE_SCHEMA_ID = "urn:tamforge:schema:coach-note-v1"
COACH_JOB_TYPE = "claude.followup"
COACH_MAX_TURNS = 4
COACH_WALL_TIME_SECONDS = 120.0
COACHING_ROLES: frozenset[str] = frozenset({"coach", "tutor"})
# Interviewer contracts forbid coaching during Attempt A, not after it is committed;
# only the sealed final mock forbids it outright.
SEALED_MOCK_PHASE = "sealed_final_mock"
CoachPhase = Literal["before_commit", "after_commit"]
MAX_MESSAGE_CHARS = 2000
EvidenceKind = Literal["note", "correction", "question", "card"]


class CoachUnavailable(RoleContractError):
    """Claude is disabled or the runtime failed; the learner keeps going without it."""


class ProposedEvidence(BaseModel):
    """Something the Coach suggests recording. The learner accepts it or not."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: EvidenceKind
    text: str = Field(min_length=1, max_length=1000)
    answer: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def card_needs_an_answer(self) -> ProposedEvidence:
        if self.kind == "card" and not self.answer.strip():
            raise ValueError("a card proposal needs an answer")
        if self.kind != "card" and self.answer:
            raise ValueError("only a card proposal carries an answer")
        return self


class CoachTurn(BaseModel):
    """The only shape a Coach answer may take. No completion, no scores, no plan edits."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    next_step: str = Field(min_length=1, max_length=500)
    hint_given: bool = False
    proposed_evidence: tuple[ProposedEvidence, ...] = Field(default=(), max_length=5)


@dataclass(frozen=True, slots=True)
class CoachBlock:
    """What the Coach may know about the block: the brief, never the whole roadmap."""

    stable_id: str
    objective: str
    allowed_ai_role: str
    required_output: tuple[str, ...]
    pass_criteria: tuple[str, ...]
    phases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CoachRequest:
    block: CoachBlock
    committed_attempt: str
    learner_message: str
    next_step: str
    self_review: str | None = None
    prior_messages: tuple[tuple[Literal["learner", "coach"], str], ...] = ()
    repair_errors: tuple[str, ...] = ()
    handoff: str | None = None
    reference: tuple[str, ...] = ()

    @property
    def phase(self) -> CoachPhase:
        return "after_commit" if self.committed_attempt.strip() else "before_commit"


class CoachTransport(Protocol):
    async def respond(self, request: CoachRequest) -> Mapping[str, object]: ...


class NoteQuery(BaseModel):
    """A query the learner ran and the result that was observed, never invented."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=4000)
    result: str = Field(min_length=1, max_length=2000)


class NoteFlashcard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=1000)


class CoachNoteDraft(BaseModel):
    """The polished note the Coach drafts at the end of a block; the learner approves it.

    There is no status, score or assistance field: those are recorded by the app from
    what actually happened, never written by the Coach.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=200)
    rule: str = Field(min_length=1, max_length=2000)
    explanation: str = Field(min_length=1, max_length=4000)
    example: str = Field(min_length=1, max_length=4000)
    misconceptions: tuple[str, ...] = Field(default=(), max_length=8)
    validated_queries: tuple[NoteQuery, ...] = Field(default=(), max_length=8)
    sources: tuple[str, ...] = Field(default=(), max_length=8)
    flashcards: tuple[NoteFlashcard, ...] = Field(default=(), max_length=12)


@dataclass(frozen=True, slots=True)
class NoteRequest:
    block: CoachBlock
    committed_attempt: str
    self_review: str | None = None
    coach_messages: tuple[tuple[Literal["learner", "coach"], str], ...] = ()
    accepted_evidence: tuple[str, ...] = ()
    repair_errors: tuple[str, ...] = ()


class NoteTransport(Protocol):
    async def draft_note(self, request: NoteRequest) -> Mapping[str, object]: ...


def coaching_allowed(block: CoachBlock) -> bool:
    if block.allowed_ai_role in COACHING_ROLES:
        return True
    return block.allowed_ai_role == "interviewer" and SEALED_MOCK_PHASE not in block.phases


def validate_coach_turn(
    payload: Mapping[str, object], *, next_step: str, phase: CoachPhase = "after_commit"
) -> tuple[str, ...]:
    """Issues by name; empty means the turn may be shown."""
    try:
        turn = CoachTurn.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "turn"
        return (f"coach turn {location}: {first['msg']}",)
    if turn.next_step.strip() != next_step.strip():
        return ("the next step must be the plan's, not the coach's",)
    if turn.hint_given and phase == "after_commit":
        return ("a hint is recorded only before the commit",)
    lowered = turn.message.lower()
    for marker in ("marked as done", "i marked", "i recorded", "i completed"):
        if marker in lowered:
            return ("the coach cannot claim to have recorded or completed anything",)
    return ()


def validate_note_draft(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Issues by name; empty means the draft may be shown to the learner."""
    try:
        draft = CoachNoteDraft.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "note"
        return (f"note draft {location}: {first['msg']}",)
    lowered = " ".join((draft.title, draft.rule, draft.explanation, draft.example)).lower()
    for marker in ("marked as done", "i marked", "i recorded", "i completed", "demonstrated"):
        if marker in lowered:
            return ("the note cannot claim completion, recording or mastery",)
    for item in draft.flashcards:
        if not item.question.rstrip().endswith("?"):
            return ("every flashcard question must end with a question mark",)
    return ()


@dataclass
class _NoteRuntimeAdapter:
    transport: NoteTransport
    request: NoteRequest

    async def invoke(
        self, run: PreparedAgentRun, *, repair_errors: tuple[str, ...] = ()
    ) -> TransportResult:
        del run
        request = replace(self.request, repair_errors=repair_errors)
        payload = await self.transport.draft_note(request)
        return TransportResult(payload=payload, turns=1)


@dataclass
class _RuntimeAdapter:
    transport: CoachTransport
    request: CoachRequest
    last_payload: Mapping[str, object] | None = None

    async def invoke(
        self, run: PreparedAgentRun, *, repair_errors: tuple[str, ...] = ()
    ) -> TransportResult:
        del run
        request = replace(self.request, repair_errors=repair_errors)
        payload = await self.transport.respond(request)
        self.last_payload = payload
        return TransportResult(payload=payload, turns=1)


class CoachService:
    def __init__(self, transport: CoachTransport | None, *, model: str) -> None:
        self._transport = transport
        self._model = model

    async def turn(self, request: CoachRequest) -> CoachTurn:
        """One coaching turn, or a contract error the caller renders as such."""
        if not coaching_allowed(request.block):
            raise RoleContractError("this block does not allow coaching")
        if request.block.allowed_ai_role == "interviewer" and request.phase == "before_commit":
            raise RoleContractError(
                "an interviewer block is coached only after Attempt A is committed"
            )
        prepare_role_prompt(
            AgentRole.COACH,
            committed=request.phase == "after_commit",
            requested_context=(TASK_BRIEF, COMMITTED_ATTEMPT, SELF_REVIEW),
        )
        if self._transport is None:
            raise CoachUnavailable("the coach needs Claude enabled on the server")
        adapter = _RuntimeAdapter(self._transport, request)
        runtime = BoundedClaudeRuntime(
            adapter,
            validate=lambda payload: validate_coach_turn(
                payload, next_step=request.next_step, phase=request.phase
            ),
        )
        digest = hashlib.sha256(
            f"{request.block.stable_id}:{len(request.prior_messages)}:{request.learner_message}".encode()
        ).hexdigest()[:24]
        prepared = PreparedAgentRun(
            run_key=f"coach:{request.block.stable_id}:{digest}",
            job_type=COACH_JOB_TYPE,
            model=self._model,
            schema_id=COACH_SCHEMA_ID,
            prompt_version="v2",
            max_turns=COACH_MAX_TURNS,
            wall_time_seconds=COACH_WALL_TIME_SECONDS,
        )
        try:
            result = await runtime.run(prepared)
        except AgentOutputInvalid:
            raise CoachUnavailable("the coach did not return a valid turn") from None
        except AgentRuntimeError as exc:
            raise CoachUnavailable(str(exc)) from None
        return CoachTurn.model_validate(result.payload)

    async def draft_note(self, request: NoteRequest) -> CoachNoteDraft:
        """One polished note draft, or a contract error the caller renders as such."""
        if not coaching_allowed(request.block):
            raise RoleContractError("this block does not allow coaching")
        if not request.committed_attempt.strip():
            raise RoleContractError("the coach drafts a note only after the learner commits")
        prepare_role_prompt(
            AgentRole.COACH,
            committed=True,
            requested_context=(TASK_BRIEF, COMMITTED_ATTEMPT, SELF_REVIEW),
        )
        transport = self._transport
        if transport is None or not hasattr(transport, "draft_note"):
            raise CoachUnavailable("the coach needs Claude enabled on the server")
        runtime = BoundedClaudeRuntime(
            _NoteRuntimeAdapter(cast(NoteTransport, transport), request),
            validate=validate_note_draft,
        )
        digest = hashlib.sha256(
            f"{request.block.stable_id}:{request.committed_attempt}:{len(request.coach_messages)}".encode()
        ).hexdigest()[:24]
        prepared = PreparedAgentRun(
            run_key=f"coach-note:{request.block.stable_id}:{digest}",
            job_type=COACH_JOB_TYPE,
            model=self._model,
            schema_id=NOTE_SCHEMA_ID,
            prompt_version="v1",
            max_turns=COACH_MAX_TURNS,
            wall_time_seconds=COACH_WALL_TIME_SECONDS,
        )
        try:
            result = await runtime.run(prepared)
        except AgentOutputInvalid:
            raise CoachUnavailable("the coach did not return a valid note") from None
        except AgentRuntimeError as exc:
            raise CoachUnavailable(str(exc)) from None
        return CoachNoteDraft.model_validate(result.payload)


def coach_turn_schema() -> dict[str, object]:
    return CoachTurn.model_json_schema()


def note_draft_schema() -> dict[str, object]:
    return CoachNoteDraft.model_json_schema()


def render_note_prompt(request: NoteRequest) -> str:
    """The prompt for the end-of-block note; polished English, nothing invented."""
    lines: list[str] = [
        f"Block: {request.block.stable_id}. Objective: {request.block.objective}",
        "Required output: " + "; ".join(request.block.required_output),
        "Pass criteria: " + "; ".join(request.block.pass_criteria),
        "Draft a polished study note in English from the committed attempt and the coaching "
        "that followed: the rule, a plain explanation, one concrete example, the misconceptions "
        "that were corrected, only queries that were actually run with the results observed, "
        "the sources used, and flashcard-ready questions and answers. Do not grade, do not "
        "claim the block is done, and do not invent queries, results or sources.",
        "Committed attempt:\n" + request.committed_attempt,
    ]
    if request.self_review:
        lines.append("Self-review:\n" + request.self_review)
    if request.coach_messages:
        lines.append(
            "Coaching thread:\n"
            + "\n".join(f"{speaker}: {text}" for speaker, text in request.coach_messages)
        )
    if request.accepted_evidence:
        lines.append(
            "Evidence the learner accepted:\n"
            + "\n".join(f"- {item}" for item in request.accepted_evidence)
        )
    if request.repair_errors:
        lines.append(
            "Your previous draft was refused; fix these:\n"
            + "\n".join(f"- {error}" for error in request.repair_errors)
        )
    return "\n\n".join(lines)


def render_coach_prompt(request: CoachRequest) -> str:
    """The prompt the SDK transport sends; kept here so the seam stays thin."""
    lines: list[str] = [
        f"Block: {request.block.stable_id}. Objective: {request.block.objective}",
        "Required output: " + "; ".join(request.block.required_output),
        "Pass criteria: " + "; ".join(request.block.pass_criteria),
        f"The plan's next step (repeat it verbatim as next_step): {request.next_step}",
    ]
    if request.phase == "before_commit":
        lines.append(
            "Phase: before the commit. The learner has not committed Attempt A yet. Open with "
            "one recall question for the objective, wait for their attempt, and when they ask "
            "for help give the smallest hint that unblocks them, never the full answer. Set "
            "hint_given to true on any turn that gives a hint; it is recorded as assistance."
        )
    else:
        lines.append("Phase: after the commit.")
        lines.append("Committed attempt:\n" + request.committed_attempt)
    if request.self_review:
        lines.append("Self-review:\n" + request.self_review)
    if request.handoff:
        lines.append(
            "Where the previous study day left off (the plan's words; a coached block is "
            "not a demonstrated one):\n" + request.handoff
        )
    if request.reference:
        lines.append(
            "Reference material the learner wrote earlier (answer bank, story catalog). Cite an "
            "entry by its heading when it helps; its readiness label is the learner's own claim, "
            "unverified until the ledger holds evidence, so never present it as demonstrated:\n"
            + "\n".join(f"- {item}" for item in request.reference)
        )
    for speaker, text in request.prior_messages:
        lines.append(f"{speaker}: {text}")
    lines.append(f"learner: {request.learner_message}")
    if request.repair_errors:
        lines.append(
            "Your previous answer was refused; fix these:\n"
            + "\n".join(f"- {error}" for error in request.repair_errors)
        )
    return "\n\n".join(lines)


__all__ = [
    "COACHING_ROLES",
    "COACH_JOB_TYPE",
    "COACH_SCHEMA_ID",
    "CoachBlock",
    "CoachPhase",
    "CoachRequest",
    "CoachService",
    "CoachTransport",
    "CoachTurn",
    "CoachNoteDraft",
    "CoachUnavailable",
    "NOTE_SCHEMA_ID",
    "NoteFlashcard",
    "NoteQuery",
    "NoteRequest",
    "NoteTransport",
    "ProposedEvidence",
    "Sequence",
    "coach_turn_schema",
    "coaching_allowed",
    "note_draft_schema",
    "render_coach_prompt",
    "render_note_prompt",
    "validate_coach_turn",
    "validate_note_draft",
]
