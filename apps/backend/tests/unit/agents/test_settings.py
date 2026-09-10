"""Claude stays off unless a current attestation says otherwise."""

from __future__ import annotations

import pytest


def attestation(**overrides):
    from tamforge_backend.agents.settings import EXPECTED_POLICY_VERSION, AttestationRecord

    data = {
        "policy_version": EXPECTED_POLICY_VERSION,
        "model_improvement_disabled": True,
        "subscription_policy_acknowledged": True,
    }
    data.update(overrides)
    return AttestationRecord.model_validate(data)


def test_a_matching_attestation_is_current():
    from tamforge_backend.agents.settings import attestation_is_current

    assert attestation_is_current(attestation()) is True


def test_an_attestation_for_another_policy_version_is_stale():
    from tamforge_backend.agents.settings import attestation_is_current

    assert attestation_is_current(attestation(policy_version="superseded-v0")) is False


@pytest.mark.parametrize(
    "field", ["model_improvement_disabled", "subscription_policy_acknowledged"]
)
def test_both_claims_must_be_affirmative(field):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        attestation(**{field: False})


def test_missing_attestation_disables_claude_rather_than_defaulting_on():
    from tamforge_backend.agents.settings import claude_availability

    status, reason = claude_availability(enabled=True, stored=None)
    assert status == "disabled"
    assert reason == "attestation_missing"


def test_a_stale_attestation_disables_claude():
    from tamforge_backend.agents.settings import claude_availability

    status, reason = claude_availability(
        enabled=True, stored=attestation(policy_version="superseded-v0")
    )
    assert status == "disabled"
    assert reason == "attestation_superseded"


def test_claude_off_by_configuration_is_not_an_error():
    from tamforge_backend.agents.settings import claude_availability

    assert claude_availability(enabled=False, stored=None) == ("disabled", "not_enabled")
    assert claude_availability(enabled=False, stored=attestation()) == (
        "disabled",
        "not_enabled",
    )


def test_enabled_with_a_current_attestation_is_ready():
    from tamforge_backend.agents.settings import claude_availability

    assert claude_availability(enabled=True, stored=attestation()) == ("ready", "none")


def test_the_application_starts_with_claude_disabled():
    from tamforge_backend.config import APPROVED_GITHUB_USER_ID, Settings

    settings = Settings(
        environment="test",
        github_user_id=APPROVED_GITHUB_USER_ID,
        secure_cookies=False,
        _env_file=None,
    )
    assert settings.claude_enabled is False


def test_reasons_are_machine_only_slugs():
    import re

    from tamforge_backend.agents.settings import DISABLED_REASONS

    assert all(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", item) for item in DISABLED_REASONS)


# Issue #66: startup rejects Anthropic API credentials and any paid fallback, and
# records that Claude execution is authorized only through the approved subscription.

# Deliberately not shaped like a real credential: the repository secret scanner reads
# every tracked file, and a realistic token here would be a finding rather than a test.
SUBSCRIPTION_ENV = {"CLAUDE_CODE_OAUTH_TOKEN": "subscription-token-for-tests"}


def worker(environ=None, stored=None):
    from tamforge_backend.agents.settings import ClaudeSubscriptionSettings

    return ClaudeSubscriptionSettings.for_worker(
        environ=dict(SUBSCRIPTION_ENV if environ is None else environ),
        stored=attestation() if stored is None else stored,
    )


def test_a_subscription_token_and_a_current_attestation_start_the_worker():
    from tamforge_backend.agents.settings import ClaudeSubscriptionSettings

    settings = worker()

    assert isinstance(settings, ClaudeSubscriptionSettings)
    assert settings.authorization == "subscription_session"
    assert settings.max_concurrent_jobs == 1
    assert settings.token.get_secret_value() == SUBSCRIPTION_ENV["CLAUDE_CODE_OAUTH_TOKEN"]


@pytest.mark.parametrize(
    "variable",
    [
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_PROFILE",
        "ANTHROPIC_FEDERATION_RULE_ID",
        "ANTHROPIC_SERVICE_ACCOUNT_ID",
        "ANTHROPIC_IDENTITY_TOKEN",
        "ANTHROPIC_IDENTITY_TOKEN_FILE",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
    ],
)
def test_a_paid_or_redirected_credential_is_a_hard_configuration_error(variable):
    from tamforge_backend.agents.settings import PaidCredentialForbidden

    with pytest.raises(PaidCredentialForbidden):
        worker({**SUBSCRIPTION_ENV, variable: "any-value-at-all"})


def test_an_empty_forbidden_variable_still_counts_as_set():
    """An empty ANTHROPIC_API_KEY still outranks the subscription profile."""
    from tamforge_backend.agents.settings import PaidCredentialForbidden

    with pytest.raises(PaidCredentialForbidden):
        worker({**SUBSCRIPTION_ENV, "ANTHROPIC_API_KEY": ""})


def test_a_missing_subscription_token_is_refused_without_falling_back():
    from tamforge_backend.agents.settings import SubscriptionCredentialMissing

    for environ in ({}, {"CLAUDE_CODE_OAUTH_TOKEN": "   "}):
        with pytest.raises(SubscriptionCredentialMissing):
            worker(environ)


@pytest.mark.parametrize("kind", ["missing", "stale"])
def test_an_unapproved_attestation_never_yields_a_token(kind):
    from tamforge_backend.agents.settings import (
        ClaudeSubscriptionSettings,
        ClaudeWorkerConfigurationError,
    )

    record = None if kind == "missing" else attestation(policy_version="superseded-v0")
    with pytest.raises(ClaudeWorkerConfigurationError):
        ClaudeSubscriptionSettings.for_worker(environ=dict(SUBSCRIPTION_ENV), stored=record)


def test_the_token_never_appears_in_a_repr_or_a_dump():
    settings = worker()
    secret = SUBSCRIPTION_ENV["CLAUDE_CODE_OAUTH_TOKEN"]

    assert secret not in repr(settings)
    assert secret not in str(settings)
    assert secret not in str(settings.model_dump())
    assert secret not in settings.model_dump_json()


def test_a_rejection_never_quotes_the_credential_it_rejected():
    from tamforge_backend.agents.settings import PaidCredentialForbidden

    with pytest.raises(PaidCredentialForbidden) as raised:
        worker({**SUBSCRIPTION_ENV, "ANTHROPIC_API_KEY": "a-value-that-must-never-be-quoted"})

    assert "a-value-that-must-never-be-quoted" not in str(raised.value)
    assert "ANTHROPIC_API_KEY" in str(raised.value)


def test_the_worker_environment_carries_the_token_and_no_paid_switch():
    from tamforge_backend.agents.settings import (
        FORBIDDEN_CREDENTIAL_VARS,
        SUBSCRIPTION_TOKEN_VAR,
        WORKER_TELEMETRY_OPT_OUTS,
    )

    environment = worker().worker_environment()

    assert environment[SUBSCRIPTION_TOKEN_VAR] == SUBSCRIPTION_ENV[SUBSCRIPTION_TOKEN_VAR]
    assert not set(environment) & set(FORBIDDEN_CREDENTIAL_VARS)
    for variable, value in WORKER_TELEMETRY_OPT_OUTS.items():
        assert environment[variable] == value


def test_concurrency_and_bounds_cannot_be_widened():
    from pydantic import ValidationError
    from tamforge_backend.agents.settings import ClaudeSubscriptionSettings

    settings = worker()
    assert settings.max_turns >= 1 and settings.wall_time_seconds >= 1

    for field, value in (
        ("max_concurrent_jobs", 2),
        ("max_turns", 0),
        ("wall_time_seconds", 0),
    ):
        with pytest.raises(ValidationError):
            ClaudeSubscriptionSettings.model_validate(
                {**settings.model_dump(), "token": "x", field: value}
            )


def test_the_api_still_starts_with_claude_disabled_and_no_credential():
    """Independent study must not depend on any Claude credential existing."""
    from tamforge_backend.agents.settings import claude_availability

    assert claude_availability(enabled=False, stored=None) == ("disabled", "not_enabled")
