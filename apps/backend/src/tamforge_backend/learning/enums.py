"""Closed activity workflow values shared by policy, persistence, and HTTP schemas."""

from __future__ import annotations

from enum import StrEnum


class ActivityState(StrEnum):
    READY = "ready"
    ACTIVE = "active"
    PAUSED = "paused"
    OUTPUT_COMMITTED = "output_committed"
    SELF_REVIEW_COMPLETE = "self_review_complete"
    AI_PROCESSING = "ai_processing"
    FEEDBACK_READY = "feedback_ready"
    CORRECTION_DUE = "correction_due"
    DEMONSTRATED = "demonstrated"
    NEEDS_WORK = "needs_work"
    INCOMPLETE = "incomplete"
    SUPERSEDED = "superseded"


class IncompleteClassification(StrEnum):
    REQUIRED = "required"
    USEFUL = "useful"
    OPTIONAL = "optional"
    SUPERSEDED = "superseded"
