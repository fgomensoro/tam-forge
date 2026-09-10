"""The role matrix, the typed input, and the audit trail every call leaves."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel, ConfigDict
from tamforge_backend.agents.tools import (
    AgentRole,
    ToolInputInvalid,
    ToolNotAuthorized,
    ToolNotFound,
    ToolRegistry,
    ToolSpec,
)
from tamforge_backend.agents.tools.registry import MAX_ITEM_LIMIT, ToolFailed


def call(registry, context, role, name, arguments):
    return asyncio.run(registry.call(role, name, arguments, context=context))


def test_an_authorized_role_reaches_the_handler(registry, context, handled) -> None:
    result = call(registry, context, AgentRole.REVIEWER, "search_evidence", {"skill": "sql"})

    assert result == {"rows": []}
    assert handled[0][0].skill == "sql"
    assert handled[0][1].owner_id == 1


@pytest.mark.parametrize(
    "role,name",
    [
        (AgentRole.INTERVIEWER, "search_evidence"),
        (AgentRole.COACH, "propose_memory_candidate"),
        (AgentRole.REVIEWER, "propose_memory_candidate"),
        (AgentRole.PLANNER, "search_evidence"),
    ],
)
def test_a_forbidden_role_and_tool_pair_never_reaches_the_handler(
    registry, context, handled, role, name
) -> None:
    with pytest.raises(ToolNotAuthorized):
        call(registry, context, role, name, {"skill": "sql", "statement": "x"})
    assert handled == []


def test_the_role_matrix_is_what_a_prompt_should_list(registry) -> None:
    assert registry.authorized(AgentRole.ANALYST) == (
        "propose_memory_candidate",
        "search_evidence",
    )
    assert registry.authorized(AgentRole.REVIEWER) == ("search_evidence",)
    assert registry.authorized(AgentRole.INTERVIEWER) == ()


@pytest.mark.parametrize("name", ["bash", "fetch", "read_file", "run_sql", "http.request"])
def test_there_is_no_shell_network_or_filesystem_tool_to_call(
    registry, context, handled, name
) -> None:
    # Nothing is registered under these names, so they resolve to nothing at all.
    with pytest.raises(ToolNotFound):
        call(registry, context, AgentRole.ANALYST, name, {})
    assert handled == []


def test_arguments_that_miss_the_schema_never_reach_the_handler(
    registry, context, handled
) -> None:
    for arguments in ({}, {"skill": "NOT A SLUG"}, {"skill": "sql", "extra": 1}):
        with pytest.raises(ToolInputInvalid):
            call(registry, context, AgentRole.ANALYST, "search_evidence", arguments)
    assert handled == []


def test_a_rejection_never_quotes_the_value_it_rejected(registry, context) -> None:
    secret = "a-value-that-must-not-be-echoed"
    with pytest.raises(ToolInputInvalid) as raised:
        call(registry, context, AgentRole.ANALYST, "search_evidence", {"skill": secret})

    assert secret not in str(raised.value)


def test_an_unbounded_limit_is_refused(registry, context, handled) -> None:
    assert MAX_ITEM_LIMIT == 200
    assert call(
        registry, context, AgentRole.ANALYST, "search_evidence", {"skill": "sql", "limit": 200}
    )
    with pytest.raises(ToolInputInvalid):
        call(
            registry,
            context,
            AgentRole.ANALYST,
            "search_evidence",
            {"skill": "sql", "limit": 201},
        )
    assert len(handled) == 1


def test_every_call_to_a_registered_tool_is_audited(registry, context, sink) -> None:
    call(registry, context, AgentRole.ANALYST, "search_evidence", {"skill": "sql"})
    assert sink.phases() == ["request", "succeeded"]

    with pytest.raises(ToolNotAuthorized):
        call(registry, context, AgentRole.INTERVIEWER, "search_evidence", {"skill": "sql"})
    assert sink.phases() == ["request", "succeeded", "request", "failed"]
    assert sink.records[-1].error_category == "permission_required"
    assert sink.records[-1].tool_name == "search_evidence"
    assert sink.records[-1].schema_hash == sink.records[0].schema_hash


class NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


async def _unused(payload: object, ctx: object) -> None:
    return None


def test_a_tool_name_is_registered_once(registry) -> None:
    with pytest.raises(ValueError):
        registry.register(
            ToolSpec(
                name="search_evidence",
                version="v2",
                roles=frozenset({AgentRole.ANALYST}),
                schema=NoArguments,
                handler=_unused,
            )
        )


def test_a_tool_nobody_may_call_is_not_registered() -> None:
    with pytest.raises(ValueError):
        ToolSpec(
            name="orphan",
            version="v1",
            roles=frozenset(),
            schema=NoArguments,
            handler=_unused,
        )


def test_a_failing_handler_is_audited_without_its_message(sink, context) -> None:
    async def explode(payload, ctx):
        raise RuntimeError("row contents that must not travel")

    built = ToolRegistry(audit=sink)
    built.register(
        ToolSpec(
            name="explodes",
            version="v1",
            roles=frozenset({AgentRole.ANALYST}),
            schema=NoArguments,
            handler=explode,
        )
    )

    with pytest.raises(ToolFailed) as raised:
        asyncio.run(built.call(AgentRole.ANALYST, "explodes", {}, context=context))

    assert "row contents" not in str(raised.value)
    assert sink.phases() == ["request", "failed"]
    assert sink.records[-1].error_category == "processing_failure"
