"""Whether Claude may run: stored evidence, configuration, and a content-free probe.

`claude_status` answers the first half from configuration and the stored attestation.
`probe_claude_compatibility` answers the second half by asking the installed runtime
what it is, and both halves have to agree before any Claude work is allowed.

The probe sends no owner content. It passes one requested model identifier and reads
back versions, an authentication method, a resolved model, and a fixed structured
echo, so running it cannot disclose a transcript, an attempt, or a prompt. It also
runs the configuration gate first and skips the runtime entirely when Claude is
disabled, because there is nothing to learn about a runtime nobody may call.

Every failure becomes a machine-readable reason plus nonsecret remediation. An
unexpected exception from the runtime is classified, never propagated and never
rendered: its message can carry a token or an endpoint, and the caller renders this
result.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from types import MappingProxyType
from typing import Literal, Protocol

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import ImmutableVersionConflict, InvalidProvenance
from .hashing import canonical_bytes
from .models import PrivacyAttestation
from .prompt_registry import verified
from .settings import DISABLED_REASONS, AttestationRecord, claude_availability


class AttestationSource(Protocol):
    """What `claude_status` needs; `AttestationRepository` satisfies it structurally."""

    async def current(self, *, owner_id: int) -> AttestationRecord | None: ...


class AttestationRepository:
    """Reads the stored attestation, and records one the operator has decided to make."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(self, *, owner_id: int, record: AttestationRecord) -> None:
        """Persist an attestation in the exact canonical bytes the table's checks demand.

        Without this the runbook would be asking a human to hand-write canonical JSON and
        its matching hash into an INSERT, which is not a procedure anyone can follow
        correctly, and the gate could never open.

        Re-attesting to the same policy version is idempotent: the unique constraint on
        (owner_id, policy_version) makes the second attempt a no-op rather than a
        duplicate, and the canonical bytes are identical for identical claims.
        """
        if type(owner_id) is not int or type(owner_id) is bool or owner_id <= 0:
            raise InvalidProvenance()
        record = AttestationRecord.model_validate(record.model_dump())
        payload = canonical_bytes(record.model_dump(mode="json"), limit=16384)
        try:
            async with self.session.begin():
                existing = await self.session.scalar(
                    select(PrivacyAttestation).where(
                        PrivacyAttestation.owner_id == owner_id,
                        PrivacyAttestation.policy_version == record.policy_version,
                    )
                )
                if existing is not None:
                    if verified(existing).canonical_json != payload.decode():
                        raise ImmutableVersionConflict()
                    return
                self.session.add(
                    PrivacyAttestation(
                        owner_id=owner_id,
                        canonical_json=payload.decode(),
                        content_hash=sha256(payload).digest(),
                    )
                )
        except SQLAlchemyError:
            raise InvalidProvenance() from None

    async def current(self, *, owner_id: int) -> AttestationRecord | None:
        if type(owner_id) is not int or owner_id <= 0:
            raise InvalidProvenance()
        try:
            async with self.session.begin():
                row = await self.session.scalar(
                    select(PrivacyAttestation)
                    .where(PrivacyAttestation.owner_id == owner_id)
                    .order_by(PrivacyAttestation.id.desc())
                    .limit(1)
                )
                if row is None:
                    return None
                payload = verified(row).canonical_json
        except SQLAlchemyError:
            raise InvalidProvenance() from None
        try:
            return AttestationRecord.model_validate(json.loads(payload))
        except (json.JSONDecodeError, ValidationError):
            # A broken attestation is not consent: treat it as none, not an error.
            return None


async def claude_status(
    *, repository: AttestationSource, owner_id: int, enabled: bool
) -> tuple[Literal["disabled", "ready"], str]:
    """Load the current attestation and delegate the decision to `claude_availability`."""
    stored = await repository.current(owner_id=owner_id)
    return claude_availability(enabled=enabled, stored=stored)


# The floor this build has been verified against. Bump it together with the runbook's
# policy check when a newer SDK becomes the supported one; a version below it is a
# blocked runtime rather than a silent best effort.
# The Agent SDK release this build is pinned against (apps/backend/pyproject.toml).
MINIMUM_SDK_VERSION = (0, 2, 152)

# The probe's whole payload. It carries no owner content by construction, and an
# exact match is what proves the structured-response path works end to end.
EXPECTED_STRUCTURED_RESPONSE: Mapping[str, object] = MappingProxyType(
    {"probe": "ok", "schema_version": 1}
)

SUBSCRIPTION_AUTHENTICATION = "subscription"

ProbeStatus = Literal["disabled", "blocked", "ready", "needs_attention"]

PROBE_REASONS: tuple[str, ...] = (
    "none",
    *DISABLED_REASONS,
    "sdk_not_installed",
    "sdk_version_unsupported",
    "authentication_missing",
    "authentication_not_subscription",
    "authentication_rejected",
    "model_unavailable",
    "structured_output_unsupported",
    "policy_rejected",
    "quota_exhausted",
    "probe_failed",
)

# Nonsecret, actionable, and safe to render anywhere: no token, endpoint, account or
# transcript text appears here or may be added later.
PROBE_REMEDIATION: Mapping[str, str] = MappingProxyType(
    {
        "none": "No action required. Claude work may run.",
        "not_enabled": "Set TAMFORGE_CLAUDE_ENABLED once the runbook's activation steps are done.",
        "attestation_missing": (
            "Record the privacy attestation from docs/runbooks/claude-subscription.md."
        ),
        "attestation_superseded": (
            "Re-read the current Anthropic data policy and record a new attestation for it."
        ),
        "sdk_not_installed": "Install the Claude Agent SDK on the worker host.",
        "sdk_version_unsupported": (
            "Upgrade the Claude Agent SDK to the version this build was verified against."
        ),
        "authentication_missing": (
            "Provision the subscription credential as a host secret; run claude setup-token "
            "locally and install its output as a root-owned service credential."
        ),
        "authentication_not_subscription": (
            "Remove the API key or cloud-provider switch. This deployment is subscription only "
            "and must not fall back to paid inference."
        ),
        "authentication_rejected": (
            "The subscription credential was refused. Re-run the browser login and reinstall "
            "the credential; check its one-year rotation date."
        ),
        "model_unavailable": (
            "The requested model did not resolve to one this subscription supports. Pin a "
            "model the runbook lists as current."
        ),
        "structured_output_unsupported": (
            "The runtime did not return the structured probe response. Confirm the SDK's "
            "structured-output path before enabling Claude work."
        ),
        "policy_rejected": (
            "Anthropic policy refused this use. Leave Claude disabled and re-check the "
            "subscription and data-usage pages named in the runbook."
        ),
        "quota_exhausted": (
            "The subscription quota is spent. Wait for the window to reset rather than "
            "retrying; do not add paid credentials."
        ),
        "probe_failed": (
            "The compatibility probe did not complete. Check the worker host's logs for the "
            "recorded failure and re-run the probe."
        ),
    }
)


class ProbeError(Exception):
    """A runtime failure the probe understands. Its message is never rendered."""


class ProbeQuotaExhausted(ProbeError):
    """The subscription's quota is spent; this is temporary and must not be retried hard."""


class ProbeAuthenticationFailed(ProbeError):
    """The runtime refused the supplied credential."""


class ProbePolicyRejected(ProbeError):
    """Anthropic policy refused this use of the subscription."""


@dataclass(frozen=True, slots=True)
class ProbeObservation:
    """What one content-free probe call learned. Absent facts are None, never guessed."""

    sdk_version: str | None
    cli_version: str | None
    authentication_method: str
    resolved_model: str | None
    supported_models: tuple[str, ...]
    structured_response: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    status: ProbeStatus
    reason: str
    remediation: str
    checked_at: datetime
    resolved_model: str | None = None
    sdk_version: str | None = None
    cli_version: str | None = None

    @property
    def claude_may_run(self) -> bool:
        return self.status == "ready"


class ClaudeRuntime(Protocol):
    """The installed Agent SDK, narrowed to what a content-free probe needs."""

    async def probe(self, *, requested_model: str) -> ProbeObservation: ...


def _version_tuple(version: str) -> tuple[int, int, int]:
    """Version as exactly three numbers; suffixes such as -beta are ignored.

    Padding to a fixed width matters: Python compares a shorter tuple as less than a
    longer one that starts with it, so an unpadded "1" would have sorted below
    (1, 0, 0) and reported a supported SDK as too old.
    """
    parts: list[int] = []
    for piece in version.split("."):
        digits = ""
        for character in piece:
            if not character.isdigit():
                break
            digits += character
        if not digits:
            break
        parts.append(int(digits))
    padded = (parts + [0, 0, 0])[:3]
    return (padded[0], padded[1], padded[2])


def _classify(observation: ProbeObservation) -> str:
    if observation.sdk_version is None:
        return "sdk_not_installed"
    if _version_tuple(observation.sdk_version) < MINIMUM_SDK_VERSION:
        return "sdk_version_unsupported"
    if observation.authentication_method in ("", "none"):
        return "authentication_missing"
    if observation.authentication_method != SUBSCRIPTION_AUTHENTICATION:
        return "authentication_not_subscription"
    # Only the resolved identifier decides: a model the subscription lists but the
    # runtime did not resolve to is not the model a job would actually run.
    if observation.resolved_model is None or observation.resolved_model not in (
        observation.supported_models
    ):
        return "model_unavailable"
    if observation.structured_response != EXPECTED_STRUCTURED_RESPONSE:
        return "structured_output_unsupported"
    return "none"


def _result(
    status: ProbeStatus, reason: str, now: datetime, **facts: str | None
) -> CompatibilityResult:
    return CompatibilityResult(
        status=status,
        reason=reason,
        remediation=PROBE_REMEDIATION[reason],
        checked_at=now,
        **facts,
    )


async def probe_claude_compatibility(
    *,
    runtime: ClaudeRuntime,
    repository: AttestationSource,
    owner_id: int,
    enabled: bool,
    requested_model: str,
    now: datetime,
) -> CompatibilityResult:
    """Report whether Claude work may run, and what to do about it when it may not."""
    status, reason = await claude_status(repository=repository, owner_id=owner_id, enabled=enabled)
    if status == "disabled":
        return _result("disabled", reason, now)

    try:
        observation = await runtime.probe(requested_model=requested_model)
    except ProbeQuotaExhausted:
        return _result("needs_attention", "quota_exhausted", now)
    except ProbeAuthenticationFailed:
        return _result("blocked", "authentication_rejected", now)
    except ProbePolicyRejected:
        return _result("blocked", "policy_rejected", now)
    except Exception:
        # Deliberately broad and deliberately silent about the message: an SDK error
        # can carry the credential it tried to use, and this result gets rendered.
        return _result("needs_attention", "probe_failed", now)

    facts: dict[str, str | None] = {
        "resolved_model": observation.resolved_model,
        "sdk_version": observation.sdk_version,
        "cli_version": observation.cli_version,
    }
    probe_reason = _classify(observation)
    if probe_reason != "none":
        return _result("blocked", probe_reason, now, **facts)
    return _result("ready", "none", now, **facts)
