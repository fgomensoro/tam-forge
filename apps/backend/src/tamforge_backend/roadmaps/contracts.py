"""Immutable normalized contracts for parsed and diffed roadmaps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

JsonValue = str | int | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class NormalizedProcedureStep:
    phase: str
    minutes: int | None
    requirement: str

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "phase": self.phase,
            "minutes": self.minutes,
            "requirement": self.requirement,
        }


@dataclass(frozen=True, slots=True)
class NormalizedCorrectionSelection:
    source: str
    maximum_items: int
    allowed_kinds: tuple[str, ...]
    inherits_core_prompt: bool
    inherits_original_exercise: bool
    inherits_original_mapping_version: bool
    no_attempt_c: bool
    skill_level_effect: str

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "source": self.source,
            "maximum_items": self.maximum_items,
            "allowed_kinds": list(self.allowed_kinds),
            "inherits_core_prompt": self.inherits_core_prompt,
            "inherits_original_exercise": self.inherits_original_exercise,
            "inherits_original_mapping_version": self.inherits_original_mapping_version,
            "no_attempt_c": self.no_attempt_c,
            "skill_level_effect": self.skill_level_effect,
        }


@dataclass(frozen=True, slots=True)
class NormalizedTask:
    stable_id: str
    month: int
    week: int
    day: int
    block: str
    order: int
    source_path: str
    source_heading: str
    exercise_type: str | None
    mapping_version: str | None
    required: bool
    timebox_minutes: int
    objective: str
    required_output: tuple[str, ...]
    pass_criteria: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    procedure: tuple[NormalizedProcedureStep, ...]
    constraints: tuple[str, ...]
    correction_selection: NormalizedCorrectionSelection | None
    allowed_ai_role: str

    def core_dict(self) -> dict[str, JsonValue]:
        return {
            "stable_id": self.stable_id,
            "month": self.month,
            "week": self.week,
            "day": self.day,
            "block": self.block,
            "order": self.order,
            "source_path": self.source_path,
            "source_heading": self.source_heading,
            "exercise_type": self.exercise_type,
            "mapping_version": self.mapping_version,
            "required": self.required,
            "timebox_minutes": self.timebox_minutes,
            "objective": self.objective,
            "allowed_ai_role": self.allowed_ai_role,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        payload = self.core_dict()
        payload.update(
            {
                "required_output": list(self.required_output),
                "pass_criteria": list(self.pass_criteria),
                "evidence_requirements": list(self.evidence_requirements),
                "procedure": [step.to_dict() for step in self.procedure],
                "constraints": list(self.constraints),
                "correction_selection": (
                    self.correction_selection.to_dict()
                    if self.correction_selection is not None
                    else None
                ),
            }
        )
        return payload


@dataclass(frozen=True, slots=True)
class NormalizedTaskContract:
    stable_id: str
    required_output: tuple[str, ...]
    pass_criteria: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    procedure: tuple[NormalizedProcedureStep, ...]
    constraints: tuple[str, ...]
    correction_selection: NormalizedCorrectionSelection | None

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "stable_id": self.stable_id,
            "required_output": list(self.required_output),
            "pass_criteria": list(self.pass_criteria),
            "evidence_requirements": list(self.evidence_requirements),
            "procedure": [step.to_dict() for step in self.procedure],
            "constraints": list(self.constraints),
            "correction_selection": (
                self.correction_selection.to_dict()
                if self.correction_selection is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class NormalizedResource:
    key: str
    kind: Literal["external", "local"]
    labels: tuple[str, ...]
    source_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "key": self.key,
            "kind": self.kind,
            "labels": list(self.labels),
            "source_paths": list(self.source_paths),
        }


@dataclass(frozen=True, slots=True)
class NormalizedExitCriterion:
    text: str
    source_paths: tuple[str, ...]

    @property
    def key(self) -> str:
        return self.text

    def to_dict(self) -> dict[str, JsonValue]:
        return {"text": self.text, "source_paths": list(self.source_paths)}


@dataclass(frozen=True, slots=True)
class ParsedRoadmap:
    schema_version: int
    roadmap_version: str
    tasks: tuple[NormalizedTask, ...]
    contracts: tuple[NormalizedTaskContract, ...]
    resources: tuple[NormalizedResource, ...]
    exit_criteria: tuple[NormalizedExitCriterion, ...]
    normalized_hash: str

    def payload_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "roadmap_version": self.roadmap_version,
            "tasks": [item.to_dict() for item in self.tasks],
            "contracts": [item.to_dict() for item in self.contracts],
            "resources": [item.to_dict() for item in self.resources],
            "exit_criteria": [item.to_dict() for item in self.exit_criteria],
        }

    def to_dict(self) -> dict[str, JsonValue]:
        payload = self.payload_dict()
        payload["normalized_hash"] = self.normalized_hash
        return payload


ChangeStatus = Literal["added", "removed", "changed", "unchanged"]


@dataclass(frozen=True, slots=True)
class FieldChange:
    name: str
    before: JsonValue
    after: JsonValue


@dataclass(frozen=True, slots=True)
class EntityChange:
    key: str
    status: ChangeStatus
    fields: tuple[FieldChange, ...]
    before: dict[str, JsonValue] | None
    after: dict[str, JsonValue] | None

    def field(self, name: str) -> FieldChange:
        for item in self.fields:
            if item.name == name:
                return item
        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class DiffSection:
    entries: tuple[EntityChange, ...]

    def by_key(self, key: str) -> EntityChange:
        for item in self.entries:
            if item.key == key:
                return item
        raise KeyError(key)


@dataclass(frozen=True, slots=True)
class SemanticRoadmapDiff:
    tasks: DiffSection
    pass_contracts: DiffSection
    resources: DiffSection
    exit_criteria: DiffSection

    @property
    def summary(self) -> dict[str, int]:
        summary = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}
        for section in (
            self.tasks,
            self.pass_contracts,
            self.resources,
            self.exit_criteria,
        ):
            for entry in section.entries:
                summary[entry.status] += 1
        return summary

    @property
    def is_semantically_identical(self) -> bool:
        return not any(self.summary[key] for key in ("added", "removed", "changed"))
