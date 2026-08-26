"""FastAPI application entrypoint."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Create the TAM Forge API application."""
    app = FastAPI(title="TAM Forge API", version="0.1.0")

    @app.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "tam-forge-backend"}

    return app


app = create_app()
