"""HTTP API wiring reserved for future TAM Forge routes."""

from fastapi import FastAPI


def register_routes(app: FastAPI) -> None:
    """Register application routes as the API grows."""
    del app
