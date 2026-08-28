"""Versioned universal activity-output contracts and canonical snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)


class OutputContractError(ValueError):
    """A committed output is incomplete or mismatched with its assigned task."""


def _bounded_text(value: str, *, maximum_bytes: int = 1_048_576) -> str:
    if not value.strip():
        raise ValueError("value must be non-blank")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ValueError("value exceeds the byte limit")
    return value


Text256 = Annotated[
    str,
    AfterValidator(lambda value: _bounded_text(value, maximum_bytes=256)),
]
Text4096 = Annotated[
    str,
    AfterValidator(lambda value: _bounded_text(value, maximum_bytes=4096)),
]
Text1M = Annotated[str, AfterValidator(_bounded_text)]
Text4M = Annotated[
    str,
    AfterValidator(lambda value: _bounded_text(value, maximum_bytes=4 * 1024 * 1024)),
]


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _OutputBase(_StrictContract):
    contract_version: Literal[1]
    prompt: Text1M
    audience: Text256
    time_limit_minutes: Annotated[int, Field(gt=0, le=255)]
    domain_competency_slug: Annotated[
        str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    ] | None = None
    story_competency_slug: Annotated[
        str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    ] | None = None

    @model_validator(mode="after")
    def one_dynamic_selector(self) -> _OutputBase:
        if (
            self.domain_competency_slug is not None
            and self.story_competency_slug is not None
        ):
            raise ValueError("only one competency selector may be committed")
        return self


class ReadingOutput(_OutputBase):
    kind: Literal["reading"]
    key_ideas: Annotated[tuple[Text4096, ...], Field(min_length=3, max_length=3)]
    boundary_or_failure: Text4096
    tam_customer_example: Text4096
    unresolved_question: Text4096


class SqlOutput(_OutputBase):
    kind: Literal["sql"]
    query: Text4M
    result: Text4M
    validation: Text4096
    explanation: Text4096
    business_meaning: Text4096
    solving_seconds: Annotated[int, Field(ge=0, le=255 * 60)]
    assistance_used: Literal[
        "none",
        "coach_preparation",
        "hint_ladder",
        "time_expired",
        "reference_only",
    ]


class CaseOutput(_OutputBase):
    kind: Literal["case"]
    canonical_prompt: Text1M
    canonical_facts: Annotated[tuple[Text4096, ...], Field(min_length=1, max_length=128)]
    discovery_questions: Annotated[tuple[Text4096, ...], Field(min_length=1, max_length=128)]
    assumptions: Annotated[tuple[Text4096, ...], Field(min_length=1, max_length=128)]
    working_notes: Text4M
    final_artifact: Text4M
    decisions: Annotated[tuple[Text4096, ...], Field(min_length=1, max_length=128)]
    risks: Annotated[tuple[Text4096, ...], Field(min_length=1, max_length=128)]
    unresolved_questions: Annotated[tuple[Text4096, ...], Field(min_length=1, max_length=128)]


class WritingOutput(_OutputBase):
    kind: Literal["writing"]
    requested_action: Text4096
    facts: Annotated[tuple[Text4096, ...], Field(min_length=1, max_length=128)]
    unknowns: Annotated[tuple[Text4096, ...], Field(min_length=1, max_length=128)]
    tone: Text256
    word_or_character_limit: Text256
    draft_markdown: Text4M
    self_edit_notes: Text4096


class PipelineOutput(_OutputBase):
    kind: Literal["pipeline"]
    company: Text256
    role: Text256
    stage: Text256
    completed_action: Text4096
    artifact_summary: Text4096
    next_action: Text4096


ActivityOutput = Annotated[
    ReadingOutput | SqlOutput | CaseOutput | WritingOutput | PipelineOutput,
    Field(discriminator="kind"),
]
_OUTPUT_ADAPTER: TypeAdapter[ActivityOutput] = TypeAdapter(ActivityOutput)

_ALLOWED_KINDS_BY_BLOCK: dict[str, frozenset[str]] = {
    "technical_learning": frozenset({"reading"}),
    "sql": frozenset({"sql"}),
    "tam_case": frozenset({"case"}),
    "communication_spoken": frozenset({"case", "writing"}),
    "career_pipeline": frozenset({"pipeline"}),
    "correction_warmup": frozenset({"sql", "case", "writing"}),
    "daily_close": frozenset({"writing"}),
    "saturday_assessment": frozenset({"sql", "case", "writing"}),
}


@dataclass(frozen=True, slots=True)
class ContractContext:
    block: str
    source_hidden: bool
    timebox_minutes: int
    task_stable_id: str
    exercise_type: str
    mapping_version: str
    roadmap_version_key: str
    task_definition_id: int

    def __post_init__(self) -> None:
        if (
            self.block not in _ALLOWED_KINDS_BY_BLOCK
            or not 0 < self.timebox_minutes <= 255
            or self.task_definition_id <= 0
            or any(
                not item.strip()
                for item in (
                    self.task_stable_id,
                    self.exercise_type,
                    self.mapping_version,
                    self.roadmap_version_key,
                )
            )
        ):
            raise OutputContractError("activity contract context is invalid")


@dataclass(frozen=True, slots=True)
class ValidatedOutput:
    kind: str
    prompt: str
    audience: str
    canonical_payload: dict[str, object]
    canonical_json: str
    original_markdown: str | None
    original_sql: str | None


def validate_output_contract(
    payload: object,
    *,
    context: ContractContext,
) -> ValidatedOutput:
    """Validate learner evidence and bind it to immutable server-side task context."""
    try:
        parsed = _OUTPUT_ADAPTER.validate_python(payload)
    except ValidationError as exc:
        message = exc.errors(include_url=False)[0]["msg"]
        raise OutputContractError(f"output contract is invalid: {message}") from None
    if parsed.kind not in _ALLOWED_KINDS_BY_BLOCK[context.block]:
        raise OutputContractError("output kind is not allowed for this task block")
    if parsed.time_limit_minutes != context.timebox_minutes:
        raise OutputContractError("output time limit does not match the assigned task")
    if isinstance(parsed, ReadingOutput) and not context.source_hidden:
        raise OutputContractError("source must be hidden before reading recall is committed")
    if isinstance(parsed, SqlOutput) and parsed.solving_seconds > context.timebox_minutes * 60:
        raise OutputContractError("SQL solving time exceeds the assigned time limit")

    output = parsed.model_dump(mode="json", exclude_none=True)
    output.pop("contract_version")
    canonical_payload: dict[str, object] = {
        "contract_version": parsed.contract_version,
        "task_context": {
            "task_definition_id": context.task_definition_id,
            "task_stable_id": context.task_stable_id,
            "exercise_type": context.exercise_type,
            "mapping_version": context.mapping_version,
            "roadmap_version_key": context.roadmap_version_key,
            "time_limit_minutes": context.timebox_minutes,
        },
        "output": output,
    }
    canonical_json = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    original_markdown: str | None = None
    original_sql: str | None = None
    if isinstance(parsed, WritingOutput):
        original_markdown = parsed.draft_markdown
    elif isinstance(parsed, CaseOutput):
        original_markdown = parsed.final_artifact
    elif isinstance(parsed, PipelineOutput):
        original_markdown = parsed.artifact_summary
    elif isinstance(parsed, SqlOutput):
        original_sql = parsed.query
    return ValidatedOutput(
        kind=parsed.kind,
        prompt=parsed.prompt,
        audience=parsed.audience,
        canonical_payload=canonical_payload,
        canonical_json=canonical_json,
        original_markdown=original_markdown,
        original_sql=original_sql,
    )


__all__ = [
    "ActivityOutput",
    "ContractContext",
    "OutputContractError",
    "ValidatedOutput",
    "validate_output_contract",
]
