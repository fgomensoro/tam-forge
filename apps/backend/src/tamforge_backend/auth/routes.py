"""GitHub OAuth and single-owner browser-session HTTP routes."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Cookie, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from ..config import Settings
from .crypto import InvalidOAuthState
from .dependencies import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    STATE_COOKIE_NAME,
    OriginRejected,
    get_auth_service,
    get_authenticated_owner,
    verify_request_origin,
)
from .schemas import AuthenticatedOwner, ProblemResponse, SessionResponse
from .service import (
    AuthError,
    AuthMisconfigured,
    AuthService,
    CsrfRejected,
    ExternalIdentityProviderError,
    ForbiddenIdentity,
    Unauthenticated,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


def _set_cookie(
    response: Response,
    *,
    name: str,
    value: str,
    max_age: int,
    path: str,
    secure: bool,
) -> None:
    response.set_cookie(
        key=name,
        value=value,
        max_age=max_age,
        path=path,
        secure=secure,
        httponly=True,
        samesite="lax",
    )


def _clear_cookie(
    response: Response,
    *,
    name: str,
    path: str,
    secure: bool,
) -> None:
    response.delete_cookie(
        key=name,
        path=path,
        secure=secure,
        httponly=True,
        samesite="lax",
    )


def problem_response(exc: Exception) -> JSONResponse:
    """Map internal auth failures to stable generic problem documents."""
    if isinstance(exc, InvalidOAuthState):
        status, title, detail, code = (
            400,
            "Invalid OAuth state",
            "Login could not be completed.",
            "invalid_oauth_state",
        )
    elif isinstance(exc, Unauthenticated):
        status, title, detail, code = (
            401,
            "Authentication required",
            "Authentication is required.",
            "unauthenticated",
        )
    elif isinstance(exc, ForbiddenIdentity):
        status, title, detail, code = (
            403,
            "Authentication failed",
            "Authentication failed.",
            "forbidden_identity",
        )
    elif isinstance(exc, OriginRejected):
        status, title, detail, code = (
            403,
            "Request rejected",
            "Request verification failed.",
            "origin_rejected",
        )
    elif isinstance(exc, CsrfRejected):
        status, title, detail, code = (
            403,
            "Request rejected",
            "Request verification failed.",
            "csrf_rejected",
        )
    elif isinstance(exc, ExternalIdentityProviderError):
        status, title, detail, code = (
            502,
            "Authentication unavailable",
            "Authentication is temporarily unavailable.",
            "identity_provider_error",
        )
    elif isinstance(exc, AuthMisconfigured):
        status, title, detail, code = (
            503,
            "Authentication unavailable",
            "Authentication is unavailable.",
            "auth_unavailable",
        )
    else:
        status, title, detail, code = (
            500,
            "Authentication failed",
            "Authentication failed.",
            "auth_error",
        )
    problem = ProblemResponse(
        type=f"https://tamforge.local/problems/{code}",
        title=title,
        status=status,
        detail=detail,
        code=code,
    )
    response = JSONResponse(
        problem.model_dump(),
        status_code=status,
        media_type="application/problem+json",
    )
    _prevent_storage(response)
    return response


async def auth_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return problem_response(exc)


@router.get("/login", status_code=302)
async def login(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    settings = _settings(request)
    started = service.start_login(redirect_uri=settings.github_callback_url)
    response = RedirectResponse(started.authorization_url, status_code=302)
    _prevent_storage(response)
    _set_cookie(
        response,
        name=STATE_COOKIE_NAME,
        value=started.state,
        max_age=settings.oauth_state_ttl_seconds,
        path="/api/v1/auth/callback",
        secure=bool(settings.secure_cookies),
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    state_cookie: Annotated[
        str | None,
        Cookie(alias=STATE_COOKIE_NAME),
    ] = None,
) -> Response:
    settings = _settings(request)
    try:
        issued = await service.complete_login(
            code=code,
            state=state,
            state_cookie=state_cookie,
            redirect_uri=settings.github_callback_url,
        )
        response: Response = RedirectResponse("/", status_code=303)
        _prevent_storage(response)
        _set_cookie(
            response,
            name=SESSION_COOKIE_NAME,
            value=issued.raw_session_token,
            max_age=settings.session_ttl_seconds,
            path="/api/v1",
            secure=bool(settings.secure_cookies),
        )
        _set_cookie(
            response,
            name=CSRF_COOKIE_NAME,
            value=issued.raw_csrf_token,
            max_age=settings.session_ttl_seconds,
            path="/api/v1/auth/session",
            secure=bool(settings.secure_cookies),
        )
    except (AuthError, InvalidOAuthState) as exc:
        response = problem_response(exc)
    _clear_cookie(
        response,
        name=STATE_COOKIE_NAME,
        path="/api/v1/auth/callback",
        secure=bool(settings.secure_cookies),
    )
    return response


@router.get("/session", response_model=SessionResponse)
async def session(
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    csrf_cookie: Annotated[
        str | None,
        Cookie(alias=CSRF_COOKIE_NAME),
    ] = None,
) -> SessionResponse:
    csrf_token = await service.expose_csrf(owner, csrf_cookie)
    _prevent_storage(response)
    return SessionResponse(github_login=owner.github_login, csrf_token=csrf_token)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    session_token: Annotated[
        str | None,
        Cookie(alias=SESSION_COOKIE_NAME),
    ] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Response:
    settings = _settings(request)
    verify_request_origin(
        request_origin=request.headers.get("origin"),
        allowed_origins=settings.cors_origins,
    )
    await service.logout(session_token, csrf_token)
    response = Response(status_code=204)
    _prevent_storage(response)
    _clear_cookie(
        response,
        name=SESSION_COOKIE_NAME,
        path="/api/v1",
        secure=bool(settings.secure_cookies),
    )
    _clear_cookie(
        response,
        name=CSRF_COOKIE_NAME,
        path="/api/v1/auth/session",
        secure=bool(settings.secure_cookies),
    )
    return response
