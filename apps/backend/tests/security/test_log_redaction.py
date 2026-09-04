import io
import json
import logging

import pytest
from fastapi.testclient import TestClient
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app
from tamforge_backend.observability.logging import AccessLogFilter, ServerErrorFilter, safe_event

SECRETS = (
    "oauth-code-secret",
    "sk-ant-api03-secret",
    "cookie-secret",
    "My private transcript",
    "Interview with Jane",
    "https://private.invalid/?X-Amz-Signature=secret",
    '{"prompt":"private"}',
    "SELECT private FROM answers",
    "owners/1/private.wav",
)


@pytest.mark.parametrize("secret", SECRETS)
def test_secret_and_content_injection_cannot_escape_any_allowed_field(secret: str) -> None:
    for key in (
        "request_id",
        "job_id",
        "evidence_id",
        "status",
        "error_code",
        "version",
        "duration_seconds",
        "size_bytes",
        "http_status",
        "exception",
        "prompt",
    ):
        assert secret not in safe_event("request_failed", **{key: secret})
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        "%s",
        (
            secret,
            secret,
            secret,
            secret,
            secret,
        ),
        None,
    )
    AccessLogFilter().filter(record)
    assert secret not in record.getMessage()
    try:
        raise RuntimeError(secret)
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            "uvicorn.error", logging.ERROR, "", 0, "ASGI error", (), sys.exc_info()
        )
    record.exc_text = secret
    record.stack_info = secret
    ServerErrorFilter().filter(record)
    assert secret not in logging.Formatter().format(record)
    without_traceback = logging.LogRecord(
        "uvicorn.error",
        logging.ERROR,
        "",
        0,
        "connection error: %s",
        (secret,),
        None,
    )
    ServerErrorFilter().filter(without_traceback)
    assert secret not in logging.Formatter().format(without_traceback)


def test_requests_emit_only_server_generated_correlation_and_safe_outcomes() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    @app.get("/private/{name}")
    def failure(name: str) -> None:
        raise RuntimeError("private transcript and token")

    logger = logging.getLogger("tamforge.operations")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    original_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/private/Jane?token=secret",
                headers={
                    "Authorization": "Bearer private-token",
                    "X-Request-ID": "user-secret",
                },
            )
            assert response.status_code == 500
            assert client.get("/healthz").status_code == 200
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert len(events) == 2
    assert events[0]["event"] == "request_failed"
    assert events[0]["error_code"] == "internal_error"
    assert events[1]["event"] == "request_completed"
    for secret in ("private", "Jane", "secret", "Bearer", "healthz"):
        assert secret not in stream.getvalue()


def test_server_filters_are_installed_and_removed_with_application_lifecycle() -> None:
    app = create_app(Settings(environment="test", _env_file=None))
    access = logging.getLogger("uvicorn.access")
    errors = logging.getLogger("uvicorn.error")
    before_access, before_errors = list(access.filters), list(errors.filters)
    with TestClient(app):
        assert any(isinstance(item, AccessLogFilter) for item in access.filters)
        assert any(isinstance(item, ServerErrorFilter) for item in errors.filters)
    assert access.filters == before_access
    assert errors.filters == before_errors
