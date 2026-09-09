"""Claude is off unless stored evidence says it may run. Absence is never permission."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import model_validator

from .contracts import Contract

# The Anthropic data policy version this build expects. Bump it when the policy
# changes; every earlier attestation stops being current at that moment, which is
# what the runbook's policy check exists to catch.
EXPECTED_POLICY_VERSION = "anthropic-data-policy-2026-09"

DISABLED_REASONS = (
    "not_enabled",
    "attestation_missing",
    "attestation_superseded",
)


class AttestationRecord(Contract):
    """Both claims are affirmative by construction; a negative one is not an attestation."""

    policy_version: str
    model_improvement_disabled: bool
    subscription_policy_acknowledged: bool

    @model_validator(mode="after")
    def affirmative(self) -> Self:
        if not (self.model_improvement_disabled and self.subscription_policy_acknowledged):
            raise ValueError("an attestation asserts both claims or is not one")
        return self


def attestation_is_current(record: AttestationRecord) -> bool:
    return record.policy_version == EXPECTED_POLICY_VERSION


def claude_availability(
    *, enabled: bool, stored: AttestationRecord | None
) -> tuple[Literal["disabled", "ready"], str]:
    """Report status and a machine-only reason. Never raises, never names a secret."""
    if not enabled:
        return "disabled", "not_enabled"
    if stored is None:
        return "disabled", "attestation_missing"
    if not attestation_is_current(stored):
        return "disabled", "attestation_superseded"
    return "ready", "none"
