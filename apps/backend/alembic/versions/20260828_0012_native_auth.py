"""Add durable native OAuth, exchange, and rotating token records.

Revision ID: 20260828_0012_native_auth
Revises: 20260828_0011_durable_jobs
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0012_native_auth"
down_revision: str | None = "20260828_0011_durable_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "native_oauth_flows",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("state_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("pkce_challenge", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("octet_length(state_hash) = 32", name="state_hash_length"),
        sa.CheckConstraint(
            "char_length(pkce_challenge) = 43 "
            "AND pkce_challenge ~ '^[A-Za-z0-9_-]+$'",
            name="pkce_challenge_s256",
        ),
        sa.CheckConstraint("expires_at > created_at", name="expires_after_creation"),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="consumed_after_creation",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_native_oauth_flows"),
        sa.UniqueConstraint("state_hash", name="uq_native_oauth_flows_state_hash"),
    )
    op.create_index(
        "ix_native_oauth_flows_expires_at", "native_oauth_flows", ["expires_at"]
    )

    op.create_table(
        "native_exchange_codes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("code_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("pkce_challenge", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("octet_length(code_hash) = 32", name="code_hash_length"),
        sa.CheckConstraint(
            "char_length(pkce_challenge) = 43 "
            "AND pkce_challenge ~ '^[A-Za-z0-9_-]+$'",
            name="pkce_challenge_s256",
        ),
        sa.CheckConstraint("expires_at > created_at", name="expires_after_creation"),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="consumed_after_creation",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_native_exchange_codes_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_native_exchange_codes"),
        sa.UniqueConstraint("code_hash", name="uq_native_exchange_codes_code_hash"),
    )
    op.create_index(
        "ix_native_exchange_codes_owner_id", "native_exchange_codes", ["owner_id"]
    )
    op.create_index(
        "ix_native_exchange_codes_expires_at",
        "native_exchange_codes",
        ["expires_at"],
    )

    op.create_table(
        "native_auth_sessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("access_token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(access_token_hash) = 32",
            name="access_token_hash_length",
        ),
        sa.CheckConstraint(
            "access_expires_at > created_at", name="access_expires_after_creation"
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="revoked_after_creation",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_native_auth_sessions_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_native_auth_sessions"),
        sa.UniqueConstraint(
            "access_token_hash", name="uq_native_auth_sessions_access_hash"
        ),
    )
    op.create_index(
        "ix_native_auth_sessions_owner_id", "native_auth_sessions", ["owner_id"]
    )
    op.create_index(
        "ix_native_auth_sessions_access_expires_at",
        "native_auth_sessions",
        ["access_expires_at"],
    )

    op.create_table(
        "native_refresh_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.BigInteger(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("octet_length(token_hash) = 32", name="token_hash_length"),
        sa.CheckConstraint("expires_at > created_at", name="expires_after_creation"),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="consumed_after_creation",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="revoked_after_creation",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["native_auth_sessions.id"],
            name="fk_native_refresh_tokens_session_id_native_auth_sessions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["native_refresh_tokens.id"],
            name="fk_native_refresh_tokens_replaced_by_id_native_refresh_tokens",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_native_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_native_refresh_tokens_token_hash"),
    )
    op.create_index(
        "ix_native_refresh_tokens_session_id", "native_refresh_tokens", ["session_id"]
    )
    op.create_index(
        "ix_native_refresh_tokens_expires_at", "native_refresh_tokens", ["expires_at"]
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM native_auth_sessions AS sessions
                JOIN native_refresh_tokens AS refresh
                  ON refresh.session_id = sessions.id
                WHERE sessions.revoked_at IS NULL
                  AND refresh.consumed_at IS NULL
                  AND refresh.revoked_at IS NULL
                  AND refresh.expires_at > CURRENT_TIMESTAMP
            ) THEN
                RAISE EXCEPTION
                    'active native sessions must be revoked before downgrade';
            END IF;
        END;
        $$;
        """
    )
    op.drop_index("ix_native_refresh_tokens_expires_at", table_name="native_refresh_tokens")
    op.drop_index("ix_native_refresh_tokens_session_id", table_name="native_refresh_tokens")
    op.drop_table("native_refresh_tokens")
    op.drop_index(
        "ix_native_auth_sessions_access_expires_at", table_name="native_auth_sessions"
    )
    op.drop_index("ix_native_auth_sessions_owner_id", table_name="native_auth_sessions")
    op.drop_table("native_auth_sessions")
    op.drop_index(
        "ix_native_exchange_codes_expires_at", table_name="native_exchange_codes"
    )
    op.drop_index("ix_native_exchange_codes_owner_id", table_name="native_exchange_codes")
    op.drop_table("native_exchange_codes")
    op.drop_index("ix_native_oauth_flows_expires_at", table_name="native_oauth_flows")
    op.drop_table("native_oauth_flows")
