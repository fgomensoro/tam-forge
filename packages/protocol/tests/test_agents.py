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
