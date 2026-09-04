"""Construct safe events rather than attempting to redact arbitrary prose."""

from __future__ import annotations

import json
import logging
import math
from typing import cast
from uuid import UUID

EVENTS = frozenset(
    {
        "request_completed",
        "request_failed",
        "component_changed",
        "job_completed",
        "server_event",
    }
)
STATUSES = frozenset(
    {
        "ok",
        "succeeded",
        "failed",
        "queued",
        "running",
        "canceled",
        "pending",
        "needs_attention",
        "unknown",
        "overdue",
    }
)
REASONS = frozenset(
    {
        "none",
        "quota",
        "auth",
        "service",
        "memory_pressure",
        "disk_pressure",
        "stale",
        "not_observed",
        "processing_failure",
        "internal_error",
        "invalid_input",
        "permission_required",
        "durability_failure",
        "integrity_failure",
        "timeout",
        "transient_dependency",
        "resource_exhausted",
    }
)


def safe_event(event: str, **fields: object) -> str:
    """Only UUID objects, integer row IDs, finite numbers and enums survive.

    In particular, an allowlisted field name is not permission to log a string.
    Never call str/repr on a rejected object (including exception objects).
    """
    payload: dict[str, object] = {"event": event if event in EVENTS else "invalid_event"}
    for key, value in fields.items():
        if key == "request_id" and type(value) is UUID:
            payload[key] = str(value)
        elif key in {"job_id", "evidence_id", "version"}:
            if type(value) is int and 0 < value < 2**63:
                payload[key] = value
        elif key in {"duration_seconds", "size_bytes"}:
            if type(value) in {int, float}:
                number = cast(int | float, value)
                if 0 <= number <= 1e18 and math.isfinite(number):
                    payload[key] = number
        elif key == "status" and type(value) is str and value in STATUSES:
            payload[key] = value
        elif key == "error_code" and type(value) is str and value in REASONS:
            payload[key] = value
        elif key == "http_status" and type(value) is int and 100 <= value <= 599:
            payload[key] = value
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ServerErrorFilter(logging.Filter):
    """Uvicorn also logs WebSocket targets at INFO, so sanitize every level."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING or record.exc_info or record.stack_info:
            record.msg = safe_event("request_failed", error_code="internal_error")
        else:
            record.msg = safe_event("server_event")
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


class AccessLogFilter(logging.Filter):
    """Suppress raw access records; OperationalMiddleware emits safe events.

    Uvicorn's AccessFormatter requires its original five-argument record, so
    rewriting it to JSON would fail formatting and dump logging diagnostics.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return False
