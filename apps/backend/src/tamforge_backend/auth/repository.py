"""Transactional PostgreSQL owner/session repository."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import transaction_scope
from .audit import AuditFlagKey, AuditMetadataV1, AuditOutcome, AuditReasonCode
from .models import (
    AuditEvent,
    AuthSession,
    NativeAuthSession,
    NativeExchangeCode,
    NativeOAuthFlow,
    NativeRefreshToken,
    Owner,
)
from .schemas import PersistedNativeSession, PersistedSession


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
                    created_at=func.current_timestamp(),
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

    async def create_native_oauth_flow(
        self,
        *,
        state_hash: bytes,
        pkce_challenge: str,
        flow_ttl: timedelta,
    ) -> None:
        async with transaction_scope(self._session):
            await self._session.execute(
                insert(NativeOAuthFlow).values(
                    state_hash=state_hash,
                    pkce_challenge=pkce_challenge,
                    created_at=func.now(),
                    expires_at=func.now() + flow_ttl,
                )
            )

    async def consume_native_oauth_flow(self, state_hash: bytes) -> str | None:
        async with transaction_scope(self._session):
            row = (
                await self._session.execute(
                    update(NativeOAuthFlow)
                    .where(NativeOAuthFlow.state_hash == state_hash)
                    .where(NativeOAuthFlow.consumed_at.is_(None))
                    .where(NativeOAuthFlow.expires_at > func.now())
                    .values(consumed_at=func.now())
                    .returning(NativeOAuthFlow.pkce_challenge)
                )
            ).one_or_none()
        return None if row is None else row[0]

    async def create_native_exchange(
        self,
        *,
        github_user_id: int,
        github_login: str,
        code_hash: bytes,
        pkce_challenge: str,
        exchange_ttl: timedelta,
    ) -> None:
        async with transaction_scope(self._session):
            owner = (
                await self._session.execute(
                    insert(Owner)
                    .values(github_user_id=github_user_id, github_login=github_login)
                    .on_conflict_do_update(
                        index_elements=[Owner.github_user_id],
                        set_={"github_login": github_login, "updated_at": func.now()},
                    )
                    .returning(Owner.id)
                )
            ).one()
            await self._session.execute(
                insert(NativeExchangeCode).values(
                    owner_id=owner.id,
                    code_hash=code_hash,
                    pkce_challenge=pkce_challenge,
                    created_at=func.now(),
                    expires_at=func.now() + exchange_ttl,
                )
            )

    async def consume_native_exchange_and_create_session(
        self,
        *,
        code_hash: bytes,
        pkce_challenge: str,
        access_token_hash: bytes,
        refresh_token_hash: bytes,
        access_ttl: timedelta,
        refresh_ttl: timedelta,
    ) -> PersistedNativeSession | None:
        result: PersistedNativeSession | None = None
        async with transaction_scope(self._session):
            exchange = (
                await self._session.execute(
                    update(NativeExchangeCode)
                    .where(NativeExchangeCode.code_hash == code_hash)
                    .where(NativeExchangeCode.pkce_challenge == pkce_challenge)
                    .where(NativeExchangeCode.consumed_at.is_(None))
                    .where(NativeExchangeCode.expires_at > func.now())
                    .values(consumed_at=func.now())
                    .returning(NativeExchangeCode.id, NativeExchangeCode.owner_id)
                )
            ).one_or_none()
            if exchange is None:
                denied = (
                    await self._session.execute(
                        select(
                            NativeExchangeCode.id,
                            NativeExchangeCode.owner_id,
                            NativeExchangeCode.consumed_at,
                            (NativeExchangeCode.expires_at <= func.now()).label("expired"),
                        ).where(NativeExchangeCode.code_hash == code_hash)
                    )
                ).one_or_none()
                self._session.add(
                    self._native_audit_event(
                        owner_id=None if denied is None else denied.owner_id,
                        subject_hash=code_hash,
                        action="auth.native_exchange.denied",
                        aggregate_id="unknown" if denied is None else str(denied.id),
                        outcome=AuditOutcome.DENIED,
                        reason=(
                            AuditReasonCode.NOT_FOUND
                            if denied is None
                            else AuditReasonCode.EXPIRED
                            if denied.expired
                            else AuditReasonCode.CONFLICT
                        ),
                        replayed=denied is not None and denied.consumed_at is not None,
                    )
                )
            else:
                owner = (
                    await self._session.execute(
                        select(Owner.github_user_id, Owner.github_login).where(
                            Owner.id == exchange.owner_id
                        )
                    )
                ).one()
                native_session = (
                    await self._session.execute(
                        insert(NativeAuthSession)
                        .values(
                            owner_id=exchange.owner_id,
                            access_token_hash=access_token_hash,
                            created_at=func.now(),
                            access_expires_at=func.now() + access_ttl,
                        )
                        .returning(
                            NativeAuthSession.id,
                            NativeAuthSession.access_expires_at,
                            NativeAuthSession.revoked_at,
                        )
                    )
                ).one()
                refresh = (
                    await self._session.execute(
                        insert(NativeRefreshToken)
                        .values(
                            session_id=native_session.id,
                            token_hash=refresh_token_hash,
                            created_at=func.now(),
                            expires_at=func.now() + refresh_ttl,
                        )
                        .returning(NativeRefreshToken.expires_at)
                    )
                ).one()
                self._session.add(
                    self._native_audit_event(
                        owner_id=exchange.owner_id,
                        subject_hash=code_hash,
                        action="auth.native_exchange.succeeded",
                        aggregate_id=str(native_session.id),
                        outcome=AuditOutcome.SUCCEEDED,
                        reason=AuditReasonCode.NONE,
                    )
                )
                result = PersistedNativeSession(
                    session_id=native_session.id,
                    owner_id=exchange.owner_id,
                    github_user_id=owner.github_user_id,
                    github_login=owner.github_login,
                    access_token_hash=access_token_hash,
                    access_expires_at=native_session.access_expires_at,
                    refresh_token_hash=refresh_token_hash,
                    refresh_expires_at=refresh.expires_at,
                    revoked_at=native_session.revoked_at,
                )
        return result

    async def rotate_native_refresh_token(
        self,
        *,
        refresh_token_hash: bytes,
        new_access_token_hash: bytes,
        new_refresh_token_hash: bytes,
        access_ttl: timedelta,
        refresh_ttl: timedelta,
    ) -> PersistedNativeSession | None:
        result: PersistedNativeSession | None = None
        async with transaction_scope(self._session):
            row = (
                await self._session.execute(
                    select(
                        NativeRefreshToken.id.label("refresh_id"),
                        NativeRefreshToken.session_id,
                        NativeRefreshToken.consumed_at,
                        NativeRefreshToken.revoked_at.label("refresh_revoked_at"),
                        (NativeRefreshToken.expires_at <= func.now()).label("expired"),
                        NativeAuthSession.owner_id,
                        NativeAuthSession.revoked_at.label("session_revoked_at"),
                        Owner.github_user_id,
                        Owner.github_login,
                    )
                    .join(
                        NativeAuthSession,
                        NativeAuthSession.id == NativeRefreshToken.session_id,
                    )
                    .join(Owner, Owner.id == NativeAuthSession.owner_id)
                    .where(NativeRefreshToken.token_hash == refresh_token_hash)
                    .with_for_update()
                )
            ).one_or_none()
            denied = (
                row is None
                or row.consumed_at is not None
                or row.refresh_revoked_at is not None
                or row.expired
                or row.session_revoked_at is not None
            )
            if denied:
                if (
                    row is not None
                    and row.consumed_at is not None
                    and row.session_revoked_at is None
                ):
                    await self._session.execute(
                        update(NativeAuthSession)
                        .where(NativeAuthSession.id == row.session_id)
                        .where(NativeAuthSession.revoked_at.is_(None))
                        .values(revoked_at=func.now())
                    )
                    await self._session.execute(
                        update(NativeRefreshToken)
                        .where(NativeRefreshToken.session_id == row.session_id)
                        .where(NativeRefreshToken.revoked_at.is_(None))
                        .values(revoked_at=func.now())
                    )
                self._session.add(
                    self._native_audit_event(
                        owner_id=None if row is None else row.owner_id,
                        subject_hash=refresh_token_hash,
                        action="auth.native_refresh.denied",
                        aggregate_id="unknown" if row is None else str(row.session_id),
                        outcome=AuditOutcome.DENIED,
                        reason=(
                            AuditReasonCode.NOT_FOUND
                            if row is None
                            else AuditReasonCode.CONFLICT
                            if row.consumed_at is not None
                            else AuditReasonCode.EXPIRED
                            if row.expired
                            else AuditReasonCode.REVOKED
                        ),
                        replayed=row is not None and row.consumed_at is not None,
                    )
                )
            else:
                assert row is not None
                new_refresh = (
                    await self._session.execute(
                        insert(NativeRefreshToken)
                        .values(
                            session_id=row.session_id,
                            token_hash=new_refresh_token_hash,
                            created_at=func.now(),
                            expires_at=func.now() + refresh_ttl,
                        )
                        .returning(NativeRefreshToken.id, NativeRefreshToken.expires_at)
                    )
                ).one()
                await self._session.execute(
                    update(NativeRefreshToken)
                    .where(NativeRefreshToken.id == row.refresh_id)
                    .values(consumed_at=func.now(), replaced_by_id=new_refresh.id)
                )
                native_session = (
                    await self._session.execute(
                        update(NativeAuthSession)
                        .where(NativeAuthSession.id == row.session_id)
                        .values(
                            access_token_hash=new_access_token_hash,
                            access_expires_at=func.now() + access_ttl,
                        )
                        .returning(
                            NativeAuthSession.access_expires_at,
                            NativeAuthSession.revoked_at,
                        )
                    )
                ).one()
                self._session.add(
                    self._native_audit_event(
                        owner_id=row.owner_id,
                        subject_hash=refresh_token_hash,
                        action="auth.native_refresh.succeeded",
                        aggregate_id=str(row.session_id),
                        outcome=AuditOutcome.SUCCEEDED,
                        reason=AuditReasonCode.NONE,
                    )
                )
                result = PersistedNativeSession(
                    session_id=row.session_id,
                    owner_id=row.owner_id,
                    github_user_id=row.github_user_id,
                    github_login=row.github_login,
                    access_token_hash=new_access_token_hash,
                    access_expires_at=native_session.access_expires_at,
                    refresh_token_hash=new_refresh_token_hash,
                    refresh_expires_at=new_refresh.expires_at,
                    revoked_at=native_session.revoked_at,
                )
        return result

    async def find_active_native_session(
        self, access_token_hash: bytes
    ) -> PersistedNativeSession | None:
        row = (
            await self._session.execute(
                select(
                    NativeAuthSession.id.label("session_id"),
                    NativeAuthSession.owner_id,
                    Owner.github_user_id,
                    Owner.github_login,
                    NativeAuthSession.access_token_hash,
                    NativeAuthSession.access_expires_at,
                    NativeAuthSession.revoked_at,
                    NativeRefreshToken.token_hash.label("refresh_token_hash"),
                    NativeRefreshToken.expires_at.label("refresh_expires_at"),
                )
                .join(Owner, Owner.id == NativeAuthSession.owner_id)
                .join(
                    NativeRefreshToken,
                    NativeRefreshToken.session_id == NativeAuthSession.id,
                )
                .where(NativeAuthSession.access_token_hash == access_token_hash)
                .where(NativeAuthSession.revoked_at.is_(None))
                .where(NativeAuthSession.access_expires_at > func.now())
                .where(NativeRefreshToken.consumed_at.is_(None))
                .where(NativeRefreshToken.revoked_at.is_(None))
                .where(NativeRefreshToken.expires_at > func.now())
            )
        ).one_or_none()
        await self._session.rollback()
        if row is None:
            return None
        return PersistedNativeSession(
            session_id=row.session_id,
            owner_id=row.owner_id,
            github_user_id=row.github_user_id,
            github_login=row.github_login,
            access_token_hash=row.access_token_hash,
            access_expires_at=row.access_expires_at,
            refresh_token_hash=row.refresh_token_hash,
            refresh_expires_at=row.refresh_expires_at,
            revoked_at=row.revoked_at,
        )

    async def revoke_native_session(self, refresh_token_hash: bytes) -> bool:
        found = False
        async with transaction_scope(self._session):
            row = (
                await self._session.execute(
                    select(
                        NativeRefreshToken.session_id,
                        NativeAuthSession.owner_id,
                        NativeAuthSession.revoked_at,
                    )
                    .join(
                        NativeAuthSession,
                        NativeAuthSession.id == NativeRefreshToken.session_id,
                    )
                    .where(NativeRefreshToken.token_hash == refresh_token_hash)
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                self._session.add(
                    self._native_audit_event(
                        owner_id=None,
                        subject_hash=refresh_token_hash,
                        action="auth.native_revoke.denied",
                        aggregate_id="unknown",
                        outcome=AuditOutcome.DENIED,
                        reason=AuditReasonCode.NOT_FOUND,
                    )
                )
            else:
                found = True
                await self._session.execute(
                    update(NativeAuthSession)
                    .where(NativeAuthSession.id == row.session_id)
                    .where(NativeAuthSession.revoked_at.is_(None))
                    .values(revoked_at=func.now())
                )
                await self._session.execute(
                    update(NativeRefreshToken)
                    .where(NativeRefreshToken.session_id == row.session_id)
                    .where(NativeRefreshToken.revoked_at.is_(None))
                    .values(revoked_at=func.now())
                )
                self._session.add(
                    self._native_audit_event(
                        owner_id=row.owner_id,
                        subject_hash=refresh_token_hash,
                        action="auth.native_revoke.succeeded",
                        aggregate_id=str(row.session_id),
                        outcome=(
                            AuditOutcome.NOOP
                            if row.revoked_at is not None
                            else AuditOutcome.SUCCEEDED
                        ),
                        reason=(
                            AuditReasonCode.REVOKED
                            if row.revoked_at is not None
                            else AuditReasonCode.NONE
                        ),
                    )
                )
        return found

    @staticmethod
    def _native_audit_event(
        *,
        owner_id: int | None,
        subject_hash: bytes,
        action: str,
        aggregate_id: str,
        outcome: AuditOutcome,
        reason: AuditReasonCode,
        replayed: bool = False,
    ) -> AuditEvent:
        return AuditEvent(
            owner_id=owner_id,
            actor_kind="native_session",
            actor_subject_hash=subject_hash,
            action=action,
            aggregate_type="native_auth_session",
            aggregate_id=aggregate_id,
            request_correlation_hash=None,
            idempotency_correlation_hash=None,
            redacted_metadata=AuditMetadataV1(
                outcome=outcome,
                reason_code=reason,
                flags={
                    AuditFlagKey.AUTHENTICATED: owner_id is not None,
                    AuditFlagKey.REPLAYED: replayed,
                    AuditFlagKey.REDACTED: True,
                },
            ).to_payload(),
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
