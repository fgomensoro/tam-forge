"""HTTP API route and public error-handler wiring."""

from fastapi import FastAPI

from .auth.crypto import InvalidOAuthState
from .auth.routes import auth_exception_handler
from .auth.routes import router as auth_router
from .auth.service import AuthError


def register_routes(app: FastAPI) -> None:
    """Register the versioned API without importing database resources eagerly."""
    app.include_router(auth_router)
    app.add_exception_handler(AuthError, auth_exception_handler)
    app.add_exception_handler(InvalidOAuthState, auth_exception_handler)
