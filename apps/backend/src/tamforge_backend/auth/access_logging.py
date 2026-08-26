"""Access-log protection for browser OAuth query secrets."""

from __future__ import annotations

import logging

_AUTH_PATH = "/api/v1/auth"


class UvicornAuthQueryFilter(logging.Filter):
    """Remove every auth query string from Uvicorn's access-log target."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 3:
            return True
        request_target = args[2]
        if not isinstance(request_target, str):
            return True
        path, separator, _query = request_target.partition("?")
        if not separator or not (path == _AUTH_PATH or path.startswith(f"{_AUTH_PATH}/")):
            return True
        sanitized = list(args)
        sanitized[2] = path
        record.args = tuple(sanitized)
        return True
