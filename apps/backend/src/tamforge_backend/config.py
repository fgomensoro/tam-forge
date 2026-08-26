"""Minimal typed configuration for the initial backend shell."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings that later services can extend."""

    environment: str = "development"


def get_settings() -> Settings:
    """Read the non-secret environment selector."""
    return Settings(environment=os.getenv("TAM_FORGE_ENV") or "development")
