"""A registry with two tools and a recording audit sink."""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel, ConfigDict, Field
from tamforge_backend.agents.tools import AgentRole, ToolContext, ToolRegistry, ToolSpec


class SearchEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    skill: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 10
    context_ordinals: tuple[Annotated[int, Field(strict=True, ge=0, le=63)], ...] = ()


class ProposeMemory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    statement: Annotated[str, Field(min_length=1, max_length=512)]


class RecordingSink:
    def __init__(self) -> None:
        self.records: list[object] = []

    async def record(self, audit: object) -> None:
        self.records.append(audit)

    def phases(self) -> list[str]:
        return [entry.phase for entry in self.records]  # type: ignore[attr-defined]


@pytest.fixture
def sink() -> RecordingSink:
    return RecordingSink()


@pytest.fixture
def handled() -> list[tuple[object, ToolContext]]:
    return []


@pytest.fixture
def registry(sink: RecordingSink, handled: list) -> ToolRegistry:
    async def search(payload, context):
        handled.append((payload, context))
        return {"rows": []}

    async def propose(payload, context):
        handled.append((payload, context))
        return {"accepted": True}

    built = ToolRegistry(audit=sink)
    built.register(
        ToolSpec(
            name="search_evidence",
            version="v1",
            roles=frozenset({AgentRole.REVIEWER, AgentRole.ANALYST}),
            schema=SearchEvidence,
            handler=search,
        )
    )
    built.register(
        ToolSpec(
            name="propose_memory_candidate",
            version="v1",
            roles=frozenset({AgentRole.ANALYST}),
            schema=ProposeMemory,
            handler=propose,
        )
    )
    return built


@pytest.fixture
def context() -> ToolContext:
    return ToolContext(owner_id=1, activity_id=7, allowed_context_ordinals=frozenset({0, 1, 2}))
