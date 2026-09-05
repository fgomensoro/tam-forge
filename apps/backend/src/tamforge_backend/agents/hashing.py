"""Provenance JSON v1: UTF-8, sorted keys, plain finite decimals, no whitespace."""

from __future__ import annotations

import json
from decimal import Decimal
from hashlib import sha256


def prompt_bytes(content: str) -> bytes:
    if not isinstance(content, str) or not content or "\x00" in content:
        raise ValueError("invalid provenance content")
    try:
        encoded = content.encode("utf-8")
    except UnicodeError:
        raise ValueError("invalid provenance content") from None
    if len(encoded) > 1048576:
        raise ValueError("invalid provenance content")
    return encoded


def _canonical(value: object, depth: int = 0) -> str:
    if depth > 64:
        raise ValueError("invalid provenance JSON")
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("invalid provenance JSON")
        value.encode("utf-8")
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
        if not number.is_finite() or abs(number.adjusted()) > 1000:
            raise ValueError("invalid provenance JSON")
        if number == 0:
            return "0"
        result = format(number, "f")
        return result.rstrip("0").rstrip(".") if "." in result else result
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("invalid provenance JSON")
        return (
            "{"
            + ",".join(
                _canonical(key, depth + 1) + ":" + _canonical(value[key], depth + 1)
                for key in sorted(value)
            )
            + "}"
        )
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical(item, depth + 1) for item in value) + "]"
    raise ValueError("invalid provenance JSON")


def canonical_bytes(value: object, *, limit: int = 262144) -> bytes:
    try:
        data = _canonical(value).encode("utf-8")
    except (UnicodeError, RecursionError, ArithmeticError):
        raise ValueError("invalid provenance JSON") from None
    if len(data) > limit:
        raise ValueError("invalid provenance JSON")
    return data


def digest(value: object, *, limit: int = 262144) -> str:
    return sha256(canonical_bytes(value, limit=limit)).hexdigest()
