"""Versioned, bounded, machine-only audit metadata contract."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

AUDIT_METADATA_MAX_BYTES = 2048
AUDIT_COUNT_MAX = 1_000_000
AUDIT_CHANGED_FIELDS_MAX = 16
AUDIT_METADATA_KEYS = frozenset(
    {
        "schema_version",
        "outcome",
        "reason_code",
        "changed_fields",
        "counts",
        "flags",
    }
)


class AuditContractError(ValueError):
    """Raised without echoing a potentially sensitive rejected value."""


class AuditOutcome(StrEnum):
    """Closed outcomes supported by audit metadata version 1."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    NOOP = "noop"


class AuditReasonCode(StrEnum):
    """Machine-only reason codes supported by audit metadata version 1."""

    NONE = "none"
    INVALID_INPUT = "invalid_input"
    UNAUTHORIZED = "unauthorized"
    CONFLICT = "conflict"
    EXPIRED = "expired"
    REVOKED = "revoked"
    NOT_FOUND = "not_found"
    INTERNAL_ERROR = "internal_error"


class AuditChangedField(StrEnum):
    """Allowlisted field classes that may be reported as changed."""

    GITHUB_LOGIN = "github_login"
    EXPIRES_AT = "expires_at"
    REVOKED_AT = "revoked_at"
    LAST_SEEN_AT = "last_seen_at"
    STATUS = "status"
    STATE = "state"
    RESULT_PAYLOAD = "result_payload"


class AuditCountKey(StrEnum):
    """Allowlisted bounded counter names."""

    ATTEMPTED = "attempted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    AFFECTED = "affected"
    REMAINING = "remaining"


class AuditFlagKey(StrEnum):
    """Allowlisted boolean flag names."""

    REPLAYED = "replayed"
    RETRYABLE = "retryable"
    AUTHENTICATED = "authenticated"
    AUTHORIZED = "authorized"
    REDACTED = "redacted"


_OUTCOMES = frozenset(item.value for item in AuditOutcome)
_REASON_CODES = frozenset(item.value for item in AuditReasonCode)
_CHANGED_FIELDS = frozenset(item.value for item in AuditChangedField)
_COUNT_KEYS = frozenset(item.value for item in AuditCountKey)
_FLAG_KEYS = frozenset(item.value for item in AuditFlagKey)

_MACHINE_VALUE = re.compile(r"^[a-z0-9][a-z0-9_.:-]*$")
_UUID_VALUE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SECRET_PREFIX = re.compile(
    r"^(bearer|gh[pousr]_|github_pat_|sk-|api[_-]?key|session[_-]?token|eyj)"
)
_JWT_VALUE = re.compile(r"^[a-z0-9_-]{10,}\.[a-z0-9_-]{10,}\.[a-z0-9_-]{10,}$")
_OPAQUE_TOKEN_VALUE = re.compile(r"^[a-z0-9_-]{32,}$")


def _metadata_error() -> AuditContractError:
    return AuditContractError("audit metadata violates v1 contract")


def _event_error() -> AuditContractError:
    return AuditContractError("audit event violates storage contract")


def validate_audit_metadata(value: Mapping[str, object]) -> dict[str, object]:
    """Validate and return a detached canonical JSON-compatible payload."""
    if set(value) != AUDIT_METADATA_KEYS:
        raise _metadata_error()
    schema_version = value.get("schema_version")
    outcome = value.get("outcome")
    reason_code = value.get("reason_code")
    changed_fields = value.get("changed_fields")
    counts = value.get("counts")
    flags = value.get("flags")

    if type(schema_version) is not int or schema_version != 1:
        raise _metadata_error()
    if not isinstance(outcome, str) or outcome not in _OUTCOMES:
        raise _metadata_error()
    if not isinstance(reason_code, str) or reason_code not in _REASON_CODES:
        raise _metadata_error()
    if not isinstance(changed_fields, list):
        raise _metadata_error()
    if len(changed_fields) > AUDIT_CHANGED_FIELDS_MAX:
        raise _metadata_error()
    if any(not isinstance(item, str) or item not in _CHANGED_FIELDS for item in changed_fields):
        raise _metadata_error()
    if len(set(changed_fields)) != len(changed_fields):
        raise _metadata_error()
    if not isinstance(counts, Mapping) or set(counts) - _COUNT_KEYS:
        raise _metadata_error()
    canonical_counts: dict[str, int] = {}
    for key, count in counts.items():
        if not isinstance(key, str) or type(count) is not int:
            raise _metadata_error()
        if count < 0 or count > AUDIT_COUNT_MAX:
            raise _metadata_error()
        canonical_counts[key] = count
    if not isinstance(flags, Mapping) or set(flags) - _FLAG_KEYS:
        raise _metadata_error()
    canonical_flags: dict[str, bool] = {}
    for key, flag_value in flags.items():
        if not isinstance(key, str) or type(flag_value) is not bool:
            raise _metadata_error()
        canonical_flags[key] = flag_value

    canonical: dict[str, object] = {
        "schema_version": 1,
        "outcome": outcome,
        "reason_code": reason_code,
        "changed_fields": sorted(changed_fields),
        "counts": dict(sorted(canonical_counts.items())),
        "flags": dict(sorted(canonical_flags.items())),
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > AUDIT_METADATA_MAX_BYTES:
        raise _metadata_error()
    return canonical


def validate_audit_hash(value: object, *, nullable: bool = False) -> None:
    """Require a fixed SHA-256-sized byte string without exposing it in errors."""
    if nullable and value is None:
        return
    if not isinstance(value, bytes) or len(value) != 32:
        raise _event_error()


def validate_audit_machine_value(value: object, *, max_bytes: int) -> None:
    """Accept short lowercase machine identifiers while rejecting secret shapes."""
    if not isinstance(value, str):
        raise _event_error()
    encoded = value.encode()
    lowered = value.lower()
    if not encoded or len(encoded) > max_bytes or _MACHINE_VALUE.fullmatch(value) is None:
        raise _event_error()
    if _SECRET_PREFIX.match(lowered) or _JWT_VALUE.fullmatch(lowered):
        raise _event_error()
    if _OPAQUE_TOKEN_VALUE.fullmatch(lowered) and _UUID_VALUE.fullmatch(lowered) is None:
        raise _event_error()


@dataclass(frozen=True, slots=True)
class AuditMetadataV1:
    """Typed builder for the exact audit metadata version 1 payload."""

    outcome: AuditOutcome
    reason_code: AuditReasonCode
    changed_fields: tuple[AuditChangedField, ...] = ()
    counts: Mapping[AuditCountKey, int] = field(default_factory=dict)
    flags: Mapping[AuditFlagKey, bool] = field(default_factory=dict)

    def to_payload(self) -> dict[str, object]:
        """Build and revalidate a canonical JSON payload."""
        try:
            payload: dict[str, object] = {
                "schema_version": 1,
                "outcome": self.outcome.value,
                "reason_code": self.reason_code.value,
                "changed_fields": [item.value for item in self.changed_fields],
                "counts": {key.value: value for key, value in self.counts.items()},
                "flags": {key.value: value for key, value in self.flags.items()},
            }
        except (AttributeError, TypeError):
            raise _metadata_error() from None
        return validate_audit_metadata(payload)


__all__ = [
    "AUDIT_CHANGED_FIELDS_MAX",
    "AUDIT_COUNT_MAX",
    "AUDIT_METADATA_MAX_BYTES",
    "AuditChangedField",
    "AuditContractError",
    "AuditCountKey",
    "AuditFlagKey",
    "AuditMetadataV1",
    "AuditOutcome",
    "AuditReasonCode",
    "validate_audit_hash",
    "validate_audit_machine_value",
    "validate_audit_metadata",
]
