"""Proposals in, ledger revisions out, and every step recorded.

The policy says what a proposal may become; this service makes it so without letting
anything skip the policy. An accepted proposal becomes an approved revision at once. A
hypothesis becomes a proposed hypothesis revision and stays one until enough evidence
has accumulated to promote it, at which point a new semantic memory is written that names
the hypothesis it came from; the hypothesis itself is never edited into a fact. A proposal
that needs the learner waits as a pending item and becomes a revision only when the
learner approves it; a rejection is kept, with its reason, so the same claim is not
proposed again as if it were new.

Conflicts and corrections go through the ledger's own rules: a correction is a new
revision that supersedes the current one, a contradiction is an explicit link, and an
expiry is a revision with a `valid_to`. Nothing here reaches into the ledger to change
what is already there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, cast

from tamforge_protocol.memory import (
    EvidenceLink,
    MemoryError,
    MemoryLedger,
    MemoryRevision,
    MemoryScope,
    Provenance,
    Role,
)

from .policy import MemoryProposal, PolicyOutcome, decide

ProposalStatus = Literal["written", "pending_approval", "rejected", "approved", "promoted"]


def _provenance(proposal: MemoryProposal) -> Provenance:
    # The ledger knows roles and the learner; a system fact is recorded as the learner's
    # own record (it is about them and verified), with no model run behind it.
    if proposal.author in ("learner", "system"):
        return Provenance(author="learner")
    return Provenance(author=cast(Role, proposal.author), model_run_id=proposal.model_run_id)


class ReviewError(ValueError):
    """A review action that the proposal's state does not allow."""


@dataclass(frozen=True, slots=True)
class ProposalRecord:
    proposal_id: int
    proposal: MemoryProposal
    outcome: PolicyOutcome
    status: ProposalStatus
    revision_id: int | None
    decided_at: datetime
    reviewed_by: str | None = None
    promoted_to_revision_id: int | None = None


@dataclass
class MemoryReview:
    """In-memory orchestration over an immutable ledger; the SQL store mirrors this shape."""

    ledger: MemoryLedger = field(default_factory=MemoryLedger)
    records: dict[int, ProposalRecord] = field(default_factory=dict)
    _next_proposal: int = 1
    _next_memory: int = 1
    _next_revision: int = 1

    def _write(
        self,
        proposal: MemoryProposal,
        outcome: PolicyOutcome,
        *,
        now: datetime,
        approval: Literal["proposed", "approved"],
        evidence: tuple[EvidenceLink, ...],
        scope: MemoryScope = "global",
        scope_reference_id: int | None = None,
    ) -> MemoryRevision:
        assert outcome.stored_kind is not None
        revision = MemoryRevision(
            memory_id=self._next_memory,
            revision_id=self._next_revision,
            revision_number=1,
            kind=outcome.stored_kind,
            scope=scope,
            scope_reference_id=scope_reference_id,
            claim=proposal.claim,
            confidence=0.5 if outcome.stored_kind == "hypothesis" else 0.8,
            sensitivity=proposal.sensitivity,
            visible_to=outcome.visible_to,
            evidence=evidence,
            provenance=_provenance(proposal),
            valid_from=now,
            expires_at=(now + outcome.retention) if outcome.retention else None,
            approval=approval,
            recorded_at=now,
        )
        self.ledger = self.ledger.append(revision)
        self._next_memory += 1
        self._next_revision += 1
        return revision

    def propose(
        self,
        proposal: MemoryProposal,
        *,
        evidence: tuple[EvidenceLink, ...],
        now: datetime,
    ) -> ProposalRecord:
        outcome = decide(proposal)
        if len(evidence) < outcome.required_evidence and outcome.decision == "AUTO_ACCEPT":
            raise ReviewError("an accepted fact must cite the evidence it rests on")
        proposal_id = self._next_proposal
        self._next_proposal += 1
        revision_id: int | None = None
        status: ProposalStatus
        if outcome.decision == "AUTO_ACCEPT":
            revision_id = self._write(
                proposal, outcome, now=now, approval="approved", evidence=evidence
            ).revision_id
            status = "written"
        elif outcome.decision == "STORE_HYPOTHESIS":
            revision_id = self._write(
                proposal, outcome, now=now, approval="proposed", evidence=evidence
            ).revision_id
            status = "written"
        elif outcome.decision == "REQUIRE_USER_APPROVAL":
            status = "pending_approval"
        else:
            status = "rejected"
        record = ProposalRecord(
            proposal_id=proposal_id,
            proposal=proposal,
            outcome=outcome,
            status=status,
            revision_id=revision_id,
            decided_at=now,
        )
        self.records[proposal_id] = record
        return record

    def approve(
        self, proposal_id: int, *, by: str, evidence: tuple[EvidenceLink, ...], now: datetime
    ) -> ProposalRecord:
        record = self.records.get(proposal_id)
        if record is None or record.status != "pending_approval":
            raise ReviewError("only a pending proposal can be approved")
        if len(evidence) < record.outcome.required_evidence:
            needed = record.outcome.required_evidence
            raise ReviewError(f"approval needs {needed} pieces of evidence, got {len(evidence)}")
        # The learner confirmed it, so it is written as the fact that was proposed, not
        # as a hypothesis: the ledger never approves a guess.
        confirmed = PolicyOutcome(
            decision=record.outcome.decision,
            reason=record.outcome.reason,
            stored_kind="semantic"
            if record.proposal.kind == "hypothesis"
            else record.proposal.kind,
            retention=record.outcome.retention,
            visible_to=record.outcome.visible_to,
            required_evidence=record.outcome.required_evidence,
        )
        revision = self._write(
            record.proposal, confirmed, now=now, approval="approved", evidence=evidence
        )
        updated = ProposalRecord(
            proposal_id=proposal_id,
            proposal=record.proposal,
            outcome=record.outcome,
            status="approved",
            revision_id=revision.revision_id,
            decided_at=now,
            reviewed_by=by,
        )
        self.records[proposal_id] = updated
        return updated

    def reject(self, proposal_id: int, *, by: str, now: datetime) -> ProposalRecord:
        record = self.records.get(proposal_id)
        if record is None or record.status != "pending_approval":
            raise ReviewError("only a pending proposal can be rejected")
        updated = ProposalRecord(
            proposal_id=proposal_id,
            proposal=record.proposal,
            outcome=record.outcome,
            status="rejected",
            revision_id=None,
            decided_at=now,
            reviewed_by=by,
        )
        self.records[proposal_id] = updated
        return updated

    def promote(
        self, proposal_id: int, *, evidence: tuple[EvidenceLink, ...], now: datetime
    ) -> ProposalRecord:
        """A hypothesis with enough evidence becomes a new semantic memory; the hypothesis stays."""
        record = self.records.get(proposal_id)
        if (
            record is None
            or record.revision_id is None
            or record.outcome.stored_kind != "hypothesis"
        ):
            raise ReviewError("only a stored hypothesis can be promoted")
        if record.status == "promoted":
            raise ReviewError("already promoted")
        if len(evidence) < record.outcome.required_evidence:
            needed = record.outcome.required_evidence
            raise ReviewError(f"promotion needs {needed} pieces of evidence, got {len(evidence)}")
        hypothesis = self.ledger.current(self._memory_of(record.revision_id))
        assert hypothesis is not None
        semantic = PolicyOutcome(
            decision="AUTO_ACCEPT",
            reason="verified_fact",
            stored_kind="semantic",
            retention=record.outcome.retention,
            visible_to=record.outcome.visible_to,
            required_evidence=record.outcome.required_evidence,
        )
        revision = self._write(
            record.proposal, semantic, now=now, approval="approved", evidence=evidence
        )
        updated = ProposalRecord(
            proposal_id=proposal_id,
            proposal=record.proposal,
            outcome=record.outcome,
            status="promoted",
            revision_id=record.revision_id,
            decided_at=now,
            promoted_to_revision_id=revision.revision_id,
        )
        self.records[proposal_id] = updated
        return updated

    def correct(self, revision_id: int, *, claim: str, now: datetime) -> MemoryRevision:
        """A correction is a new revision superseding the current one; history stays readable."""
        memory_id = self._memory_of(revision_id)
        current = self.ledger.current(memory_id)
        if current is None or current.revision_id != revision_id:
            raise ReviewError("only the current revision of a memory can be corrected")
        revision = current.model_copy(
            update={
                "revision_id": self._next_revision,
                "revision_number": current.revision_number + 1,
                "supersedes_revision_id": current.revision_id,
                "claim": claim,
                "recorded_at": now,
            }
        )
        try:
            self.ledger = self.ledger.append(revision)
        except MemoryError as error:
            raise ReviewError(str(error)) from error
        self._next_revision += 1
        return revision

    def expire(self, revision_id: int, *, at: datetime, now: datetime) -> MemoryRevision:
        """Expiry is a revision with a valid_to, never a deletion."""
        memory_id = self._memory_of(revision_id)
        current = self.ledger.current(memory_id)
        if current is None or current.revision_id != revision_id:
            raise ReviewError("only the current revision of a memory can be expired")
        revision = current.model_copy(
            update={
                "revision_id": self._next_revision,
                "revision_number": current.revision_number + 1,
                "supersedes_revision_id": current.revision_id,
                "valid_to": at,
                "recorded_at": now,
            }
        )
        self.ledger = self.ledger.append(revision)
        self._next_revision += 1
        return revision

    def _memory_of(self, revision_id: int) -> int:
        for revision in self.ledger.revisions:
            if revision.revision_id == revision_id:
                return revision.memory_id
        raise ReviewError(f"revision {revision_id} is not in the ledger")


__all__ = ["MemoryReview", "ProposalRecord", "ProposalStatus", "ReviewError"]
