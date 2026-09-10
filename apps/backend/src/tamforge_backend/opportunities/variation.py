"""What a live opportunity may change about practice, and what it may never touch.

An interview next week is the best reason there will ever be to practise something
specific, and it is also the best reason there will ever be to quietly abandon the plan.
So the two are separated here rather than balanced.

Variation covers the surface: which scenario the prompt describes, who the learner is
speaking to, how much pressure they are under. Those are the things a real opportunity
genuinely tells you something about.

The spine is untouchable: the minutes the roadmap allocates, the coverage it requires,
the assessment days, and the exit criteria. `VariedPractice` holds the slice by reference
instead of copying its fields, so there is no version of those numbers for a variation to
edit. That is the whole design: the invariant is not checked, it is unrepresentable.
"""

from __future__ import annotations

from dataclasses import dataclass

from tamforge_protocol.families import Audience, InterviewFamily, Pressure
from tamforge_protocol.opportunities import Opportunity


class VariationError(ValueError):
    """A variation that would move the roadmap rather than the prompt."""


@dataclass(frozen=True, slots=True)
class RoadmapSlice:
    """The part of the plan a day is working through. None of this varies."""

    slice_key: str
    minutes: int
    required_families: tuple[InterviewFamily, ...]
    assessment_days: tuple[str, ...]
    exit_criteria_sha256: str

    def __post_init__(self) -> None:
        if self.minutes < 1:
            raise VariationError("a roadmap slice allocates time")
        if not self.required_families:
            raise VariationError("a roadmap slice requires coverage of something")
        if len(self.exit_criteria_sha256) != 64:
            raise VariationError("a roadmap slice pins its exit criteria")


@dataclass(frozen=True, slots=True)
class VariedPractice:
    """One session's surface, and the slice it is still working through.

    The slice is held rather than copied, so the minutes, coverage, assessment days and
    exit criteria a variation could otherwise edit simply do not exist here to edit.
    """

    slice: RoadmapSlice
    family: InterviewFamily
    scenario_key: str
    audience: Audience
    pressure: Pressure

    def __post_init__(self) -> None:
        if self.family not in self.slice.required_families:
            # Practising something the slice does not require is not variation, it is a
            # different plan wearing this one's name.
            raise VariationError("a variation stays inside the coverage the slice requires")
        if not self.scenario_key.strip():
            raise VariationError("a variation names the scenario it uses")

    @property
    def minutes(self) -> int:
        return self.slice.minutes

    @property
    def exit_criteria_sha256(self) -> str:
        return self.slice.exit_criteria_sha256


def vary_for_opportunity(
    slice_: RoadmapSlice,
    opportunity: Opportunity,
    *,
    family: InterviewFamily,
    audience: Audience,
    pressure: Pressure,
    owner_id: int,
) -> VariedPractice:
    """Shape a session around a live opportunity without touching the plan."""
    if opportunity.owner_id != owner_id:
        raise VariationError("this opportunity belongs to another owner")
    if opportunity.closed:
        # A closed opportunity is history. Letting it steer today's practice is how a
        # search that ended keeps deciding what someone works on.
        raise VariationError("a closed opportunity does not vary practice")
    return VariedPractice(
        slice=slice_,
        family=family,
        scenario_key=f"{opportunity.company}:{opportunity.current_stage}".lower(),
        audience=audience,
        pressure=pressure,
    )


__all__ = [
    "RoadmapSlice",
    "VariationError",
    "VariedPractice",
    "vary_for_opportunity",
]
