"""Behavioral contracts for separate, explicitly versioned analysis domains."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from tamforge_protocol.agents import EnglishAnalysisV1, TAMAnalysisV1

ENGLISH = (
    "communication_effectiveness",
    "fluency",
    "accuracy",
    "vocabulary",
    "pronunciation_intelligibility",
    "listening",
)
TAM = (
    "correctness",
    "structure",
    "relevance",
    "customer_judgment",
    "technical_reasoning",
    "business_framing",
    "trade_offs",
    "audience_adaptation",
    "decision_quality",
)


def unavailable(reason="insufficient_evidence", availability="unavailable"):
    return dict(
        availability=availability,
        score=None,
        reason_code=reason,
        explanation="Evidence is not available.",
    )


def reference():
    return dict(
        kind="attempt_text",
        attempt_id=2,
        commitment_sha256="a" * 64,
        json_pointer="/output/draft_markdown",
        start_codepoint=0,
        end_codepoint=5,
    )


def scored(ref=None):
    return dict(
        availability="scored",
        score="3.5",
        rationale="Matches the cited rubric.",
        observations=[
            dict(
                statement="The response explains the decision.",
                attribution="observed_content",
                availability="available",
                confidence="0.8",
                references=[ref or reference()],
            )
        ],
    )


def payload(domain="english"):
    dimensions = ENGLISH if domain == "english" else TAM
    result = dict(
        analysis_kind=f"{domain}_analysis",
        schema_version=f"{domain}-analysis-v1",
        activity_id=1,
        attempt_id=2,
        config_version_key="phase-1-six-week-v1",
        rubric_slug=f"{domain}_core",
        rubric_version="v1",
        dimensions={key: unavailable() for key in dimensions},
    )
    if domain == "english":
        result["source_mode"] = "written"
        result["dimensions"]["fluency"] = unavailable("speech_pipeline_unavailable")
        result["dimensions"]["pronunciation_intelligibility"] = unavailable(
            "pronunciation_not_measured"
        )
        result["dimensions"]["listening"] = unavailable("modality_not_applicable", "not_applicable")
    return result


@pytest.mark.parametrize("model,domain", [(EnglishAnalysisV1, "english"), (TAMAnalysisV1, "tam")])
def test_valid_unavailable_and_scored_round_trip(model, domain):
    data = payload(domain)
    unavailable_result = model.model_validate(data)
    assert unavailable_result.model_dump(mode="json")["dimensions"] == data["dimensions"]
    key = "accuracy" if domain == "english" else "correctness"
    data["dimensions"][key] = scored()
    result = model.model_validate(data)
    assert model.model_validate_json(result.model_dump_json()) == result
    with pytest.raises(ValidationError):
        result.activity_id = 4


@pytest.mark.parametrize("model,domain", [(EnglishAnalysisV1, "english"), (TAMAnalysisV1, "tam")])
@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", None),
        ("analysis_kind", None),
        ("schema_version", "future-v2"),
        ("activity_id", True),
        ("attempt_id", "2"),
        ("activity_id", 0),
        ("config_version_key", "BAD VERSION"),
    ],
)
def test_required_versions_and_strict_identity(model, domain, field, value):
    data = payload(domain)
    if value is None:
        del data[field]
    else:
        data[field] = value
    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_cross_domain_missing_and_extra_dimensions_rejected():
    with pytest.raises(ValidationError):
        TAMAnalysisV1.model_validate(payload())
    with pytest.raises(ValidationError):
        EnglishAnalysisV1.model_validate(payload("tam"))
    for key, value in [("correctness", scored()), ("accent", scored()), ("asr_confidence", 0.99)]:
        data = payload()
        data["dimensions"][key] = value
        with pytest.raises(ValidationError):
            EnglishAnalysisV1.model_validate(data)
    data = payload("tam")
    del data["dimensions"]["customer_judgment"]
    with pytest.raises(ValidationError):
        TAMAnalysisV1.model_validate(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("score", -1),
        ("score", 5),
        ("score", "NaN"),
        ("score", "Infinity"),
        ("score", True),
        ("rationale", "  "),
        ("observations", []),
    ],
)
def test_scored_dimension_requires_finite_score_and_support(field, value):
    data = payload("tam")
    data["dimensions"]["correctness"] = scored()
    data["dimensions"]["correctness"][field] = value
    with pytest.raises(ValidationError):
        TAMAnalysisV1.model_validate(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("confidence", -0.1),
        ("confidence", 1.1),
        ("confidence", "NaN"),
        ("confidence", True),
        ("statement", " "),
        ("attribution", "unknown"),
        ("attribution", "measured"),
        ("availability", "unavailable"),
        ("references", []),
        ("references", [reference(), reference()]),
    ],
)
def test_observation_cannot_masquerade_as_supported_score(field, value):
    data = payload("tam")
    data["dimensions"]["correctness"] = scored()
    data["dimensions"]["correctness"]["observations"][0][field] = value
    with pytest.raises(ValidationError):
        TAMAnalysisV1.model_validate(data)


@pytest.mark.parametrize("attribution", ["user_stated", "inferred"])
def test_attribution_is_preserved(attribution):
    data = payload("tam")
    data["dimensions"]["correctness"] = scored()
    data["dimensions"]["correctness"]["observations"][0]["attribution"] = attribution
    result = TAMAnalysisV1.model_validate(data)
    assert result.dimensions.correctness.observations[0].attribution == attribution


@pytest.mark.parametrize(
    "field,value",
    [
        ("start_codepoint", -1),
        ("end_codepoint", 0),
        ("end_codepoint", 16 * 1024 * 1024 + 1),
        ("start_codepoint", True),
        ("attempt_id", 99),
        ("commitment_sha256", "A" * 64),
        ("json_pointer", "/task_context/prompt"),
        ("json_pointer", "/output"),
        ("json_pointer", "/output/bad~2"),
        ("url", "https://example.invalid/audio.wav"),
    ],
)
def test_evidence_reference_structure_and_attempt_binding(field, value):
    ref = reference()
    ref[field] = value
    data = payload("tam")
    data["dimensions"]["correctness"] = scored(ref)
    with pytest.raises(ValidationError):
        TAMAnalysisV1.model_validate(data)


def test_escaped_pointer_and_unicode_offsets_round_trip():
    ref = reference()
    ref["json_pointer"] = "/output/a~1b/~0field"
    data = payload("tam")
    data["dimensions"]["correctness"] = scored(ref)
    result = TAMAnalysisV1.model_validate(data)
    assert (
        result.model_dump(mode="json")["dimensions"]["correctness"]["observations"][0][
            "references"
        ][0]
        == ref
    )


@pytest.mark.parametrize(
    "mode,availability",
    [
        ("written", "not_applicable"),
        ("monologue_transcript", "not_applicable"),
        ("interactive_transcript", "unavailable"),
    ],
)
def test_listening_state_follows_source_mode(mode, availability):
    data = payload()
    data["source_mode"] = mode
    data["dimensions"]["listening"] = unavailable(availability=availability)
    EnglishAnalysisV1.model_validate(data)
    data["dimensions"]["listening"] = scored()
    with pytest.raises(ValidationError):
        EnglishAnalysisV1.model_validate(data)


@pytest.mark.parametrize("dimension", ["fluency", "pronunciation_intelligibility"])
def test_v1_cannot_enable_unmeasured_speech(dimension):
    data = payload()
    data["dimensions"][dimension] = scored()
    with pytest.raises(ValidationError):
        EnglishAnalysisV1.model_validate(data)
    data["dimensions"][dimension] = unavailable("invented_reason")
    with pytest.raises(ValidationError):
        EnglishAnalysisV1.model_validate(data)


@pytest.mark.parametrize("kind", ["raw_transcript", "corrected_transcript", "written", "time"])
def test_english_scoring_requires_prepared_text(kind):
    ref = dict(
        kind="artifact_text",
        artifact_id=3,
        immutable_version=1,
        sha256="b" * 64,
        text_kind=kind,
        start_codepoint=0,
        end_codepoint=5,
    )
    if kind == "time":
        ref = dict(
            kind="artifact_time",
            artifact_id=3,
            immutable_version=1,
            sha256="b" * 64,
            start_ms=0,
            end_ms=1000,
        )
    data = payload()
    data["dimensions"]["accuracy"] = scored(ref)
    if kind in ("raw_transcript", "time"):
        with pytest.raises(ValidationError):
            EnglishAnalysisV1.model_validate(data)
    else:
        EnglishAnalysisV1.model_validate(data)


def test_unavailable_cannot_carry_score_or_scored_rationale():
    for field, value in [("score", 3), ("rationale", "Pretend scored")]:
        data = payload("tam")
        data["dimensions"]["correctness"][field] = value
        with pytest.raises(ValidationError):
            TAMAnalysisV1.model_validate(data)


def test_payload_byte_budget():
    data = payload("tam")
    dimension = scored()
    for index in range(16):
        ref = reference()
        ref["json_pointer"] = "/output/" + ("x" * 490) + str(index)
        dimension["observations"][0]["references"].append(ref)
    dimension["observations"][0]["references"] = dimension["observations"][0]["references"][1:]
    dimension["observations"] *= 16
    data["dimensions"] = {key: copy.deepcopy(dimension) for key in TAM}
    assert len(json.dumps(data).encode()) > 1024 * 1024
    with pytest.raises(ValidationError, match="1 MiB"):
        TAMAnalysisV1.model_validate(data)


@pytest.mark.parametrize(
    "model,name", [(EnglishAnalysisV1, "english-analysis-v1"), (TAMAnalysisV1, "tam-analysis-v1")]
)
def test_versioned_json_schema_snapshot(model, name):
    schema = model.model_json_schema()
    assert schema["$id"] == f"urn:tamforge:schema:{name}"
    assert schema == json.loads((Path(__file__).parent / "schemas" / f"{name}.json").read_text())


def feedback(**overrides):
    data = {
        "status": "processing",
        "activity_id": 1,
        "attempt_id": 2,
        "versions": None,
        "english": None,
        "tam": None,
        "withheld_reason": None,
    }
    data.update(overrides)
    return data


def versions():
    return {
        "model_run": {"id": 1, "content_hash": "a" * 64},
        "prompt": {"id": 2, "content_hash": "b" * 64},
        "output_schema": {"id": 3, "content_hash": "c" * 64},
        "rubric_binding": {"id": 4, "content_hash": "d" * 64},
    }


def cited(statement):
    return {
        "statement": statement,
        "attribution": "observed_content",
        "availability": "available",
        "confidence": "0.75",
        "references": [
            {
                "kind": "attempt_text",
                "attempt_id": 2,
                "commitment_sha256": "a" * 64,
                "json_pointer": "/output/draft_markdown",
                "start_codepoint": 0,
                "end_codepoint": 12,
            }
        ],
    }


def released(**overrides):
    """A ready read carries the verdict, the four findings, and the redo as well."""
    data = feedback(
        status="ready",
        versions=versions(),
        english=payload(),
        tam=payload("tam"),
        verdict="Clear on impact, thin on the trade-off.",
        strengths=[
            {"statement": "Named the customer impact first.", "evidence": cited("Impact first.")},
            {"statement": "Closed on a decision.", "evidence": cited("Ends on a recommendation.")},
        ],
        corrections=[
            {
                "statement": "The trade-off was never stated.",
                "instruction": "State the cost of the chosen option in one sentence.",
                "target_skill": "trade_offs",
                "evidence": cited("No cost is named."),
            },
            {
                "statement": "The timeline had no basis.",
                "instruction": "Give the timeline a source or mark it an estimate.",
                "target_skill": "business_framing",
                "evidence": cited("A date with no basis."),
            },
        ],
        attempt_b={"instruction": "Rewrite the recommendation with its cost.", "minutes": 10},
    )
    data.update(overrides)
    return data


def test_ready_feedback_requires_both_analyses_and_versions():
    from tamforge_protocol.agents import FeedbackRead

    for missing in ("english", "tam", "versions"):
        with pytest.raises(ValidationError):
            FeedbackRead.model_validate(released(**{missing: None}))


def test_ready_feedback_requires_the_verdict_the_findings_and_the_redo():
    from tamforge_protocol.agents import FeedbackRead

    for missing in ("verdict", "attempt_b"):
        with pytest.raises(ValidationError):
            FeedbackRead.model_validate(released(**{missing: None}))
    for field in ("strengths", "corrections"):
        full = released()[field]
        for supply in ([], full[:1], full + full[:1]):
            with pytest.raises(ValidationError):
                FeedbackRead.model_validate(released(**{field: supply}))


def test_a_finding_without_attributed_evidence_is_refused():
    from tamforge_protocol.agents import FeedbackRead

    for field in ("strengths", "corrections"):
        broken = released()
        first = dict(broken[field][0])
        first["evidence"] = {**first["evidence"], "references": []}
        broken[field] = [first, broken[field][1]]
        with pytest.raises(ValidationError):
            FeedbackRead.model_validate(broken)


def test_an_attempt_b_longer_than_the_next_lesson_is_refused():
    from tamforge_protocol.agents import ATTEMPT_B_MAX_MINUTES, FeedbackRead

    for minutes in (0, ATTEMPT_B_MAX_MINUTES + 1):
        with pytest.raises(ValidationError):
            FeedbackRead.model_validate(
                released(attempt_b={"instruction": "Redo it.", "minutes": minutes})
            )


def test_ready_feedback_accepts_the_matching_release():
    from tamforge_protocol.agents import FeedbackRead

    read = FeedbackRead.model_validate(released())
    assert read.withheld_reason is None
    assert read.english is not None and read.tam is not None
    assert read.verdict and len(read.strengths) == 2 and len(read.corrections) == 2


@pytest.mark.parametrize("status", ["processing", "needs_attention"])
@pytest.mark.parametrize("carried", ["english", "tam"])
def test_withheld_feedback_cannot_carry_analysis(status, carried):
    from tamforge_protocol.agents import FeedbackRead

    reason = "self_review_pending" if status == "needs_attention" else None
    data = feedback(status=status, withheld_reason=reason)
    data[carried] = payload() if carried == "english" else payload("tam")
    with pytest.raises(ValidationError):
        FeedbackRead.model_validate(data)


def test_reason_presence_follows_the_status():
    from tamforge_protocol.agents import FeedbackRead

    with pytest.raises(ValidationError):
        FeedbackRead.model_validate(feedback(status="needs_attention"))
    with pytest.raises(ValidationError):
        FeedbackRead.model_validate(
            feedback(status="processing", withheld_reason="self_review_pending")
        )
    with pytest.raises(ValidationError):
        FeedbackRead.model_validate(
            feedback(
                status="ready",
                versions=versions(),
                english=payload(),
                tam=payload("tam"),
                withheld_reason="self_review_pending",
            )
        )
    ready = FeedbackRead.model_validate(
        feedback(status="needs_attention", withheld_reason="evidence_unavailable")
    )
    assert ready.status == "needs_attention"


def test_ready_feedback_rejects_analysis_from_another_attempt():
    from tamforge_protocol.agents import FeedbackRead

    other = payload("tam")
    other["attempt_id"] = 99
    with pytest.raises(ValidationError):
        FeedbackRead.model_validate(
            feedback(status="ready", versions=versions(), english=payload(), tam=other)
        )


def test_withheld_reason_vocabulary_is_closed():
    from tamforge_protocol.agents import FeedbackRead

    with pytest.raises(ValidationError):
        FeedbackRead.model_validate(feedback(status="needs_attention", withheld_reason="because"))
