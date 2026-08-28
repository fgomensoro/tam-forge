"""Small, secret-aware authentication boundary types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True, slots=True)
class GitHubIdentity:
    """The only GitHub profile fields allowed beyond the HTTP adapter."""

    id: int
    login: str

    def __post_init__(self) -> None:
        if self.id <= 0 or not self.login.strip() or len(self.login) > 255:
            raise ValueError("GitHub identity is invalid")


@dataclass(frozen=True, slots=True)
class PersistedSession:
    """A session projection containing hashes, never browser secrets."""

    session_id: int
    owner_id: int
    github_user_id: int
    github_login: str
    token_hash: bytes
    csrf_hash: bytes
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """Ephemeral browser secrets paired with their hash-only persisted row."""

    raw_session_token: str
    raw_csrf_token: str
    persisted_session: PersistedSession


@dataclass(frozen=True, slots=True)
class OAuthStart:
    """One short-lived state and the fixed-provider authorization URL."""

    state: str
    authorization_url: str


@dataclass(frozen=True, slots=True)
class AuthenticatedOwner:
    """Internal request identity derived exclusively from a valid session."""

    owner_id: int
    github_user_id: int
    github_login: str
    session_id: int
    csrf_hash: bytes
    expires_at: datetime


class SessionResponse(BaseModel):
    """The authenticated browser's minimal owner display and CSRF view."""

    model_config = ConfigDict(extra="forbid")

    github_login: str = Field(min_length=1, max_length=255)
    csrf_token: str = Field(min_length=43, max_length=43)


class ProblemResponse(BaseModel):
    """RFC 9457-style public error without provider or secret detail."""

    model_config = ConfigDict(extra="forbid")

    type: str
    title: str
    status: int
    detail: str
    code: str
