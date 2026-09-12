from __future__ import annotations

from tamforge_backend.cli import main


def test_record_attestation_refuses_a_policy_version_the_build_does_not_expect(
    capsys,  # type: ignore[no-untyped-def]
) -> None:
    code = main(
        [
            "record-attestation",
            "--database-url",
            "postgresql+asyncpg://tamforge:tamforge@127.0.0.1:1/never",
            "--policy-version",
            "anthropic-data-policy-1999-01",
            "--model-improvement-disabled",
            "--subscription-policy-acknowledged",
        ]
    )
    assert code == 2
    assert "policy version must be" in capsys.readouterr().out


def test_record_attestation_requires_both_claims(capsys) -> None:  # type: ignore[no-untyped-def]
    from tamforge_backend.agents.settings import EXPECTED_POLICY_VERSION

    code = main(
        [
            "record-attestation",
            "--database-url",
            "postgresql+asyncpg://tamforge:tamforge@127.0.0.1:1/never",
            "--policy-version",
            EXPECTED_POLICY_VERSION,
            "--model-improvement-disabled",
        ]
    )
    assert code == 2
    assert "both claims" in capsys.readouterr().out
