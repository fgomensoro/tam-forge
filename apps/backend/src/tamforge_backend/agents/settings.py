"""Claude is off unless stored evidence says it may run. Absence is never permission.

The worker settings below are the second half of that rule. This deployment runs Claude
through one person's subscription session and through nothing else, so the worker
refuses to start when the environment offers any other way in. That is not only an API
key: an unset `ANTHROPIC_API_KEY` does not mean there are no credentials, because the
SDK also resolves `ANTHROPIC_AUTH_TOKEN`, a named profile, and a workload-identity
federation set, and `ANTHROPIC_BASE_URL` can point the same token somewhere else. Any
of them present is a configuration error rather than a fallback, because a fallback is
exactly what must not exist.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, SecretStr, model_validator

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


# Every environment variable that offers Claude a way in other than this deployment's
# subscription session. Presence is what matters, not the value: an empty
# ANTHROPIC_API_KEY still outranks the subscription profile in the SDK's resolution
# order, and a set ANTHROPIC_BASE_URL points a valid token at another endpoint.
FORBIDDEN_CREDENTIAL_VARS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_FEDERATION_RULE_ID",
    "ANTHROPIC_SERVICE_ACCOUNT_ID",
    "ANTHROPIC_IDENTITY_TOKEN",
    "ANTHROPIC_IDENTITY_TOKEN_FILE",
    "ANTHROPIC_WORKSPACE_ID",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)

# The one credential this deployment accepts, produced by `claude setup-token` and
# installed as a root-owned service credential; see docs/runbooks/claude-subscription.md.
SUBSCRIPTION_TOKEN_VAR = "CLAUDE_CODE_OAUTH_TOKEN"

# Nonessential traffic stays off. This is a private single-user workspace and its
# transcripts are the last thing that should leave it in a crash report.
WORKER_TELEMETRY_OPT_OUTS: Mapping[str, str] = MappingProxyType(
    {
        "DISABLE_TELEMETRY": "1",
        "DISABLE_ERROR_REPORTING": "1",
        "DISABLE_BUG_COMMAND": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    }
)


class ClaudeWorkerConfigurationError(ValueError):
    """The worker may not start. The message names the variable, never its value."""


class PaidCredentialForbidden(ClaudeWorkerConfigurationError):
    """The environment offers a paid or redirected path to Claude."""


class SubscriptionCredentialMissing(ClaudeWorkerConfigurationError):
    """The subscription credential is absent, and there is no fallback to take."""


class ClaudeSubscriptionSettings(Contract):
    """What the Claude worker runs with once the environment has been judged safe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    token: SecretStr
    # One job at a time. A personal subscription is not a pool, and parallel jobs turn
    # a quota into an outage.
    max_concurrent_jobs: Literal[1] = 1
    max_turns: Annotated[int, Field(strict=True, ge=1, le=64)] = 24
    wall_time_seconds: Annotated[int, Field(strict=True, ge=1, le=1_800)] = 600
    authorization: Literal["subscription_session"] = "subscription_session"

    @classmethod
    def for_worker(
        cls, *, environ: Mapping[str, str], stored: AttestationRecord | None
    ) -> Self:
        """Judge the environment, then hand back the settings, or refuse.

        `environ` is passed in rather than read from the process, so this is decided by
        what the caller actually intends to give the worker and nothing else picks up a
        stray variable from a shell, a dotenv file or a secrets directory.
        """
        for variable in FORBIDDEN_CREDENTIAL_VARS:
            if variable in environ:
                raise PaidCredentialForbidden(
                    f"{variable} is set; this deployment is subscription only"
                )
        if stored is None or not attestation_is_current(stored):
            raise ClaudeWorkerConfigurationError(
                "no current privacy attestation authorizes Claude execution"
            )
        token = environ.get(SUBSCRIPTION_TOKEN_VAR, "").strip()
        if not token:
            raise SubscriptionCredentialMissing(
                f"{SUBSCRIPTION_TOKEN_VAR} is not installed on this host"
            )
        return cls(token=SecretStr(token))

    def worker_environment(self) -> dict[str, str]:
        """The complete environment the worker process gets, and nothing besides."""
        return {
            SUBSCRIPTION_TOKEN_VAR: self.token.get_secret_value(),
            **WORKER_TELEMETRY_OPT_OUTS,
        }
