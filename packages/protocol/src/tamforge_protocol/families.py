"""Readiness per interview family, and why one good answer is not readiness.

Seventeen families, because that is what the interviews actually are: a recruiter screen
and a final panel are not the same exercise and being good at one says little about the
other.

Within a family, readiness is about transfer rather than repetition. Answering the same
question well to the same audience under the same conditions, twice, is evidence of
having answered it before. So the states climb on variation: practised once, transferred
when the same competence held with a different audience, ready when it also held under
pressure. Nothing here counts assisted work at all, which is why the independence flag is
a single-valued literal rather than a check somebody can forget.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

PositiveId = Annotated[int, Field(strict=True, gt=0)]

InterviewFamily = Literal[
    "recruiter_screen",
    "introduction_motivation",
    "hiring_manager_judgment",
    "behavioral_leadership",
    "api_integration_fundamentals",
    "sql_reconciliation",
    "technical_troubleshooting",
    "production_incidents",
    "integration_system_design",
    "customer_discovery",
    "implementation_launch",
    "executive_communication",
    "account_strategy_qbr",
    "portfolio_prioritization",
    "presentation_take_home",
    "cross_functional_conflict",
    "final_panel_gauntlet",
]

INTERVIEW_FAMILIES: tuple[str, ...] = (
    "recruiter_screen",
    "introduction_motivation",
    "hiring_manager_judgment",
    "behavioral_leadership",
    "api_integration_fundamentals",
    "sql_reconciliation",
    "technical_troubleshooting",
    "production_incidents",
    "integration_system_design",
    "customer_discovery",
    "implementation_launch",
    "executive_communication",
    "account_strategy_qbr",
    "portfolio_prioritization",
    "presentation_take_home",
    "cross_functional_conflict",
    "final_panel_gauntlet",
)

Audience = Literal["peer", "hiring_manager", "executive", "cross_functional"]
Pressure = Literal["calm", "time_pressured", "challenged"]

# Anything other than calm is pressure. Readiness needs at least one of them, because an
# interview that never pushes back is not the interview anyone is preparing for.
PRESSURED = frozenset({"time_pressured", "challenged"})

FamilyReadiness = Literal["untested", "practiced", "transferred", "ready"]
READINESS_ORDER: tuple[FamilyReadiness, ...] = (
    "untested",
    "practiced",
    "transferred",
    "ready",
)

# Transfer means a second audience, not a second attempt.
AUDIENCES_FOR_TRANSFER = 2


class FamilyError(ValueError):
    """Readiness asked about something that is not one of the families."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TransferEvidence(_StrictModel):
    """One independent performance in one family, under one set of conditions."""

    event_id: PositiveId
    family: InterviewFamily
    audience: Audience
    pressure: Pressure
    # Single-valued on purpose: assisted work never contributes to readiness, and a
    # flag that can be False is a flag somebody sets False.
    independent: Literal[True] = True


def family_readiness(
    evidence: Iterable[TransferEvidence], *, family: str
) -> FamilyReadiness:
    """Where one family stands, from the evidence that names it."""
    if family not in INTERVIEW_FAMILIES:
        raise FamilyError("that is not one of the tracked interview families")
    relevant = [item for item in evidence if item.family == family]
    if not relevant:
        return "untested"
    audiences = {item.audience for item in relevant}
    pressured = {item.pressure for item in relevant if item.pressure in PRESSURED}
    if len(audiences) < AUDIENCES_FOR_TRANSFER:
        return "practiced"
    if not pressured:
        return "transferred"
    return "ready"


def readiness_across(
    evidence: Iterable[TransferEvidence],
) -> dict[str, FamilyReadiness]:
    """Every family, including the ones nothing has touched yet."""
    collected = tuple(evidence)
    return {family: family_readiness(collected, family=family) for family in INTERVIEW_FAMILIES}


__all__ = [
    "AUDIENCES_FOR_TRANSFER",
    "INTERVIEW_FAMILIES",
    "PRESSURED",
    "READINESS_ORDER",
    "Audience",
    "FamilyError",
    "FamilyReadiness",
    "InterviewFamily",
    "Pressure",
    "TransferEvidence",
    "family_readiness",
    "readiness_across",
]
