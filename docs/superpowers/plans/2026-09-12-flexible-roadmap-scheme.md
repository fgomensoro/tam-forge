# Flexible Roadmap Scheme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a roadmap package carry its own structure (`roadmap.yaml`: days, blocks, minutes, sources) so any plan (the old Month 1, the six-week Phase 1, a two-hour day tomorrow) imports, activates and drives Today without a code change, with an AI planner that proposes and reforecasts schemes.

**Architecture:** A new `roadmaps/scheme.py` parses and validates `roadmap.yaml` against the release's contract vocabulary and projects it onto the existing `ParsedRoadmap`, so approval, curriculum nodes, task definitions and Today keep working. The stored `RoadmapVersion` gains a `scheme` JSON column (rest weekdays and per-day budgets); scheduling walks non-rest dates from the study start and takes the budget from the stored day instead of fixed 240/120 constants. The planner role produces a scheme payload validated by the same code before anyone sees it. The legacy schema-1 path stays until ticket F1-6.

**Tech Stack:** FastAPI, Pydantic 2, SQLAlchemy async + Alembic, PyYAML (already used by `evidence/config_loader.py`), pytest; SwiftUI macOS app with the generated OpenAPI types.

**Spec:** `docs/superpowers/specs/2026-09-11-flexible-roadmap-scheme-design.md` (system of record is the app; Obsidian is import/export only) and `docs/superpowers/specs/2026-09-11-ai-usage-and-reports-design.md` (planner runs on Fable 5.1 medium with Opus 5 high fallback).

## Global Constraints

- Contract vocabulary is fixed: block `type` must be a key of `config.roadmap_contracts` (sql, technical, pipeline, correction, case, communication, close, saturday_*).
- No fixed day count and no fixed minute totals in the scheme path; required block minutes of a day equal `budget_minutes`.
- Ids match `^[a-z0-9][a-z0-9-]{2,63}$` and are unique in the package.
- A block's `source.file` must exist in the package and `source.heading` must be a heading in it (exactly once); other links may leave the package.
- The v1 parser and its tests keep passing untouched until F1-6.
- Alembic revision ids are at most 32 characters; Pydantic fields on response models must not be `None`-typed without a value (Swift generator trap), so new report fields default to concrete values.
- Every proposal from the planner is validated by `validate_scheme` before it is returned; invalid proposals are refused with the validation issues.

---

### Task 1: Scheme model and validation (`roadmaps/scheme.py`)

**Files:**
- Create: `apps/backend/src/tamforge_backend/roadmaps/scheme.py`
- Test: `apps/backend/tests/unit/roadmaps/test_scheme.py`

**Interfaces:**
- Produces: `SchemeFile` (Pydantic), `SchemeBlock`, `SchemeDay`, `SchemeValidationError(ValueError)`, `parse_scheme_text(text: str) -> SchemeFile`, `validate_scheme(scheme: SchemeFile, *, files: Mapping[str, bytes], config: ConfigBundle) -> tuple[str, ...]` (issues, empty when valid), `WEEKDAY_NAMES: tuple[str, ...]`, `CONTRACT_BLOCKS: Mapping[str, str]` (contract type -> block name), `DEFAULT_AI_ROLES: Mapping[str, str]`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/unit/roadmaps/test_scheme.py
from __future__ import annotations

from pathlib import Path

import pytest
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.roadmaps.scheme import (
    SchemeValidationError,
    parse_scheme_text,
    validate_scheme,
)

ROOT = Path(__file__).parents[5]
CONFIG = load_config_bundle(ROOT / "config")

WEEK = "Week 1.md"
FILES = {
    WEEK: b"# Week 1\n\n## Day 1\n\nDo it.\n\n## Day 2\n\nAgain.\n",
    "docs/Queue.md": b"# Queue\n\n## P1-Q01\n\nTell me about yourself.\n",
}

SCHEME = """
schema_version: 1
program: {key: demo, title: Demo}
rest_weekdays: [sunday]
days:
  - id: d01
    kind: weekday
    budget_minutes: 120
    blocks:
      - {id: d01-interview, type: communication, minutes: 60, source: {file: docs/Queue.md, heading: P1-Q01}, objective: Answer P1-Q01.}
      - {id: d01-learning, type: technical, minutes: 45, source: {file: Week 1.md, heading: Day 1}, objective: Read the day.}
      - {id: d01-close, type: close, minutes: 15, source: {file: Week 1.md, heading: Day 1}, objective: Close the day.}
  - id: d02
    kind: assessment
    budget_minutes: 60
    blocks:
      - {id: d02-sql, type: saturday_sql, minutes: 60, source: {file: Week 1.md, heading: Day 2}, objective: Assess.}
"""


def test_valid_scheme_has_no_issues() -> None:
    scheme = parse_scheme_text(SCHEME)
    assert validate_scheme(scheme, files=FILES, config=CONFIG) == ()
    assert [day.kind for day in scheme.days] == ["weekday", "assessment"]


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        ("heading: P1-Q99", "heading 'P1-Q99' is missing"),
        ("file: docs/Queue.md", "file 'docs/Missing.md' is missing"),
        ("minutes: 45, source: {file: Week 1.md, heading: Day 1}, objective: Read the day.}",
         "day 'd01' required minutes 105 do not equal budget 120"),
        ("type: technical", "type 'physics' is not a contract"),
        ("id: d01-close", "id 'd01-interview' is duplicated"),
    ],
)
def test_invalid_schemes_report_named_issues(mutation: str, fragment: str) -> None:
    replacements = {
        "heading: P1-Q99": SCHEME.replace("heading: P1-Q01", "heading: P1-Q99"),
        "file: docs/Queue.md": SCHEME.replace("file: docs/Queue.md", "file: docs/Missing.md"),
        "minutes: 45, source: {file: Week 1.md, heading: Day 1}, objective: Read the day.}": SCHEME.replace(
            "minutes: 45, source: {file: Week 1.md, heading: Day 1}, objective: Read the day.}",
            "minutes: 30, source: {file: Week 1.md, heading: Day 1}, objective: Read the day.}",
        ),
        "type: technical": SCHEME.replace("type: technical", "type: physics"),
        "id: d01-close": SCHEME.replace("id: d01-close", "id: d01-interview"),
    }
    scheme = parse_scheme_text(replacements[mutation])
    issues = validate_scheme(scheme, files=FILES, config=CONFIG)
    assert any(fragment in issue for issue in issues), issues


def test_malformed_yaml_is_a_validation_error() -> None:
    with pytest.raises(SchemeValidationError):
        parse_scheme_text("schema_version: 1\ndays: [")
    with pytest.raises(SchemeValidationError):
        parse_scheme_text("schema_version: 2\nprogram: {key: x, title: X}\ndays: []")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest apps/backend/tests/unit/roadmaps/test_scheme.py -q`
Expected: FAIL with `ModuleNotFoundError: tamforge_backend.roadmaps.scheme`

- [ ] **Step 3: Write the module**

```python
# apps/backend/src/tamforge_backend/roadmaps/scheme.py
"""The scheme a package carries: days, blocks, minutes and sources, validated generically."""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..evidence.config_models import ConfigBundle
from .parser import _headings, _decode_markdown  # reuse the heading index

WEEKDAY_NAMES: tuple[str, ...] = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)
Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

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
_ID = r"^[a-z0-9][a-z0-9-]{2,63}$"


class SchemeValidationError(ValueError):
    """The scheme file cannot be read at all."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SchemeProgram(_Strict):
    key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
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
    allowed_ai_role: (
        Literal["none", "planner", "tutor", "coach", "interviewer", "reviewer", "analyst"] | None
    ) = None


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
    if len(text.encode("utf-8")) > 2 * 1024 * 1024:
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
        location = ".".join(str(part) for part in first["loc"])
        raise SchemeValidationError(f"roadmap.yaml {location}: {first['msg']}") from None


def validate_scheme(
    scheme: SchemeFile, *, files: Mapping[str, bytes], config: ConfigBundle
) -> tuple[str, ...]:
    """Every rule the spec lists, reported by name; empty means valid."""
    issues: list[str] = []
    markdown = _decode_markdown(
        {path: data for path, data in files.items() if path.lower().endswith(".md")}
    )
    headings = _headings(markdown)
    seen: set[str] = set()
    for day in scheme.days:
        if day.id in seen:
            issues.append(f"id '{day.id}' is duplicated")
        seen.add(day.id)
        required_minutes = 0
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
            if block.required:
                required_minutes += block.minutes
        if required_minutes != day.budget_minutes:
            issues.append(
                f"day '{day.id}' required minutes {required_minutes} do not equal "
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


__all__ = [
    "CONTRACT_BLOCKS",
    "DEFAULT_AI_ROLES",
    "SCHEME_FILE_NAME",
    "WEEKDAY_NAMES",
    "SchemeBlock",
    "SchemeDay",
    "SchemeFile",
    "SchemeValidationError",
    "block_name",
    "default_ai_role",
    "parse_scheme_text",
    "scheme_from_payload",
    "validate_scheme",
]
```

`_headings` and `_decode_markdown` are private names in `parser.py` today; rename them to `headings_index` and `decode_markdown` (public) in the same task and update the two call sites inside `parser.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest apps/backend/tests/unit/roadmaps/test_scheme.py apps/backend/tests/unit/roadmaps/test_parser.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/tamforge_backend/roadmaps/scheme.py apps/backend/src/tamforge_backend/roadmaps/parser.py apps/backend/tests/unit/roadmaps/test_scheme.py
git commit -m "feat(roadmaps): scheme model and generic validation for roadmap.yaml"
```

---

### Task 2: Project a scheme onto `ParsedRoadmap` (parser v2)

**Files:**
- Modify: `apps/backend/src/tamforge_backend/roadmaps/parser.py` (add `parse_roadmap_scheme`, make `_resources` tolerate links that leave the package, make exit criteria optional in the scheme path, dispatch in `parse_roadmap`)
- Modify: `apps/backend/src/tamforge_backend/roadmaps/contracts.py` (`ParsedRoadmap.scheme: dict | None = None`)
- Test: `apps/backend/tests/unit/roadmaps/test_scheme.py` (append)

**Interfaces:**
- Produces: `parse_roadmap(*, files, config)` now returns a scheme projection when `roadmap.yaml` is in `files`; `ParsedRoadmap.scheme` is `{"rest_weekdays": [6], "program": {...}, "days": {"1": {"id": ..., "kind": ..., "budget_minutes": ...}, ...}}` (JSON-serializable, day numbers as strings) or `None` for legacy packages.
- Consumes: Task 1.

- [ ] **Step 1: Write the failing test**

```python
def test_scheme_package_projects_onto_parsed_roadmap() -> None:
    from tamforge_backend.roadmaps.parser import parse_roadmap

    files = dict(FILES)
    files["roadmap.yaml"] = SCHEME.encode("utf-8")
    parsed = parse_roadmap(files=files, config=CONFIG)
    assert parsed.roadmap_version == "demo"
    assert [task.stable_id for task in parsed.tasks] == [
        "d01-interview", "d01-learning", "d01-close", "d02-sql",
    ]
    first = parsed.tasks[0]
    assert (first.day, first.week, first.order, first.block) == (1, 1, 1, "communication_spoken")
    assert first.allowed_ai_role == "interviewer"
    assert first.procedure  # inherited from the communication contract
    assert parsed.tasks[3].block == "saturday_assessment"
    assert parsed.scheme == {
        "rest_weekdays": [6],
        "program": {"key": "demo", "title": "Demo"},
        "days": {
            "1": {"id": "d01", "kind": "weekday", "budget_minutes": 120},
            "2": {"id": "d02", "kind": "assessment", "budget_minutes": 60},
        },
    }
    assert parsed.exit_criteria == ()


def test_scheme_package_with_issues_raises_parse_error() -> None:
    from tamforge_backend.roadmaps.parser import RoadmapParseError, parse_roadmap

    files = dict(FILES)
    files["roadmap.yaml"] = SCHEME.replace("heading: P1-Q01", "heading: P1-Q99").encode()
    with pytest.raises(RoadmapParseError, match="P1-Q99"):
        parse_roadmap(files=files, config=CONFIG)


def test_scheme_package_keeps_links_that_leave_the_package() -> None:
    from tamforge_backend.roadmaps.parser import parse_roadmap

    files = dict(FILES)
    files[WEEK] = FILES[WEEK] + b"\nSee [[Docs/2026-09-08 - Active Study Reforecast]].\n"
    files["roadmap.yaml"] = SCHEME.encode("utf-8")
    parsed = parse_roadmap(files=files, config=CONFIG)
    assert all(item.kind == "external" or item.key in files for item in parsed.resources)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest apps/backend/tests/unit/roadmaps/test_scheme.py -q -k "projects or issues_raises or leave"`
Expected: FAIL (roadmap.yaml ignored by the v1 path: "source file ... is missing" or similar)

- [ ] **Step 3: Implement**

In `contracts.py` add to `ParsedRoadmap`: `scheme: dict[str, JsonValue] | None = None` and include it in `payload_dict()` as `"scheme": self.scheme`.

In `parser.py`:

```python
from .scheme import SCHEME_FILE_NAME, SchemeFile, SchemeValidationError, block_name, default_ai_role, parse_scheme_text, validate_scheme

_DEFAULT_CORRECTION = NormalizedCorrectionSelection(
    source="due_corrections", maximum_items=1,
    allowed_kinds=("spoken_attempt_b", "targeted_sql_correction", "written_attempt_b"),
    inherits_core_prompt=True, inherits_original_exercise=True,
    inherits_original_mapping_version=True, no_attempt_c=True, skill_level_effect="none",
)
STUDY_DAYS_PER_WEEK = 6  # grouping only; the calendar walk owns dates


def parse_roadmap(*, files: Mapping[str, bytes], config: ConfigBundle) -> ParsedRoadmap:
    if SCHEME_FILE_NAME in files:
        return parse_roadmap_scheme(files=files, config=config)
    ...existing v1 body unchanged...


def parse_roadmap_scheme(*, files: Mapping[str, bytes], config: ConfigBundle) -> ParsedRoadmap:
    try:
        scheme = parse_scheme_text(files[SCHEME_FILE_NAME].decode("utf-8"))
    except (SchemeValidationError, UnicodeDecodeError) as exc:
        raise RoadmapParseError(str(exc)) from None
    issues = validate_scheme(scheme, files=files, config=config)
    if issues:
        raise RoadmapParseError("; ".join(issues))
    markdown = decode_markdown({p: d for p, d in files.items() if p.lower().endswith(".md")})
    tasks: list[NormalizedTask] = []
    for day_number, day in enumerate(scheme.days, start=1):
        for order, block in enumerate(day.blocks, start=1):
            contract = config.roadmap_contracts[block.type]
            is_correction = block.type == "correction"
            exercise = None if is_correction else config.exercise(block.exercise_type)
            tasks.append(NormalizedTask(
                stable_id=block.id, month=1,
                week=(day_number - 1) // STUDY_DAYS_PER_WEEK + 1, day=day_number,
                block=block_name(block.type), order=order,
                source_path=block.source.file, source_heading=block.source.heading,
                exercise_type=None if is_correction else block.exercise_type,
                mapping_version=None if exercise is None else exercise.mapping_version,
                required=block.required and not is_correction,
                timebox_minutes=block.minutes, objective=block.objective,
                required_output=tuple(contract.required_output),
                pass_criteria=tuple(contract.pass_criteria),
                evidence_requirements=tuple(contract.evidence_requirements),
                procedure=tuple(NormalizedProcedureStep(step.phase, step.minutes, step.requirement) for step in contract.procedure),
                constraints=tuple(contract.constraints),
                correction_selection=_DEFAULT_CORRECTION if is_correction else None,
                allowed_ai_role=block.allowed_ai_role or default_ai_role(block.type),
            ))
    contracts = tuple(_contract(item) for item in tasks)
    resources = _resources(files, markdown, require_local=False)
    exit_criteria = _exit_criteria(markdown, required=False)
    scheme_payload = {
        "rest_weekdays": sorted(scheme.rest_weekday_indexes),
        "program": {"key": scheme.program.key, "title": scheme.program.title},
        "days": {str(n): {"id": d.id, "kind": d.kind, "budget_minutes": d.budget_minutes} for n, d in enumerate(scheme.days, start=1)},
    }
    payload = {"schema_version": 2, "roadmap_version": scheme.program.key, "scheme": scheme_payload,
               "tasks": [t.to_dict() for t in tasks], "contracts": [c.to_dict() for c in contracts],
               "resources": [r.to_dict() for r in resources], "exit_criteria": [e.to_dict() for e in exit_criteria]}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return ParsedRoadmap(schema_version=2, roadmap_version=scheme.program.key, tasks=tuple(tasks),
                         contracts=contracts, resources=resources, exit_criteria=exit_criteria,
                         normalized_hash=hashlib.sha256(canonical).hexdigest(), scheme=scheme_payload)
```

`_resources(files, markdown, *, require_local=True)`: when `require_local` is False, a `RoadmapParseError` from `_resolve_local_resource` is caught and the link is skipped. `_exit_criteria(markdown, *, required=True)`: when `required` is False, an empty result returns `()` instead of raising, and the heading match becomes `title.endswith("exit criteria")`.

Check `TaskContractConfig` field names in `evidence/config_models.py:431` before writing the contract projection (`required_output`, `pass_criteria`, `evidence_requirements`, `procedure`, `constraints`); use them verbatim.

Also check `_parsed_from_payload` in `service.py` reads `scheme` back (add `scheme=payload.get("scheme")`), so the diff against a previous version and the approval path carry it.

- [ ] **Step 4: Run all roadmap unit tests**

Run: `uv run pytest apps/backend/tests/unit/roadmaps -q`
Expected: PASS (v1 tests untouched)

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/tamforge_backend/roadmaps apps/backend/tests/unit/roadmaps/test_scheme.py
git commit -m "feat(roadmaps): parse roadmap.yaml packages onto the normalized roadmap"
```

---

### Task 3: Store the scheme with the version and report it (F1-1 ends here)

**Files:**
- Create: `apps/backend/alembic/versions/20260912_0019_roadmap_scheme.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/models.py` (`RoadmapVersion.scheme: Mapped[dict | None]` JSONB, `CurriculumNode` unchanged)
- Modify: `apps/backend/src/tamforge_backend/roadmaps/repository.py` (`approve_import` writes `scheme=parsed.scheme`; `RoadmapVersionRecord.scheme`)
- Modify: `apps/backend/src/tamforge_backend/roadmaps/ports.py` (`RoadmapVersionRecord.scheme: Mapping[str, object] | None`)
- Modify: `apps/backend/src/tamforge_backend/roadmaps/service.py` (validation report gains `scheme_summary`)
- Modify: `apps/backend/src/tamforge_backend/roadmaps/routes.py` (`RoadmapVersionResponse.scheme_summary: dict[str, object]` default `{}`)
- Test: `apps/backend/tests/unit/roadmaps/test_service.py`, `apps/backend/tests/unit/learning/test_study_activity_schema.py` (schema snapshot), `apps/backend/tests/integration/roadmaps/test_import_flow.py`

**Interfaces:**
- Produces: `RoadmapVersionRecord.scheme` and `scheme_summary = {"program": str, "study_days": int, "budget_minutes": {"1": 180, ...}, "blocks_per_day": {"1": 4, ...}}` in both the validation report and the version response.

- [ ] **Step 1: Migration**

```python
"""roadmap versions carry their scheme

Revision ID: 20260912_0019_roadmap_scheme
Revises: 20260909_0018_transcripts
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260912_0019_roadmap_scheme"
down_revision = "20260909_0018_transcripts"


def upgrade() -> None:
    op.add_column("roadmap_versions", sa.Column("scheme", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("roadmap_versions", "scheme")
```

Read `20260909_0018_transcripts.py` first and copy its exact `revision`/`down_revision` string style.

- [ ] **Step 2: Failing service test**

```python
# apps/backend/tests/unit/roadmaps/test_service.py (append)
async def test_scheme_package_reports_a_scheme_summary(tmp_path) -> None:
    ...stage a package built from test_scheme.FILES + SCHEME through the existing fake
    repository/object store helpers in this file...
    report = staged.validation_report
    assert report["scheme_summary"] == {
        "program": "Demo", "study_days": 2,
        "budget_minutes": {"1": 120, "2": 60}, "blocks_per_day": {"1": 3, "2": 1},
    }
```

Build `scheme_summary` in `service.py` next to `task_count`: `_scheme_summary(parsed)` returning `{}` when `parsed.scheme is None`.

- [ ] **Step 3: Run, implement, run**

Run: `uv run pytest apps/backend/tests/unit/roadmaps apps/backend/tests/unit/learning/test_study_activity_schema.py -q` — update the schema snapshot test for the new column.
Then integration: `TEST_DATABASE_URL=... uv run pytest -m integration apps/backend/tests/integration/roadmaps -q` and assert in `test_import_flow.py` that a legacy package stores `scheme IS NULL`.

- [ ] **Step 4: Regenerate the native OpenAPI document and refreeze its hash**

Run: `uv run python scripts/ci/check_openapi.py --write` then update `FROZEN_OPENAPI_SHA256` in `scripts/ci/tests/test_check_openapi.py` with the printed hash of `normalized_openapi_document()`; `uv run pytest scripts/ci/tests -q`.

- [ ] **Step 5: Commit, push, PR "feat(roadmaps): F1-1 scheme model, parser v2 and stored scheme (#270)"**

---

### Task 4: Calendar walk and per-day budgets (F1-2, #271)

**Files:**
- Modify: `apps/backend/src/tamforge_backend/learning/scheduling.py` (`study_day_number(study_start_date, local_date, *, rest_weekdays)`, `build_day(..., budget: DayBudget | None = None)`)
- Modify: `apps/backend/src/tamforge_backend/learning/time_policy.py` (`budget_for_day(kind, budget_minutes)`)
- Modify: `apps/backend/src/tamforge_backend/learning/repository.py` (load version before the day number; use the scheme)
- Modify: `apps/backend/src/tamforge_backend/today/repository.py:93,278,604` and `today/service.py:218` (rest days and budget from the version's scheme)
- Modify: `apps/backend/src/tamforge_backend/today/schemas.py:115` (`target_minutes` cap `le=720`)
- Test: `apps/backend/tests/unit/learning/test_scheduling.py` (append), `apps/backend/tests/unit/learning/test_time_policy.py` (append), `apps/backend/tests/integration/today/test_today_api.py` (append a 180-minute day case)

**Interfaces:**
- Produces:
  - `study_day_number(study_start_date: date, local_date: date, *, rest_weekdays: frozenset[int]) -> int | None` (None on a rest day; walks dates, no Monday requirement; raises before start).
  - `budget_for_day(kind: Literal["weekday", "assessment"], budget_minutes: int) -> DayBudget` = weekday: `DayBudget("weekday", b, max(b - 15, 0), b + 15)`; assessment: `DayBudget("saturday", b, 0, b)`.
  - `scheme_for_version(version: RoadmapVersion) -> SchemeInfo` in `learning/scheduling.py`: `SchemeInfo(rest_weekdays: frozenset[int], budgets: Mapping[int, DayBudget])`; for a legacy version (`scheme is None`) returns `rest_weekdays={6}` and an empty mapping so callers fall back to `budget_for(local_date)` and `curriculum_day_number`.
  - `build_day(..., budget=None)`: when `budget` is given it replaces `budget_for(local_date)`; `curriculum_day` still positive.

- [ ] **Step 1: Failing tests**

```python
# apps/backend/tests/unit/learning/test_scheduling.py (append)
from datetime import date
from tamforge_backend.learning.scheduling import study_day_number

def test_study_day_number_walks_non_rest_dates_from_any_start() -> None:
    start = date(2026, 9, 9)  # a Wednesday
    rest = frozenset({6})
    assert study_day_number(start, date(2026, 9, 9), rest_weekdays=rest) == 1
    assert study_day_number(start, date(2026, 9, 12), rest_weekdays=rest) == 4  # Saturday counts
    assert study_day_number(start, date(2026, 9, 13), rest_weekdays=rest) is None  # Sunday
    assert study_day_number(start, date(2026, 9, 14), rest_weekdays=rest) == 5

def test_study_day_number_with_two_rest_days() -> None:
    start = date(2026, 9, 7)  # Monday
    rest = frozenset({5, 6})
    assert study_day_number(start, date(2026, 9, 14), rest_weekdays=rest) == 6

# apps/backend/tests/unit/learning/test_time_policy.py (append)
from tamforge_backend.learning.time_policy import budget_for_day

def test_budget_for_day_uses_the_scheme_budget() -> None:
    assert budget_for_day("weekday", 180).maximum_minutes == 195
    assert budget_for_day("weekday", 180).acceptable_minimum == 165
    assert budget_for_day("assessment", 120).day_type == "saturday"
    assert budget_for_day("assessment", 120).maximum_minutes == 120
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest apps/backend/tests/unit/learning/test_scheduling.py apps/backend/tests/unit/learning/test_time_policy.py -q`

- [ ] **Step 3: Implement**

```python
# scheduling.py
def study_day_number(study_start_date: date, local_date: date, *, rest_weekdays: frozenset[int]) -> int | None:
    if local_date < study_start_date:
        raise SchedulePolicyError("study date precedes the roadmap anchor")
    if local_date.weekday() in rest_weekdays:
        return None
    number = 0
    current = study_start_date
    while current <= local_date:
        if current.weekday() not in rest_weekdays:
            number += 1
        current += timedelta(days=1)
    return number

@dataclass(frozen=True, slots=True)
class SchemeInfo:
    rest_weekdays: frozenset[int]
    budgets: Mapping[int, DayBudget]

def scheme_for_version(scheme: Mapping[str, Any] | None) -> SchemeInfo:
    if not scheme:
        return SchemeInfo(frozenset({6}), MappingProxyType({}))
    days = scheme.get("days", {})
    budgets = {int(k): budget_for_day(v["kind"], int(v["budget_minutes"])) for k, v in days.items()}
    return SchemeInfo(frozenset(int(i) for i in scheme.get("rest_weekdays", [6])), MappingProxyType(budgets))
```

`build_day` takes `budget: DayBudget | None = None`; `budget = budget or budget_for(local_date)`.

`learning/repository.py`: load `setting`, then `version` (needed anyway), then `info = scheme_for_version(version.scheme)`; `curriculum_day = study_day_number(setting.study_start_date, context.local_date, rest_weekdays=info.rest_weekdays)` when `version.scheme` else the legacy `curriculum_day_number`; pass `budget=info.budgets.get(curriculum_day)` to `build_day`. Reorder the early return for a rest day accordingly (the version lookup must happen before, but the `StudyDay` existing check stays first).

`today/repository.py`: replace `local_date.weekday() != 6` with `local_date.weekday() not in info.rest_weekdays` (load the version first; for a missing version keep the legacy set), `day=local_date.weekday() + 1` stays, and `next_study_date` loops while `weekday() in rest_weekdays`. Add `budget: DayBudget` to `TodayReadInput` computed as `info.budgets.get(curriculum_day) or budget_for(local_date)`; `today/service.py:218` uses `source.budget`.

- [ ] **Step 4: Integration test for a 180-minute day**

In `apps/backend/tests/integration/today/test_today_api.py`, add a case that imports the scheme package from Task 1 (write `FILES` + `SCHEME` into a zip in a `tmp_path`), approves, activates with `timezone="America/Montevideo"`, requests `/api/v1/today?date=<study_start_date>` and asserts `planned_minutes == 120` and the three blocks, then `date + 1 day` (assessment) shows `day_type == "saturday"` with 60 minutes. Look at the existing test in that file for the exact setup helpers.

Run: `uv run pytest apps/backend/tests/unit/learning apps/backend/tests/unit/today -q` then the integration file with the local database.

- [ ] **Step 5: Commit, push, PR "feat(learning): F1-2 calendar walk and per-day budgets from the scheme (#271)"**

---

### Task 5: Packages accept `roadmap.yaml`; converter and reference packages (F1-3, #272)

**Files:**
- Modify: `apps/backend/src/tamforge_backend/roadmaps/package.py:25` (`".yaml": "application/yaml"`, only at the package root: reject nested `.yaml` with issue code `yaml_outside_root`)
- Create: `scripts/dev/convert_task_map.py`
- Create: `apps/backend/tests/fixtures/roadmaps/month-1-scheme-v1.zip`, `apps/backend/tests/fixtures/roadmaps/phase-1-six-week-scheme-v1.zip`
- Test: `apps/backend/tests/unit/roadmaps/test_package.py` (append), `apps/backend/tests/unit/roadmaps/test_scheme.py` (append), `scripts/dev/tests/test_convert_task_map.py`

**Interfaces:**
- Produces: `convert_task_map(task_map_path: Path, package_zip: Path, output_zip: Path) -> SchemeFile` and CLI `uv run python scripts/dev/convert_task_map.py <task-map.yaml> <package.zip> <output.zip> [--check]` (`--check` regenerates in memory and exits 1 when the output zip differs).

- [ ] **Step 1: Failing tests**

```python
# apps/backend/tests/unit/roadmaps/test_scheme.py (append)
@pytest.mark.parametrize("name", ["month-1-scheme-v1.zip", "phase-1-six-week-scheme-v1.zip"])
def test_reference_scheme_packages_parse(name: str) -> None:
    from tamforge_backend.roadmaps.parser import parse_roadmap
    files = _fixture_files(name)  # copy the helper from test_parser.py
    parsed = parse_roadmap(files=files, config=CONFIG)
    assert parsed.scheme is not None
    expected = {"month-1-scheme-v1.zip": (24, 158), "phase-1-six-week-scheme-v1.zip": (36, 148)}[name]
    assert (len(parsed.scheme["days"]), len(parsed.tasks)) == expected
```

Converter mapping: for each `days[]` entry of the task map (schema 1 or 2) create a `SchemeDay` with `id=f"{roadmap_version}-d{day:02d}"`, `kind="assessment"` when every task block is `saturday_assessment` else `"weekday"`, `budget_minutes=sum(required minutes)`, and one `SchemeBlock` per task: `id=stable_id`, `type=<contract key>` (schema 2 has `contract:` per task; schema 1 derives it from the block name through the inverse of `CONTRACT_BLOCKS`, and for `saturday_assessment` from `contract` if present else `saturday_sql`), `minutes=timebox_minutes`, `source={file: day.source_path, heading: day.source_heading}` (schema 1: the task's own `source_path`/`source_heading`), `objective`, `required`, `exercise_type`, `allowed_ai_role`. Write `roadmap.yaml` with `yaml.safe_dump(..., sort_keys=False, allow_unicode=True)` into a copy of the package zip with deterministic timestamps (`ZipInfo` date `(1980, 1, 1, 0, 0, 0)`), entries sorted.

The six-week map lives in `config/releases/phase-1-six-week-v1/tam-roadmap-task-map.yaml` and its package is `apps/backend/tests/fixtures/roadmaps/phase-1-six-week-v1.zip`; the Month 1 map is `config/tam-roadmap-task-map.yaml` with package `month-v1.zip`. The six-week contracts (`interview`, `roadmap`, ...) are not in the server vocabulary: map `interview`->`communication`, `roadmap`->`technical`, `close`->`close`, `pipeline`->`pipeline`, and Saturday contracts by name.

- [ ] **Step 2: Run, implement, generate the fixtures, run**

Run: `uv run python scripts/dev/convert_task_map.py config/tam-roadmap-task-map.yaml apps/backend/tests/fixtures/roadmaps/month-v1.zip apps/backend/tests/fixtures/roadmaps/month-1-scheme-v1.zip` and the six-week equivalent, then `uv run pytest apps/backend/tests/unit/roadmaps scripts/dev/tests -q`.

- [ ] **Step 3: Commit, push, PR "feat(roadmaps): F1-3 packages carry roadmap.yaml; converter and reference packages (#272)"**

---

### Task 6: Planner role: generate and reforecast (F1-4, #273)

**Files:**
- Create: `apps/backend/src/tamforge_backend/roadmaps/planner.py`
- Modify: `apps/backend/src/tamforge_backend/roadmaps/routes.py` (two endpoints, `PlannerUnavailable` -> 503 problem `planner_unavailable`)
- Modify: `apps/backend/src/tamforge_backend/roadmaps/service.py` (`attach_scheme` and `stage_reforecast`)
- Modify: `apps/backend/src/tamforge_backend/roadmaps/repository.py` (`replace_validation` for attach; `create_import_from_snapshot` for reforecast)
- Modify: `apps/backend/src/tamforge_backend/main.py` (planner transport wiring: `None` unless `settings.claude_enabled`)
- Test: `apps/backend/tests/unit/roadmaps/test_planner.py`, `apps/backend/tests/unit/roadmaps/test_routes.py` (append)

**Interfaces:**
- Produces:
  - `class PlannerTransport(Protocol): async def propose(self, request: PlannerRequest) -> Mapping[str, object]` (the seam F2 fills with the Agent SDK; returns the scheme payload as a mapping).
  - `PlannerRequest(mode: Literal["generate", "reforecast"], files: Mapping[str, str] (markdown text only), instruction: str, current_scheme: Mapping | None, evidence_summary: tuple[EvidenceLine, ...], today: date)`; `EvidenceLine(block_id: str, status: Literal["done", "pending"])`.
  - `PlannerService(transport: PlannerTransport | None, config: ConfigBundle, model: str)`: `async generate(files, instruction) -> SchemeProposal`, `async reforecast(files, current_scheme, evidence, today, instruction) -> SchemeProposal`; `SchemeProposal(yaml_text: str, summary: dict, issues: tuple[str, ...])` where `issues` non-empty means refused (the yaml is still returned for inspection).
  - Raises `PlannerUnavailable` when `transport is None` (Claude disabled).
  - Endpoints: `POST /api/v1/roadmap-imports/{import_id}/scheme-proposals` body `{"mode": "generate", "instruction": ""}` -> `SchemeProposalResponse{yaml_text, summary, issues}`; `POST /api/v1/roadmap-versions/{version_id}/scheme-proposals` body `{"mode": "reforecast", "instruction": ""}`; `POST /api/v1/roadmap-imports/{import_id}/scheme` body `{"yaml_text": "..."}` re-validates the staged package with the attached scheme (stores the yaml as one more file in a new snapshot object, re-runs `finish_validation`); `POST /api/v1/roadmap-versions/{version_id}/reforecasts` body `{"yaml_text": "..."}` creates a new import from the version's stored snapshot plus the scheme with `lineage.predecessor_version` set, returns `RoadmapImportResponse`.
  - The planner uses `prepare_role_prompt(AgentRole.PLANNER, committed=True, requested_context=(TASK_BRIEF, ROADMAP_STATE, EVIDENCE_SUMMARY))` and `PreparedAgentRun(job_type="planner", model=model, schema_id="urn:tamforge:schema:planner-v1", max_turns=8, wall_time_seconds=300)`; the transport call goes through `BoundedClaudeRuntime(transport_adapter, validate=_scheme_issues)` so the one-repair rule applies.

- [ ] **Step 1: Failing tests**

```python
# apps/backend/tests/unit/roadmaps/test_planner.py
import pytest
from tamforge_backend.roadmaps.planner import PlannerService, PlannerUnavailable, PlannerRequest

class FakeTransport:
    def __init__(self, payload): self.payload = payload; self.requests = []
    async def propose(self, request: PlannerRequest):
        self.requests.append(request); return self.payload

VALID = yaml.safe_load(SCHEME)  # from test_scheme

async def test_generate_returns_a_validated_proposal() -> None:
    service = PlannerService(FakeTransport(VALID), config=CONFIG, model="claude-fable-5-1")
    proposal = await service.generate(files=FILES, instruction="two hours a day")
    assert proposal.issues == ()
    assert proposal.summary["study_days"] == 2
    assert "budget_minutes: 120" in proposal.yaml_text

async def test_invalid_proposal_is_refused_with_issues() -> None:
    broken = dict(VALID); broken["days"] = [dict(VALID["days"][0], budget_minutes=999)]
    service = PlannerService(FakeTransport(broken), config=CONFIG, model="m")
    proposal = await service.generate(files=FILES, instruction="")
    assert proposal.issues and "do not equal budget" in proposal.issues[0]

async def test_planner_is_unavailable_without_claude() -> None:
    service = PlannerService(None, config=CONFIG, model="m")
    with pytest.raises(PlannerUnavailable):
        await service.generate(files=FILES, instruction="")

async def test_reforecast_passes_evidence_and_today() -> None:
    transport = FakeTransport(VALID)
    service = PlannerService(transport, config=CONFIG, model="m")
    await service.reforecast(files=FILES, current_scheme=VALID, evidence=(EvidenceLine("d01-interview", "done"),), today=date(2026, 9, 12), instruction="from tomorrow two hours")
    request = transport.requests[0]
    assert request.mode == "reforecast" and request.today == date(2026, 9, 12)
    assert request.evidence_summary[0].status == "done"
```

Route tests in `test_routes.py`: fake service returns a proposal; `POST /api/v1/roadmap-imports/3/scheme-proposals` -> 200 with the three fields; when the fake raises `PlannerUnavailable` -> 503 problem code `planner_unavailable`; `POST /api/v1/roadmap-imports/3/scheme` with an invalid yaml -> 422 problem `invalid_roadmap_scheme`.

- [ ] **Step 2: Run, implement, run**

The `BoundedClaudeRuntime` transport adapter: a tiny class whose `invoke(run, repair_errors)` calls `transport.propose(request_with_repair_errors)` and returns `TransportResult(payload, turns=1)`. Validator: `lambda payload: validate_scheme(scheme_from_payload(payload), files=..., config=...)` wrapped to return a tuple of strings (a `SchemeValidationError` becomes a one-item tuple). Note `AgentOutputInvalid` after one repair -> proposal with `issues=("output did not satisfy the scheme after one repair",)`.

`attach_scheme` in the service: read the stored snapshot (`_open_package`), build `files` plus `roadmap.yaml`, `parse_roadmap`, write a new snapshot object (`inspect_zip_stream` over a rebuilt zip; reuse the staging code path used by `stage_import`), then `repository.replace_validation(import_id, object_key, package_hash, manifest, validation_report, semantic_diff)`. Only imports in `validated` or `validation_failed` status accept a scheme.

`stage_reforecast`: same, starting from the version's snapshot (`RoadmapVersion.object_key`; confirm the column name in `models.py`), creating a fresh `RoadmapImport` for the same source with idempotency key `f"reforecast:{version_id}:{sha256(yaml)}"`.

Run: `uv run pytest apps/backend/tests/unit/roadmaps -q`; regenerate the OpenAPI document and refreeze the hash (same as Task 3 Step 4).

- [ ] **Step 3: Evals**

Add two cases to `apps/backend/src/tamforge_backend/evals/cases.py` following its existing shape: `planner_refuses_invalid_budget` and `planner_reforecast_keeps_done_blocks_out` (the proposal must not contain a block id that evidence marks done). Run `uv run pytest apps/backend/tests/evals -q`.

- [ ] **Step 4: Commit, push, PR "feat(roadmaps): F1-4 planner role proposes and reforecasts schemes (#273)"**

---

### Task 7: macOS: scheme summary, Generate, Reforecast, in-app editing, Export (F1-5, #274)

**Files:**
- Modify: `apps/macos/TAMForge/Features/Roadmaps/RoadmapService.swift` (protocol + live: `proposeScheme(importID:mode:instruction:)`, `proposeReforecast(versionID:instruction:)`, `attachScheme(importID:yaml:)`, `stageReforecast(versionID:yaml:)`, `exportVersion(versionID:) -> Data`)
- Modify: `apps/macos/TAMForge/Features/Roadmaps/RoadmapAdministrationModel.swift` (`schemeProposal: SchemeProposal?`, `schemeDraft: String`, `generateScheme()`, `attachScheme()`, `reforecast()`, `exportActive()`)
- Modify: `apps/macos/TAMForge/Features/Roadmaps/RoadmapAdministrationView.swift` (scheme summary rows in "2. Validation"; a "Scheme" group with the editor, Generate/Attach buttons; Reforecast and Export buttons in "4.")
- Modify: `apps/macos/TAMForge/App/NativeParityUIFixture.swift` and `NativeUIFixtures.swift` (routes for the new endpoints; the parity journey stays green)
- Modify: `apps/macos/TAMForgeUITests/TAMForgeUITests.swift` (assert the scheme summary text "2 study days" appears in the parity fixture)
- Backend: `GET /api/v1/roadmap-versions/{version_id}/export` returns the stored snapshot zip plus `roadmap.yaml` (`application/zip`) — add it in this task with a unit route test.
- Test: `apps/macos/TAMForgeTests/RoadmapAdministrationModelTests.swift` (append: generate stores the proposal, attach re-stages, unavailable planner shows the message)

**Interfaces:**
- Consumes: Task 6 endpoints and `scheme_summary` from Task 3 (`validation_report["scheme_summary"]`, `RoadmapVersionResponse.scheme_summary`).
- Produces: `struct SchemeProposal: Codable, Equatable, Sendable { let yamlText: String; let summary: RoadmapJSONValue; let issues: [String] }`.

- [ ] **Step 1: Failing model tests**

```swift
func testGenerateStoresTheProposalAndDraft() async {
    let service = FakeRoadmapService()
    service.proposal = SchemeProposal(yamlText: "schema_version: 1\n", summary: .object(["study_days": .integer(2)]), issues: [])
    let model = RoadmapAdministrationModel(service: service)
    model.setStagedImportForTesting(.validated(id: 17))
    await model.generateScheme(instruction: "three hours a day")
    XCTAssertEqual(model.schemeDraft, "schema_version: 1\n")
    XCTAssertNil(model.errorMessage)
}

func testPlannerUnavailableShowsAnActionableMessage() async {
    let service = FakeRoadmapService()
    service.error = .problem(statusCode: 503, code: "planner_unavailable")
    let model = RoadmapAdministrationModel(service: service)
    model.setStagedImportForTesting(.validated(id: 17))
    await model.generateScheme(instruction: "")
    XCTAssertEqual(model.errorMessage, "The planner needs Claude enabled on the server.")
}
```

Look at the existing `FakeRoadmapService` in the tests folder and extend it with `proposal`, `error`, `attached`, `exported` fields.

- [ ] **Step 2: Run (`xcodebuild ... -only-testing:TAMForgeTests/RoadmapAdministrationModelTests test`), implement, run**

View changes: in `validationReport`, after the metrics `HStack`, when `report["scheme_summary"]` is a non-empty object show `"\(studyDays) study days"` and a compact list "Day 1: 120 min, 3 blocks" (first 7 days, then "…"). Add `GroupBox("3. Scheme")` with a `TextEditor` bound to `model.schemeDraft` (monospaced, 200 pt tall), a `TextField("Instruction for the planner")`, buttons "Generate with AI" (disabled when no staged import), "Attach scheme" (disabled when draft empty), and the proposal's `issues` listed in red. In "4." add "Reforecast…" (opens the same editor prefilled from the proposal) and "Export package" (`NSSavePanel`, writes the `Data` from `exportVersion`). Renumber the later group boxes.

- [ ] **Step 3: Parity fixture and UI test**

Add the routes to `NativeParityUIFixture.swift`: `POST /api/v1/roadmap-imports/17/scheme-proposals` -> `{"yaml_text": "schema_version: 1\n...", "summary": {"study_days": 1}, "issues": []}`; `POST /api/v1/roadmap-imports/17/scheme` -> the validated import payload with `scheme_summary`; `GET /api/v1/roadmap-versions/8/export` -> a tiny zip body. Keep the existing journey unchanged except one added assertion after "Validation passed": `XCTAssertTrue(textContaining("1 study day", in: app).waitForExistence(timeout: underLoadTimeout))` once the fixture's validation report carries `scheme_summary`.

- [ ] **Step 4: Full native check**

Run: `make macos-check` (build + unit tests) and the parity UI test locally: `xcodebuild ... -only-testing:TAMForgeUITests/TAMForgeUITests/testNativeFoundationParityJourney test` with the screen unlocked.

- [ ] **Step 5: Commit, push, PR "feat(macos): F1-5 scheme summary, planner proposals, in-app editing and export (#274)"**

---

## Self-review notes

- Spec coverage: scheme file and rules (Task 1), calendar (Task 4), import pipeline and stored scheme (Tasks 2, 3), AI assistance with validation before display (Task 6), macOS without vault write-back (Task 7), migration of the two known plans (Task 5), testing sections (each task). Retiring the v1 path and Frank's production import are F1-6 and out of this plan on purpose.
- Names used across tasks: `parse_roadmap`, `ParsedRoadmap.scheme`, `validate_scheme`, `scheme_from_payload`, `study_day_number`, `budget_for_day`, `scheme_for_version`, `PlannerService`, `SchemeProposal`, `scheme_summary`.
