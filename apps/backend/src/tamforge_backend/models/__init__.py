"""Cycle-free shared ORM registry loaded explicitly by Alembic and tooling."""

from importlib import import_module

from .base import Base

_MODEL_MODULES = (
    "tamforge_backend.auth.models",
    "tamforge_backend.roadmaps.models",
    "tamforge_backend.learning.models",
    "tamforge_backend.evidence.models",
    "tamforge_backend.notifications.models",
    "tamforge_backend.today.models",
    "tamforge_backend.recordings.models",
    "tamforge_backend.workspaces.models",
)


def load_all_models() -> None:
    """Import every domain model module so it registers with shared metadata."""
    for module_name in _MODEL_MODULES:
        import_module(module_name)


__all__ = ["Base", "load_all_models"]
