"""The scheme a package carries: days, blocks, minutes and sources, validated generically.

Nothing here knows how many days a plan has or how long a day is. Those numbers come
from the file; this module only checks that the file is consistent with itself and
with the release's contract vocabulary.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..evidence.config_models import ConfigBundle
from .parser import decode_markdown, headings_index

WEEKDAY_NAMES: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
AiRole = Literal["none", "planner", "tutor", "coach", "interviewer", "reviewer", "analyst"]

# Contract type -> the block name Today and the scheduler already understand.
CONTRACT_BLOCKS: Mapping[str, str] = MappingProxyType(
    {
        "sql": "sql",
        "technical": "technical_learning",
        "pipeline": "career_pipeline",
        "correction": "correction_warmup",
        "case": "tam_case",
        "communication": "communication_spoken",
        "close": "daily_close",
    }
)
DEFAULT_AI_ROLES: Mapping[str, str] = MappingProxyType(
    {
        "sql": "tutor",
        "technical": "tutor",
        "pipeline": "planner",
        "correction": "none",
        "case": "interviewer",
        "communication": "interviewer",
        "close": "analyst",
    }
)
SCHEME_FILE_NAME = "roadmap.yaml"
# Study days store minutes in a 0-255 column and an assessment day is capped at 120,
# so a scheme cannot declare more than the storage accepts (weekdays keep a 15-minute
# tolerance above the budget).
WEEKDAY_MAX_MINUTES = 240
ASSESSMENT_MAX_MINUTES = 120
MAX_SCHEME_BYTES = 2 * 1024 * 1024
_ID = r"^[a-z0-9][a-z0-9-]{2,63}$"


class SchemeValidationError(ValueError):
    """The scheme file cannot be read at all."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SchemeProgram(_Strict):
    key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")]
    title: Annotated[str, Field(min_length=1, max_length=128)]


class SchemeSource(_Strict):
    file: Annotated[str, Field(min_length=1, max_length=2048)]
    heading: Annotated[str, Field(min_length=1, max_length=512)]


class SchemeBlock(_Strict):
    id: Annotated[str, Field(pattern=_ID)]
    type: Annotated[str, Field(min_length=1, max_length=64)]
    minutes: Annotated[int, Field(gt=0, le=255)]
    source: SchemeSource
    objective: Annotated[str, Field(min_length=1, max_length=4096)]
    required: bool = True
    exercise_type: Annotated[str, Field(min_length=1, max_length=64)] = "official_reading"
    allowed_ai_role: AiRole | None = None


class SchemeDay(_Strict):
    id: Annotated[str, Field(pattern=_ID)]
    kind: Literal["weekday", "assessment"]
    budget_minutes: Annotated[int, Field(ge=0, le=720)]
    blocks: Annotated[tuple[SchemeBlock, ...], Field(min_length=1)]


class SchemeLineage(_Strict):
    predecessor_version: Annotated[str, Field(min_length=1, max_length=128)]


class SchemeFile(_Strict):
    schema_version: Literal[1]
    program: SchemeProgram
    rest_weekdays: tuple[Weekday, ...] = ("sunday",)
    lineage: SchemeLineage | None = None
    days: Annotated[tuple[SchemeDay, ...], Field(min_length=1)]

    @property
    def rest_weekday_indexes(self) -> frozenset[int]:
        return frozenset(WEEKDAY_NAMES.index(name) for name in self.rest_weekdays)


def parse_scheme_text(text: str) -> SchemeFile:
    if len(text.encode("utf-8")) > MAX_SCHEME_BYTES:
        raise SchemeValidationError("roadmap.yaml exceeds 2 MiB")
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SchemeValidationError(f"roadmap.yaml is not valid YAML: {exc}") from None
    return scheme_from_payload(payload)


def scheme_from_payload(payload: object) -> SchemeFile:
    if not isinstance(payload, dict):
        raise SchemeValidationError("roadmap.yaml must be a mapping")
    try:
        return SchemeFile.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "document"
        raise SchemeValidationError(f"roadmap.yaml {location}: {first['msg']}") from None


def validate_scheme(
    scheme: SchemeFile, *, files: Mapping[str, bytes], config: ConfigBundle
) -> tuple[str, ...]:
    """Every rule the spec lists, reported by name; empty means valid."""
    issues: list[str] = []
    markdown = decode_markdown(files)
    headings = headings_index(markdown)
    seen: set[str] = set()
    for day in scheme.days:
        if day.id in seen:
            issues.append(f"id '{day.id}' is duplicated")
        seen.add(day.id)
        total_minutes = 0
        for block in day.blocks:
            if block.id in seen:
                issues.append(f"id '{block.id}' is duplicated")
            seen.add(block.id)
            if block.type not in config.roadmap_contracts:
                issues.append(f"block '{block.id}': type '{block.type}' is not a contract")
            if block.type != "correction":
                try:
                    config.exercise(block.exercise_type)
                except KeyError:
                    issues.append(
                        f"block '{block.id}': exercise '{block.exercise_type}' is unknown"
                    )
            if block.source.file not in files:
                issues.append(f"block '{block.id}': file '{block.source.file}' is missing")
            else:
                count = headings.get(block.source.file, {}).get(block.source.heading, 0)
                if count == 0:
                    issues.append(
                        f"block '{block.id}': heading '{block.source.heading}' is missing "
                        f"from '{block.source.file}'"
                    )
                elif count > 1:
                    issues.append(
                        f"block '{block.id}': heading '{block.source.heading}' appears "
                        f"{count} times in '{block.source.file}'"
                    )
            total_minutes += block.minutes
        cap = ASSESSMENT_MAX_MINUTES if day.kind == "assessment" else WEEKDAY_MAX_MINUTES
        if day.budget_minutes > cap:
            issues.append(
                f"day '{day.id}' budget {day.budget_minutes} exceeds the {day.kind} "
                f"maximum of {cap} minutes"
            )
        if total_minutes != day.budget_minutes:
            issues.append(
                f"day '{day.id}' block minutes {total_minutes} do not equal "
                f"budget {day.budget_minutes}"
            )
        if sum(item.type == "correction" for item in day.blocks) > 1:
            issues.append(f"day '{day.id}' has more than one correction block")
    return tuple(issues)


def block_name(contract_type: str) -> str:
    if contract_type.startswith("saturday_"):
        return "saturday_assessment"
    return CONTRACT_BLOCKS[contract_type]


def default_ai_role(contract_type: str) -> str:
    if contract_type.startswith("saturday_"):
        return "none"
    return DEFAULT_AI_ROLES[contract_type]


def scheme_summary_from_payload(scheme: Mapping[str, object] | None) -> dict[str, object]:
    """The compact shape the review screen and the version response show.

    Empty for legacy packages, so the field is always present and never null.
    """
    if not scheme:
        return {}
    days = scheme.get("days")
    program = scheme.get("program")
    if not isinstance(days, Mapping) or not isinstance(program, Mapping):
        return {}
    ordered = sorted(days.items(), key=lambda item: int(item[0]))
    return {
        "program": str(program.get("title", "")),
        "study_days": len(ordered),
        "budget_minutes": {
            number: int(day["budget_minutes"])
            for number, day in ordered
            if isinstance(day, Mapping)
        },
    }


__all__ = [
    "CONTRACT_BLOCKS",
    "DEFAULT_AI_ROLES",
    "ASSESSMENT_MAX_MINUTES",
    "MAX_SCHEME_BYTES",
    "SCHEME_FILE_NAME",
    "WEEKDAY_MAX_MINUTES",
    "WEEKDAY_NAMES",
    "SchemeBlock",
    "SchemeDay",
    "SchemeFile",
    "SchemeLineage",
    "SchemeProgram",
    "SchemeSource",
    "SchemeValidationError",
    "block_name",
    "default_ai_role",
    "parse_scheme_text",
    "scheme_from_payload",
    "scheme_summary_from_payload",
    "validate_scheme",
]
