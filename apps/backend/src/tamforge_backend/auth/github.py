"""Fixed-endpoint GitHub OAuth adapter; provider tokens never leave this module."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client  # type: ignore[import-untyped]

from .schemas import GitHubIdentity
from .service import ExternalIdentityProviderError

_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_USER_URL = "https://api.github.com/user"


class GitHubOAuthGateway:
    """Exchange a one-time code and return only immutable identity fields."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
    ) -> None:
        if not client_id.strip() or not client_secret.strip():
            raise ValueError("GitHub OAuth is not configured")
        self._client_id = client_id
        self._client_secret = client_secret

    def __repr__(self) -> str:
        return "GitHubOAuthGateway(client_id=<redacted>, client_secret=<redacted>)"

    def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "state": state,
            }
        )
        return f"{_AUTHORIZE_URL}?{query}"

    async def fetch_identity(self, *, code: str, redirect_uri: str) -> GitHubIdentity:
        try:
            async with AsyncOAuth2Client(
                client_id=self._client_id,
                client_secret=self._client_secret,
                redirect_uri=redirect_uri,
                token_endpoint_auth_method="client_secret_post",
                timeout=httpx.Timeout(10.0),
                follow_redirects=False,
                headers={"User-Agent": "tam-forge/0.1"},
            ) as client:
                token = await client.fetch_token(
                    _TOKEN_URL,
                    code=code,
                    grant_type="authorization_code",
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    },
                )
                access_token = token.get("access_token")
                if (
                    not isinstance(access_token, str)
                    or not access_token
                    or len(access_token) > 512
                ):
                    raise ExternalIdentityProviderError("GitHub authentication failed")
                user_response = await client.get(
                    _USER_URL,
                    headers={
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                user_response.raise_for_status()
                user_payload = user_response.json()
        except ExternalIdentityProviderError:
            raise
        except Exception:
            raise ExternalIdentityProviderError("GitHub authentication failed") from None

        if not isinstance(user_payload, dict):
            raise ExternalIdentityProviderError("GitHub authentication failed")
        github_id = user_payload.get("id")
        login = user_payload.get("login")
        if (
            isinstance(github_id, bool)
            or not isinstance(github_id, int)
            or not isinstance(login, str)
        ):
            raise ExternalIdentityProviderError("GitHub authentication failed")
        try:
            return GitHubIdentity(id=github_id, login=login)
        except ValueError:
            raise ExternalIdentityProviderError("GitHub authentication failed") from None
