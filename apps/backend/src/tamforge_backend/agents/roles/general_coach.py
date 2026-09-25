"""The Coach outside any activity: the plan, what to study next, a concept, the app.

It runs under the Coach's contract with the screen context only: the name of the screen
the learner is on and a short summary the app writes of it, never an attempt or a draft.
Its only output is a message. There is no next step, no proposed evidence and no hint
accounting, and a message that claims to have recorded, scheduled or changed anything
is refused like any other malformed turn.
"""

from __future__ import annotations

import hashlib
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
from ..tools.registry import AgentRole
from .coach import (
    COACH_JOB_TYPE,
    COACH_MAX_TURNS,
    COACH_WALL_TIME_SECONDS,
    MAX_MESSAGE_CHARS,
    CoachUnavailable,
)
from .contracts import SCREEN_CONTEXT, prepare_role_prompt

GENERAL_COACH_SCHEMA_ID = "urn:tamforge:schema:general-coach-v1"
_CLAIMS = ("i recorded", "i scheduled", "i marked", "i completed", "i changed your plan")


class GeneralCoachTurn(BaseModel):
    """The only shape a general Coach answer may take: a message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


@dataclass(frozen=True, slots=True)
class GeneralCoachRequest:
    screen: str
    summary: str
    learner_message: str
    prior_messages: tuple[tuple[Literal["learner", "coach"], str], ...] = ()
    repair_errors: tuple[str, ...] = ()


class GeneralCoachTransport(Protocol):
    async def general_reply(self, request: GeneralCoachRequest) -> Mapping[str, object]: ...


def general_coach_schema() -> dict[str, object]:
    return GeneralCoachTurn.model_json_schema()


def validate_general_turn(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Issues by name; empty means the turn may be shown."""
    try:
        turn = GeneralCoachTurn.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "turn"
        return (f"general coach turn {location}: {first['msg']}",)
    lowered = turn.message.lower()
    if any(marker in lowered for marker in _CLAIMS):
        return ("the coach cannot claim to have recorded, scheduled or changed anything",)
    return ()


def render_general_prompt(request: GeneralCoachRequest) -> str:
    lines = [f"Screen the learner is on: {request.screen}."]
    if request.summary:
        lines.append("What that screen shows:\n" + request.summary)
    for speaker, text in request.prior_messages:
        lines.append(f"{speaker}: {text}")
    lines.append(f"learner: {request.learner_message}")
    if request.repair_errors:
        lines.append(
            "Your previous answer was refused; fix these:\n"
            + "\n".join(f"- {e}" for e in request.repair_errors)
        )
    return "\n\n".join(lines)


@dataclass
class _RuntimeAdapter:
    transport: GeneralCoachTransport
    request: GeneralCoachRequest

    async def invoke(
        self, run: PreparedAgentRun, *, repair_errors: tuple[str, ...] = ()
    ) -> TransportResult:
        del run
        request = replace(self.request, repair_errors=repair_errors)
        return TransportResult(payload=await self.transport.general_reply(request), turns=1)


class GeneralCoachService:
    def __init__(self, transport: GeneralCoachTransport | None, *, model: str) -> None:
        self._transport = transport
        self._model = model

    async def reply(self, request: GeneralCoachRequest) -> GeneralCoachTurn:
        """One general turn, or a contract error the caller renders as such."""
        prepare_role_prompt(AgentRole.COACH, committed=False, requested_context=(SCREEN_CONTEXT,))
        if self._transport is None:
            raise CoachUnavailable("the coach needs Claude enabled on the server")
        runtime = BoundedClaudeRuntime(
            _RuntimeAdapter(self._transport, request), validate=validate_general_turn
        )
        digest = hashlib.sha256(
            f"{request.screen}:{len(request.prior_messages)}:{request.learner_message}".encode()
        ).hexdigest()[:24]
        prepared = PreparedAgentRun(
            run_key=f"general-coach:{digest}",
            job_type=COACH_JOB_TYPE,
            model=self._model,
            schema_id=GENERAL_COACH_SCHEMA_ID,
            prompt_version="v1",
            max_turns=COACH_MAX_TURNS,
            wall_time_seconds=COACH_WALL_TIME_SECONDS,
        )
        try:
            result = await runtime.run(prepared)
        except AgentOutputInvalid:
            raise CoachUnavailable("the coach did not return a valid turn") from None
        except AgentRuntimeError as exc:
            raise CoachUnavailable(str(exc)) from None
        return GeneralCoachTurn.model_validate(result.payload)


__all__ = [
    "GENERAL_COACH_SCHEMA_ID",
    "GeneralCoachRequest",
    "GeneralCoachService",
    "GeneralCoachTransport",
    "GeneralCoachTurn",
    "general_coach_schema",
    "render_general_prompt",
    "validate_general_turn",
]
