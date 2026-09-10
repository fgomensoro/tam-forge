"""Role-authorized typed tools, and nothing an agent can reach around them.

An agent has no shell, no network client and no filesystem. It has this registry, and
the registry dispatches only to handlers registered in this process under a name and a
typed input schema. A name nobody registered does not resolve to anything, which is why
`bash`, `fetch` and `read_file` are refusals rather than capabilities: there is no
mechanism here that could run one.

Every call to a registered tool is checked in a fixed order and audited whatever the
outcome. Authorization comes before validation, and validation before the handler, so a
tool a role may not use never sees its arguments and a malformed call never reaches
code. Context is checked last and separately: a role may be allowed a tool in general
and still not be allowed the rows this call asks for.

`ToolNotFound` is the one refusal that is not audited. `ToolAudit` pins a tool's version
and the hash of its input schema, and an unregistered name has neither; recording a
placeholder for both would put a fiction in the audit trail. The caller logs that
refusal through the observability layer, where it belongs.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from ..contracts import Failure, ToolAudit

# The maximum number of rows any tool may be asked for. A tool that wants more is a
# tool that would let one call read the whole workspace into a prompt.
MAX_ITEM_LIMIT = 200


class AgentRole(StrEnum):
    PLANNER = "planner"
    TUTOR = "tutor"
    COACH = "coach"
    REVIEWER = "reviewer"
    ANALYST = "analyst"
    INTERVIEWER = "interviewer"


class ToolError(Exception):
    """A tool call was refused. The message names no argument value."""


class ToolNotFound(ToolError):
    """No tool is registered under that name, so nothing ran."""


class ToolNotAuthorized(ToolError):
    """The active role may not use this tool."""


class ToolInputInvalid(ToolError):
    """The arguments did not satisfy the tool's typed schema."""


class ToolContextForbidden(ToolError):
    """The call asked for context this run was not granted."""


class ToolFailed(ToolError):
    """The handler itself failed. Its own message never reaches the caller."""


@dataclass(frozen=True, slots=True)
class ToolContext:
    """What one run is allowed to touch, decided before the agent starts."""

    owner_id: int
    activity_id: int
    allowed_context_ordinals: frozenset[int] = frozenset()
    opportunity_id: int | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One tool: its name, its typed input, who may call it, and what runs."""

    name: str
    version: str
    roles: frozenset[AgentRole]
    schema: type[BaseModel]
    handler: Callable[[Any, ToolContext], Awaitable[object]]
    schema_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.roles:
            raise ValueError("a tool nobody may call should not be registered")
        encoded = json.dumps(self.schema.model_json_schema(), sort_keys=True).encode("utf-8")
        object.__setattr__(self, "schema_hash", sha256(encoded).hexdigest())


class ToolAuditSink(Protocol):
    async def record(self, audit: ToolAudit) -> None: ...


def _requested_ordinals(payload: BaseModel) -> frozenset[int]:
    ordinals = getattr(payload, "context_ordinals", ())
    return frozenset(ordinals)


def _requested_limit(payload: BaseModel) -> int | None:
    limit = getattr(payload, "limit", None)
    return limit if isinstance(limit, int) else None


class ToolRegistry:
    def __init__(
        self, *, audit: ToolAuditSink, monotonic: Callable[[], float] = time.monotonic
    ) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._audit = audit
        self._monotonic = monotonic

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError("a tool name is registered once")
        self._specs[spec.name] = spec

    def authorized(self, role: AgentRole) -> tuple[str, ...]:
        """Exactly the tools this role may call, which is what a prompt should list."""
        return tuple(sorted(name for name, spec in self._specs.items() if role in spec.roles))

    async def call(
        self,
        role: AgentRole,
        name: str,
        arguments: Mapping[str, object],
        *,
        context: ToolContext,
    ) -> object:
        spec = self._specs.get(name)
        if spec is None:
            raise ToolNotFound("no tool is registered under that name")

        call_key = uuid4().hex
        started = self._monotonic()
        await self._record(spec, call_key, "request", started, ())
        try:
            payload = self._prepare(spec, role, arguments, context)
            result = await spec.handler(payload, context)
        except ToolError as refusal:
            await self._record(spec, call_key, "failed", started, (), _category(refusal))
            raise
        except Exception:
            # The handler's message can quote rows it was reading, so it stops here.
            await self._record(spec, call_key, "failed", started, (), "processing_failure")
            raise ToolFailed("the tool handler failed") from None
        await self._record(
            spec, call_key, "succeeded", started, tuple(_requested_ordinals(payload))
        )
        return result

    def _prepare(
        self,
        spec: ToolSpec,
        role: AgentRole,
        arguments: Mapping[str, object],
        context: ToolContext,
    ) -> BaseModel:
        if role not in spec.roles:
            raise ToolNotAuthorized("this role may not use this tool")
        try:
            payload = spec.schema.model_validate(dict(arguments))
        except ValidationError:
            # Deliberately not the pydantic message: it echoes the rejected values.
            raise ToolInputInvalid("arguments did not satisfy the tool schema") from None
        limit = _requested_limit(payload)
        if limit is not None and limit > MAX_ITEM_LIMIT:
            raise ToolInputInvalid("requested more items than any tool may return")
        requested = _requested_ordinals(payload)
        if not requested <= context.allowed_context_ordinals:
            raise ToolContextForbidden("the call asked for context this run was not granted")
        return payload

    async def _record(
        self,
        spec: ToolSpec,
        call_key: str,
        phase: str,
        started: float,
        ordinals: tuple[int, ...],
        error_category: Failure | None = None,
    ) -> None:
        await self._audit.record(
            ToolAudit(
                call_key=call_key,
                phase=phase,  # type: ignore[arg-type]
                tool_name=spec.name,
                tool_version=spec.version,
                schema_hash=spec.schema_hash,
                elapsed_ms=max(0, int((self._monotonic() - started) * 1000)),
                context_ordinals=ordinals,
                error_category=error_category,
            )
        )


def _category(refusal: ToolError) -> Failure:
    if isinstance(refusal, ToolInputInvalid):
        return "invalid_input"
    if isinstance(refusal, (ToolNotAuthorized, ToolContextForbidden)):
        return "permission_required"
    return "processing_failure"


__all__ = [
    "MAX_ITEM_LIMIT",
    "AgentRole",
    "ToolAuditSink",
    "ToolContext",
    "ToolContextForbidden",
    "ToolError",
    "ToolFailed",
    "ToolInputInvalid",
    "ToolNotAuthorized",
    "ToolNotFound",
    "ToolRegistry",
    "ToolSpec",
]
