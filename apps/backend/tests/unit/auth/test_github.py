from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx


@pytest.mark.anyio
@respx.mock
async def test_adapter_exchanges_code_then_returns_only_numeric_id_and_login() -> None:
    from tamforge_backend.auth.github import GitHubOAuthGateway

    token_route = respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "short-lived-provider-token", "token_type": "bearer"},
        )
    )
    user_route = respx.get("https://api.github.com/user").mock(
        return_value=httpx.Response(200, json={"id": 102269369, "login": "renamed-owner"})
    )

    gateway = GitHubOAuthGateway(
        client_id="client-id",
        client_secret="client-secret",
    )
    identity = await gateway.fetch_identity(
        code="one-time-code",
        redirect_uri="https://app.example.test/api/v1/auth/callback",
    )

    assert (identity.id, identity.login) == (102269369, "renamed-owner")
    assert token_route.call_count == 1
    assert token_route.calls.last.request.headers["accept"] == "application/json"
    assert user_route.call_count == 1
    assert user_route.calls.last.request.headers["authorization"] == (
        "Bearer short-lived-provider-token"
    )
    assert "short-lived-provider-token" not in repr(identity)


def test_authorization_request_asks_for_no_repository_or_profile_scope() -> None:
    from tamforge_backend.auth.github import GitHubOAuthGateway

    gateway = GitHubOAuthGateway(client_id="client-id", client_secret="client-secret")
    url = gateway.authorization_url(
        state="signed-state",
        redirect_uri="https://app.example.test/api/v1/auth/callback",
    )

    query = parse_qs(urlsplit(url).query)
    assert query["client_id"] == ["client-id"]
    assert query["state"] == ["signed-state"]
    assert query["redirect_uri"] == ["https://app.example.test/api/v1/auth/callback"]
    assert "scope" not in query


@pytest.mark.anyio
@pytest.mark.parametrize("github_id", ["102269369", True, None])
@respx.mock
async def test_adapter_rejects_nonnumeric_github_ids(github_id: object) -> None:
    from tamforge_backend.auth.github import GitHubOAuthGateway
    from tamforge_backend.auth.service import ExternalIdentityProviderError

    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "provider-token", "token_type": "bearer"},
        )
    )
    respx.get("https://api.github.com/user").mock(
        return_value=httpx.Response(200, json={"id": github_id, "login": "fgomensoro"})
    )

    gateway = GitHubOAuthGateway(
        client_id="client-id",
        client_secret="client-secret",
    )

    with pytest.raises(ExternalIdentityProviderError, match="GitHub authentication failed"):
        await gateway.fetch_identity(
            code="one-time-code",
            redirect_uri="https://app.example.test/api/v1/auth/callback",
        )


def test_adapter_repr_redacts_oauth_credentials() -> None:
    from tamforge_backend.auth.github import GitHubOAuthGateway

    gateway = GitHubOAuthGateway(client_id="do-not-leak-id", client_secret="do-not-leak-secret")

    rendered = repr(gateway)
    assert "do-not-leak-id" not in rendered
    assert "do-not-leak-secret" not in rendered


@pytest.mark.anyio
@respx.mock
async def test_adapter_turns_malformed_provider_payload_into_generic_failure() -> None:
    from tamforge_backend.auth.github import GitHubOAuthGateway
    from tamforge_backend.auth.service import ExternalIdentityProviderError

    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "provider-token", "token_type": "bearer"},
        )
    )
    respx.get("https://api.github.com/user").mock(
        return_value=httpx.Response(200, json=["unexpected", "payload"])
    )

    gateway = GitHubOAuthGateway(
        client_id="client-id",
        client_secret="client-secret",
    )

    with pytest.raises(ExternalIdentityProviderError, match="GitHub authentication failed"):
        await gateway.fetch_identity(
            code="one-time-code",
            redirect_uri="https://app.example.test/api/v1/auth/callback",
        )


@pytest.mark.anyio
@respx.mock
async def test_adapter_rejects_oversized_token_before_profile_lookup() -> None:
    from tamforge_backend.auth.github import GitHubOAuthGateway
    from tamforge_backend.auth.service import ExternalIdentityProviderError

    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "x" * 513, "token_type": "bearer"},
        )
    )
    user_route = respx.get("https://api.github.com/user").mock(
        return_value=httpx.Response(
            200,
            json={"id": 102269369, "login": "fgomensoro"},
        )
    )
    gateway = GitHubOAuthGateway(client_id="client-id", client_secret="client-secret")

    with pytest.raises(ExternalIdentityProviderError, match="GitHub authentication failed"):
        await gateway.fetch_identity(
            code="one-time-code",
            redirect_uri="https://app.example.test/api/v1/auth/callback",
        )

    assert user_route.call_count == 0
