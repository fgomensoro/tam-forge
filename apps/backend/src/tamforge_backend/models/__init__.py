"""Shared ORM model registry."""

from .base import Base, TimestampMixin, utc_now

__all__ = ["Base", "TimestampMixin", "utc_now"]
