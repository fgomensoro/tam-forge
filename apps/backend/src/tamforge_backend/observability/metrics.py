"""Process-local aggregate metrics with fixed names and bounded label sets."""

from __future__ import annotations

import math
from threading import Lock

from .logging import REASONS, STATUSES

CATEGORIES = frozenset(
    {
        "http",
        "ingest",
        "queue",
        "speech",
        "feedback",
        "claude",
        "backup",
        "resources",
        "export",
        "import",
        "retention",
        "interviewer",
        "notification",
    }
)
NOTIFICATIONS = frozenset(
    {
        "feedback_ready",
        "correction_due",
        "upcoming_real_interview",
        "saturday_assessment",
        "processing_failure_requires_action",
    }
)
# Each metric has a closed set of label keys. No IDs, model names, URLs or text.
SCHEMAS: dict[str, tuple[str, frozenset[str]]] = {
    "http_requests_total": ("counter", frozenset({"status"})),
    "http_duration_seconds": ("summary", frozenset({"status"})),
    "ingest_ack_seconds": ("summary", frozenset({"status"})),
    "queue_depth": ("gauge", frozenset({"category"})),
    "queue_oldest_seconds": ("gauge", frozenset({"category"})),
    "job_duration_seconds": ("summary", frozenset({"category", "status"})),
    "job_errors_total": ("counter", frozenset({"category", "reason"})),
    "speech_deadline_total": ("counter", frozenset({"status"})),
    "composite_total": ("counter", frozenset({"window", "status"})),
    "composite_wall_seconds": ("summary", frozenset({"window", "status"})),
    "composite_active_seconds": ("summary", frozenset({"window", "status"})),
    "composite_suspension_seconds": ("summary", frozenset({"window", "reason"})),
    "overdue_runs": ("gauge", frozenset({"category"})),
    "capability_state": ("gauge", frozenset({"category"})),
    "backup_age_seconds": ("gauge", frozenset()),
    "backup_verified": ("gauge", frozenset()),
    "disk_free_bytes": ("gauge", frozenset()),
    "ram_available_bytes": ("gauge", frozenset()),
    "integrity_total": ("counter", frozenset({"category", "status"})),
    "recoverable_deletions": ("gauge", frozenset({"status"})),
    "interviewer_followup_seconds": ("summary", frozenset({"status"})),
    "notifications_total": ("counter", frozenset({"notification"})),
}
LABEL_VALUES = {
    "category": CATEGORIES,
    "status": STATUSES,
    "reason": REASONS,
    "window": frozenset({"15", "60"}),
    "notification": NOTIFICATIONS,
}
Key = tuple[str, tuple[tuple[str, str], ...]]


def _number(value: float) -> bool:
    return type(value) in {int, float} and 0 <= value <= 1e18 and math.isfinite(value)


class Metrics:
    """No raw samples; an explicit series ceiling also bounds memory use."""

    def __init__(self) -> None:
        self._values: dict[Key, tuple[float, int]] = {}
        self._lock = Lock()

    def observe(self, name: str, value: float, **labels: str) -> None:
        schema = SCHEMAS.get(name)
        if schema is None or not _number(value):
            raise ValueError("invalid metric")
        kind, allowed_keys = schema
        if any(
            key not in allowed_keys or type(label) is not str or label not in LABEL_VALUES[key]
            for key, label in labels.items()
        ):
            raise ValueError("invalid metric labels")
        key: Key = (name, tuple(sorted(labels.items())))
        with self._lock:
            if key not in self._values and len(self._values) >= 4096:
                raise ValueError("metric series limit reached")
            previous, count = self._values.get(key, (0.0, 0))
            total = value if kind == "gauge" else previous + value
            if not math.isfinite(total):
                raise ValueError("invalid metric total")
            self._values[key] = (total, count + 1)

    def render(self) -> str:
        with self._lock:
            values = sorted(self._values.items())
        lines = []
        for (name, labels), (value, count) in values:
            suffix = "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}" if labels else ""
            if SCHEMAS[name][0] == "summary":
                lines.append(f"tamforge_{name}_count{suffix} {count}")
                lines.append(f"tamforge_{name}_sum{suffix} {value:g}")
            else:
                lines.append(f"tamforge_{name}{suffix} {value:g}")
        return "\n".join(lines) + ("\n" if lines else "")


def record_composite(
    metrics: Metrics,
    *,
    window_minutes: int,
    wall_seconds: float,
    active_seconds: float,
    suspension_seconds: float,
    suspension_reason: str,
    completed: bool,
    speech_deadline_met: bool,
    deadline_seconds: float,
) -> str:
    """Observe one finalized run, or a single overdue/pending evaluation.

    The durable producer owns exactly-once reporting. These process-local totals
    do not replace durable SLO evidence. Thresholds come from approved policy.
    """
    if (
        type(window_minutes) is not int
        or window_minutes not in {15, 60}
        or not all(
            _number(v)
            for v in (
                wall_seconds,
                active_seconds,
                suspension_seconds,
                deadline_seconds,
            )
        )
        or deadline_seconds <= 0
        or not math.isclose(wall_seconds, active_seconds + suspension_seconds, abs_tol=0.001)
        or suspension_reason not in {"none", "quota", "auth", "service", "memory_pressure"}
        or (suspension_seconds > 0) != (suspension_reason != "none")
        or type(completed) is not bool
        or type(speech_deadline_met) is not bool
    ):
        raise ValueError("invalid composite observation")
    if suspension_reason != "none":
        status = "needs_attention"
    elif not speech_deadline_met:
        status = "failed"
    elif not completed:
        status = "overdue" if wall_seconds > deadline_seconds else "pending"
    else:
        status = "succeeded" if active_seconds <= deadline_seconds else "failed"
    window = str(window_minutes)
    metrics.observe("composite_total", 1, window=window, status=status)
    metrics.observe("composite_wall_seconds", wall_seconds, window=window, status=status)
    metrics.observe("composite_active_seconds", active_seconds, window=window, status=status)
    metrics.observe(
        "composite_suspension_seconds",
        suspension_seconds,
        window=window,
        reason=suspension_reason,
    )
    return status
