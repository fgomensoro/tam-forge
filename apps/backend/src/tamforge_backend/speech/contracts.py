"""Safe transcript-repository errors. Never carry submitted content or DB diagnostics."""

from __future__ import annotations


class TranscriptError(ValueError):
    """Base transcript failure; message is safe for logs, never submitted content."""


class TranscriptNotFound(TranscriptError):
    def __init__(self) -> None:
        super().__init__("transcript not found")


class TranscriptConflict(TranscriptError):
    def __init__(self) -> None:
        super().__init__("transcript conflicts with an existing record")


class TranscriptTooLarge(TranscriptError):
    def __init__(self) -> None:
        super().__init__("transcript body exceeds the size limit")


__all__ = [
    "TranscriptConflict",
    "TranscriptError",
    "TranscriptNotFound",
    "TranscriptTooLarge",
]
