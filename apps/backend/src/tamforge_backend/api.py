"""HTTP API route and public error-handler wiring."""

from fastapi import FastAPI

from .auth.crypto import InvalidOAuthState
from .auth.routes import auth_exception_handler
from .auth.routes import router as auth_router
from .auth.service import AuthError
from .roadmaps.ports import RoadmapWorkflowError
from .roadmaps.routes import roadmap_exception_handler
from .roadmaps.routes import router as roadmap_router
from .storage.models import ObjectStoreError


def register_routes(app: FastAPI) -> None:
    """Register the versioned API without importing database resources eagerly."""
    app.include_router(auth_router)
    app.include_router(roadmap_router)
    app.add_exception_handler(AuthError, auth_exception_handler)
    app.add_exception_handler(InvalidOAuthState, auth_exception_handler)
    app.add_exception_handler(RoadmapWorkflowError, roadmap_exception_handler)
    app.add_exception_handler(ObjectStoreError, roadmap_exception_handler)
