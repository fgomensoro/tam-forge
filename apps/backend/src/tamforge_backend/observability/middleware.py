"""ASGI timing without reading bodies or buffering uploads and SSE responses."""

import logging
import time
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .logging import safe_event
from .metrics import Metrics


class OperationalMiddleware:
    def __init__(self, app: ASGIApp, *, metrics: Metrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.monotonic()
        request_id = uuid4()
        status_code = 500
        failed = False

        async def observe_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, observe_send)
        except BaseException:
            failed = True
            raise
        finally:
            elapsed = max(0, time.monotonic() - started)
            status = "failed" if failed or status_code >= 400 else "succeeded"
            try:
                self.metrics.observe("http_requests_total", 1, status=status)
                self.metrics.observe("http_duration_seconds", elapsed, status=status)
            except ValueError:
                # A full registry must not fail uploads or mask application errors.
                pass
            logging.getLogger("tamforge.operations").info(
                safe_event(
                    "request_failed" if failed else "request_completed",
                    request_id=request_id,
                    status=status,
                    http_status=status_code,
                    duration_seconds=elapsed,
                    error_code="internal_error" if failed else "none",
                )
            )
