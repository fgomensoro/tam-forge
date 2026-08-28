"""Pure single-owner authentication policy and session orchestration."""

from __future__ import annotations

import hmac
from datetime import timedelta

from .crypto import OAuthStateManager, hash_secret, issue_browser_secret
from .ports import AuthSessionRepository, GitHubGateway
from .schemas import (
    AuthenticatedOwner,
    GitHubIdentity,
    IssuedSession,
    OAuthStart,
    PersistedSession,
)


class AuthError(Exception):
    """Base class for public-safe authentication failures."""


class ForbiddenIdentity(AuthError):
    """GitHub authenticated a user other than the configured owner."""


class Unauthenticated(AuthError):
    """No active browser session exists for the supplied token."""


class CsrfRejected(AuthError):
    """The request's CSRF secret is absent or not bound to the session."""


class ExternalIdentityProviderError(AuthError):
    """GitHub could not complete an identity lookup safely."""


class AuthMisconfigured(AuthError):
    """Required authentication configuration is unavailable."""


class AuthService:
    """Authenticate only the immutable numeric owner and issue hash-only sessions."""

    def __init__(
        self,
        *,
        owner_github_id: int,
        github: GitHubGateway,
        sessions: AuthSessionRepository,
        state_manager: OAuthStateManager,
        session_ttl: timedelta,
    ) -> None:
        if owner_github_id <= 0:
            raise ValueError("owner GitHub ID is invalid")
        if not timedelta(minutes=5) <= session_ttl <= timedelta(days=1):
            raise ValueError("session lifetime is invalid")
        self.owner_github_id = owner_github_id
        self.github = github
        self.sessions = sessions
        self.state_manager = state_manager
        self.session_ttl = session_ttl

    def start_login(self, *, redirect_uri: str) -> OAuthStart:
        state = self.state_manager.issue()
        return OAuthStart(
            state=state,
            authorization_url=self.github.authorization_url(
                state=state,
                redirect_uri=redirect_uri,
            ),
        )

    async def complete_login(
        self,
        *,
        code: str | None,
        state: str | None,
        state_cookie: str | None,
        redirect_uri: str,
    ) -> IssuedSession:
        self.state_manager.consume(state=state, state_cookie=state_cookie)
        if not code or len(code) > 512:
            raise Unauthenticated("login failed")
        identity = await self.github.fetch_identity(code=code, redirect_uri=redirect_uri)
        if identity.id != self.owner_github_id:
            raise ForbiddenIdentity("identity is not authorized")
        return await self.issue_session(identity)

    async def issue_session(self, identity: GitHubIdentity) -> IssuedSession:
        if identity.id != self.owner_github_id:
            raise ForbiddenIdentity("identity is not authorized")
        raw_session_token = issue_browser_secret()
        raw_csrf_token = issue_browser_secret()
        persisted = await self.sessions.create_owner_session(
            github_user_id=identity.id,
            github_login=identity.login,
            token_hash=hash_secret(raw_session_token),
            csrf_hash=hash_secret(raw_csrf_token),
            session_ttl=self.session_ttl,
        )
        return IssuedSession(
            raw_session_token=raw_session_token,
            raw_csrf_token=raw_csrf_token,
            persisted_session=persisted,
        )

    async def issue_session_for_identity(
        self, github_user_id: int, github_login: str
    ) -> IssuedSession:
        """Convenience boundary for trusted identity adapters and focused tests."""
        return await self.issue_session(GitHubIdentity(id=github_user_id, login=github_login))

    async def authenticate(self, raw_session_token: str | None) -> AuthenticatedOwner:
        token_hash = self._browser_secret_hash(raw_session_token)
        persisted = await self.sessions.find_active_session(token_hash)
        if persisted is None:
            raise Unauthenticated("authentication required")
        return self._authenticated_owner(persisted)

    def verify_csrf(self, owner: AuthenticatedOwner, raw_csrf_token: str | None) -> None:
        supplied_hash = self._browser_secret_hash(raw_csrf_token, csrf=True)
        if not hmac.compare_digest(owner.csrf_hash, supplied_hash):
            raise CsrfRejected("CSRF validation failed")

    async def expose_csrf(
        self,
        owner: AuthenticatedOwner,
        raw_csrf_token: str | None,
    ) -> str:
        self.verify_csrf(owner, raw_csrf_token)
        assert raw_csrf_token is not None
        return raw_csrf_token

    async def logout(
        self,
        raw_session_token: str | None,
        raw_csrf_token: str | None,
    ) -> None:
        token_hash = self._browser_secret_hash(raw_session_token)
        persisted = await self.sessions.find_session_for_logout(token_hash)
        if persisted is None:
            raise Unauthenticated("authentication required")
        owner = self._authenticated_owner(persisted)
        self.verify_csrf(owner, raw_csrf_token)
        await self.sessions.revoke_session(token_hash)

    @staticmethod
    def _authenticated_owner(session: PersistedSession) -> AuthenticatedOwner:
        return AuthenticatedOwner(
            owner_id=session.owner_id,
            github_user_id=session.github_user_id,
            github_login=session.github_login,
            session_id=session.session_id,
            csrf_hash=session.csrf_hash,
            expires_at=session.expires_at,
        )

    @staticmethod
    def _browser_secret_hash(raw: str | None, *, csrf: bool = False) -> bytes:
        if (
            raw is None
            or len(raw) != 43
            or any(not (character.isalnum() or character in "-_") for character in raw)
        ):
            if csrf:
                raise CsrfRejected("CSRF validation failed")
            raise Unauthenticated("authentication required")
        return hash_secret(raw)
