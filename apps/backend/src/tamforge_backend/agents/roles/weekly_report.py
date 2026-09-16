"""The weekly report: what the week did, learned and improved, the 14 skills, and suggestions.

The analyst reads structured aggregates the server already computed (minutes, closed days,
assessments, interviews, classes, the skill estimates and the coverage ledger), never raw
audio. It writes a report Frank reads on Sunday evening and suggests adjustments to the
plan; it never applies one, and never claims to have recorded or scheduled anything.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..runtime import (
    AgentOutputInvalid,
    AgentRuntimeError,
    BoundedClaudeRuntime,
    PreparedAgentRun,
    TransportResult,
)
from ..tools.registry import AgentRole
from .contracts import EVIDENCE_SUMMARY, RoleContractError, prepare_role_prompt

WEEKLY_REPORT_SCHEMA_ID = "urn:tamforge:schema:weekly-report-v1"
WEEKLY_REPORT_JOB_TYPE = "claude.weekly_report"
WEEKLY_REPORT_MAX_TURNS = 4
WEEKLY_REPORT_WALL_TIME_SECONDS = 300.0
WEEKLY_REPORT_PROMPT_VERSION = "v1"
PLAN_CHANGE_MARKERS = (
    "i changed the plan",
    "i updated the plan",
    "i rescheduled",
    "i moved the block",
    "i added a block",
    "i removed the block",
    "i marked",
    "i recorded",
    "i scheduled",
    "i completed",
    "i applied",
)


class WeeklyReportUnavailable(RoleContractError):
    """Claude is disabled or the runtime failed; the week stays without its report."""


@dataclass(frozen=True, slots=True)
class WeeklySkillInput:
    slug: str
    name: str
    level_at_start: str
    level_at_end: str
    events_this_week: int


@dataclass(frozen=True, slots=True)
class WeeklyReportRequest:
    week_start: date
    week_end: date
    skills: tuple[WeeklySkillInput, ...]
    aggregates: Mapping[str, object]
    assessments: tuple[str, ...] = ()
    interviews: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    coverage: Mapping[str, object] | None = None
    repair_errors: tuple[str, ...] = ()


class SkillLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    skill_slug: str = Field(min_length=1, max_length=64)
    direction: Literal["up", "flat", "down"]
    note: str = Field(min_length=1, max_length=300)


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    change: str = Field(min_length=1, max_length=400)
    reason: str = Field(min_length=1, max_length=400)
    skill_slug: str = Field(min_length=1, max_length=64)


class WeeklyReportOutcome(BaseModel):
    """The only shape a weekly report may take."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    headline: str = Field(min_length=1, max_length=300)
    did: tuple[str, ...] = Field(min_length=1, max_length=8)
    learned: tuple[str, ...] = Field(min_length=1, max_length=8)
    improved: tuple[str, ...] = Field(min_length=1, max_length=8)
    skills: tuple[SkillLine, ...] = Field(min_length=1, max_length=20)
    suggestions: tuple[Suggestion, ...] = Field(min_length=1, max_length=4)
    risks: tuple[str, ...] = Field(max_length=5)
    decision_for_frank: str = Field(min_length=1, max_length=400)


class WeeklyReportTransport(Protocol):
    async def weekly_report(self, request: WeeklyReportRequest) -> Mapping[str, object]: ...


def validate_weekly_report(
    payload: Mapping[str, object], *, skills: Sequence[WeeklySkillInput]
) -> tuple[str, ...]:
    """Issues by name; empty means the report may be stored."""
    try:
        outcome = WeeklyReportOutcome.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "report"
        return (f"report {location}: {first['msg']}",)
    expected = sorted(skill.slug for skill in skills)
    if sorted(line.skill_slug for line in outcome.skills) != expected:
        return ("the report lists every skill exactly once: " + ", ".join(expected),)
    for suggestion in outcome.suggestions:
        if suggestion.skill_slug not in expected:
            return (f"a suggestion names a skill outside the catalog: {suggestion.skill_slug}",)
    lowered = " ".join(
        [outcome.headline, outcome.decision_for_frank]
        + list(outcome.did + outcome.learned + outcome.improved + outcome.risks)
        + [s.change + " " + s.reason for s in outcome.suggestions]
        + [line.note for line in outcome.skills]
    ).lower()
    for marker in PLAN_CHANGE_MARKERS:
        if marker in lowered:
            return ("the report suggests changes; it never applies them or records anything",)
    return ()


@dataclass
class _WeeklyReportRuntimeAdapter:
    transport: WeeklyReportTransport
    request: WeeklyReportRequest

    async def invoke(
        self, run: PreparedAgentRun, *, repair_errors: tuple[str, ...] = ()
    ) -> TransportResult:
        del run
        request = WeeklyReportRequest(
            week_start=self.request.week_start,
            week_end=self.request.week_end,
            skills=self.request.skills,
            aggregates=self.request.aggregates,
            assessments=self.request.assessments,
            interviews=self.request.interviews,
            classes=self.request.classes,
            coverage=self.request.coverage,
            repair_errors=repair_errors,
        )
        payload = await self.transport.weekly_report(request)
        return TransportResult(payload=payload, turns=1)


class WeeklyReportService:
    def __init__(self, transport: WeeklyReportTransport | None, *, model: str) -> None:
        self._transport = transport
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def compose(self, request: WeeklyReportRequest) -> WeeklyReportOutcome:
        """One bounded report, or a contract error the caller renders as such."""
        if not request.skills:
            raise RoleContractError("the weekly report needs the skill catalog")
        if request.week_end < request.week_start:
            raise RoleContractError("the week ends before it starts")
        prepare_role_prompt(
            AgentRole.ANALYST, committed=True, requested_context=(EVIDENCE_SUMMARY,)
        )
        if self._transport is None:
            raise WeeklyReportUnavailable("the weekly report needs Claude enabled on the server")
        runtime = BoundedClaudeRuntime(
            _WeeklyReportRuntimeAdapter(self._transport, request),
            validate=lambda payload: validate_weekly_report(payload, skills=request.skills),
        )
        digest = hashlib.sha256(
            f"{request.week_start.isoformat()}:{sorted(request.aggregates.items())!r}".encode()
        ).hexdigest()[:24]
        prepared = PreparedAgentRun(
            run_key=f"weekly-report:{request.week_start.isoformat()}:{digest}",
            job_type=WEEKLY_REPORT_JOB_TYPE,
            model=self._model,
            schema_id=WEEKLY_REPORT_SCHEMA_ID,
            prompt_version=WEEKLY_REPORT_PROMPT_VERSION,
            max_turns=WEEKLY_REPORT_MAX_TURNS,
            wall_time_seconds=WEEKLY_REPORT_WALL_TIME_SECONDS,
        )
        try:
            result = await runtime.run(prepared)
        except AgentOutputInvalid:
            raise WeeklyReportUnavailable("the report did not return a valid outcome") from None
        except AgentRuntimeError as exc:
            raise WeeklyReportUnavailable(str(exc)) from None
        return WeeklyReportOutcome.model_validate(result.payload)


def weekly_report_schema() -> dict[str, object]:
    return WeeklyReportOutcome.model_json_schema()


def render_weekly_report_prompt(request: WeeklyReportRequest) -> str:
    """The prompt the SDK transport sends: aggregates only, never raw audio or transcripts."""
    lines: list[str] = [
        f"Week {request.week_start.isoformat()} to {request.week_end.isoformat()}.",
        "Aggregates:\n" + "\n".join(f"- {k}: {v}" for k, v in request.aggregates.items()),
        "Skills (estimate at the start of the week, at its end, and how many scored "
        "events landed this week):\n"
        + "\n".join(
            f"- {s.slug}: {s.name}; {s.level_at_start} -> {s.level_at_end}; "
            f"{s.events_this_week} events"
            for s in request.skills
        ),
    ]
    if request.assessments:
        lines.append("Saturday assessment:\n" + "\n".join(f"- {a}" for a in request.assessments))
    if request.interviews:
        lines.append("Real interviews:\n" + "\n".join(f"- {i}" for i in request.interviews))
    if request.classes:
        lines.append("English classes:\n" + "\n".join(f"- {c}" for c in request.classes))
    if request.coverage:
        lines.append(
            "Coverage ledger:\n" + "\n".join(f"- {k}: {v}" for k, v in request.coverage.items())
        )
    lines.append(
        "Write the week: a headline; what the learner did, learned and improved (short "
        "bullets); every skill above exactly once with a direction (up, flat, down) and a "
        "one-line note; one to four suggested adjustments to the plan, each with a reason "
        "and the skill it serves, phrased as proposals the learner may approve; the risks; "
        "and the one decision the learner has to make this week. Never apply a change and "
        "never claim to have recorded or scheduled anything."
    )
    if request.repair_errors:
        lines.append(
            "Your previous answer was refused; fix these:\n"
            + "\n".join(f"- {error}" for error in request.repair_errors)
        )
    return "\n\n".join(lines)


__all__ = [
    "WEEKLY_REPORT_JOB_TYPE",
    "WEEKLY_REPORT_PROMPT_VERSION",
    "WEEKLY_REPORT_SCHEMA_ID",
    "SkillLine",
    "Suggestion",
    "WeeklyReportOutcome",
    "WeeklyReportRequest",
    "WeeklyReportService",
    "WeeklyReportTransport",
    "WeeklyReportUnavailable",
    "WeeklySkillInput",
    "render_weekly_report_prompt",
    "validate_weekly_report",
    "weekly_report_schema",
]
