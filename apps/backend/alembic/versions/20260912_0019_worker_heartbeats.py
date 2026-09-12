"""One row per worker process: the last beat it sent and how it felt."""

from alembic import op

revision = "20260912_0019_worker_heartbeats"
down_revision = "20260909_0018_transcripts"
branch_labels = None
depends_on = None

TABLE = r"""
CREATE TABLE worker_heartbeats (
    worker TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_worker_heartbeats PRIMARY KEY (worker),
    CONSTRAINT ck_worker_heartbeats_worker_safe CHECK (worker ~ '^[a-z][a-z0-9_]{0,63}$'),
    CONSTRAINT ck_worker_heartbeats_status_allowed
        CHECK (status IN ('ok', 'needs_attention', 'unknown')),
    CONSTRAINT ck_worker_heartbeats_reason_bounded CHECK (octet_length(reason) BETWEEN 1 AND 64)
)
"""


def upgrade() -> None:
    op.execute(TABLE)


def downgrade() -> None:
    op.execute("DROP TABLE worker_heartbeats")
