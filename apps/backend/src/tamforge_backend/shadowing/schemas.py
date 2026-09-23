"""Wire shapes of shadowing clips and of the excerpt upload and download."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..learning.schemas import PresignedUploadResponse
from .models import MAX_CLIP_DURATION_MS, MAX_EXCERPT_BYTES

ShadowingFormat = Literal["solo", "dialogue"]
PreparationState = Literal["pending", "ready", "failed"]
ExcerptContentType = Literal["audio/mp4", "video/mp4", "video/quicktime"]
MAX_PHRASES = 200

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ShadowingPhrase(StrictModel):
    """One loopable stretch of the excerpt. `enabled` is how a dialogue is followed by hand:
    the learner switches off the phrases of the speaker they are not shadowing."""

    index: Annotated[int, Field(ge=0, lt=MAX_PHRASES)]
    start_ms: Annotated[int, Field(ge=0, le=MAX_CLIP_DURATION_MS)]
    end_ms: Annotated[int, Field(ge=1, le=MAX_CLIP_DURATION_MS)]
    text: Annotated[str, Field(min_length=1, max_length=1000)]
    enabled: bool


class ShadowingAnnotation(StrictModel):
    """Something in the clip worth stealing, written by clip preparation."""

    phrase_index: Annotated[int, Field(ge=0, lt=MAX_PHRASES)]
    kind: Literal["slang", "idiom", "phrase"]
    text: Annotated[str, Field(min_length=1, max_length=500)]
    note: Annotated[str, Field(min_length=1, max_length=500)]


class ShadowingClipCommand(StrictModel):
    """Everything the learner decides about a clip. Create and replace take the same body."""

    title: Annotated[str, Field(min_length=1, max_length=200)]
    format: ShadowingFormat
    skill_slug: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
    source_note: Annotated[str, Field(default="", max_length=500)]
    license_note: Annotated[str, Field(default="", max_length=500)]
    duration_ms: Annotated[int, Field(ge=1000, le=MAX_CLIP_DURATION_MS)]
    phrases: Annotated[tuple[ShadowingPhrase, ...], Field(default=(), max_length=MAX_PHRASES)]

    @model_validator(mode="after")
    def _phrases_fit_the_clip(self) -> ShadowingClipCommand:
        if not self.title.strip():
            raise ValueError("the title cannot be blank")
        previous_end = 0
        for position, phrase in enumerate(self.phrases):
            if phrase.index != position:
                raise ValueError("phrase indexes must count up from zero")
            if phrase.end_ms <= phrase.start_ms:
                raise ValueError("a phrase must end after it starts")
            if phrase.start_ms < previous_end:
                raise ValueError("phrases must be ordered and must not overlap")
            if phrase.end_ms > self.duration_ms:
                raise ValueError("every phrase must be inside the clip")
            previous_end = phrase.end_ms
        return self


class ShadowingExcerptResponse(StrictModel):
    sha256: str
    byte_length: int
    content_type: ExcerptContentType


class ShadowingClipResponse(StrictModel):
    id: int
    title: str
    format: ShadowingFormat
    skill_slug: str
    source_note: str
    license_note: str
    duration_ms: int
    phrases: tuple[ShadowingPhrase, ...]
    annotations: tuple[ShadowingAnnotation, ...]
    preparation_state: PreparationState
    excerpt: ShadowingExcerptResponse | None
    created_at: datetime
    updated_at: datetime


class ShadowingClipPage(StrictModel):
    items: tuple[ShadowingClipResponse, ...]


class ExcerptUploadCommand(StrictModel):
    """What the Mac is about to upload. The signed request accepts exactly this and no other."""

    sha256: Sha256
    byte_length: Annotated[int, Field(ge=1, le=MAX_EXCERPT_BYTES)]
    content_type: ExcerptContentType


class ExcerptUploadResponse(StrictModel):
    upload: PresignedUploadResponse


class ExcerptConfirmCommand(StrictModel):
    sha256: Sha256


class ExcerptDownloadResponse(StrictModel):
    url: str
    expires_seconds: int
    sha256: str
    byte_length: int
    content_type: ExcerptContentType


__all__ = [
    "MAX_CLIP_DURATION_MS",
    "MAX_EXCERPT_BYTES",
    "MAX_PHRASES",
    "ExcerptConfirmCommand",
    "ExcerptContentType",
    "ExcerptDownloadResponse",
    "ExcerptUploadCommand",
    "ExcerptUploadResponse",
    "PreparationState",
    "ShadowingAnnotation",
    "ShadowingClipCommand",
    "ShadowingClipPage",
    "ShadowingClipResponse",
    "ShadowingExcerptResponse",
    "ShadowingFormat",
    "ShadowingPhrase",
]
