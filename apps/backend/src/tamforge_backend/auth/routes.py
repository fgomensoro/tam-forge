"""GitHub OAuth and single-owner browser-session HTTP routes."""

from __future__ import annotations

from typing import Annotated, Any, cast
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, Header, Query, Request, Response
from fastapi.exception_handlers import (
    request_validation_exception_handler as default_request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
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
from .schemas import (
    AuthenticatedOwner,
    IssuedNativeCredentials,
    NativeOAuthStartRequest,
    NativeOAuthStartResponse,
    NativeRefreshRequest,
    NativeSessionResponse,
    NativeTokenExchangeRequest,
    NativeTokenResponse,
    ProblemResponse,
    SessionResponse,
)
from .service import (
    AuthError,
    AuthMisconfigured,
    AuthService,
    CsrfRejected,
    ExternalIdentityProviderError,
    ForbiddenIdentity,
    NativeAuthCapacityExceeded,
    Unauthenticated,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
NATIVE_CALLBACK_URL = "tamforge://auth/callback"
NATIVE_VALIDATION_RESPONSE: dict[int | str, dict[str, Any]] = {
    422: {
        "model": ProblemResponse,
        "description": "Invalid native authentication request.",
    },
}
NATIVE_START_RESPONSES: dict[int | str, dict[str, Any]] = {
    **NATIVE_VALIDATION_RESPONSE,
    429: {
        "model": ProblemResponse,
        "description": "Native authentication is temporarily busy.",
    },
}


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
    elif isinstance(exc, NativeAuthCapacityExceeded):
        status, title, detail, code = (
            429,
            "Authentication busy",
            "Authentication is temporarily busy. Try again shortly.",
            "native_auth_capacity",
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
    if isinstance(exc, NativeAuthCapacityExceeded):
        response.headers["Retry-After"] = "60"
    _prevent_storage(response)
    return response


async def auth_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return problem_response(exc)


async def request_validation_exception_handler(
    request: Request,
    exc: Exception,
) -> Response:
    """Keep native credentials out of FastAPI's default validation details."""
    if not isinstance(exc, RequestValidationError):
        raise exc
    is_secret_bearing_request = request.url.path.startswith(
        ("/api/v1/auth/native/", "/api/v1/recordings")
    )
    if not is_secret_bearing_request:
        return await default_request_validation_exception_handler(request, exc)
    if request.url.path.startswith("/api/v1/recordings"):
        problem = ProblemResponse(
            type="https://tamforge.local/problems/invalid_recording_request",
            title="Invalid recording request",
            status=422,
            detail="Recording request is invalid.",
            code="invalid_recording_request",
        )
        response = JSONResponse(
            problem.model_dump(),
            status_code=422,
            media_type="application/problem+json",
        )
        _prevent_storage(response)
        return response
    problem = ProblemResponse(
        type="https://tamforge.local/problems/invalid_native_auth_request",
        title="Invalid authentication request",
        status=422,
        detail="Authentication request is invalid.",
        code="invalid_native_auth_request",
    )
    response = JSONResponse(
        problem.model_dump(),
        status_code=422,
        media_type="application/problem+json",
    )
    _prevent_storage(response)
    return response


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
    response: Response
    try:
        if AuthService.looks_like_native_state(state):
            exchange_code = await service.complete_native_login(
                code=code,
                state=state,
                redirect_uri=settings.github_callback_url,
            )
            native_response = RedirectResponse(
                f"{NATIVE_CALLBACK_URL}?{urlencode({'code': exchange_code})}",
                status_code=303,
            )
            _prevent_storage(native_response)
            return native_response
        issued = await service.complete_login(
            code=code,
            state=state,
            state_cookie=state_cookie,
            redirect_uri=settings.github_callback_url,
        )
        response = RedirectResponse("/", status_code=303)
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


@router.post(
    "/native/start",
    response_model=NativeOAuthStartResponse,
    responses=NATIVE_START_RESPONSES,
)
async def native_start(
    request: Request,
    response: Response,
    payload: NativeOAuthStartRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> NativeOAuthStartResponse:
    settings = _settings(request)
    started = await service.start_native_login(
        pkce_challenge=payload.code_challenge,
        redirect_uri=settings.github_callback_url,
    )
    _prevent_storage(response)
    return NativeOAuthStartResponse(authorization_url=started.authorization_url)


def _native_token_response(issued: IssuedNativeCredentials) -> NativeTokenResponse:
    return NativeTokenResponse(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=issued.access_expires_in,
        github_login=issued.github_login,
    )


@router.post(
    "/native/exchange",
    response_model=NativeTokenResponse,
    responses=NATIVE_VALIDATION_RESPONSE,
)
async def native_exchange(
    response: Response,
    payload: NativeTokenExchangeRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> NativeTokenResponse:
    issued = await service.exchange_native_code(
        code=payload.code,
        code_verifier=payload.code_verifier,
    )
    _prevent_storage(response)
    return _native_token_response(issued)


@router.post(
    "/native/refresh",
    response_model=NativeTokenResponse,
    responses=NATIVE_VALIDATION_RESPONSE,
)
async def native_refresh(
    response: Response,
    payload: NativeRefreshRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> NativeTokenResponse:
    issued = await service.refresh_native_session(payload.refresh_token)
    _prevent_storage(response)
    return _native_token_response(issued)


@router.post(
    "/native/revoke",
    status_code=204,
    responses=NATIVE_VALIDATION_RESPONSE,
)
async def native_revoke(
    payload: NativeRefreshRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    await service.revoke_native_session(payload.refresh_token)
    response = Response(status_code=204)
    _prevent_storage(response)
    return response


@router.get("/native/session", response_model=NativeSessionResponse)
async def native_session(
    response: Response,
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> NativeSessionResponse:
    if owner.authentication_method != "bearer":
        raise Unauthenticated("authentication required")
    _prevent_storage(response)
    return NativeSessionResponse(github_login=owner.github_login)


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
