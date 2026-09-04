"""Authenticated SQL execution and immutable history routes."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..database import get_db_session
from .sql_contracts import SqlRunnerError
from .sql_runner import PostgresSqlRunner, SqlRunner
from .sql_service import (
    SqlExecutionBusy,
    SqlExecutionCommand,
    SqlExecutionConflict,
    SqlExecutionHistory,
    SqlExecutionInvalid,
    SqlExecutionNotFound,
    SqlExecutionResponse,
    SqlExecutionService,
    SqlExecutionUnavailable,
)
from .sql_settings import SqlExerciseCatalog


class _SqlExecutionRoute(APIRoute):
    """Keep validation responses on SQL routes private and non-cacheable."""

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError:
                return sql_execution_problem_response(
                    SqlExecutionInvalid("SQL execution request validation failed")
                )

        return handler


router = APIRouter(
    prefix="/api/v1/activities",
    tags=["sql-executions"],
    route_class=_SqlExecutionRoute,
)


@dataclass(frozen=True, slots=True)
class _SqlExecutionRuntime:
    catalog: SqlExerciseCatalog | None
    runner: SqlRunner | None


def setup_sql_execution_runtime(app: FastAPI) -> None:
    """Create one process capacity guard without connecting to an exercise DB."""
    try:
        catalog = SqlExerciseCatalog.from_env()
        runtime = _SqlExecutionRuntime(catalog=catalog, runner=PostgresSqlRunner(catalog))
    except (SqlRunnerError, OSError, ValueError, TypeError):
        runtime = _SqlExecutionRuntime(catalog=None, runner=None)
    app.state.sql_execution_runtime = runtime


def get_sql_execution_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SqlExecutionService:
    runtime = cast(_SqlExecutionRuntime, request.app.state.sql_execution_runtime)
    return SqlExecutionService(session, catalog=runtime.catalog, runner=runtime.runner)


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


@router.post(
    "/{activity_id}/sql-executions",
    response_model=SqlExecutionResponse,
)
async def execute_sql(
    activity_id: int,
    command: SqlExecutionCommand,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        ),
    ],
    service: Annotated[SqlExecutionService, Depends(get_sql_execution_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> SqlExecutionResponse:
    result = await service.execute(
        owner_id=owner.owner_id,
        activity_id=activity_id,
        command=command,
        idempotency_key=idempotency_key,
    )
    _prevent_storage(response)
    return result


@router.get(
    "/{activity_id}/sql-executions",
    response_model=SqlExecutionHistory,
)
async def get_sql_execution_history(
    activity_id: int,
    response: Response,
    service: Annotated[SqlExecutionService, Depends(get_sql_execution_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> SqlExecutionHistory:
    result = await service.history(owner_id=owner.owner_id, activity_id=activity_id)
    _prevent_storage(response)
    return result


def sql_execution_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, SqlExecutionNotFound):
        status, code, title = 404, "sql_activity_not_found", "SQL activity not found"
    elif isinstance(exc, SqlExecutionConflict):
        status, code, title = 409, "sql_execution_conflict", "SQL execution conflict"
    elif isinstance(exc, SqlExecutionInvalid):
        status, code, title = 422, "invalid_sql_execution", "Invalid SQL execution"
    elif isinstance(exc, SqlExecutionBusy):
        status, code, title = 429, "sql_execution_busy", "SQL executor busy"
    elif isinstance(exc, SqlExecutionUnavailable):
        status, code, title = 503, "sql_execution_unavailable", "SQL execution unavailable"
    else:
        status, code, title = 500, "sql_execution_error", "SQL execution failed"
    problem = ProblemResponse(
        type=f"https://tamforge.local/problems/{code}",
        title=title,
        status=status,
        detail=title + ".",
        code=code,
    )
    response = JSONResponse(
        problem.model_dump(),
        status_code=status,
        media_type="application/problem+json",
    )
    _prevent_storage(response)
    return response


async def sql_execution_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return sql_execution_problem_response(exc)


__all__ = [
    "get_sql_execution_service",
    "router",
    "setup_sql_execution_runtime",
    "sql_execution_exception_handler",
]
