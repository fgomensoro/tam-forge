"""A bounded, fakeable boundary around whatever actually runs a Claude job.

Everything here is deliberately ignorant of the Claude Agent SDK. `AgentTransport` is
the seam: one method, one prepared run, one raw payload back. Tests drive a fake
through it, and the concrete adapter that builds `ClaudeAgentOptions` arrives with the
ticket that can actually exercise it. Bounds, validation, the single repair and the
error vocabulary are the same either way, and they are what this module owns.

Two rules shape the rest. Output is not trusted until it validates against the pinned
schema, and a failure buys exactly one repair attempt carrying the validation errors and
no new evidence. And no exception from the transport is ever re-raised as it arrived:
its message can carry prompt text, transcript content or a credential, and everything
above this layer renders what it is given.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

# One repair, and only one. A second is a model that cannot satisfy the schema, and
# looping on it spends a personal subscription's quota to produce the same failure.
MAX_REPAIR_ATTEMPTS = 1


class AgentRuntimeError(Exception):
    """A run failed. The message is safe to log and names no prompt or transcript."""


class AgentTimeout(AgentRuntimeError):
    """The run exceeded its wall-time budget."""


class AgentTurnsExceeded(AgentRuntimeError):
    """The run reported more turns than it was allowed."""


class AgentQuotaExhausted(AgentRuntimeError):
    """The subscription quota is spent. Not retryable in a tight loop."""


class AgentAuthenticationFailed(AgentRuntimeError):
    """The credential was refused. Retrying cannot fix it."""


class AgentServiceUnavailable(AgentRuntimeError):
    """A transient failure the caller may retry within its own bound."""


class AgentOutputInvalid(AgentRuntimeError):
    """Output did not satisfy the pinned schema, and the one repair did not either."""


@dataclass(frozen=True, slots=True)
class PreparedAgentRun:
    """Everything one invocation needs, resolved before the runtime is entered."""

    run_key: str
    job_type: str
    model: str
    schema_id: str
    prompt_version: str
    max_turns: int
    # Seconds, as a float so a test can bound a run below one second without the
    # contract pretending wall time is inherently integral.
    wall_time_seconds: float

    def __post_init__(self) -> None:
        if not self.run_key.strip():
            raise AgentRuntimeError("a run needs an idempotency key")
        if self.max_turns < 1 or self.wall_time_seconds <= 0:
            raise AgentRuntimeError("turn and wall-time bounds must be positive")


@dataclass(frozen=True, slots=True)
class ValidatedAgentResult:
    """A payload that satisfied the pinned schema, and what it cost to get it."""

    run_key: str
    model: str
    schema_id: str
    payload: Mapping[str, object]
    turns: int
    repaired: bool


@dataclass(frozen=True, slots=True)
class TransportResult:
    """What a transport returns: the raw payload and the turns it took."""

    payload: Mapping[str, object]
    turns: int


class AgentTransport(Protocol):
    """The seam the real Agent SDK adapter will sit behind."""

    async def invoke(
        self, run: PreparedAgentRun, *, repair_errors: tuple[str, ...] = ()
    ) -> TransportResult: ...


Validator = Callable[[Mapping[str, object]], tuple[str, ...]]


class BoundedClaudeRuntime:
    """Runs one prepared job under its bounds and returns only validated output."""

    def __init__(self, transport: AgentTransport, *, validate: Validator) -> None:
        self._transport = transport
        self._validate = validate

    async def run(self, prepared: PreparedAgentRun) -> ValidatedAgentResult:
        try:
            async with asyncio.timeout(prepared.wall_time_seconds):
                return await self._attempt(prepared)
        except TimeoutError:
            raise AgentTimeout("the run exceeded its wall-time budget") from None

    async def _attempt(self, prepared: PreparedAgentRun) -> ValidatedAgentResult:
        errors: tuple[str, ...] = ()
        for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
            result = await self._invoke(prepared, errors)
            if result.turns > prepared.max_turns:
                raise AgentTurnsExceeded("the run used more turns than it was allowed")
            errors = tuple(self._validate(result.payload))
            if not errors:
                return ValidatedAgentResult(
                    run_key=prepared.run_key,
                    model=prepared.model,
                    schema_id=prepared.schema_id,
                    payload=result.payload,
                    turns=result.turns,
                    repaired=attempt > 0,
                )
        raise AgentOutputInvalid("output did not satisfy the pinned schema after one repair")

    async def _invoke(
        self, prepared: PreparedAgentRun, repair_errors: tuple[str, ...]
    ) -> TransportResult:
        try:
            return await self._transport.invoke(prepared, repair_errors=repair_errors)
        except (AgentRuntimeError, asyncio.CancelledError, TimeoutError):
            # Already ours, or the caller's cancellation, or the wall-time budget
            # firing inside the transport. None of the three needs translating.
            raise
        except Exception:
            # Deliberately broad and deliberately silent about the message. An SDK
            # error can carry prompt text, transcript content or the credential it
            # tried to use, and this result gets logged and rendered.
            raise AgentServiceUnavailable("the agent runtime failed to complete") from None


async def with_timeout(awaitable: Awaitable[object], seconds: float) -> object:
    """Small helper so callers bound their own work the same way this module does."""
    async with asyncio.timeout(seconds):
        return await awaitable


__all__ = [
    "MAX_REPAIR_ATTEMPTS",
    "AgentAuthenticationFailed",
    "AgentOutputInvalid",
    "AgentQuotaExhausted",
    "AgentRuntimeError",
    "AgentServiceUnavailable",
    "AgentTimeout",
    "AgentTransport",
    "AgentTurnsExceeded",
    "BoundedClaudeRuntime",
    "PreparedAgentRun",
    "TransportResult",
    "ValidatedAgentResult",
    "Validator",
    "with_timeout",
]
