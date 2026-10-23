"""Every non-2xx response uses the contract error shape:
{"error": {"code", "message", "details", "request_id"}}
"""
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("labellock")

# Framework-raised statuses -> contract codes. 405 has no contract code; a wrong method is
# reported as NOT_FOUND (no such operation).
STATUS_CODES = {
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    501: "NOT_IMPLEMENTED",
    502: "UPSTREAM_FAILED",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def error_response(request: Request, status: int, code: str, message: str, details=None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or new_request_id()
    body = {"error": {"code": code, "message": message, "details": details, "request_id": request_id}}
    return JSONResponse(body, status_code=status, headers={"X-Request-ID": request_id})


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = new_request_id()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return error_response(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        fields = [{"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()]
        return error_response(request, 422, "VALIDATION_ERROR", "Request is invalid", {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        code = STATUS_CODES.get(exc.status_code, "INTERNAL_ERROR" if exc.status_code >= 500 else "VALIDATION_ERROR")
        return error_response(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error")
        return error_response(request, 500, "INTERNAL_ERROR", "Internal server error")
