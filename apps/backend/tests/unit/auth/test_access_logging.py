from __future__ import annotations

import io
import logging

from fastapi.testclient import TestClient
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app


def _emit_access_log(logger: logging.Logger, request_target: str) -> None:
    logger.info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:12345",
        "GET",
        request_target,
        "1.1",
        400,
    )


def test_lifespan_strips_auth_query_secrets_from_uvicorn_access_logs() -> None:
    logger = logging.getLogger("uvicorn.access")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    original_handlers = list(logger.handlers)
    original_filters = list(logger.filters)
    original_level = logger.level
    original_propagate = logger.propagate
    target = "/api/v1/auth/callback?code=oauth-code-marker&state=oauth-state-marker"
    settings = Settings(environment="test", _env_file=None)

    try:
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False
        with TestClient(create_app(settings)):
            _emit_access_log(logger, target)
        filtered_output = stream.getvalue()
        stream.seek(0)
        stream.truncate(0)
        _emit_access_log(logger, target)
        unfiltered_output = stream.getvalue()
    finally:
        logger.handlers = original_handlers
        logger.filters = original_filters
        logger.setLevel(original_level)
        logger.propagate = original_propagate

    assert filtered_output == ""
    assert "/api/v1/auth/callback" not in filtered_output
    assert "oauth-code-marker" not in filtered_output
    assert "oauth-state-marker" not in filtered_output
    assert "?" not in filtered_output
    assert "oauth-code-marker" in unfiltered_output
    assert "oauth-state-marker" in unfiltered_output
