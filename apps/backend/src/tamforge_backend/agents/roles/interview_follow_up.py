"""The interviewer's follow-up: at most one short spoken question about the answer just given.

The learner answered a practice question aloud and the Mac transcribed it. One bounded,
tool-less read decides whether a real interviewer would follow up: on a weak point (a vague
claim, a missing number, an assertion with no example) or, on a minority of solid answers,
as a pressure probe, so a follow-up never comes to mean "I answered badly". The follow-up
must reuse something the learner actually said. The interviewer never coaches.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..runtime import (
    AgentOutputInvalid,
    AgentRuntimeError,
    BoundedClaudeRuntime,
    PreparedAgentRun,
    TransportResult,
)
from .contracts import RoleContractError

INTERVIEW_FOLLOW_UP_PROMPT_KEY = "tamforge.interview_follow_up"
INTERVIEW_FOLLOW_UP_PROMPT_VERSION = "v1"
INTERVIEW_FOLLOW_UP_SCHEMA_ID = "urn:tamforge:schema:interview-follow-up-v1"
INTERVIEW_FOLLOW_UP_JOB_TYPE = "claude.interview_follow_up"
INTERVIEW_FOLLOW_UP_MAX_TURNS = 4
# The learner is waiting in front of the Mac; the app gives up at 45 seconds overall.
INTERVIEW_FOLLOW_UP_WALL_TIME_SECONDS = 30.0
MAX_FOLLOW_UPS = 2
MAX_FOLLOW_UP_CHARS = 240
MAX_FOLLOW_UP_WORDS = 30
MINIMUM_ANSWER_WORDS = 8
MAX_ANSWER_CHARS = 40_000
# A real interviewer does not give up on a one-word answer; it asks the learner to say more,
# without spending a model call on it.
SHORT_ANSWER_FOLLOW_UP = "Can you expand on that?"
# A solid answer is probed about one time in three, decided by the answer itself so the
# same answer always gets the same treatment and the share stays a minority.
PRESSURE_PROBE_ONE_IN = 3
_COMMON_WORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "because",
        "before",
        "could",
        "every",
        "going",
        "really",
        "should",
        "something",
        "their",
        "there",
        "these",
        "thing",
        "things",
        "think",
        "those",
        "through",
        "where",
        "which",
        "while",
        "would",
        "years",
    }
)

FollowUpReason = Literal["weak_point", "pressure_probe"]


class InterviewFollowUpUnavailable(RoleContractError):
    """Claude is disabled or the runtime failed; the session moves on without a follow-up."""


@dataclass(frozen=True, slots=True)
class FollowUpRequest:
    question: str
    answer_transcript: str
    reference_answer: str = ""
    prior_follow_ups: tuple[str, ...] = ()
    repair_errors: tuple[str, ...] = ()


class FollowUpOutcome(BaseModel):
    """The only shape a follow-up decision may take: both fields set, or both null."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    follow_up: str | None = Field(min_length=1, max_length=MAX_FOLLOW_UP_CHARS)
    reason: FollowUpReason | None


NO_FOLLOW_UP = FollowUpOutcome(follow_up=None, reason=None)


class FollowUpTransport(Protocol):
    async def follow_up(self, request: FollowUpRequest) -> Mapping[str, object]: ...


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z'-]*", text.casefold())


def _content_words(text: str) -> set[str]:
    return {word for word in _words(text) if len(word) >= 5 and word not in _COMMON_WORDS}


def _normalize(text: str) -> str:
    return " ".join(_words(text))


def pressure_probe_allowed(question: str, answer_transcript: str) -> bool:
    digest = hashlib.sha256(f"{question}:{answer_transcript}".encode()).digest()
    return digest[0] % PRESSURE_PROBE_ONE_IN == 0


def validate_follow_up(
    payload: Mapping[str, object],
    *,
    answer_transcript: str,
    prior_follow_ups: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Issues by name; empty means the decision may be used."""
    try:
        outcome = FollowUpOutcome.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "follow-up"
        return (f"follow-up {location}: {first['msg']}",)
    if (outcome.follow_up is None) != (outcome.reason is None):
        return ("follow_up and reason must both be set or both be null",)
    if outcome.follow_up is None:
        return ()
    text = outcome.follow_up.strip()
    if "\n" in text or text.count("?") != 1 or not text.endswith("?"):
        return ("the follow-up must be one spoken question ending in a question mark",)
    if len(_words(text)) > MAX_FOLLOW_UP_WORDS:
        return (f"the follow-up must be at most {MAX_FOLLOW_UP_WORDS} words",)
    if _normalize(text) in {_normalize(prior) for prior in prior_follow_ups}:
        return ("the follow-up repeats one that was already asked",)
    if not _content_words(text) & _content_words(answer_transcript):
        return ("the follow-up must reuse a word the learner actually said",)
    return ()


@dataclass
class _FollowUpRuntimeAdapter:
    transport: FollowUpTransport
    request: FollowUpRequest

    async def invoke(
        self, run: PreparedAgentRun, *, repair_errors: tuple[str, ...] = ()
    ) -> TransportResult:
        del run
        payload = await self.transport.follow_up(
            replace(self.request, repair_errors=repair_errors)
        )
        return TransportResult(payload=payload, turns=1)


class InterviewFollowUpService:
    def __init__(self, transport: FollowUpTransport | None, *, model: str) -> None:
        self._transport = transport
        self._model = model

    async def decide(self, request: FollowUpRequest) -> FollowUpOutcome:
        """One bounded decision, or a contract error the caller renders as such."""
        if not request.question.strip():
            raise RoleContractError("the follow-up needs the question that was asked")
        word_count = len(_words(request.answer_transcript))
        if word_count == 0:
            raise RoleContractError("the answer is too short to follow up on")
        if len(request.answer_transcript) > MAX_ANSWER_CHARS:
            raise RoleContractError("the answer is longer than the interviewer may read")
        if len(request.prior_follow_ups) >= MAX_FOLLOW_UPS:
            return NO_FOLLOW_UP
        if self._transport is None:
            raise InterviewFollowUpUnavailable(
                "the follow-up needs Claude enabled on the server"
            )
        if word_count < MINIMUM_ANSWER_WORDS:
            # Too short to reason about; a real interviewer just asks for more, no model call.
            if _normalize(SHORT_ANSWER_FOLLOW_UP) in {
                _normalize(prior) for prior in request.prior_follow_ups
            }:
                return NO_FOLLOW_UP
            return FollowUpOutcome(follow_up=SHORT_ANSWER_FOLLOW_UP, reason="weak_point")
        runtime = BoundedClaudeRuntime(
            _FollowUpRuntimeAdapter(self._transport, request),
            validate=lambda payload: validate_follow_up(
                payload,
                answer_transcript=request.answer_transcript,
                prior_follow_ups=request.prior_follow_ups,
            ),
        )
        key = f"{request.question}:{request.answer_transcript}:{len(request.prior_follow_ups)}"
        digest = hashlib.sha256(key.encode()).hexdigest()[:24]
        prepared = PreparedAgentRun(
            run_key=f"interview-follow-up:{digest}",
            job_type=INTERVIEW_FOLLOW_UP_JOB_TYPE,
            model=self._model,
            schema_id=INTERVIEW_FOLLOW_UP_SCHEMA_ID,
            prompt_version=INTERVIEW_FOLLOW_UP_PROMPT_VERSION,
            max_turns=INTERVIEW_FOLLOW_UP_MAX_TURNS,
            wall_time_seconds=INTERVIEW_FOLLOW_UP_WALL_TIME_SECONDS,
        )
        try:
            result = await runtime.run(prepared)
        except AgentOutputInvalid:
            raise InterviewFollowUpUnavailable(
                "the interviewer did not return a valid follow-up"
            ) from None
        except AgentRuntimeError as exc:
            raise InterviewFollowUpUnavailable(str(exc)) from None
        outcome = FollowUpOutcome.model_validate(result.payload)
        if outcome.reason == "pressure_probe" and not pressure_probe_allowed(
            request.question, request.answer_transcript
        ):
            return NO_FOLLOW_UP
        return outcome


def follow_up_schema() -> dict[str, object]:
    return FollowUpOutcome.model_json_schema()


def render_follow_up_prompt(request: FollowUpRequest) -> str:
    """The prompt the SDK transport sends: the question, the answer, what was already asked."""
    lines: list[str] = [
        "A learner preparing for Technical Account Manager interviews is practising aloud. "
        "You are the interviewer. This is practice, not a real interview.",
        f"Question asked: {request.question.strip()}",
    ]
    if request.prior_follow_ups:
        lines.append(
            "Follow-ups you already asked, in order (the answer below responds to the last "
            "one):\n" + "\n".join(f"- {prior.strip()}" for prior in request.prior_follow_ups)
        )
    lines.append(
        "The learner's answer, transcribed from the recording:\n"
        + request.answer_transcript.strip()
    )
    if request.reference_answer.strip():
        lines.append(
            "The learner's own reference answer (what they intended to say, not something "
            "they said):\n" + request.reference_answer.strip()
        )
    probe = (
        "If the answer is solid, you may still ask one pressure probe, the way a real "
        "interviewer tests a good answer; set reason to pressure_probe."
        if pressure_probe_allowed(request.question, request.answer_transcript)
        else "If the answer is solid, ask nothing: set follow_up and reason to null."
    )
    lines.append(
        "Decide whether to ask one follow-up. Ask one when something said is weak: a vague "
        "claim, a missing number, an assertion with no example; set reason to weak_point. "
        + probe
        + f" A follow-up is one short spoken question of at most {MAX_FOLLOW_UP_WORDS} words, "
        "ends in a question mark, reuses the learner's own words for the thing it targets, "
        "and never repeats an earlier follow-up. Never coach, hint at the answer, or comment "
        "on quality."
    )
    if request.repair_errors:
        lines.append(
            "Your previous answer was refused; fix these:\n"
            + "\n".join(f"- {error}" for error in request.repair_errors)
        )
    return "\n\n".join(lines)


__all__ = [
    "INTERVIEW_FOLLOW_UP_JOB_TYPE",
    "INTERVIEW_FOLLOW_UP_PROMPT_KEY",
    "INTERVIEW_FOLLOW_UP_PROMPT_VERSION",
    "INTERVIEW_FOLLOW_UP_SCHEMA_ID",
    "MAX_FOLLOW_UPS",
    "NO_FOLLOW_UP",
    "SHORT_ANSWER_FOLLOW_UP",
    "FollowUpOutcome",
    "FollowUpRequest",
    "FollowUpTransport",
    "InterviewFollowUpService",
    "InterviewFollowUpUnavailable",
    "follow_up_schema",
    "pressure_probe_allowed",
    "render_follow_up_prompt",
    "validate_follow_up",
]
