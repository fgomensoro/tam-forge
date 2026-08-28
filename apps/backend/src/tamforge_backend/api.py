"""HTTP API route and public error-handler wiring."""

from fastapi import FastAPI

from .auth.crypto import InvalidOAuthState
from .auth.routes import auth_exception_handler
from .auth.routes import router as auth_router
from .auth.service import AuthError
from .evidence.routes import evidence_exception_handler
from .evidence.routes import router as evidence_router
from .evidence.service import EvidenceError
from .learning.routes import activity_exception_handler
from .learning.routes import router as activity_router
from .learning.service import ActivityCommandError
from .notifications.routes import notification_exception_handler
from .notifications.routes import router as notification_router
from .notifications.service import NotificationError
from .roadmaps.ports import RoadmapWorkflowError
from .roadmaps.routes import roadmap_exception_handler
from .roadmaps.routes import router as roadmap_router
from .storage.models import ObjectStoreError
from .today.routes import router as today_router
from .today.routes import today_exception_handler
from .today.service import TodayError


def register_routes(app: FastAPI) -> None:
    """Register the versioned API without importing database resources eagerly."""
    app.include_router(auth_router)
    app.include_router(activity_router)
    app.include_router(evidence_router)
    app.include_router(notification_router)
    app.include_router(roadmap_router)
    app.include_router(today_router)
    app.add_exception_handler(AuthError, auth_exception_handler)
    app.add_exception_handler(InvalidOAuthState, auth_exception_handler)
    app.add_exception_handler(ActivityCommandError, activity_exception_handler)
    app.add_exception_handler(EvidenceError, evidence_exception_handler)
    app.add_exception_handler(NotificationError, notification_exception_handler)
    app.add_exception_handler(RoadmapWorkflowError, roadmap_exception_handler)
    app.add_exception_handler(ObjectStoreError, roadmap_exception_handler)
    app.add_exception_handler(TodayError, today_exception_handler)
