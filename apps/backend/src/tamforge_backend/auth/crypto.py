"""Authentication secret generation, hashing, and bounded OAuth state."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

_STATE_VERSION = "v1"
_MAX_CLOCK_SKEW_SECONDS = 30


class InvalidOAuthState(ValueError):
    """Raised for any malformed, mismatched, expired, or replayed state."""


def issue_browser_secret() -> str:
    """Return exactly 32 random bytes encoded as an opaque URL-safe token."""
    return secrets.token_urlsafe(32)


def hash_secret(raw_secret: str) -> bytes:
    """Hash a bounded opaque browser secret for persistence or comparison."""
    if not isinstance(raw_secret, str) or not 1 <= len(raw_secret) <= 512:
        raise ValueError("browser secret is invalid")
    return hashlib.sha256(raw_secret.encode("utf-8")).digest()


class OAuthStateManager:
    """Issue signed expiring states and reject in-process callback replay.

    Only state hashes are retained, and only until the state's short expiry.
    Browser cookie deletion is the first replay barrier; this bounded consumed
    set closes the same-process retry window before GitHub code exchange.
    """

    def __init__(
        self,
        *,
        signing_secret: str,
        ttl: timedelta,
        now: Callable[[], datetime] | None = None,
        max_consumed_states: int = 4096,
    ) -> None:
        if len(signing_secret.encode("utf-8")) < 32:
            raise ValueError("OAuth state signing secret is invalid")
        if not timedelta(minutes=1) <= ttl <= timedelta(minutes=10):
            raise ValueError("OAuth state lifetime is invalid")
        if not 1 <= max_consumed_states <= 4096:
            raise ValueError("OAuth replay cache bound is invalid")
        self._key = signing_secret.encode("utf-8")
        self._ttl_seconds = int(ttl.total_seconds())
        self._now = now or (lambda: datetime.now(UTC))
        self._max_consumed_states = max_consumed_states
        self._consumed_until: dict[bytes, int] = {}

    def issue(self) -> str:
        issued_at = int(self._utc_now().timestamp())
        payload = f"{_STATE_VERSION}.{issued_at}.{issue_browser_secret()}"
        signature = hmac.new(self._key, payload.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def verify(self, *, state: str | None, state_cookie: str | None) -> None:
        if (
            state is None
            or state_cookie is None
            or not 1 <= len(state) <= 256
            or not 1 <= len(state_cookie) <= 256
            or not hmac.compare_digest(state, state_cookie)
        ):
            raise InvalidOAuthState("OAuth state is invalid")
        parts = state.split(".")
        if len(parts) != 4 or parts[0] != _STATE_VERSION:
            raise InvalidOAuthState("OAuth state is invalid")
        version, raw_issued_at, nonce, supplied_signature = parts
        if len(nonce) != 43 or any(not (char.isalnum() or char in "-_") for char in nonce):
            raise InvalidOAuthState("OAuth state is invalid")
        try:
            issued_at = int(raw_issued_at)
        except ValueError:
            raise InvalidOAuthState("OAuth state is invalid") from None
        payload = f"{version}.{raw_issued_at}.{nonce}"
        expected_signature = hmac.new(
            self._key,
            payload.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise InvalidOAuthState("OAuth state is invalid")
        now = int(self._utc_now().timestamp())
        if issued_at > now + _MAX_CLOCK_SKEW_SECONDS or now - issued_at > self._ttl_seconds:
            raise InvalidOAuthState("OAuth state is invalid")

    def consume(self, *, state: str | None, state_cookie: str | None) -> None:
        self.verify(state=state, state_cookie=state_cookie)
        assert state is not None
        now = int(self._utc_now().timestamp())
        self._remove_expired(now)
        state_hash = hash_secret(state)
        if state_hash in self._consumed_until:
            raise InvalidOAuthState("OAuth state is invalid")
        if len(self._consumed_until) >= self._max_consumed_states:
            raise InvalidOAuthState("OAuth state is invalid")
        self._consumed_until[state_hash] = now + self._ttl_seconds

    def _remove_expired(self, now: int) -> None:
        expired = [key for key, deadline in self._consumed_until.items() if deadline < now]
        for key in expired:
            del self._consumed_until[key]

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("OAuth state clock must be timezone-aware")
        return value.astimezone(UTC)
