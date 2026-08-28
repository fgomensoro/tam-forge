"""Authentication persistence and bounded audit contracts.

Authentication flows and session issuance are intentionally implemented later.
"""

from .audit import (
    AuditChangedField,
    AuditContractError,
    AuditCountKey,
    AuditFlagKey,
    AuditMetadataV1,
    AuditOutcome,
    AuditReasonCode,
    validate_audit_metadata,
)
from .models import (
    AuditEvent,
    AuthSession,
    CommandReceipt,
    Owner,
    validate_audit_event_insert,
)

__all__ = [
    "AuditChangedField",
    "AuditContractError",
    "AuditCountKey",
    "AuditEvent",
    "AuditFlagKey",
    "AuditMetadataV1",
    "AuditOutcome",
    "AuditReasonCode",
    "AuthSession",
    "CommandReceipt",
    "Owner",
    "validate_audit_event_insert",
    "validate_audit_metadata",
]
