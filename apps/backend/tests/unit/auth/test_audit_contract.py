from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest


def _valid_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "outcome": "succeeded",
        "reason_code": "none",
        "changed_fields": ["status"],
        "counts": {"affected": 1},
        "flags": {"replayed": False},
    }


def _audit_event(**overrides: Any) -> Any:
    from tamforge_backend.auth.models import AuditEvent

    values: dict[str, Any] = {
        "actor_kind": "owner",
        "actor_subject_hash": b"a" * 32,
        "action": "session.created",
        "aggregate_type": "auth_session",
        "aggregate_id": "1",
        "request_correlation_hash": b"r" * 32,
        "idempotency_correlation_hash": b"i" * 32,
        "redacted_metadata": _valid_payload(),
    }
    values.update(overrides)
    return AuditEvent(**values)


def test_typed_audit_metadata_builds_a_canonical_round_trip_payload() -> None:
    from tamforge_backend.auth import (
        AuditChangedField,
        AuditCountKey,
        AuditFlagKey,
        AuditMetadataV1,
        AuditOutcome,
        AuditReasonCode,
        validate_audit_metadata,
    )

    metadata = AuditMetadataV1(
        outcome=AuditOutcome.SUCCEEDED,
        reason_code=AuditReasonCode.NONE,
        changed_fields=(AuditChangedField.STATUS,),
        counts={AuditCountKey.AFFECTED: 1},
        flags={AuditFlagKey.REPLAYED: False},
    )

    payload = metadata.to_payload()
    assert payload == _valid_payload()
    assert validate_audit_metadata(json.loads(json.dumps(payload))) == payload


def test_default_audit_metadata_is_fresh_and_canonical() -> None:
    from tamforge_backend.auth import default_audit_metadata

    first = default_audit_metadata()
    second = default_audit_metadata()

    assert first == {
        "schema_version": 1,
        "outcome": "succeeded",
        "reason_code": "none",
        "changed_fields": [],
        "counts": {},
        "flags": {},
    }
    assert first is not second
    assert first["changed_fields"] is not second["changed_fields"]
    assert first["counts"] is not second["counts"]
    assert first["flags"] is not second["flags"]


@pytest.mark.parametrize(
    ("mutator", "candidate"),
    [
        (lambda value: value.update({"notes": "free form customer text"}), "free form"),
        (lambda value: value.update({"outcome": "maybe"}), "maybe"),
        (lambda value: value.update({"reason_code": "ghp_AAAAAAAAAAAAA"}), "ghp_"),
        (
            lambda value: value.update({"changed_fields": ["Bearer session-secret"]}),
            "session-secret",
        ),
        (lambda value: value.update({"counts": {"affected": -1}}), "-1"),
        (lambda value: value.update({"counts": {"affected": 1_000_001}}), "1000001"),
        (lambda value: value.update({"flags": {"replayed": "yes"}}), "yes"),
        (
            lambda value: value.update({"changed_fields": ["status"] * 2000}),
            "status",
        ),
    ],
)
def test_audit_metadata_rejects_forbidden_free_form_and_oversize_values_without_echo(
    mutator: Any,
    candidate: str,
) -> None:
    from tamforge_backend.auth import AuditContractError, validate_audit_metadata

    payload = _valid_payload()
    mutator(payload)

    with pytest.raises(AuditContractError) as error:
        validate_audit_metadata(payload)

    assert candidate not in str(error.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actor_subject_hash", b"short"),
        ("request_correlation_hash", b"short"),
        ("idempotency_correlation_hash", b"short"),
    ],
)
def test_audit_insert_contract_rejects_wrong_hash_lengths_without_echo(
    field: str,
    value: bytes,
) -> None:
    from tamforge_backend.auth import AuditContractError, validate_audit_event_insert

    event = _audit_event(**{field: value})

    with pytest.raises(AuditContractError) as error:
        validate_audit_event_insert(None, None, event)

    assert "short" not in str(error.value)


@pytest.mark.parametrize(
    ("field", "candidate"),
    [
        ("actor_kind", "Bearer credential"),
        ("action", "ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
        ("aggregate_type", "sk-secretvalue"),
        (
            "aggregate_id",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signaturevalue",
        ),
        ("aggregate_id", "a" * 43),
    ],
)
def test_audit_insert_contract_rejects_unsafe_machine_values_without_echo(
    field: str,
    candidate: str,
) -> None:
    from tamforge_backend.auth import AuditContractError, validate_audit_event_insert

    event = _audit_event(**{field: candidate})

    with pytest.raises(AuditContractError) as error:
        validate_audit_event_insert(None, None, event)

    assert candidate not in str(error.value)


def test_audit_insert_contract_canonicalizes_valid_metadata() -> None:
    from tamforge_backend.auth import validate_audit_event_insert

    original: Mapping[str, object] = _valid_payload()
    event = _audit_event(redacted_metadata=original)

    validate_audit_event_insert(None, None, event)

    assert event.redacted_metadata == _valid_payload()
    assert event.redacted_metadata is not original


def test_audit_insert_contract_never_accepts_an_arbitrary_dict_silently() -> None:
    from tamforge_backend.auth import AuditContractError, validate_audit_event_insert

    event = _audit_event(redacted_metadata={"message": "customer transcript"})

    with pytest.raises(AuditContractError, match="contract"):
        validate_audit_event_insert(None, None, event)
