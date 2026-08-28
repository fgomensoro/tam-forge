from __future__ import annotations

from datetime import timedelta

import pytest


def test_origin_requires_exact_configured_origin() -> None:
    from tamforge_backend.auth.dependencies import OriginRejected, verify_request_origin

    verify_request_origin(
        request_origin="https://app.example.test",
        allowed_origins=("https://app.example.test",),
    )

    for rejected in (
        None,
        "https://evil.example.test",
        "https://app.example.test.evil.test",
        "null",
    ):
        with pytest.raises(OriginRejected):
            verify_request_origin(
                request_origin=rejected,
                allowed_origins=("https://app.example.test",),
            )


@pytest.mark.anyio
async def test_csrf_uses_hash_bound_to_the_authenticated_session() -> None:
    from tamforge_backend.auth.crypto import OAuthStateManager
    from tamforge_backend.auth.schemas import GitHubIdentity
    from tamforge_backend.auth.service import AuthService, CsrfRejected
    from test_service import NOW, FakeAuthRepository, FakeGitHubGateway

    identity = GitHubIdentity(id=102269369, login="fgomensoro")
    repository = FakeAuthRepository()
    service = AuthService(
        owner_github_id=102269369,
        github=FakeGitHubGateway(identity),
        sessions=repository,
        state_manager=OAuthStateManager(
            signing_secret="state-signing-secret-with-enough-entropy",
            ttl=timedelta(minutes=5),
            now=lambda: NOW,
        ),
        session_ttl=timedelta(hours=12),
    )
    issued = await service.issue_session(identity)
    authenticated = await service.authenticate(issued.raw_session_token)

    service.verify_csrf(authenticated, issued.raw_csrf_token)
    with pytest.raises(CsrfRejected):
        service.verify_csrf(authenticated, "different-csrf-token")
