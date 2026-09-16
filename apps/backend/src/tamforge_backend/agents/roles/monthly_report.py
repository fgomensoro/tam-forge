"""The monthly report: every skill against its baseline, month-one and final targets.

The analyst reads what the month left in the ledger: each skill's estimate at the start
and the end of the month, the targets from the configuration, the coverage ledger, the
Saturday assessments, the real interviews and the English classes. It writes the
trajectory with the largest gaps first and a recommendation for the next month, as a
proposal. It never changes the plan and never claims to have recorded anything.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
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

MONTHLY_REPORT_SCHEMA_ID = "urn:tamforge:schema:monthly-report-v1"
MONTHLY_REPORT_JOB_TYPE = "claude.monthly_report"
MONTHLY_REPORT_MAX_TURNS = 4
MONTHLY_REPORT_WALL_TIME_SECONDS = 420.0
MONTHLY_REPORT_PROMPT_VERSION = "v1"
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


class MonthlyReportUnavailable(RoleContractError):
    """Claude is disabled or the runtime failed; the month stays without its report."""


@dataclass(frozen=True, slots=True)
class MonthlySkillInput:
    """One skill's month, with the targets it is measured against; gaps are computed here."""

    slug: str
    name: str
    baseline: Decimal
    month_one_target: Decimal
    final_target: Decimal
    level_at_start: Decimal
    level_at_end: Decimal
    events_this_month: int

    @property
    def gap_to_month_one(self) -> Decimal:
        return self.month_one_target - self.level_at_end

    @property
    def gap_to_final(self) -> Decimal:
        return self.final_target - self.level_at_end


@dataclass(frozen=True, slots=True)
class MonthlyReportRequest:
    month_start: date
    month_end: date
    skills: tuple[MonthlySkillInput, ...]
    aggregates: Mapping[str, object]
    coverage: Mapping[str, object] | None = None
    assessments: tuple[str, ...] = ()
    interviews: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    repair_errors: tuple[str, ...] = ()


class SkillTrajectory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    skill_slug: str = Field(min_length=1, max_length=64)
    status: Literal["ahead", "on_track", "behind", "no_evidence"]
    note: str = Field(min_length=1, max_length=400)


class MonthlyReportOutcome(BaseModel):
    """The only shape a monthly report may take."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    headline: str = Field(min_length=1, max_length=300)
    trajectory: tuple[SkillTrajectory, ...] = Field(min_length=1, max_length=20)
    largest_gaps: tuple[str, ...] = Field(min_length=1, max_length=5)
    coverage_verdict: str = Field(min_length=1, max_length=600)
    exit_criteria_verdict: str = Field(min_length=1, max_length=600)
    best_evidence: tuple[str, ...] = Field(max_length=8)
    recommendation: Literal["keep", "reforecast", "change_scheme"]
    recommendation_reasoning: str = Field(min_length=1, max_length=1000)
    next_month_priorities: tuple[str, ...] = Field(min_length=1, max_length=5)


class MonthlyReportTransport(Protocol):
    async def monthly_report(self, request: MonthlyReportRequest) -> Mapping[str, object]: ...


def validate_monthly_report(
    payload: Mapping[str, object], *, skills: Sequence[MonthlySkillInput]
) -> tuple[str, ...]:
    """Issues by name; empty means the report may be stored."""
    try:
        outcome = MonthlyReportOutcome.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "report"
        return (f"report {location}: {first['msg']}",)
    expected = sorted(skill.slug for skill in skills)
    if sorted(item.skill_slug for item in outcome.trajectory) != expected:
        return ("the trajectory lists every skill exactly once: " + ", ".join(expected),)
    known = set(expected)
    for gap in outcome.largest_gaps:
        if gap not in known:
            return (f"largest_gaps names a skill outside the catalog: {gap}",)
    if len(set(outcome.largest_gaps)) != len(outcome.largest_gaps):
        return ("largest_gaps lists each skill once",)
    # The largest gaps are a fact of the ledger, not an opinion: they must be the skills
    # farthest from their month-one target, in that order.
    ranked = [
        s.slug
        for s in sorted(skills, key=lambda s: (-s.gap_to_month_one, s.slug))
        if s.gap_to_month_one > 0
    ]
    if ranked and list(outcome.largest_gaps) != ranked[: len(outcome.largest_gaps)]:
        return ("largest_gaps must be the skills farthest from their month-one target, in order",)
    lowered = " ".join(
        [
            outcome.headline,
            outcome.coverage_verdict,
            outcome.exit_criteria_verdict,
            outcome.recommendation_reasoning,
        ]
        + list(outcome.best_evidence + outcome.next_month_priorities)
        + [item.note for item in outcome.trajectory]
    ).lower()
    for marker in PLAN_CHANGE_MARKERS:
        if marker in lowered:
            return ("the report recommends; it never applies a change or records anything",)
    return ()


@dataclass
class _MonthlyReportRuntimeAdapter:
    transport: MonthlyReportTransport
    request: MonthlyReportRequest

    async def invoke(
        self, run: PreparedAgentRun, *, repair_errors: tuple[str, ...] = ()
    ) -> TransportResult:
        del run
        request = MonthlyReportRequest(
            month_start=self.request.month_start,
            month_end=self.request.month_end,
            skills=self.request.skills,
            aggregates=self.request.aggregates,
            coverage=self.request.coverage,
            assessments=self.request.assessments,
            interviews=self.request.interviews,
            classes=self.request.classes,
            repair_errors=repair_errors,
        )
        payload = await self.transport.monthly_report(request)
        return TransportResult(payload=payload, turns=1)


class MonthlyReportService:
    def __init__(self, transport: MonthlyReportTransport | None, *, model: str) -> None:
        self._transport = transport
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def compose(self, request: MonthlyReportRequest) -> MonthlyReportOutcome:
        """One bounded report, or a contract error the caller renders as such."""
        if not request.skills:
            raise RoleContractError("the monthly report needs the skill catalog with targets")
        if request.month_end < request.month_start:
            raise RoleContractError("the month ends before it starts")
        prepare_role_prompt(
            AgentRole.ANALYST, committed=True, requested_context=(EVIDENCE_SUMMARY,)
        )
        if self._transport is None:
            raise MonthlyReportUnavailable("the monthly report needs Claude enabled on the server")
        runtime = BoundedClaudeRuntime(
            _MonthlyReportRuntimeAdapter(self._transport, request),
            validate=lambda payload: validate_monthly_report(payload, skills=request.skills),
        )
        digest = hashlib.sha256(
            f"{request.month_start.isoformat()}:"
            f"{[(s.slug, str(s.level_at_end)) for s in request.skills]!r}".encode()
        ).hexdigest()[:24]
        prepared = PreparedAgentRun(
            run_key=f"monthly-report:{request.month_start.isoformat()}:{digest}",
            job_type=MONTHLY_REPORT_JOB_TYPE,
            model=self._model,
            schema_id=MONTHLY_REPORT_SCHEMA_ID,
            prompt_version=MONTHLY_REPORT_PROMPT_VERSION,
            max_turns=MONTHLY_REPORT_MAX_TURNS,
            wall_time_seconds=MONTHLY_REPORT_WALL_TIME_SECONDS,
        )
        try:
            result = await runtime.run(prepared)
        except AgentOutputInvalid:
            raise MonthlyReportUnavailable("the report did not return a valid outcome") from None
        except AgentRuntimeError as exc:
            raise MonthlyReportUnavailable(str(exc)) from None
        return MonthlyReportOutcome.model_validate(result.payload)


def monthly_report_schema() -> dict[str, object]:
    return MonthlyReportOutcome.model_json_schema()


def render_monthly_report_prompt(request: MonthlyReportRequest) -> str:
    """The prompt the SDK transport sends: targets, estimates and aggregates, never audio."""
    ranked = sorted(request.skills, key=lambda s: (-s.gap_to_month_one, s.slug))
    lines: list[str] = [
        f"Month {request.month_start.isoformat()} to {request.month_end.isoformat()}.",
        "Skills against their targets, largest gap to the month-one target first "
        "(baseline / month-one target / final target; estimate at the start of the month -> "
        "at its end; scored events this month; gap to month-one; gap to final):\n"
        + "\n".join(
            f"- {s.slug}: {s.name}; {s.baseline} / {s.month_one_target} / {s.final_target}; "
            f"{s.level_at_start} -> {s.level_at_end}; {s.events_this_month} events; "
            f"gap {s.gap_to_month_one}; final gap {s.gap_to_final}"
            for s in ranked
        ),
        "Aggregates:\n" + "\n".join(f"- {k}: {v}" for k, v in request.aggregates.items()),
    ]
    if request.coverage:
        lines.append(
            "Coverage ledger:\n" + "\n".join(f"- {k}: {v}" for k, v in request.coverage.items())
        )
    if request.assessments:
        lines.append("Saturday assessments:\n" + "\n".join(f"- {a}" for a in request.assessments))
    if request.interviews:
        lines.append("Real interviews:\n" + "\n".join(f"- {i}" for i in request.interviews))
    if request.classes:
        lines.append("English classes:\n" + "\n".join(f"- {c}" for c in request.classes))
    lines.append(
        "Write the month: a headline; every skill above exactly once with a status (ahead, "
        "on_track, behind, no_evidence) and a one-line note; largest_gaps as the skill slugs "
        "farthest from their month-one target in the order given above (only those with a "
        "positive gap, at most five); a coverage verdict and an exit-criteria verdict from "
        "the ledger; the best evidence of the month; a recommendation (keep, reforecast, "
        "change_scheme) with its reasoning; and the next month's priorities. Never apply a "
        "change and never claim to have recorded or scheduled anything."
    )
    if request.repair_errors:
        lines.append(
            "Your previous answer was refused; fix these:\n"
            + "\n".join(f"- {error}" for error in request.repair_errors)
        )
    return "\n\n".join(lines)


__all__ = [
    "MONTHLY_REPORT_JOB_TYPE",
    "MONTHLY_REPORT_PROMPT_VERSION",
    "MONTHLY_REPORT_SCHEMA_ID",
    "MonthlyReportOutcome",
    "MonthlyReportRequest",
    "MonthlyReportService",
    "MonthlyReportTransport",
    "MonthlyReportUnavailable",
    "MonthlySkillInput",
    "SkillTrajectory",
    "monthly_report_schema",
    "render_monthly_report_prompt",
    "validate_monthly_report",
]
