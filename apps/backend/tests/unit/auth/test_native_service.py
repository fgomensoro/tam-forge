from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)


class FakeGitHubGateway:
    def __init__(self, *, github_id: int = 102269369) -> None:
        from tamforge_backend.auth.schemas import GitHubIdentity

        self.identity = GitHubIdentity(id=github_id, login="fgomensoro")
        self.fetch_calls = 0

    def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        return f"https://github.example/authorize?state={state}&redirect_uri={redirect_uri}"

    async def fetch_identity(self, *, code: str, redirect_uri: str) -> object:
        del code, redirect_uri
        self.fetch_calls += 1
        return self.identity


class FakeNativeRepository:
    def __init__(self) -> None:
        self.flows: dict[bytes, tuple[str, bool]] = {}
        self.exchanges: dict[bytes, tuple[int, int, str, str, bool]] = {}
        self.access: dict[bytes, object] = {}
        self.refresh: dict[bytes, object] = {}
        self.consumed_refresh: dict[bytes, object] = {}
        self.persisted_values: list[dict[str, object]] = []
        self.next_session_id = 1

    async def create_native_oauth_flow(self, **values: object) -> None:
        state_hash = bytes(values["state_hash"])
        self.flows[state_hash] = (str(values["pkce_challenge"]), False)
        self.persisted_values.append(values)

    async def consume_native_oauth_flow(self, state_hash: bytes) -> str | None:
        flow = self.flows.get(state_hash)
        if flow is None or flow[1]:
            return None
        self.flows[state_hash] = (flow[0], True)
        return flow[0]

    async def create_native_exchange(self, **values: object) -> None:
        code_hash = bytes(values["code_hash"])
        self.exchanges[code_hash] = (
            7,
            int(values["github_user_id"]),
            str(values["github_login"]),
            str(values["pkce_challenge"]),
            False,
        )
        self.persisted_values.append(values)

    async def consume_native_exchange_and_create_session(self, **values: object) -> object | None:
        from tamforge_backend.auth.schemas import PersistedNativeSession

        code_hash = bytes(values["code_hash"])
        exchange = self.exchanges.get(code_hash)
        if exchange is None or exchange[4] or exchange[3] != values["pkce_challenge"]:
            return None
        self.exchanges[code_hash] = (*exchange[:4], True)
        session = PersistedNativeSession(
            session_id=self.next_session_id,
            owner_id=exchange[0],
            github_user_id=exchange[1],
            github_login=exchange[2],
            access_token_hash=bytes(values["access_token_hash"]),
            access_expires_at=NOW + timedelta(minutes=15),
            refresh_token_hash=bytes(values["refresh_token_hash"]),
            refresh_expires_at=NOW + timedelta(days=30),
            revoked_at=None,
        )
        self.next_session_id += 1
        self.access[session.access_token_hash] = session
        self.refresh[session.refresh_token_hash] = session
        self.persisted_values.append(values)
        return session

    async def rotate_native_refresh_token(self, **values: object) -> object | None:
        old_hash = bytes(values["refresh_token_hash"])
        session = self.refresh.pop(old_hash, None)
        if session is None:
            replayed = self.consumed_refresh.get(old_hash)
            if replayed is not None:
                revoked = replace(replayed, revoked_at=NOW)
                self.access = {
                    token_hash: revoked if value.session_id == replayed.session_id else value
                    for token_hash, value in self.access.items()
                }
                self.refresh = {
                    token_hash: revoked if value.session_id == replayed.session_id else value
                    for token_hash, value in self.refresh.items()
                }
            return None
        if session.revoked_at is not None:
            return None
        self.consumed_refresh[old_hash] = session
        updated = replace(
            session,
            access_token_hash=bytes(values["new_access_token_hash"]),
            access_expires_at=NOW + timedelta(minutes=15),
            refresh_token_hash=bytes(values["new_refresh_token_hash"]),
            refresh_expires_at=NOW + timedelta(days=30),
        )
        self.access.pop(session.access_token_hash, None)
        self.access[updated.access_token_hash] = updated
        self.refresh[updated.refresh_token_hash] = updated
        self.persisted_values.append(values)
        return updated

    async def find_active_native_session(self, access_token_hash: bytes) -> object | None:
        session = self.access.get(access_token_hash)
        if session is None or session.revoked_at is not None:
            return None
        return session

    async def revoke_native_session(self, refresh_token_hash: bytes) -> bool:
        session = self.refresh.get(refresh_token_hash) or self.consumed_refresh.get(
            refresh_token_hash
        )
        if session is None:
            return False
        revoked = replace(session, revoked_at=NOW)
        self.access = {
            token_hash: revoked if value.session_id == session.session_id else value
            for token_hash, value in self.access.items()
        }
        self.refresh = {
            token_hash: revoked if value.session_id == session.session_id else value
            for token_hash, value in self.refresh.items()
        }
        return True


def make_service(
    *, github_id: int = 102269369
) -> tuple[object, FakeNativeRepository, FakeGitHubGateway]:
    from tamforge_backend.auth.crypto import OAuthStateManager
    from tamforge_backend.auth.service import AuthService

    repository = FakeNativeRepository()
    github = FakeGitHubGateway(github_id=github_id)
    service = AuthService(
        owner_github_id=102269369,
        github=github,
        sessions=repository,
        native_sessions=repository,
        state_manager=OAuthStateManager(
            signing_secret="state-signing-secret-with-enough-entropy",
            ttl=timedelta(minutes=5),
            now=lambda: NOW,
        ),
        session_ttl=timedelta(hours=12),
        native_access_ttl=timedelta(minutes=15),
        native_refresh_ttl=timedelta(days=30),
        native_exchange_ttl=timedelta(minutes=2),
    )
    return service, repository, github


@pytest.mark.anyio
async def test_native_start_persists_only_state_hash_and_pkce_challenge() -> None:
    service, repository, _ = make_service()
    verifier = "v" * 43
    challenge = service.pkce_challenge(verifier)

    started = await service.start_native_login(
        pkce_challenge=challenge,
        redirect_uri="https://app.example.test/api/v1/auth/callback",
    )

    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    assert len(state) == 43
    assert state.encode() not in b"".join(repository.flows)
    assert repository.flows
    assert next(iter(repository.flows.values()))[0] == challenge


@pytest.mark.anyio
async def test_native_state_replay_stops_before_second_provider_exchange() -> None:
    service, _, github = make_service()
    verifier = "v" * 43
    started = await service.start_native_login(
        pkce_challenge=service.pkce_challenge(verifier),
        redirect_uri="https://app.example.test/api/v1/auth/callback",
    )
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]

    await service.complete_native_login(
        code="provider-code",
        state=state,
        redirect_uri="https://app.example.test/api/v1/auth/callback",
    )
    with pytest.raises(Exception, match="state"):
        await service.complete_native_login(
            code="provider-code",
            state=state,
            redirect_uri="https://app.example.test/api/v1/auth/callback",
        )

    assert github.fetch_calls == 1


@pytest.mark.anyio
async def test_native_exchange_binds_pkce_and_is_single_use() -> None:
    from tamforge_backend.auth.service import Unauthenticated

    service, repository, _ = make_service()
    verifier = "v" * 43
    started = await service.start_native_login(
        pkce_challenge=service.pkce_challenge(verifier),
        redirect_uri="https://app.example.test/api/v1/auth/callback",
    )
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    exchange_code = await service.complete_native_login(
        code="provider-code",
        state=state,
        redirect_uri="https://app.example.test/api/v1/auth/callback",
    )

    with pytest.raises(Unauthenticated):
        await service.exchange_native_code(code=exchange_code, code_verifier="x" * 43)

    issued = await service.exchange_native_code(code=exchange_code, code_verifier=verifier)
    with pytest.raises(Unauthenticated):
        await service.exchange_native_code(code=exchange_code, code_verifier=verifier)

    assert issued.access_token.encode() not in b"".join(repository.access)
    assert issued.refresh_token.encode() not in b"".join(repository.refresh)


@pytest.mark.anyio
async def test_native_login_keeps_immutable_owner_check() -> None:
    from tamforge_backend.auth.service import ForbiddenIdentity

    service, repository, _ = make_service(github_id=999)
    verifier = "v" * 43
    started = await service.start_native_login(
        pkce_challenge=service.pkce_challenge(verifier),
        redirect_uri="https://app.example.test/api/v1/auth/callback",
    )
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]

    with pytest.raises(ForbiddenIdentity):
        await service.complete_native_login(
            code="provider-code",
            state=state,
            redirect_uri="https://app.example.test/api/v1/auth/callback",
        )

    assert repository.exchanges == {}


@pytest.mark.anyio
async def test_refresh_rotates_once_and_old_token_replay_fails_closed() -> None:
    from tamforge_backend.auth.service import Unauthenticated

    service, _, _ = make_service()
    verifier = "v" * 43
    started = await service.start_native_login(
        pkce_challenge=service.pkce_challenge(verifier),
        redirect_uri="https://app.example.test/api/v1/auth/callback",
    )
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    code = await service.complete_native_login(
        code="provider-code",
        state=state,
        redirect_uri="https://app.example.test/api/v1/auth/callback",
    )
    first = await service.exchange_native_code(code=code, code_verifier=verifier)

    second = await service.refresh_native_session(first.refresh_token)
    with pytest.raises(Unauthenticated):
        await service.refresh_native_session(first.refresh_token)
    with pytest.raises(Unauthenticated):
        await service.authenticate_bearer(first.access_token)
    with pytest.raises(Unauthenticated):
        await service.authenticate_bearer(second.access_token)


@pytest.mark.anyio
async def test_native_revoke_invalidates_access_and_is_idempotent() -> None:
    from tamforge_backend.auth.service import Unauthenticated

    service, _, _ = make_service()
    verifier = "v" * 43
    started = await service.start_native_login(
        pkce_challenge=service.pkce_challenge(verifier),
        redirect_uri="https://app.example.test/api/v1/auth/callback",
    )
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    code = await service.complete_native_login(
        code="provider-code",
        state=state,
        redirect_uri="https://app.example.test/api/v1/auth/callback",
    )
    issued = await service.exchange_native_code(code=code, code_verifier=verifier)

    await service.revoke_native_session(issued.refresh_token)
    await service.revoke_native_session(issued.refresh_token)

    with pytest.raises(Unauthenticated):
        await service.authenticate_bearer(issued.access_token)


@pytest.mark.anyio
async def test_native_revoke_does_not_reveal_unknown_refresh_tokens() -> None:
    service, _, _ = make_service()

    await service.revoke_native_session("x" * 43)
