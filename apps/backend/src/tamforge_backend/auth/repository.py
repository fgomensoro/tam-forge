"""Transactional PostgreSQL owner/session repository."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import transaction_scope
from .models import AuthSession, Owner
from .schemas import PersistedSession


class SqlAlchemyAuthRepository:
    """Persist only fixed SHA-256 hashes and use database time for lifecycle writes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_owner_session(
        self,
        *,
        github_user_id: int,
        github_login: str,
        token_hash: bytes,
        csrf_hash: bytes,
        session_ttl: timedelta,
    ) -> PersistedSession:
        async with transaction_scope(self._session):
            owner_statement = (
                insert(Owner)
                .values(github_user_id=github_user_id, github_login=github_login)
                .on_conflict_do_update(
                    index_elements=[Owner.github_user_id],
                    set_={"github_login": github_login, "updated_at": func.now()},
                )
                .returning(Owner.id, Owner.github_user_id, Owner.github_login)
            )
            owner = (await self._session.execute(owner_statement)).one()
            session_statement = (
                insert(AuthSession)
                .values(
                    owner_id=owner.id,
                    token_hash=token_hash,
                    csrf_hash=csrf_hash,
                    expires_at=func.now() + session_ttl,
                )
                .returning(
                    AuthSession.id,
                    AuthSession.owner_id,
                    AuthSession.token_hash,
                    AuthSession.csrf_hash,
                    AuthSession.created_at,
                    AuthSession.expires_at,
                    AuthSession.revoked_at,
                )
            )
            row = (await self._session.execute(session_statement)).one()
        return PersistedSession(
            session_id=row.id,
            owner_id=row.owner_id,
            github_user_id=owner.github_user_id,
            github_login=owner.github_login,
            token_hash=row.token_hash,
            csrf_hash=row.csrf_hash,
            created_at=row.created_at,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
        )

    async def find_active_session(self, token_hash: bytes) -> PersistedSession | None:
        statement = (
            self._session_projection()
            .where(AuthSession.token_hash == token_hash)
            .where(AuthSession.revoked_at.is_(None))
            .where(AuthSession.expires_at > func.now())
        )
        row = (await self._session.execute(statement)).one_or_none()
        await self._session.rollback()
        return self._to_persisted(row)

    async def find_session_for_logout(self, token_hash: bytes) -> PersistedSession | None:
        statement = self._session_projection().where(AuthSession.token_hash == token_hash)
        row = (await self._session.execute(statement)).one_or_none()
        await self._session.rollback()
        return self._to_persisted(row)

    async def revoke_session(self, token_hash: bytes) -> None:
        async with transaction_scope(self._session):
            await self._session.execute(
                update(AuthSession)
                .where(AuthSession.token_hash == token_hash)
                .where(AuthSession.revoked_at.is_(None))
                .values(revoked_at=func.now())
            )

    @staticmethod
    def _session_projection() -> Select[
        tuple[int, int, int, str, bytes, bytes, datetime, datetime, datetime | None]
    ]:
        return select(
            AuthSession.id.label("session_id"),
            AuthSession.owner_id,
            Owner.github_user_id,
            Owner.github_login,
            AuthSession.token_hash,
            AuthSession.csrf_hash,
            AuthSession.created_at,
            AuthSession.expires_at,
            AuthSession.revoked_at,
        ).join(Owner, Owner.id == AuthSession.owner_id)

    @staticmethod
    def _to_persisted(
        row: Row[tuple[int, int, int, str, bytes, bytes, datetime, datetime, datetime | None]]
        | None,
    ) -> PersistedSession | None:
        if row is None:
            return None
        return PersistedSession(
            session_id=row[0],
            owner_id=row[1],
            github_user_id=row[2],
            github_login=row[3],
            token_hash=row[4],
            csrf_hash=row[5],
            created_at=row[6],
            expires_at=row[7],
            revoked_at=row[8],
        )
