"""What a call may reach, and what it may not, whatever the arguments say."""

from __future__ import annotations

import asyncio

import pytest
from tamforge_backend.agents.tools import (
    AgentRole,
    ToolContext,
    ToolContextForbidden,
    ToolInputInvalid,
)


def call(registry, context, arguments, role=AgentRole.ANALYST, name="search_evidence"):
    return asyncio.run(registry.call(role, name, arguments, context=context))


def test_a_call_stays_inside_the_context_this_run_was_granted(
    registry, context, handled
) -> None:
    assert call(registry, context, {"skill": "sql", "context_ordinals": (0, 2)})
    assert handled[0][0].context_ordinals == (0, 2)


def test_context_outside_the_grant_is_refused_before_the_handler(
    registry, context, handled
) -> None:
    with pytest.raises(ToolContextForbidden):
        call(registry, context, {"skill": "sql", "context_ordinals": (0, 9)})
    assert handled == []


def test_a_run_granted_nothing_reaches_nothing(registry, handled) -> None:
    empty = ToolContext(owner_id=1, activity_id=7)

    with pytest.raises(ToolContextForbidden):
        call(registry, empty, {"skill": "sql", "context_ordinals": (0,)})
    assert handled == []
    # A call that asks for no context at all is still fine.
    assert call(registry, empty, {"skill": "sql"})


def test_the_owner_and_activity_come_from_the_context_not_the_arguments(
    registry, context, handled
) -> None:
    # There is no argument that can move a call to another owner: the schema forbids
    # the field, and the handler is handed the context the run was started with.
    with pytest.raises(ToolInputInvalid):
        call(registry, context, {"skill": "sql", "owner_id": 2})

    assert call(registry, context, {"skill": "sql"})
    assert handled[0][1].owner_id == 1 and handled[0][1].activity_id == 7


@pytest.mark.parametrize(
    "injected",
    [
        "sql'; drop table evidence; --",
        "../../etc/passwd",
        "https://example.invalid/exfiltrate",
        "sql\nAND 1=1",
    ],
)
def test_argument_text_shaped_like_an_attack_is_just_an_invalid_argument(
    registry, context, handled, injected
) -> None:
    # The point is not that these strings are recognised. It is that the typed schema
    # admits a slug and nothing else, so there is no path where they mean anything.
    with pytest.raises(ToolInputInvalid):
        call(registry, context, {"skill": injected})
    assert handled == []


def test_the_audit_records_which_context_a_successful_call_read(
    registry, context, sink
) -> None:
    call(registry, context, {"skill": "sql", "context_ordinals": (1, 2)})

    assert sink.records[-1].phase == "succeeded"
    assert sorted(sink.records[-1].context_ordinals) == [1, 2]
