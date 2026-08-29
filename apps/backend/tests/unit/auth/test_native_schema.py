from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa

MIGRATION_PATH = Path("apps/backend/alembic/versions/20260828_0012_native_auth.py")
NATIVE_TABLES = {
    "native_oauth_flows",
    "native_exchange_codes",
    "native_auth_sessions",
    "native_refresh_tokens",
}


def test_native_auth_models_use_hash_only_secret_columns() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    assert NATIVE_TABLES <= set(Base.metadata.tables)

    flows = Base.metadata.tables["native_oauth_flows"]
    exchanges = Base.metadata.tables["native_exchange_codes"]
    sessions = Base.metadata.tables["native_auth_sessions"]
    refresh = Base.metadata.tables["native_refresh_tokens"]

    for column in (
        flows.c.state_hash,
        exchanges.c.code_hash,
        sessions.c.access_token_hash,
        refresh.c.token_hash,
    ):
        assert isinstance(column.type, sa.LargeBinary)
        assert column.type.length == 32
    for forbidden in {"state", "code", "access_token", "refresh_token", "verifier"}:
        assert forbidden not in flows.c
        assert forbidden not in exchanges.c
        assert forbidden not in sessions.c
        assert forbidden not in refresh.c
    assert refresh.c.replaced_by_id.nullable is True
    assert refresh.c.consumed_at.type.timezone is True


def test_native_auth_migration_is_single_revision_with_guarded_downgrade() -> None:
    assert MIGRATION_PATH.exists()
    spec = importlib.util.spec_from_file_location("native_auth_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "20260828_0012_native_auth"
    assert module.down_revision == "20260828_0011_durable_jobs"
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "active native sessions must be revoked before downgrade" in source
    assert source.count("op.create_table(") == 4


def test_denied_native_audit_does_not_claim_authentication() -> None:
    from tamforge_backend.auth.audit import AuditOutcome, AuditReasonCode
    from tamforge_backend.auth.repository import SqlAlchemyAuthRepository

    event = SqlAlchemyAuthRepository._native_audit_event(
        owner_id=7,
        subject_hash=b"h" * 32,
        action="auth.native_refresh.denied",
        aggregate_id="11",
        outcome=AuditOutcome.DENIED,
        reason=AuditReasonCode.CONFLICT,
        authenticated=False,
        replayed=True,
    )

    assert event.redacted_metadata["flags"]["authenticated"] is False
    assert event.redacted_metadata["flags"]["replayed"] is True
