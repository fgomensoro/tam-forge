from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import pytest
from tamforge_backend.agents.roles.coach import CoachUnavailable
from tamforge_backend.agents.roles.general_coach import (
    GeneralCoachRequest,
    GeneralCoachService,
    render_general_prompt,
    validate_general_turn,
)

REQUEST = GeneralCoachRequest(
    screen="Today",
    summary="- block A (ready)\n- block B (done)",
    learner_message="que hago ahora?",
    prior_messages=(("learner", "hola"), ("coach", "Hola, en que te ayudo?")),
)


class FakeTransport:
    def __init__(self, payloads: list[Mapping[str, object]]) -> None:
        self.payloads = list(payloads)
        self.requests: list[GeneralCoachRequest] = []

    async def general_reply(self, request: GeneralCoachRequest) -> Mapping[str, object]:
        self.requests.append(request)
        return self.payloads.pop(0)


def test_a_message_alone_is_a_valid_turn() -> None:
    assert validate_general_turn({"message": "ok"}) == ()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": ""},
        {"message": "x" * 2001},
        {"message": "ok", "next_step": "no"},
        {"message": "I recorded your answer"},
        {"message": "Listo, I changed your plan for tomorrow."},
    ],
    ids=["missing", "empty", "too-long", "extra-field", "recorded-claim", "plan-claim"],
)
def test_a_malformed_or_claiming_turn_is_refused(payload: Mapping[str, object]) -> None:
    assert validate_general_turn(payload) != ()


def test_the_prompt_carries_the_screen_the_summary_the_thread_and_the_message() -> None:
    prompt = render_general_prompt(REQUEST)

    assert "Screen the learner is on: Today." in prompt
    assert "- block A (ready)\n- block B (done)" in prompt
    assert "learner: hola" in prompt and "coach: Hola, en que te ayudo?" in prompt
    assert prompt.endswith("learner: que hago ahora?")


def test_the_prompt_leaves_out_an_empty_summary_and_lists_repair_errors() -> None:
    prompt = render_general_prompt(replace(REQUEST, summary="", repair_errors=("too long",)))

    assert "What that screen shows" not in prompt
    assert prompt.endswith("Your previous answer was refused; fix these:\n- too long")


@pytest.mark.anyio
async def test_without_a_transport_the_coach_is_unavailable() -> None:
    with pytest.raises(CoachUnavailable):
        await GeneralCoachService(None, model="m").reply(REQUEST)


@pytest.mark.anyio
async def test_a_transport_turn_comes_back_validated() -> None:
    transport = FakeTransport([{"message": "Empeza por el bloque A."}])

    turn = await GeneralCoachService(transport, model="m").reply(REQUEST)

    assert turn.message == "Empeza por el bloque A."
    assert transport.requests == [REQUEST]


@pytest.mark.anyio
async def test_a_refused_turn_is_repaired_once_then_given_up() -> None:
    transport = FakeTransport([{"message": "I scheduled it."}, {"message": "Hacelo mañana."}])

    turn = await GeneralCoachService(transport, model="m").reply(REQUEST)

    assert turn.message == "Hacelo mañana."
    assert transport.requests[1].repair_errors != ()

    stubborn = FakeTransport([{"message": "I marked it done."}] * 2)
    with pytest.raises(CoachUnavailable):
        await GeneralCoachService(stubborn, model="m").reply(REQUEST)
