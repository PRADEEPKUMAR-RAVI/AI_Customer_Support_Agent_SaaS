"""RFC 7807 error envelope + exception handlers (the single error shape for every endpoint)."""

from __future__ import annotations

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.common import Problem

PROBLEM_MEDIA_TYPE = "application/problem+json"


class AppError(Exception):
    """Domain error carrying an HTTP status + machine-readable code for the RFC7807 body."""

    def __init__(self, *, status_code: int, title: str, detail: str | None = None,
                 code: str | None = None) -> None:
        super().__init__(detail or title)
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.code = code


def _problem_response(problem: Problem) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(exclude_none=True),
        media_type=PROBLEM_MEDIA_TYPE,
    )


def register_error_handlers(app) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return _problem_response(
            Problem(title=exc.title, status=exc.status_code, detail=exc.detail, code=exc.code)
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        return _problem_response(
            Problem(title=str(exc.detail), status=exc.status_code, detail=None)
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        return _problem_response(
            Problem(
                title="Validation error",
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc.errors()),
                code="validation_error",
            )
        )
