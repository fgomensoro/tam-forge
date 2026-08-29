from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest


class FakeGitHubGateway:
    def __init__(self, identity: object) -> None:
        self.identity = identity
        self.fetch_calls = 0

    def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        return f"https://github.example/authorize?state={state}&redirect_uri={redirect_uri}"

    async def fetch_identity(self, *, code: str, redirect_uri: str) -> object:
        del code, redirect_uri
        self.fetch_calls += 1
        return self.identity


class FakeAuthRepository:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.sessions: dict[bytes, object] = {}
        self.revocations = 0
        self.liveness_checks: list[int] = []

    async def create_owner_session(self, **values: object) -> object:
        from tamforge_backend.auth.schemas import PersistedSession

        self.created.append(values)
        session = PersistedSession(
            session_id=11,
            owner_id=7,
            github_user_id=int(values["github_user_id"]),
            github_login=str(values["github_login"]),
            token_hash=bytes(values["token_hash"]),
            csrf_hash=bytes(values["csrf_hash"]),
            created_at=NOW,
            expires_at=NOW + timedelta(hours=12),
            revoked_at=None,
        )
        self.sessions[session.token_hash] = session
        return session

    async def find_active_session(self, token_hash: bytes) -> object | None:
        session = self.sessions.get(token_hash)
        if session is None or session.revoked_at is not None or session.expires_at <= NOW:
            return None
        return session

    async def find_session_for_logout(self, token_hash: bytes) -> object | None:
        return self.sessions.get(token_hash)

    async def is_session_active(self, session_id: int) -> bool:
        self.liveness_checks.append(session_id)
        return any(
            session.session_id == session_id
            and session.revoked_at is None
            and session.expires_at > NOW
            for session in self.sessions.values()
        )

    async def revoke_session(self, token_hash: bytes) -> None:
        session = self.sessions.get(token_hash)
        if session is not None and session.revoked_at is None:
            self.sessions[token_hash] = replace(session, revoked_at=NOW)
            self.revocations += 1


NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)


def make_service(
    *, github_id: int = 102269369, login: str = "fgomensoro"
) -> tuple[object, FakeAuthRepository]:
    from tamforge_backend.auth.crypto import OAuthStateManager
    from tamforge_backend.auth.schemas import GitHubIdentity
    from tamforge_backend.auth.service import AuthService

    repository = FakeAuthRepository()
    gateway = FakeGitHubGateway(GitHubIdentity(id=github_id, login=login))
    service = AuthService(
        owner_github_id=102269369,
        github=gateway,
        sessions=repository,
        state_manager=OAuthStateManager(
            signing_secret="state-signing-secret-with-enough-entropy",
            ttl=timedelta(minutes=5),
            now=lambda: NOW,
        ),
        session_ttl=timedelta(hours=12),
    )
    return service, repository


@pytest.mark.anyio
async def test_rejects_valid_github_login_with_wrong_immutable_numeric_id() -> None:
    from tamforge_backend.auth.service import ForbiddenIdentity

    service, repository = make_service(github_id=999, login="fgomensoro")
    start = service.start_login(redirect_uri="https://app.example.test/api/v1/auth/callback")

    with pytest.raises(ForbiddenIdentity):
        await service.complete_login(
            code="one-time-code",
            state=start.state,
            state_cookie=start.state,
            redirect_uri="https://app.example.test/api/v1/auth/callback",
        )

    assert repository.created == []


@pytest.mark.anyio
async def test_accepts_renamed_or_lookalike_login_only_when_numeric_id_matches() -> None:
    service, repository = make_service(login="renamed-owner")
    start = service.start_login(redirect_uri="https://app.example.test/api/v1/auth/callback")

    result = await service.complete_login(
        code="one-time-code",
        state=start.state,
        state_cookie=start.state,
        redirect_uri="https://app.example.test/api/v1/auth/callback",
    )

    assert result.persisted_session.github_user_id == 102269369
    assert result.persisted_session.github_login == "renamed-owner"
    assert len(repository.created) == 1


@pytest.mark.anyio
async def test_session_issuance_persists_only_sha256_hashes() -> None:
    from tamforge_backend.auth.schemas import GitHubIdentity

    service, repository = make_service()
    result = await service.issue_session(GitHubIdentity(id=102269369, login="fgomensoro"))
    persisted = result.persisted_session

    assert result.raw_session_token.encode() not in persisted.token_hash
    assert result.raw_csrf_token.encode() not in persisted.csrf_hash
    assert len(persisted.token_hash) == 32
    assert len(persisted.csrf_hash) == 32
    assert "access_token" not in repository.created[0]


@pytest.mark.anyio
async def test_rejects_expired_and_revoked_sessions() -> None:
    from tamforge_backend.auth.service import Unauthenticated

    service, repository = make_service()
    issued = await service.issue_session_for_identity(102269369, "fgomensoro")
    stored = issued.persisted_session

    repository.sessions[stored.token_hash] = replace(stored, expires_at=NOW - timedelta(seconds=1))
    with pytest.raises(Unauthenticated):
        await service.authenticate(issued.raw_session_token)

    repository.sessions[stored.token_hash] = replace(
        stored,
        expires_at=NOW + timedelta(hours=1),
        revoked_at=NOW,
    )
    with pytest.raises(Unauthenticated):
        await service.authenticate(issued.raw_session_token)


@pytest.mark.anyio
async def test_browser_session_liveness_fails_closed_for_expiry_and_revocation() -> None:
    service, repository = make_service()
    issued = await service.issue_session_for_identity(102269369, "fgomensoro")
    owner = await service.authenticate(issued.raw_session_token)
    owner = replace(owner, expires_at=datetime.now(UTC) + timedelta(hours=1))

    assert await service.is_session_active(owner)

    stored = issued.persisted_session
    repository.sessions[stored.token_hash] = replace(stored, revoked_at=NOW)
    assert not await service.is_session_active(owner)
    assert not await service.is_session_active(
        replace(owner, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    assert repository.liveness_checks == [stored.session_id, stored.session_id]


@pytest.mark.anyio
async def test_logout_revocation_is_idempotent() -> None:
    service, repository = make_service()
    issued = await service.issue_session_for_identity(102269369, "fgomensoro")

    await service.logout(issued.raw_session_token, issued.raw_csrf_token)
    await service.logout(issued.raw_session_token, issued.raw_csrf_token)

    assert repository.revocations == 1


@pytest.mark.anyio
async def test_state_mismatch_stops_before_github_or_repository() -> None:
    from tamforge_backend.auth.crypto import InvalidOAuthState

    service, repository = make_service()
    start = service.start_login(redirect_uri="https://app.example.test/api/v1/auth/callback")

    with pytest.raises(InvalidOAuthState):
        await service.complete_login(
            code="one-time-code",
            state=start.state,
            state_cookie="wrong-state",
            redirect_uri="https://app.example.test/api/v1/auth/callback",
        )

    assert service.github.fetch_calls == 0
    assert repository.created == []
