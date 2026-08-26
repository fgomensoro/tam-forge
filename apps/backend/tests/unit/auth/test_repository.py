from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.dialects.postgresql import dialect


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


class _Result:
    def __init__(self, row: object) -> None:
        self._row = row

    def one(self) -> object:
        return self._row


class _CapturingSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    def begin(self) -> _Transaction:
        return _Transaction()

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _Result(
                SimpleNamespace(
                    id=7,
                    github_user_id=102269369,
                    github_login="fgomensoro",
                )
            )
        created_at = datetime(2026, 8, 26, 12, tzinfo=UTC)
        return _Result(
            SimpleNamespace(
                id=11,
                owner_id=7,
                token_hash=b"t" * 32,
                csrf_hash=b"c" * 32,
                created_at=created_at,
                expires_at=created_at + timedelta(hours=12),
                revoked_at=None,
            )
        )


@pytest.mark.anyio
async def test_session_insert_uses_database_current_timestamp_for_created_at() -> None:
    from tamforge_backend.auth.repository import SqlAlchemyAuthRepository

    session = _CapturingSession()
    repository = SqlAlchemyAuthRepository(session)  # type: ignore[arg-type]

    await repository.create_owner_session(
        github_user_id=102269369,
        github_login="fgomensoro",
        token_hash=b"t" * 32,
        csrf_hash=b"c" * 32,
        session_ttl=timedelta(hours=12),
    )

    compiled = session.statements[1].compile(dialect=dialect())
    assert "CURRENT_TIMESTAMP" in str(compiled)
    assert "created_at" not in compiled.params
