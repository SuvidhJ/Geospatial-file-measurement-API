import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import files, health
from app.config import Settings
from app.db import create_session_factory
from app.errors import AppError, FileTooLargeError
from app.schemas.errors import ErrorBody, ErrorResponse

logger = logging.getLogger(__name__)

UPLOAD_PATH = "/api/files/"
# Allowance for multipart boundaries and part headers around the file bytes.
MULTIPART_OVERHEAD_BYTES = 16 * 1024

HTTP_ERROR_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}

DESCRIPTION = """
Upload a **zipped Shapefile** or a **KML** file and get per-feature measurements:
area for polygons, length for lines, computed in a projected CRS chosen per feature
and cross-checked against the geodesic value on the WGS84 ellipsoid.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="Geospatial File Measurement API",
        version="1.0.0",
        description=DESCRIPTION,
        openapi_tags=[
            {"name": "files", "description": "Upload files and read their measurements."},
            {"name": "health", "description": "Service health."},
        ],
    )
    app.state.settings = settings
    app.state.session_factory = create_session_factory(settings.resolved_database_url)

    _register_upload_size_guard(app, settings.max_upload_bytes)
    _register_exception_handlers(app)
    app.include_router(files.router)
    app.include_router(health.router)
    return app


def error_response(
    status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details or {}))
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


def _register_upload_size_guard(app: FastAPI, max_upload_bytes: int) -> None:
    # The route can only count bytes after Starlette has already received the whole body.
    # Checking Content-Length here rejects honest oversized uploads before the body is read.
    @app.middleware("http")
    async def reject_oversized_uploads(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method == "POST" and request.url.path == UPLOAD_PATH:
            content_length = request.headers.get("content-length", "")
            if (
                content_length.isdigit()
                and int(content_length) > max_upload_bytes + MULTIPART_OVERHEAD_BYTES
            ):
                exc = FileTooLargeError(
                    f"Upload exceeds the maximum size of {max_upload_bytes} bytes.",
                    details={"max_upload_bytes": max_upload_bytes},
                )
                return error_response(exc.status_code, exc.code, exc.message, exc.details)
        return await call_next(request)


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            422,
            "VALIDATION_ERROR",
            "The request is invalid.",
            {"errors": jsonable_encoder(exc.errors())},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = HTTP_ERROR_CODES.get(exc.status_code, "HTTP_ERROR")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return error_response(500, "INTERNAL_ERROR", "An unexpected error occurred.")
