"""Interview day: what replaces practice, and what the last hour is protected from.

Two rules, and both are about subtraction.

Interview-day work is substituted into the study budget, never added to it. Company
preparation and the interview itself take their minutes out of the same day everything
else was going to use, because a day that grows to fit an interview is a day that ends
with the learner more tired going in, which is the opposite of the point.

And the final stretch before the interview is protected. New material and exhausting
practice are refused inside it; light review is allowed and so is nothing at all.
Cramming an hour before an interview trades a small chance of remembering one more thing
for a large chance of arriving spent.

Every read here is opportunity-scoped and owner-scoped, deferring to the protocol's own
checks rather than repeating them, so a schedule for one opportunity cannot be built from
another's interviews.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from tamforge_protocol.interviews import Interview
from tamforge_protocol.opportunities import Opportunity, OpportunityError, require_linked

# The protected stretch is between one hour and an hour and a half. Shorter stops being
# protection; longer starts eating the day it was meant to protect.
MIN_PROTECTION_MINUTES = 60
MAX_PROTECTION_MINUTES = 90

ActivityLoad = Literal["light_review", "new_practice", "exhausting_practice"]

# Only one of the three is allowed close to an interview.
ALLOWED_IN_PROTECTED_WINDOW: frozenset[str] = frozenset({"light_review"})


class SchedulingError(ValueError):
    """A day that cannot be scheduled as asked."""


class BudgetExceeded(SchedulingError):
    """Interview-day work does not fit inside the study budget."""


class ProtectedWindowViolation(SchedulingError):
    """Something demanding was scheduled into the stretch before the interview."""


@dataclass(frozen=True, slots=True)
class InterviewDayPlan:
    """What the day holds once the interview has taken its share of it."""

    budget_minutes: int
    preparation_minutes: int
    interview_minutes: int
    protection_minutes: int
    interview_at: datetime

    @property
    def remaining_practice_minutes(self) -> int:
        return self.budget_minutes - self.preparation_minutes - self.interview_minutes

    @property
    def protected_from(self) -> datetime:
        return self.interview_at - timedelta(minutes=self.protection_minutes)

    def protects(self, moment: datetime) -> bool:
        return self.protected_from <= moment < self.interview_at


def plan_interview_day(
    *,
    budget_minutes: int,
    preparation_minutes: int,
    interview_minutes: int,
    interview_at: datetime,
    protection_minutes: int = MAX_PROTECTION_MINUTES,
) -> InterviewDayPlan:
    """Fit the interview into the day's existing budget, or refuse to."""
    if interview_at.tzinfo is None or interview_at.utcoffset() is None:
        raise SchedulingError("the interview time must be timezone-aware")
    if budget_minutes < 1 or preparation_minutes < 0 or interview_minutes < 1:
        raise SchedulingError("a day needs a budget and the interview needs a length")
    if not MIN_PROTECTION_MINUTES <= protection_minutes <= MAX_PROTECTION_MINUTES:
        raise SchedulingError("the protected stretch is between 60 and 90 minutes")
    if preparation_minutes + interview_minutes > budget_minutes:
        # Substituted, not added. The day does not grow to fit the interview.
        raise BudgetExceeded("interview-day work does not fit inside the study budget")
    return InterviewDayPlan(
        budget_minutes=budget_minutes,
        preparation_minutes=preparation_minutes,
        interview_minutes=interview_minutes,
        protection_minutes=protection_minutes,
        interview_at=interview_at,
    )


def admit_activity(plan: InterviewDayPlan, *, starts_at: datetime, load: ActivityLoad) -> None:
    """Raise if this activity may not run when it wants to run."""
    if starts_at.tzinfo is None or starts_at.utcoffset() is None:
        raise SchedulingError("an activity start must be timezone-aware")
    if plan.protects(starts_at) and load not in ALLOWED_IN_PROTECTED_WINDOW:
        raise ProtectedWindowViolation(
            "new or exhausting practice may not run in the protected stretch"
        )


def preparation_interviews(
    opportunity: Opportunity, interviews: Iterable[Interview], *, owner_id: int
) -> tuple[Interview, ...]:
    """The interviews this opportunity may be prepared from, and no others.

    The link check is the protocol's own, so this cannot drift from it, and an interview
    belonging elsewhere raises rather than being quietly filtered out: a schedule built
    from the wrong opportunity is a mistake worth hearing about.
    """
    selected = []
    for interview in interviews:
        if interview.owner_id != owner_id:
            raise OpportunityError("this interview belongs to another owner")
        if interview.opportunity_id != opportunity.opportunity_id:
            continue
        require_linked(opportunity, interview_id=interview.interview_id, owner_id=owner_id)
        selected.append(interview)
    return tuple(selected)


__all__ = [
    "ALLOWED_IN_PROTECTED_WINDOW",
    "MAX_PROTECTION_MINUTES",
    "MIN_PROTECTION_MINUTES",
    "ActivityLoad",
    "BudgetExceeded",
    "InterviewDayPlan",
    "ProtectedWindowViolation",
    "SchedulingError",
    "admit_activity",
    "plan_interview_day",
    "preparation_interviews",
]
