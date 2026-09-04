import json
from uuid import uuid4

from tamforge_backend.observability.logging import safe_event


def test_events_keep_only_typed_operational_fields() -> None:
    request_id = uuid4()
    event = json.loads(
        safe_event(
            "request_completed",
            request_id=request_id,
            job_id=12,
            duration_seconds=1.5,
            status="succeeded",
            error_code="internal_error",
            transcript="private phrase",
            prompt="private prompt",
            exception=RuntimeError("secret"),
        )
    )
    assert event == {
        "event": "request_completed",
        "request_id": str(request_id),
        "job_id": 12,
        "duration_seconds": 1.5,
        "status": "succeeded",
        "error_code": "internal_error",
    }


def test_allowlisted_field_names_do_not_allow_arbitrary_content() -> None:
    event = json.loads(
        safe_event(
            "private event",
            request_id="private token",
            job_id=True,
            status="private name",
            error_code="SELECT secret FROM data",
            duration_seconds=float("nan"),
            size_bytes=-1,
            version="private model payload",
        )
    )
    assert event == {"event": "invalid_event"}


def test_rejected_objects_are_not_stringified() -> None:
    class Dangerous:
        def __str__(self) -> str:
            raise AssertionError("must not inspect sensitive values")

    assert json.loads(safe_event("request_failed", error_code=Dangerous())) == {
        "event": "request_failed",
    }
