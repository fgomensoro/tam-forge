"""Pure single-owner authentication policy and session orchestration."""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import timedelta

from .crypto import InvalidOAuthState, OAuthStateManager, hash_secret, issue_browser_secret
from .ports import AuthSessionRepository, GitHubGateway, NativeAuthRepository
from .schemas import (
    AuthenticatedOwner,
    GitHubIdentity,
    IssuedNativeCredentials,
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
        native_sessions: NativeAuthRepository | None = None,
        native_access_ttl: timedelta = timedelta(minutes=15),
        native_refresh_ttl: timedelta = timedelta(days=30),
        native_exchange_ttl: timedelta = timedelta(minutes=2),
        native_flow_ttl: timedelta = timedelta(minutes=5),
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
        if not timedelta(minutes=5) <= native_access_ttl <= timedelta(hours=1):
            raise ValueError("native access lifetime is invalid")
        if not timedelta(days=1) <= native_refresh_ttl <= timedelta(days=90):
            raise ValueError("native refresh lifetime is invalid")
        if not timedelta(minutes=1) <= native_exchange_ttl <= timedelta(minutes=5):
            raise ValueError("native exchange lifetime is invalid")
        if not timedelta(minutes=1) <= native_flow_ttl <= timedelta(minutes=10):
            raise ValueError("native OAuth state lifetime is invalid")
        self.native_sessions = native_sessions
        self.native_access_ttl = native_access_ttl
        self.native_refresh_ttl = native_refresh_ttl
        self.native_exchange_ttl = native_exchange_ttl
        self.native_flow_ttl = native_flow_ttl

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

    async def start_native_login(self, *, pkce_challenge: str, redirect_uri: str) -> OAuthStart:
        repository = self._native_repository()
        self._validate_pkce_challenge(pkce_challenge)
        state = issue_browser_secret()
        await repository.create_native_oauth_flow(
            state_hash=hash_secret(state),
            pkce_challenge=pkce_challenge,
            flow_ttl=self.native_flow_ttl,
        )
        return OAuthStart(
            state=state,
            authorization_url=self.github.authorization_url(state=state, redirect_uri=redirect_uri),
        )

    async def complete_native_login(
        self,
        *,
        code: str | None,
        state: str | None,
        redirect_uri: str,
    ) -> str:
        repository = self._native_repository()
        state_hash = self._native_secret_hash(state, state_error=True)
        pkce_challenge = await repository.consume_native_oauth_flow(state_hash)
        if pkce_challenge is None:
            raise InvalidOAuthState("native OAuth state is invalid")
        if not code or len(code) > 512:
            raise Unauthenticated("login failed")
        identity = await self.github.fetch_identity(code=code, redirect_uri=redirect_uri)
        if identity.id != self.owner_github_id:
            raise ForbiddenIdentity("identity is not authorized")
        exchange_code = issue_browser_secret()
        await repository.create_native_exchange(
            github_user_id=identity.id,
            github_login=identity.login,
            code_hash=hash_secret(exchange_code),
            pkce_challenge=pkce_challenge,
            exchange_ttl=self.native_exchange_ttl,
        )
        return exchange_code

    async def exchange_native_code(
        self,
        *,
        code: str | None,
        code_verifier: str | None,
    ) -> IssuedNativeCredentials:
        repository = self._native_repository()
        code_hash = self._native_secret_hash(code)
        challenge = self.pkce_challenge(code_verifier)
        access_token = issue_browser_secret()
        refresh_token = issue_browser_secret()
        persisted = await repository.consume_native_exchange_and_create_session(
            code_hash=code_hash,
            pkce_challenge=challenge,
            access_token_hash=hash_secret(access_token),
            refresh_token_hash=hash_secret(refresh_token),
            access_ttl=self.native_access_ttl,
            refresh_ttl=self.native_refresh_ttl,
        )
        if persisted is None:
            raise Unauthenticated("native authentication failed")
        return IssuedNativeCredentials(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_in=int(self.native_access_ttl.total_seconds()),
            github_login=persisted.github_login,
        )

    async def refresh_native_session(
        self, raw_refresh_token: str | None
    ) -> IssuedNativeCredentials:
        repository = self._native_repository()
        refresh_hash = self._native_secret_hash(raw_refresh_token)
        access_token = issue_browser_secret()
        refresh_token = issue_browser_secret()
        persisted = await repository.rotate_native_refresh_token(
            refresh_token_hash=refresh_hash,
            new_access_token_hash=hash_secret(access_token),
            new_refresh_token_hash=hash_secret(refresh_token),
            access_ttl=self.native_access_ttl,
            refresh_ttl=self.native_refresh_ttl,
        )
        if persisted is None:
            raise Unauthenticated("native authentication failed")
        return IssuedNativeCredentials(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_in=int(self.native_access_ttl.total_seconds()),
            github_login=persisted.github_login,
        )

    async def authenticate_bearer(self, raw_access_token: str | None) -> AuthenticatedOwner:
        repository = self._native_repository()
        token_hash = self._native_secret_hash(raw_access_token)
        persisted = await repository.find_active_native_session(token_hash)
        if persisted is None:
            raise Unauthenticated("authentication required")
        return AuthenticatedOwner(
            owner_id=persisted.owner_id,
            github_user_id=persisted.github_user_id,
            github_login=persisted.github_login,
            session_id=persisted.session_id,
            csrf_hash=None,
            expires_at=persisted.access_expires_at,
            authentication_method="bearer",
        )

    async def revoke_native_session(self, raw_refresh_token: str | None) -> None:
        repository = self._native_repository()
        refresh_hash = self._native_secret_hash(raw_refresh_token)
        await repository.revoke_native_session(refresh_hash)

    @staticmethod
    def pkce_challenge(code_verifier: str | None) -> str:
        if (
            code_verifier is None
            or not 43 <= len(code_verifier) <= 128
            or any(not (character.isalnum() or character in "-._~") for character in code_verifier)
        ):
            raise Unauthenticated("native authentication failed")
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    @staticmethod
    def looks_like_native_state(state: str | None) -> bool:
        return (
            state is not None
            and len(state) == 43
            and all(character.isalnum() or character in "-_" for character in state)
        )

    async def authenticate(self, raw_session_token: str | None) -> AuthenticatedOwner:
        token_hash = self._browser_secret_hash(raw_session_token)
        persisted = await self.sessions.find_active_session(token_hash)
        if persisted is None:
            raise Unauthenticated("authentication required")
        return self._authenticated_owner(persisted)

    def verify_csrf(self, owner: AuthenticatedOwner, raw_csrf_token: str | None) -> None:
        if owner.authentication_method != "cookie" or owner.csrf_hash is None:
            raise CsrfRejected("CSRF validation failed")
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
            authentication_method="cookie",
        )

    def _native_repository(self) -> NativeAuthRepository:
        if self.native_sessions is None:
            raise AuthMisconfigured("native authentication is unavailable")
        return self.native_sessions

    @staticmethod
    def _validate_pkce_challenge(challenge: str) -> None:
        if (
            len(challenge) != 43
            or any(not (character.isalnum() or character in "-_") for character in challenge)
        ):
            raise Unauthenticated("native authentication failed")

    @staticmethod
    def _native_secret_hash(raw: str | None, *, state_error: bool = False) -> bytes:
        if (
            raw is None
            or len(raw) != 43
            or any(not (character.isalnum() or character in "-_") for character in raw)
        ):
            if state_error:
                raise InvalidOAuthState("native OAuth state is invalid")
            raise Unauthenticated("native authentication failed")
        return hash_secret(raw)

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
