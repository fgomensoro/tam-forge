"""HTTP API route and public error-handler wiring."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from .analysis.repository import FeedbackError
from .analysis.routes import feedback_exception_handler
from .analysis.routes import router as analysis_router
from .assessments.routes import assessments_exception_handler
from .assessments.routes import router as assessments_router
from .assessments.service import AssessmentsUnavailable
from .auth.crypto import InvalidOAuthState
from .auth.routes import auth_exception_handler, request_validation_exception_handler
from .auth.routes import router as auth_router
from .auth.service import AuthError
from .cards.routes import cards_exception_handler
from .cards.routes import router as cards_router
from .cards.service import CardsError
from .classes.routes import classes_exception_handler
from .classes.routes import router as classes_router
from .classes.service import ClassesError
from .coaching.routes import coaching_exception_handler
from .coaching.routes import router as coaching_router
from .coaching.service import CoachingError
from .coverage_ledger.routes import coverage_exception_handler
from .coverage_ledger.routes import router as coverage_router
from .coverage_ledger.service import CoverageError
from .evidence.routes import evidence_exception_handler
from .evidence.routes import router as evidence_router
from .evidence.service import EvidenceError
from .interviews.routes import interviews_exception_handler, reference_router
from .interviews.routes import router as interviews_router
from .interviews.service import InterviewsError
from .learning.routes import activity_exception_handler
from .learning.routes import router as activity_router
from .learning.service import ActivityCommandError
from .notes.routes import notes_exception_handler
from .notes.routes import router as notes_router
from .notes.service import NotesError
from .notifications.routes import notification_exception_handler
from .notifications.routes import router as notification_router
from .notifications.service import NotificationError
from .progress.routes import progress_exception_handler
from .progress.routes import router as progress_router
from .progress.service import ProgressUnavailable
from .recordings.routes import recording_exception_handler
from .recordings.routes import router as recording_router
from .recordings.service import RecordingError
from .reports.routes import reports_exception_handler
from .reports.routes import router as reports_router
from .reports.service import ReportsError
from .reviews.routes import reviews_exception_handler
from .reviews.routes import router as reviews_router
from .reviews.service import ReviewsError
from .roadmaps.ports import RoadmapWorkflowError
from .roadmaps.routes import roadmap_exception_handler
from .roadmaps.routes import router as roadmap_router
from .speech.contracts import TranscriptError
from .speech.routes import router as speech_router
from .speech.routes import transcript_exception_handler
from .storage.models import ObjectStoreError
from .today.routes import router as today_router
from .today.routes import today_exception_handler
from .today.service import TodayError
from .workspaces.routes import router as sql_execution_router
from .workspaces.routes import setup_sql_execution_runtime, sql_execution_exception_handler
from .workspaces.sql_service import SqlExecutionError


def register_routes(app: FastAPI) -> None:
    """Register the versioned API without importing database resources eagerly."""
    setup_sql_execution_runtime(app)
    app.include_router(auth_router)
    app.include_router(activity_router)
    app.include_router(coaching_router)
    app.include_router(notes_router)
    app.include_router(interviews_router)
    app.include_router(reference_router)
    app.include_router(classes_router)
    app.include_router(cards_router)
    app.include_router(progress_router)
    app.include_router(assessments_router)
    app.include_router(coverage_router)
    app.include_router(reports_router)
    app.include_router(reviews_router)
    app.include_router(evidence_router)
    app.include_router(analysis_router)
    app.include_router(notification_router)
    app.include_router(roadmap_router)
    app.include_router(recording_router)
    app.include_router(speech_router)
    app.include_router(today_router)
    app.include_router(sql_execution_router)
    app.add_exception_handler(AuthError, auth_exception_handler)
    app.add_exception_handler(InvalidOAuthState, auth_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(ActivityCommandError, activity_exception_handler)
    app.add_exception_handler(CoachingError, coaching_exception_handler)
    app.add_exception_handler(NotesError, notes_exception_handler)
    app.add_exception_handler(InterviewsError, interviews_exception_handler)
    app.add_exception_handler(ClassesError, classes_exception_handler)
    app.add_exception_handler(CardsError, cards_exception_handler)
    app.add_exception_handler(ProgressUnavailable, progress_exception_handler)
    app.add_exception_handler(AssessmentsUnavailable, assessments_exception_handler)
    app.add_exception_handler(CoverageError, coverage_exception_handler)
    app.add_exception_handler(ReportsError, reports_exception_handler)
    app.add_exception_handler(ReviewsError, reviews_exception_handler)
    app.add_exception_handler(EvidenceError, evidence_exception_handler)
    app.add_exception_handler(FeedbackError, feedback_exception_handler)
    app.add_exception_handler(NotificationError, notification_exception_handler)
    app.add_exception_handler(RoadmapWorkflowError, roadmap_exception_handler)
    app.add_exception_handler(RecordingError, recording_exception_handler)
    app.add_exception_handler(TranscriptError, transcript_exception_handler)
    app.add_exception_handler(ObjectStoreError, roadmap_exception_handler)
    app.add_exception_handler(TodayError, today_exception_handler)
    app.add_exception_handler(SqlExecutionError, sql_execution_exception_handler)
