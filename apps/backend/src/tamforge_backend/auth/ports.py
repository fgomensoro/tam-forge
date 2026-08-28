"""Ports that keep OAuth HTTP and PostgreSQL outside the auth policy service."""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from .schemas import GitHubIdentity, PersistedNativeSession, PersistedSession


class GitHubGateway(Protocol):
    """GitHub-specific network operations."""

    def authorization_url(self, *, state: str, redirect_uri: str) -> str: ...

    async def fetch_identity(self, *, code: str, redirect_uri: str) -> GitHubIdentity: ...


class AuthSessionRepository(Protocol):
    """Hash-only owner/session persistence operations."""

    async def create_owner_session(
        self,
        *,
        github_user_id: int,
        github_login: str,
        token_hash: bytes,
        csrf_hash: bytes,
        session_ttl: timedelta,
    ) -> PersistedSession: ...

    async def find_active_session(self, token_hash: bytes) -> PersistedSession | None: ...

    async def find_session_for_logout(self, token_hash: bytes) -> PersistedSession | None: ...

    async def revoke_session(self, token_hash: bytes) -> None: ...


class NativeAuthRepository(Protocol):
    """Atomic hash-only persistence required by native OAuth and token rotation."""

    async def create_native_oauth_flow(
        self,
        *,
        state_hash: bytes,
        pkce_challenge: str,
        flow_ttl: timedelta,
    ) -> None: ...

    async def consume_native_oauth_flow(self, state_hash: bytes) -> str | None: ...

    async def create_native_exchange(
        self,
        *,
        github_user_id: int,
        github_login: str,
        code_hash: bytes,
        pkce_challenge: str,
        exchange_ttl: timedelta,
    ) -> None: ...

    async def consume_native_exchange_and_create_session(
        self,
        *,
        code_hash: bytes,
        pkce_challenge: str,
        access_token_hash: bytes,
        refresh_token_hash: bytes,
        access_ttl: timedelta,
        refresh_ttl: timedelta,
    ) -> PersistedNativeSession | None: ...

    async def rotate_native_refresh_token(
        self,
        *,
        refresh_token_hash: bytes,
        new_access_token_hash: bytes,
        new_refresh_token_hash: bytes,
        access_ttl: timedelta,
        refresh_ttl: timedelta,
    ) -> PersistedNativeSession | None: ...

    async def find_active_native_session(
        self, access_token_hash: bytes
    ) -> PersistedNativeSession | None: ...

    async def revoke_native_session(self, refresh_token_hash: bytes) -> bool: ...
