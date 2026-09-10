"""HTTP contract for the gated feedback read."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import APPROVED_GITHUB_USER_ID, Settings
from tamforge_backend.main import create_app
from tamforge_protocol.agents import FeedbackRead

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=APPROVED_GITHUB_USER_ID,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


class StubFeedbackRepository:
    def __init__(self, read: FeedbackRead | None = None) -> None:
        self.read = read or FeedbackRead(status="processing", activity_id=7, attempt_id=9)
        self.calls: list[tuple[int, int, int]] = []

    async def feedback(self, *, owner_id: int, activity_id: int, attempt_id: int) -> FeedbackRead:
        self.calls.append((owner_id, activity_id, attempt_id))
        return self.read


def client(repository):
    from tamforge_backend.analysis.routes import get_feedback_repository

    app = create_app(
        Settings(
            environment="test",
            github_user_id=APPROVED_GITHUB_USER_ID,
            secure_cookies=False,
            _env_file=None,
        )
    )
    app.dependency_overrides[get_feedback_repository] = lambda: repository
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    return TestClient(app)


def test_processing_feedback_carries_no_analysis():
    repository = StubFeedbackRepository()
    response = client(repository).get("/api/v1/activities/7/attempts/9/feedback")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["english"] is None and body["tam"] is None
    assert repository.calls == [(1, 7, 9)]


def test_withheld_feedback_reports_only_a_closed_reason():
    repository = StubFeedbackRepository(
        FeedbackRead(
            status="needs_attention",
            activity_id=7,
            attempt_id=9,
            withheld_reason="self_review_pending",
        )
    )
    body = client(repository).get("/api/v1/activities/7/attempts/9/feedback").json()
    assert body["withheld_reason"] == "self_review_pending"
    assert body["english"] is None and body["tam"] is None


def released_feedback() -> FeedbackRead:
    """A ready read, so the one path that actually hands over analysis is exercised."""
    from tamforge_protocol.agents import (
        AnalysisVersions,
        EnglishAnalysisV1,
        PinnedRecord,
        TAMAnalysisV1,
    )

    unscored = {
        "availability": "not_applicable",
        "score": None,
        "reason_code": "not_exercised",
        "explanation": "This dimension was not exercised.",
    }
    scored = {
        "availability": "scored",
        "score": 3,
        "rationale": "Supported by prepared text.",
        "observations": [
            {
                "statement": "The answer named the customer impact.",
                "attribution": "observed_content",
                "availability": "available",
                "confidence": "0.8",
                "references": [
                    {
                        "kind": "attempt_text",
                        "attempt_id": 9,
                        "commitment_sha256": "a" * 64,
                        "json_pointer": "/output/draft_markdown",
                        "start_codepoint": 0,
                        "end_codepoint": 4,
                    }
                ],
            }
        ],
    }
    common = {
        "activity_id": 7,
        "attempt_id": 9,
        "config_version_key": "seed-v1",
        "rubric_slug": "tam_case",
        "rubric_version": "seed-v1",
    }
    english = EnglishAnalysisV1.model_validate(
        {
            "analysis_kind": "english_analysis",
            "schema_version": "english-analysis-v1",
            "source_mode": "written",
            **common,
            "dimensions": {
                "communication_effectiveness": scored,
                "accuracy": unscored,
                "vocabulary": unscored,
                "fluency": {
                    "availability": "unavailable",
                    "score": None,
                    "reason_code": "speech_pipeline_unavailable",
                    "explanation": "Speech pipeline is not installed.",
                },
                "pronunciation_intelligibility": {
                    "availability": "unavailable",
                    "score": None,
                    "reason_code": "pronunciation_not_measured",
                    "explanation": "Calibrated diagnostic did not run.",
                },
                "listening": {
                    "availability": "not_applicable",
                    "score": None,
                    "reason_code": "written_source",
                    "explanation": "Written submission has no listening evidence.",
                },
            },
        }
    )
    tam_keys = (
        "structure",
        "relevance",
        "customer_judgment",
        "technical_reasoning",
        "business_framing",
        "trade_offs",
        "audience_adaptation",
        "decision_quality",
    )
    tam = TAMAnalysisV1.model_validate(
        {
            "analysis_kind": "tam_analysis",
            "schema_version": "tam-analysis-v1",
            **common,
            "dimensions": {"correctness": scored, **{key: unscored for key in tam_keys}},
        }
    )
    pin = PinnedRecord(id=1, content_hash="a" * 64)
    return FeedbackRead(
        status="ready",
        activity_id=7,
        attempt_id=9,
        versions=AnalysisVersions(
            model_run=pin, prompt=pin, output_schema=pin, rubric_binding=pin
        ),
        english=english,
        tam=tam,
        verdict="Clear on impact, thin on the trade-off.",
        strengths=strengths(),
        corrections=corrections(),
        attempt_b={
            "instruction": "Rewrite the recommendation naming the trade-off you skipped.",
            "minutes": 10,
            "core_prompt_sha256": "a" * 64,
        },
    )


def evidence(statement: str) -> dict:
    return {
        "statement": statement,
        "attribution": "observed_content",
        "availability": "available",
        "confidence": "0.8",
        "references": [
            {
                "kind": "attempt_text",
                "attempt_id": 9,
                "commitment_sha256": "a" * 64,
                "json_pointer": "/output/draft_markdown",
                "start_codepoint": 0,
                "end_codepoint": 4,
            }
        ],
    }


def strengths() -> tuple[dict, ...]:
    return (
        {
            "statement": "Named the customer impact before the mechanism.",
            "evidence": evidence("The answer named the customer impact."),
        },
        {
            "statement": "Closed with a decision rather than a summary.",
            "evidence": evidence("The answer ended on a recommendation."),
        },
    )


def corrections() -> tuple[dict, ...]:
    return (
        {
            "statement": "The trade-off behind the recommendation was never stated.",
            "instruction": "State the cost of the option you chose in one sentence.",
            "target_skill": "trade_offs",
            "evidence": evidence("The recommendation cited no cost."),
        },
        {
            "statement": "The timeline was asserted without a basis.",
            "instruction": "Give the timeline a source or mark it as an estimate.",
            "target_skill": "business_framing",
            "evidence": evidence("The answer gave a date with no basis."),
        },
    )


def test_ready_feedback_hands_over_both_analyses_and_their_versions():
    body = client(StubFeedbackRepository(released_feedback())).get(
        "/api/v1/activities/7/attempts/9/feedback"
    ).json()
    assert body["status"] == "ready"
    assert body["withheld_reason"] is None
    assert body["english"]["analysis_kind"] == "english_analysis"
    assert body["tam"]["analysis_kind"] == "tam_analysis"
    assert body["versions"]["model_run"]["id"] == 1
    assert (
        body["english"]["dimensions"]["communication_effectiveness"]["observations"][0][
            "references"
        ][0]["attempt_id"]
        == 9
    )


def test_feedback_read_is_never_stored_by_a_cache():
    response = client(StubFeedbackRepository()).get("/api/v1/activities/7/attempts/9/feedback")
    assert response.headers["Cache-Control"] == "no-store"


def test_missing_attempt_is_a_problem_document():
    from tamforge_backend.analysis.repository import FeedbackNotFound

    class Missing(StubFeedbackRepository):
        async def feedback(self, *, owner_id, activity_id, attempt_id):
            raise FeedbackNotFound()

    response = client(Missing()).get("/api/v1/activities/7/attempts/9/feedback")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "feedback_not_found"


def test_unauthenticated_read_is_rejected():
    from tamforge_backend.analysis.routes import get_feedback_repository
    from tamforge_backend.auth.service import Unauthenticated

    def missing_owner() -> None:
        raise Unauthenticated("authentication required")

    app = create_app(
        Settings(
            environment="test",
            github_user_id=APPROVED_GITHUB_USER_ID,
            secure_cookies=False,
            _env_file=None,
        )
    )
    app.dependency_overrides[get_feedback_repository] = lambda: StubFeedbackRepository()
    app.dependency_overrides[get_authenticated_owner] = missing_owner

    # A bare TestClient never runs the app lifespan, so app.state.database/settings
    # stay unset; entering the client as a context manager triggers startup the same
    # way test_sql_execution_routes_require_an_authenticated_owner does.
    with TestClient(app) as client:
        response = client.get("/api/v1/activities/7/attempts/9/feedback")
    assert response.status_code in (401, 403)


# Issue #56's acceptance criterion, pinned to the contract and to the wire: every
# analysis observation carries evidence IDs or timestamps, confidence, availability,
# and a clear distinction between observed content, user recollection, inference, and
# unknowns. These assert the rule itself, not one fixture's good behaviour.

ATTRIBUTIONS = ("observed_content", "user_stated", "inferred", "unknown")


def _released_observations(body: dict) -> list[dict]:
    observations = []
    for analysis in ("english", "tam"):
        for dimension in body[analysis]["dimensions"].values():
            observations.extend(dimension.get("observations") or [])
    return observations


def _identifies_evidence(reference: dict) -> bool:
    """A reference locates evidence by id plus either a text range or a time range."""
    if reference["kind"] == "attempt_text":
        return bool(reference["attempt_id"]) and reference["end_codepoint"] > (
            reference["start_codepoint"]
        )
    if not (reference["artifact_id"] and reference["immutable_version"]):
        return False
    if reference["kind"] == "artifact_time":
        return reference["end_ms"] > reference["start_ms"]
    return reference["end_codepoint"] > reference["start_codepoint"]


def test_every_released_observation_reaches_the_client_fully_attributed():
    body = (
        client(StubFeedbackRepository(released_feedback()))
        .get("/api/v1/activities/7/attempts/9/feedback")
        .json()
    )
    observations = _released_observations(body)

    assert observations
    for observation in observations:
        assert observation["attribution"] in ATTRIBUTIONS
        assert observation["availability"] in ("available", "unavailable")
        assert 0 <= float(observation["confidence"]) <= 1
        assert observation["references"]
        assert all(_identifies_evidence(reference) for reference in observation["references"])


def test_the_attribution_vocabulary_separates_all_four_kinds_of_claim():
    from typing import get_args

    from tamforge_protocol.agents import AnalysisObservation

    attribution = AnalysisObservation.model_fields["attribution"].annotation
    assert get_args(attribution) == ATTRIBUTIONS


def _observation(**overrides):
    from tamforge_protocol.agents import AnalysisObservation

    data = {
        "statement": "The answer named the customer impact.",
        "attribution": "observed_content",
        "availability": "available",
        "confidence": "0.8",
        "references": [
            {
                "kind": "attempt_text",
                "attempt_id": 9,
                "commitment_sha256": "a" * 64,
                "json_pointer": "/output/draft_markdown",
                "start_codepoint": 0,
                "end_codepoint": 4,
            }
        ],
    }
    data.update(overrides)
    return AnalysisObservation.model_validate(data)


def _scored_with(observation):
    from tamforge_protocol.agents import ScoredDimension

    return ScoredDimension.model_validate(
        {
            "availability": "scored",
            "score": 3,
            "rationale": "Supported by prepared text.",
            "observations": [observation.model_dump(mode="json")],
        }
    )


def test_a_score_cannot_rest_on_an_observation_without_evidence():
    import pytest
    from pydantic import ValidationError

    for broken in (
        _observation(references=[]),
        _observation(availability="unavailable", references=[]),
        _observation(attribution="unknown"),
    ):
        with pytest.raises(ValidationError):
            _scored_with(broken)

    assert _scored_with(_observation(attribution="user_stated"))
    assert _scored_with(_observation(attribution="inferred"))


def test_confidence_outside_zero_to_one_is_not_a_confidence():
    import pytest
    from pydantic import ValidationError

    for value in ("-0.1", "1.1"):
        with pytest.raises(ValidationError):
            _observation(confidence=value)


def test_an_unassessed_dimension_names_its_reason_instead_of_scoring():
    import pytest
    from pydantic import ValidationError
    from tamforge_protocol.agents import UnassessedDimension

    unassessed = UnassessedDimension.model_validate(
        {
            "availability": "unavailable",
            "score": None,
            "reason_code": "speech_pipeline_unavailable",
            "explanation": "Speech pipeline is not installed.",
        }
    )
    assert unassessed.score is None
    assert unassessed.reason_code

    with pytest.raises(ValidationError):
        UnassessedDimension.model_validate(
            {
                "availability": "unavailable",
                "score": 3,
                "reason_code": "speech_pipeline_unavailable",
                "explanation": "Speech pipeline is not installed.",
            }
        )


def test_a_time_referenced_observation_carries_a_nonempty_span():
    import pytest
    from pydantic import ValidationError

    timed = {
        "kind": "artifact_time",
        "artifact_id": 4,
        "immutable_version": 2,
        "sha256": "b" * 64,
        "start_ms": 1_000,
        "end_ms": 4_500,
    }
    assert _scored_with(_observation(references=[timed]))
    assert _identifies_evidence(timed)

    with pytest.raises(ValidationError):
        _observation(references=[{**timed, "end_ms": 1_000}])


# Issue #57's acceptance criterion: feedback carries a short verdict, two demonstrated
# strengths, exactly two highest-impact corrections, timestamped evidence, a compact
# structure, and bounded Attempt B instructions.


def _ready(**overrides):
    base = released_feedback().model_dump(mode="json")
    base.update(overrides)
    return FeedbackRead.model_validate(base)


def test_ready_feedback_names_exactly_two_strengths_and_two_corrections():
    import pytest
    from pydantic import ValidationError
    from tamforge_protocol.agents import REQUIRED_CORRECTIONS, REQUIRED_STRENGTHS

    assert (REQUIRED_STRENGTHS, REQUIRED_CORRECTIONS) == (2, 2)
    feedback = released_feedback()
    assert len(feedback.strengths) == 2
    assert len(feedback.corrections) == 2

    for field, items in (("strengths", strengths()), ("corrections", corrections())):
        for count in (0, 1, 3):
            supply = (items * 3)[:count]
            with pytest.raises(ValidationError):
                _ready(**{field: list(supply)})


def test_the_same_point_twice_does_not_fill_the_second_slot():
    import pytest
    from pydantic import ValidationError

    first = strengths()[0]
    with pytest.raises(ValidationError):
        _ready(strengths=[first, dict(first)])

    correction = corrections()[0]
    with pytest.raises(ValidationError):
        _ready(corrections=[correction, dict(correction)])


def test_a_correction_carries_an_instruction_and_a_target_skill():
    feedback = released_feedback()
    for correction in feedback.corrections:
        assert correction.instruction.strip()
        assert correction.target_skill
        assert correction.evidence.references


def test_every_strength_and_correction_cites_available_attributed_evidence():
    import pytest
    from pydantic import ValidationError

    for field, items in (("strengths", strengths()), ("corrections", corrections())):
        for broken in ("references", "availability", "attribution"):
            first, second = ({**items[0]}, items[1])
            unusable = dict(first["evidence"])
            unusable[broken] = {
                "references": [],
                "availability": "unavailable",
                "attribution": "unknown",
            }[broken]
            if broken == "availability":
                unusable["references"] = []
            first["evidence"] = unusable
            with pytest.raises(ValidationError):
                _ready(**{field: [first, second]})


def test_the_attempt_b_instruction_stays_inside_the_next_lesson():
    import pytest
    from pydantic import ValidationError
    from tamforge_protocol.agents import ATTEMPT_B_MAX_MINUTES

    assert ATTEMPT_B_MAX_MINUTES == 10
    assert released_feedback().attempt_b.minutes <= ATTEMPT_B_MAX_MINUTES

    for minutes in (0, ATTEMPT_B_MAX_MINUTES + 1):
        with pytest.raises(ValidationError):
            _ready(
                attempt_b={
                    "instruction": "Redo the recommendation.",
                    "minutes": minutes,
                    "core_prompt_sha256": "a" * 64,
                }
            )


def test_ready_feedback_without_a_verdict_or_an_attempt_b_is_not_ready():
    import pytest
    from pydantic import ValidationError

    for field in ("verdict", "attempt_b"):
        with pytest.raises(ValidationError):
            _ready(**{field: None})


def test_withheld_feedback_carries_no_verdict_findings_or_redo():
    import pytest
    from pydantic import ValidationError

    for overrides in (
        {"verdict": "Clear on impact."},
        {"strengths": list(strengths())},
        {"corrections": list(corrections())},
        {"attempt_b": {"instruction": "Redo it.", "minutes": 5, "core_prompt_sha256": "a" * 64}},
    ):
        with pytest.raises(ValidationError):
            FeedbackRead.model_validate(
                {"status": "processing", "activity_id": 7, "attempt_id": 9, **overrides}
            )


def test_the_client_receives_the_verdict_the_findings_and_the_redo():
    body = (
        client(StubFeedbackRepository(released_feedback()))
        .get("/api/v1/activities/7/attempts/9/feedback")
        .json()
    )

    assert body["verdict"]
    assert len(body["strengths"]) == 2
    assert len(body["corrections"]) == 2
    assert body["attempt_b"]["minutes"] == 10
    assert body["corrections"][0]["evidence"]["references"][0]["attempt_id"] == 9


# Issue #58's acceptance criterion: at most two corrections enter the next lesson,
# Attempt B uses the same core prompt for no more than ten minutes, and no additional
# correction attempt is scheduled.


def test_attempt_b_runs_against_the_prompt_the_analysis_was_produced_from():
    import pytest
    from pydantic import ValidationError

    feedback = released_feedback()
    assert feedback.attempt_b.core_prompt_sha256 == feedback.versions.prompt.content_hash

    with pytest.raises(ValidationError):
        _ready(
            attempt_b={
                "instruction": "Rewrite the recommendation.",
                "minutes": 10,
                "core_prompt_sha256": "f" * 64,
            }
        )


def test_the_next_lesson_takes_the_two_corrections_the_report_named():
    from tamforge_protocol.agents import MAX_NEXT_LESSON_CORRECTIONS, REQUIRED_CORRECTIONS

    assert MAX_NEXT_LESSON_CORRECTIONS == REQUIRED_CORRECTIONS == 2
    scheduled = released_feedback().corrections
    assert len(scheduled) == MAX_NEXT_LESSON_CORRECTIONS
    assert [item.target_skill for item in scheduled] == ["trade_offs", "business_framing"]


def test_no_attempt_after_attempt_b_can_be_scheduled():
    import pytest
    from tamforge_protocol.agents import ATTEMPT_LABELS, next_attempt_label

    assert ATTEMPT_LABELS == ("attempt_a", "attempt_b")
    assert next_attempt_label([]) == "attempt_a"
    assert next_attempt_label(["attempt_a"]) == "attempt_b"

    with pytest.raises(ValueError, match="Attempt B"):
        next_attempt_label(["attempt_a", "attempt_b"])


def test_the_redo_is_never_longer_than_the_next_lesson_allows():
    from tamforge_protocol.agents import ATTEMPT_B_MAX_MINUTES

    assert released_feedback().attempt_b.minutes <= ATTEMPT_B_MAX_MINUTES == 10


# Issue #59's acceptance criterion: Attempt A and B are compared as improved, partially
# improved, or not improved using versioned evidence, and the workflow cannot create
# Attempt C.


def comparison(**overrides):
    from tamforge_protocol.agents import AttemptComparison

    data = {
        "attempt_a_id": 9,
        "attempt_b_id": 11,
        "comparator_version": "attempt-comparison-v1",
        "core_prompt_sha256": "a" * 64,
        "outcome": "improved",
        "observations": [evidence("Attempt B named the cost of the chosen option.")],
    }
    data.update(overrides)
    return AttemptComparison.model_validate(data)


def test_a_comparison_returns_one_of_exactly_three_outcomes():
    from typing import get_args

    import pytest
    from pydantic import ValidationError
    from tamforge_protocol.agents import ComparisonOutcome

    assert get_args(ComparisonOutcome) == ("improved", "partially_improved", "not_improved")
    for outcome in get_args(ComparisonOutcome):
        assert comparison(outcome=outcome).outcome == outcome

    for refused in ("regressed", "inconclusive", "demonstrated"):
        with pytest.raises(ValidationError):
            comparison(outcome=refused)


def test_a_comparison_pins_the_versions_it_judged_against():
    judged = comparison()

    assert judged.comparator_version == "attempt-comparison-v1"
    assert judged.core_prompt_sha256 == released_feedback().versions.prompt.content_hash
    assert judged.attempt_a_id != judged.attempt_b_id


def test_a_comparison_of_one_attempt_with_itself_is_not_a_comparison():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        comparison(attempt_b_id=9)


def test_an_outcome_rests_on_available_attributed_evidence():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        comparison(observations=[])
    for broken in ({"references": []}, {"attribution": "unknown"}):
        with pytest.raises(ValidationError):
            comparison(observations=[{**evidence("Attempt B improved."), **broken}])


def test_closing_a_correction_never_schedules_another_attempt():
    from tamforge_protocol.agents import close_correction, next_attempt_label

    assert close_correction(comparison(outcome="improved")) == "resolved"
    for unresolved in ("partially_improved", "not_improved"):
        assert close_correction(comparison(outcome=unresolved)) == "retrieval_queued"

    # And whatever the disposition, the attempt vocabulary still ends at Attempt B.
    import pytest

    with pytest.raises(ValueError):
        next_attempt_label(["attempt_a", "attempt_b"])


# Issue #60's acceptance criterion: an unresolved correction returns later in a
# materially different scenario and is not marked demonstrated from repetition of the
# original prompt.


def queued(**overrides):
    from tamforge_protocol.agents import QueuedRetrieval

    data = {
        "target_skill": "trade_offs",
        "source_scenario_key": "renewal_at_risk",
        "source_core_prompt_sha256": "a" * 64,
        "queued_from_attempt_b_id": 11,
    }
    data.update(overrides)
    return QueuedRetrieval.model_validate(data)


def later(**overrides):
    from tamforge_protocol.agents import TransferAttempt

    data = {
        "attempt_id": 27,
        "attempt_label": "attempt_a",
        "scenario_key": "migration_slipped",
        "core_prompt_sha256": "c" * 64,
    }
    data.update(overrides)
    return TransferAttempt.model_validate(data)


def test_an_unresolved_correction_is_queued_for_a_different_scenario():
    from tamforge_protocol.agents import close_correction, require_material_difference

    assert close_correction(comparison(outcome="not_improved")) == "retrieval_queued"
    assert require_material_difference(queued(), later()) is None


def test_repeating_the_original_prompt_cannot_demonstrate_the_correction():
    import pytest
    from tamforge_protocol.agents import TransferError, require_material_difference

    with pytest.raises(TransferError, match="prompt"):
        require_material_difference(queued(), later(core_prompt_sha256="a" * 64))


def test_repeating_the_original_scenario_cannot_demonstrate_it_either():
    import pytest
    from tamforge_protocol.agents import TransferError, require_material_difference

    with pytest.raises(TransferError, match="scenario"):
        require_material_difference(queued(), later(scenario_key="renewal_at_risk"))


def test_the_attempt_that_queued_the_correction_cannot_retire_it():
    import pytest
    from tamforge_protocol.agents import TransferError, require_material_difference

    with pytest.raises(TransferError, match="new attempt"):
        require_material_difference(queued(), later(attempt_id=11))


def test_transfer_needs_a_fresh_attempt_a_rather_than_another_redo():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        later(attempt_label="attempt_b")


# Issue #61's acceptance criterion: competency and readiness states advance only from
# independent attempts, no-AI assessments, mocks, or real-interview evidence, and retain
# the qualifying evidence link.


def test_only_the_four_approved_kinds_of_evidence_can_move_a_competency():
    from pathlib import Path

    from tamforge_backend.evidence.config_loader import load_config_bundle

    formula = load_config_bundle(Path(__file__).parents[5] / "config").formula

    assert formula.qualifying_modes == frozenset(
        {"independent_practice", "timed_assessment", "mock_interview", "real_interview"}
    )
    assert formula.qualifying_assistance == frozenset({"no_ai", "ai_after_committed_attempt"})
    assert formula.attempt_b_qualifies is False


def test_an_advanced_competency_always_names_the_evidence_that_advanced_it():
    import pytest
    from tamforge_backend.evidence.qualification import (
        CompetencyAdvance,
        CompetencyAdvanceError,
    )

    for level in ("practicing", "demonstrated"):
        assert CompetencyAdvance(level, (11,), "qualifies").qualifying_event_ids == (11,)
        with pytest.raises(CompetencyAdvanceError):
            CompetencyAdvance(level, (), "qualifies")


def test_readiness_cannot_advance_on_its_own():
    from tamforge_backend.evidence.qualification import readiness_from

    # It is derived, so there is no second place it could move from. Every reading
    # below follows from the levels and from nothing else.
    assert readiness_from({"structure": "practicing"}) == "partially_ready"
    assert readiness_from({"structure": "demonstrated"}) == "ready"
    assert readiness_from({"structure": "not_started"}) == "not_ready"
