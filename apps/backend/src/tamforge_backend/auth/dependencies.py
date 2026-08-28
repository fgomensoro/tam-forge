"""Reusable FastAPI authentication and same-origin/CSRF dependencies."""

from __future__ import annotations

import hmac
from collections.abc import Sequence
from datetime import timedelta
from typing import Annotated, cast

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..database import get_db_session
from .crypto import OAuthStateManager
from .github import GitHubOAuthGateway
from .ports import GitHubGateway
from .repository import SqlAlchemyAuthRepository
from .schemas import AuthenticatedOwner
from .service import AuthError, AuthMisconfigured, AuthService, Unauthenticated

SESSION_COOKIE_NAME = "tamforge_session"
CSRF_COOKIE_NAME = "tamforge_csrf"
STATE_COOKIE_NAME = "tamforge_oauth_state"


class OriginRejected(AuthError):
    """The mutation did not come from an explicitly allowed browser origin."""


def verify_request_origin(
    *,
    request_origin: str | None,
    allowed_origins: Sequence[str],
) -> None:
    """Require an exact configured origin using constant-time comparisons."""
    if request_origin is None or len(request_origin) > 2048:
        raise OriginRejected("request origin is not allowed")
    if not any(hmac.compare_digest(request_origin, allowed) for allowed in allowed_origins):
        raise OriginRejected("request origin is not allowed")


def get_github_gateway(request: Request) -> GitHubGateway:
    settings = cast(Settings, request.app.state.settings)
    try:
        return GitHubOAuthGateway(
            client_id=settings.github_client_id,
            client_secret=settings.github_client_secret.get_secret_value(),
        )
    except ValueError:
        raise AuthMisconfigured("authentication is unavailable") from None


def get_auth_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SqlAlchemyAuthRepository:
    return SqlAlchemyAuthRepository(session)


def get_oauth_state_manager(request: Request) -> OAuthStateManager:
    manager = getattr(request.app.state, "oauth_state_manager", None)
    if manager is not None:
        return cast(OAuthStateManager, manager)
    settings = cast(Settings, request.app.state.settings)
    try:
        manager = OAuthStateManager(
            signing_secret=settings.session_signing_secret.get_secret_value(),
            ttl=timedelta(seconds=settings.oauth_state_ttl_seconds),
        )
    except ValueError:
        raise AuthMisconfigured("authentication is unavailable") from None
    request.app.state.oauth_state_manager = manager
    return manager


def get_auth_service(
    request: Request,
    github: Annotated[GitHubGateway, Depends(get_github_gateway)],
    sessions: Annotated[SqlAlchemyAuthRepository, Depends(get_auth_repository)],
    state_manager: Annotated[OAuthStateManager, Depends(get_oauth_state_manager)],
) -> AuthService:
    settings = cast(Settings, request.app.state.settings)
    if settings.github_user_id is None:
        raise AuthMisconfigured("authentication is unavailable")
    return AuthService(
        owner_github_id=settings.github_user_id,
        github=github,
        sessions=sessions,
        state_manager=state_manager,
        session_ttl=timedelta(seconds=settings.session_ttl_seconds),
        native_sessions=sessions,
        native_access_ttl=timedelta(seconds=settings.native_access_ttl_seconds),
        native_refresh_ttl=timedelta(seconds=settings.native_refresh_ttl_seconds),
        native_exchange_ttl=timedelta(seconds=settings.native_exchange_ttl_seconds),
        native_flow_ttl=timedelta(seconds=settings.oauth_state_ttl_seconds),
    )


async def get_authenticated_owner(
    service: Annotated[AuthService, Depends(get_auth_service)],
    session_token: Annotated[
        str | None,
        Cookie(alias=SESSION_COOKIE_NAME),
    ] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> AuthenticatedOwner:
    """Return one unambiguous identity from a cookie or native bearer token."""
    if authorization is not None:
        if session_token is not None:
            raise Unauthenticated("authentication required")
        scheme, separator, token = authorization.partition(" ")
        if (
            separator != " "
            or scheme.lower() != "bearer"
            or not token
            or " " in token
        ):
            raise Unauthenticated("authentication required")
        return await service.authenticate_bearer(token)
    return await service.authenticate(session_token)


async def require_csrf_owner(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AuthenticatedOwner:
    """Preserve browser CSRF and accept only server-validated native bearer auth."""
    if owner.authentication_method == "bearer":
        return owner
    settings = cast(Settings, request.app.state.settings)
    verify_request_origin(
        request_origin=request.headers.get("origin"),
        allowed_origins=settings.cors_origins,
    )
    service.verify_csrf(owner, csrf_token)
    return owner
