"""Ports that keep OAuth HTTP and PostgreSQL outside the auth policy service."""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from .schemas import GitHubIdentity, PersistedSession


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
