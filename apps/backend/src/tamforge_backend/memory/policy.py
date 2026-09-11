"""Who decides what becomes a memory. Not the model.

An agent that writes what it likes into the learner's memory will, sooner or later, write
something the learner never said, promote one bad afternoon into a personality, or
carry an instruction it read in a transcript as if the learner had given it. So the
policy is a table, applied to the proposal's shape and provenance, and the model's prose
never picks its own outcome.

Four outcomes and nothing in between. A verified system or evidence fact writes itself.
An explicit learner preference writes itself if the words the learner used are quoted. A
pattern an agent noticed becomes a hypothesis and stays one until evidence confirms it,
and a single event never creates a trait, however confident the agent sounds. Anything
about the person that the learner did not say, anything sensitive, waits for the learner
to approve it. A claim with no provenance, a claim written while the Coach is speaking
about the current answer, or a claim that is really an instruction found inside a
transcript, is rejected and the rejection is recorded.

Every outcome carries a reason code, how long the memory may live, who may see it, and
how much evidence it needs, so a reviewer can read the decision without rereading the
policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Final, Literal

from tamforge_protocol.memory import EvidenceKind, MemoryKind, Role, Sensitivity

Decision = Literal["AUTO_ACCEPT", "STORE_HYPOTHESIS", "REQUIRE_USER_APPROVAL", "REJECT"]

ReasonCode = Literal[
    "verified_fact",
    "explicit_preference",
    "agent_pattern",
    "single_event_not_a_trait",
    "sensitive_inference",
    "personal_inference",
    "no_provenance",
    "no_evidence",
    "coach_mode_current_content",
    "transcript_instruction",
    "unknown_author",
]

Origin = Literal["system", "evidence", "learner_statement", "agent_inference"]

# Evidence kinds that count as verified: the system saw it happen, or a graded artifact
# exists. A conversation is a source, not a verification.
VERIFIED_EVIDENCE: Final[frozenset[EvidenceKind]] = frozenset({"activity", "assessment", "report"})

# What a claim needs before it may be treated as a trait rather than a moment.
MIN_EVENTS_FOR_TRAIT: Final = 3

# Lifetimes. An episode is permanent; the rest expire unless renewed by new evidence.
RETENTION: Final[dict[MemoryKind, timedelta | None]] = {
    "episodic": None,
    "semantic": timedelta(days=180),
    "hypothesis": timedelta(days=30),
    "procedural": timedelta(days=365),
}

# Text that reads as an instruction to the system rather than a fact about the learner.
_INSTRUCTION = re.compile(
    r"^\s*(ignore|disregard|forget|remember that you|from now on|you must|always say|never say|"
    r"system prompt|as an ai|override)\b",
    re.IGNORECASE,
)
_SENSITIVE_TOPICS = re.compile(
    r"\b(health|medical|diagnos|pregnan|religio|politic|ethnic|sexual|disabilit|salary|visa|"
    r"immigration|mental|therapy|divorce)\w*",
    re.IGNORECASE,
)


class PolicyError(ValueError):
    """A proposal shaped so that no policy row applies."""


@dataclass(frozen=True, slots=True)
class MemoryProposal:
    """What an agent (or the system) asks to remember, before any policy runs."""

    kind: MemoryKind
    claim: str
    origin: Origin
    author: Role | Literal["system", "learner"]
    model_run_id: int | None
    evidence_kinds: tuple[EvidenceKind, ...]
    event_count: int
    sensitivity: Sensitivity
    quoted_source: str | None = None
    coach_mode_current_answer: bool = False
    about_the_person: bool = False

    def __post_init__(self) -> None:
        if not self.claim.strip():
            raise PolicyError("an empty claim proposes nothing")
        if self.event_count < 0:
            raise PolicyError("event_count cannot be negative")
        if self.author not in ("system", "learner") and self.model_run_id is None:
            raise PolicyError("an agent proposal names the model run that produced it")


@dataclass(frozen=True, slots=True)
class PolicyOutcome:
    decision: Decision
    reason: ReasonCode
    stored_kind: MemoryKind | None
    retention: timedelta | None
    visible_to: frozenset[Role]
    required_evidence: int

    @property
    def writes(self) -> bool:
        return self.decision in ("AUTO_ACCEPT", "STORE_HYPOTHESIS")


_ALL_ROLES: Final[frozenset[Role]] = frozenset({"planner", "tutor", "coach", "reviewer", "analyst"})
# The Interviewer never reads memory; it is excluded from every visibility set here.
_LEARNER_FACING: Final[frozenset[Role]] = frozenset({"tutor", "coach", "planner"})


def _reject(reason: ReasonCode) -> PolicyOutcome:
    return PolicyOutcome(
        decision="REJECT",
        reason=reason,
        stored_kind=None,
        retention=None,
        visible_to=frozenset(),
        required_evidence=0,
    )


def decide(proposal: MemoryProposal) -> PolicyOutcome:
    """The table. Rows are checked in the order a reviewer would ask the questions."""
    # Refusals first: nothing below may override them.
    if proposal.coach_mode_current_answer:
        return _reject("coach_mode_current_content")
    if _INSTRUCTION.search(proposal.claim):
        return _reject("transcript_instruction")
    if proposal.author not in ("system", "learner") and proposal.author not in _ALL_ROLES:
        return _reject("unknown_author")
    if proposal.origin == "agent_inference" and proposal.model_run_id is None:
        return _reject("no_provenance")
    if not proposal.evidence_kinds:
        return _reject("no_evidence")

    sensitive = proposal.sensitivity == "real_interview" or bool(
        _SENSITIVE_TOPICS.search(proposal.claim)
    )

    # Verified system or evidence facts write themselves.
    if (
        proposal.origin in ("system", "evidence")
        and set(proposal.evidence_kinds) & VERIFIED_EVIDENCE
    ):
        if sensitive:
            return PolicyOutcome(
                decision="REQUIRE_USER_APPROVAL",
                reason="sensitive_inference",
                stored_kind=proposal.kind,
                retention=RETENTION[proposal.kind],
                visible_to=_LEARNER_FACING,
                required_evidence=1,
            )
        return PolicyOutcome(
            decision="AUTO_ACCEPT",
            reason="verified_fact",
            stored_kind=proposal.kind,
            retention=RETENTION[proposal.kind],
            visible_to=_ALL_ROLES,
            required_evidence=1,
        )

    # The learner said so, and the words are kept.
    if proposal.origin == "learner_statement" and proposal.quoted_source:
        if sensitive:
            return PolicyOutcome(
                decision="REQUIRE_USER_APPROVAL",
                reason="sensitive_inference",
                stored_kind=proposal.kind,
                retention=RETENTION[proposal.kind],
                visible_to=_LEARNER_FACING,
                required_evidence=1,
            )
        return PolicyOutcome(
            decision="AUTO_ACCEPT",
            reason="explicit_preference",
            stored_kind=proposal.kind,
            retention=RETENTION[proposal.kind],
            visible_to=_LEARNER_FACING,
            required_evidence=1,
        )
    if proposal.origin == "learner_statement":
        return _reject("no_provenance")

    # An agent noticed something.
    if sensitive or proposal.about_the_person:
        return PolicyOutcome(
            decision="REQUIRE_USER_APPROVAL",
            reason="sensitive_inference" if sensitive else "personal_inference",
            stored_kind="hypothesis",
            retention=RETENTION["hypothesis"],
            visible_to=frozenset({"coach"}),
            required_evidence=MIN_EVENTS_FOR_TRAIT,
        )
    if proposal.event_count < MIN_EVENTS_FOR_TRAIT and proposal.kind != "episodic":
        return PolicyOutcome(
            decision="STORE_HYPOTHESIS",
            reason="single_event_not_a_trait",
            stored_kind="hypothesis",
            retention=RETENTION["hypothesis"],
            visible_to=_LEARNER_FACING,
            required_evidence=MIN_EVENTS_FOR_TRAIT,
        )
    return PolicyOutcome(
        decision="STORE_HYPOTHESIS",
        reason="agent_pattern",
        stored_kind="hypothesis",
        retention=RETENTION["hypothesis"],
        visible_to=_LEARNER_FACING,
        required_evidence=MIN_EVENTS_FOR_TRAIT,
    )


__all__ = [
    "MIN_EVENTS_FOR_TRAIT",
    "RETENTION",
    "VERIFIED_EVIDENCE",
    "Decision",
    "MemoryProposal",
    "Origin",
    "PolicyError",
    "PolicyOutcome",
    "ReasonCode",
    "decide",
]
