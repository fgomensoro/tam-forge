"""The practice review role: three dimensions, half points, verbatim quotes, no claims."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest
from tamforge_backend.agents.roles.contracts import RoleContractError
from tamforge_backend.agents.roles.practice_review import (
    FOLLOW_UP_DIMENSION,
    PRACTICE_DIMENSIONS,
    PRACTICE_REVIEW_PROMPT_VERSION,
    PRACTICE_REVIEW_SCHEMA_ID,
    PracticeReviewOutcome,
    PracticeReviewRequest,
    PracticeReviewService,
    PracticeReviewUnavailable,
    dimensions_for,
    render_practice_review_prompt,
    validate_practice_review,
)

QUESTION = "Why are you leaving DataNest?"
ANSWER = (
    "I spent four years building DataNest from zero to twenty five customers and I loved "
    "the customer side. I hit the ceiling of what I can learn there, so I want to do it at scale."
)
REFERENCE = "Four anchors: four years, alone, ceiling, scale."


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "dimensions": [
            {
                "slug": "answer_clarity",
                "score": "3.0",
                "evidence": "I hit the ceiling of what I can learn there",
                "note": "Four clear sentences.",
            },
            {
                "slug": "technical_examples",
                "score": "2.0",
                "evidence": "from zero to twenty five customers",
                "note": "One number, no example of a process built.",
            },
            {
                "slug": "english_accuracy",
                "score": "3.5",
                "evidence": "I loved the customer side",
                "note": "Accurate simple past.",
            },
        ],
        "strengths": ["Opens with the four years and the number."],
        "fixes": [
            {
                "heard": "I want to do it at scale",
                "say_instead": "I want to do it at real scale, with a team I can learn from",
                "why": "The reference answer ends on the team.",
            }
        ],
        "reference_coverage": "The 'alone' anchor is missing.",
        "readiness": "drilling",
    }
    base.update(overrides)
    return base


def _request(**overrides: object) -> PracticeReviewRequest:
    values: dict[str, object] = {
        "question": QUESTION,
        "answer_transcript": ANSWER,
        "reference_answer": REFERENCE,
        "speech_metrics": {"speech_rate_wpm": 131},
    }
    values.update(overrides)
    return PracticeReviewRequest(**values)  # type: ignore[arg-type]


def test_a_quoted_half_point_review_of_the_three_dimensions_passes() -> None:
    assert [slug for slug, _ in PRACTICE_DIMENSIONS] == [
        "answer_clarity",
        "technical_examples",
        "english_accuracy",
    ]
    assert validate_practice_review(_payload(), answer_transcript=ANSWER) == ()


def test_missing_dimensions_quarter_points_invented_quotes_and_claims_are_refused() -> None:
    two = _payload(dimensions=_payload()["dimensions"][:2])  # type: ignore[index]
    assert "exactly" in validate_practice_review(two, answer_transcript=ANSWER)[0]
    dims = [dict(d) for d in _payload()["dimensions"]]  # type: ignore[union-attr]
    dims[0]["score"] = "2.75"
    assert (
        "half points"
        in validate_practice_review(_payload(dimensions=dims), answer_transcript=ANSWER)[0]
    )
    dims = [dict(d) for d in _payload()["dimensions"]]  # type: ignore[union-attr]
    dims[1]["evidence"] = "we saved forty thousand dollars"
    assert (
        "verbatim"
        in validate_practice_review(_payload(dimensions=dims), answer_transcript=ANSWER)[0]
    )
    invented_fix = _payload(
        fixes=[{"heard": "I was fired", "say_instead": "I resigned", "why": "accuracy"}]
    )
    assert "heard" in validate_practice_review(invented_fix, answer_transcript=ANSWER)[0]
    claimed = _payload(reference_coverage="I recorded this as READY in your answer bank.")
    assert "cannot claim" in validate_practice_review(claimed, answer_transcript=ANSWER)[0]
    assert validate_practice_review(_payload(readiness="perfect"), answer_transcript=ANSWER)[
        0
    ].startswith("review ")


def test_the_prompt_carries_the_question_the_answer_and_the_unverified_reference() -> None:
    prompt = render_practice_review_prompt(_request(repair_errors=("score in half points",)))
    assert "Question asked: Why are you leaving DataNest?" in prompt
    assert ANSWER in prompt
    assert "The learner's own reference answer (what they intended to say, not evidence" in prompt
    assert "- speech_rate_wpm: 131" in prompt
    assert "fix these:" in prompt
    without = render_practice_review_prompt(_request(reference_answer=""))
    assert "what they intended to say" not in without


class _Transport:
    def __init__(self, payloads: list[Mapping[str, object]]) -> None:
        self.payloads = payloads
        self.requests: list[PracticeReviewRequest] = []

    async def review_practice(self, request: PracticeReviewRequest) -> Mapping[str, object]:
        self.requests.append(request)
        return self.payloads.pop(0)


def test_the_service_repairs_once_refuses_short_answers_and_needs_claude() -> None:
    bad = _payload(readiness="perfect")
    transport = _Transport([bad, _payload()])
    service = PracticeReviewService(transport, model="claude-fable-5-1")
    outcome = asyncio.run(service.review(_request()))
    assert outcome.readiness == "drilling"
    assert len(transport.requests) == 2 and transport.requests[1].repair_errors

    with pytest.raises(RoleContractError):
        asyncio.run(service.review(_request(answer_transcript="Yes. No.")))
    with pytest.raises(PracticeReviewUnavailable):
        asyncio.run(PracticeReviewService(None, model="m").review(_request()))


FOLLOW_UP_ANSWER = (
    "I changed the weekly meeting into a daily checkpoint and the customer renewed for two "
    "years after that"
)


def _follow_up_payload(*, handled: bool) -> dict[str, object]:
    dimensions: list[dict[str, str]] = [
        {
            "slug": "answer_clarity",
            "score": "3.0",
            "evidence": "I changed the weekly meeting",
            "note": "One change, stated first.",
        },
        {
            "slug": "technical_examples",
            "score": "2.5",
            "evidence": "a daily checkpoint",
            "note": "Concrete, no number.",
        },
        {
            "slug": "english_accuracy",
            "score": "3.5",
            "evidence": "the customer renewed for two years",
            "note": "Accurate simple past.",
        },
    ]
    if handled:
        dimensions.append(
            {
                "slug": "follow_up_handling",
                "score": "3.0",
                "evidence": "renewed for two years after that",
                "note": "Answers what was asked and adds the outcome.",
            }
        )
    return _payload(
        dimensions=dimensions,
        fixes=[
            {
                "heard": "after that",
                "say_instead": "within the quarter",
                "why": "A date makes the outcome checkable.",
            }
        ],
    )


def test_an_answer_to_a_follow_up_is_also_scored_on_how_it_was_handled() -> None:
    assert FOLLOW_UP_DIMENSION[0] == "follow_up_handling"
    assert dimensions_for(follow_up=False) == PRACTICE_DIMENSIONS
    assert dimensions_for(follow_up=True) == (*PRACTICE_DIMENSIONS, FOLLOW_UP_DIMENSION)
    assert PRACTICE_REVIEW_PROMPT_VERSION == "v2"
    assert PRACTICE_REVIEW_SCHEMA_ID == "urn:tamforge:schema:practice-review-v2"

    four = _follow_up_payload(handled=True)
    three = _follow_up_payload(handled=False)
    assert validate_practice_review(four, answer_transcript=FOLLOW_UP_ANSWER, follow_up=True) == ()
    missing = validate_practice_review(three, answer_transcript=FOLLOW_UP_ANSWER, follow_up=True)
    assert "follow_up_handling" in missing[0]
    # Without a follow-up the review is exactly what it was: three dimensions, no fourth.
    assert validate_practice_review(three, answer_transcript=FOLLOW_UP_ANSWER) == ()
    unexpected = validate_practice_review(four, answer_transcript=FOLLOW_UP_ANSWER)
    assert "exactly" in unexpected[0] and "follow_up_handling" not in unexpected[0]
    # A stored v1 outcome still loads.
    assert PracticeReviewOutcome.model_validate(_payload()).readiness == "drilling"


def test_the_follow_up_prompt_carries_the_earlier_exchange_as_context_only() -> None:
    request = _request(
        answer_transcript=FOLLOW_UP_ANSWER,
        follow_up_question="What exactly did you change?",
        parent_question="Tell me about a difficult customer.",
        parent_transcript="I had an unhappy customer and I improved things.",
    )
    assert request.is_follow_up and not _request().is_follow_up
    prompt = render_practice_review_prompt(request)
    assert "Earlier question: Tell me about a difficult customer." in prompt
    assert "context only, never quote it as evidence" in prompt
    assert "Follow-up the interviewer then asked: What exactly did you change?" in prompt
    assert "- follow_up_handling:" in prompt
    assert "- follow_up_handling:" not in render_practice_review_prompt(_request())


def test_the_service_holds_a_follow_up_review_to_four_dimensions() -> None:
    request = _request(
        answer_transcript=FOLLOW_UP_ANSWER,
        follow_up_question="What exactly did you change?",
        parent_question=QUESTION,
        parent_transcript=ANSWER,
    )
    transport = _Transport([_follow_up_payload(handled=False), _follow_up_payload(handled=True)])
    outcome = asyncio.run(PracticeReviewService(transport, model="m").review(request))
    assert [d.slug for d in outcome.dimensions][-1] == "follow_up_handling"
    assert "follow_up_handling" in transport.requests[1].repair_errors[0]
    assert transport.requests[1].parent_transcript == ANSWER
