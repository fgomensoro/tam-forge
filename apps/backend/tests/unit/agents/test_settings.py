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
