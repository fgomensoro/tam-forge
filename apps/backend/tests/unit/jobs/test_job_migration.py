"""Offline migration contract for cancellation and voluntary RetryWait."""

from __future__ import annotations

from io import StringIO

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL


def _offline_sql(direction: str, revision: str) -> str:
    output = StringIO()
    config = Config("apps/backend/alembic.ini", output_buffer=output)
    config.attributes["database_url"] = URL.create(
        "postgresql+psycopg",
        username="tamforge",
        password="offline-job-contract-password",
        host="127.0.0.1",
        port=54329,
        database="tamforge_test",
    ).render_as_string(hide_password=False)
    if direction == "upgrade":
        command.upgrade(config, revision, sql=True)
    else:
        command.downgrade(config, revision, sql=True)
    return output.getvalue()


def test_job_migration_adds_cancel_and_retry_wait_with_reversible_guard() -> None:
    upgrade = _offline_sql("upgrade", "20260828_0011_durable_jobs")
    downgrade = _offline_sql(
        "downgrade",
        "20260828_0011_durable_jobs:20260828_0010_evidence_ledger",
    )

    assert "'canceled'" in upgrade
    assert "transient_dependency" in upgrade
    assert "resource_exhausted" in upgrade
    assert "tamforge_guard_background_job_mutation" in upgrade
    assert "cannot downgrade while canceled jobs exist" in downgrade
    assert "'canceled'" not in downgrade.split(
        "CREATE OR REPLACE FUNCTION public.tamforge_guard_background_job_mutation"
    )[-1]
