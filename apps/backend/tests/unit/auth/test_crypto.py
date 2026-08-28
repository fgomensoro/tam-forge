from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


def test_hashes_secrets_to_fixed_sha256_without_retaining_plaintext() -> None:
    from tamforge_backend.auth.crypto import hash_secret

    raw = "sensitive-browser-token"
    digest = hash_secret(raw)

    assert len(digest) == 32
    assert raw.encode() not in digest
    assert digest == hash_secret(raw)


def test_issues_opaque_session_and_csrf_tokens_with_32_bytes_of_entropy() -> None:
    from tamforge_backend.auth.crypto import issue_browser_secret

    first = issue_browser_secret()
    second = issue_browser_secret()

    assert len(first) == 43
    assert len(second) == 43
    assert first != second
    assert all(character.isalnum() or character in "-_" for character in first)


def test_oauth_state_is_signed_bounded_and_exactly_matches_cookie() -> None:
    from tamforge_backend.auth.crypto import InvalidOAuthState, OAuthStateManager

    now = datetime(2026, 8, 26, 12, tzinfo=UTC)
    manager = OAuthStateManager(
        signing_secret="state-signing-secret-with-enough-entropy",
        ttl=timedelta(minutes=5),
        now=lambda: now,
    )
    state = manager.issue()

    manager.verify(state=state, state_cookie=state)

    with pytest.raises(InvalidOAuthState):
        manager.verify(state=state, state_cookie=f"{state}x")
    with pytest.raises(InvalidOAuthState):
        manager.verify(state=f"{state[:-1]}x", state_cookie=f"{state[:-1]}x")


def test_oauth_state_expires_and_cannot_be_reused_after_consumption() -> None:
    from tamforge_backend.auth.crypto import InvalidOAuthState, OAuthStateManager

    current = [datetime(2026, 8, 26, 12, tzinfo=UTC)]
    manager = OAuthStateManager(
        signing_secret="state-signing-secret-with-enough-entropy",
        ttl=timedelta(minutes=5),
        now=lambda: current[0],
    )
    state = manager.issue()
    manager.consume(state=state, state_cookie=state)

    with pytest.raises(InvalidOAuthState):
        manager.consume(state=state, state_cookie=state)

    second = manager.issue()
    current[0] += timedelta(minutes=6)
    with pytest.raises(InvalidOAuthState):
        manager.consume(state=second, state_cookie=second)


def test_oauth_replay_cache_evicts_oldest_state_at_capacity() -> None:
    from tamforge_backend.auth.crypto import InvalidOAuthState, OAuthStateManager

    now = datetime(2026, 8, 26, 12, tzinfo=UTC)
    manager = OAuthStateManager(
        signing_secret="state-signing-secret-with-enough-entropy",
        ttl=timedelta(minutes=5),
        now=lambda: now,
        max_consumed_states=1,
    )
    first = manager.issue()
    second = manager.issue()
    manager.consume(state=first, state_cookie=first)
    manager.consume(state=second, state_cookie=second)

    with pytest.raises(InvalidOAuthState):
        manager.consume(state=second, state_cookie=second)

    manager.consume(state=first, state_cookie=first)
