"""RFC 9457 problem responses and the central exception handlers.

Every 4xx and 5xx body is `application/problem+json` with a stable `type` URI. Business code
raises typed errors. This module is the one place that turns them into responses, and it
never leaks a stack trace, query text, or internal host name.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.errors import (
    DomainError,
    DuplicateCustomer,
    EmailRejected,
    RateLimited,
    RegistrationBusy,
)
from app.models.problem_catalog import (
    INTERNAL_ERROR,
    PROBLEM_TYPE_PREFIX,
    VALIDATION_ERROR,
    ProblemSpec,
    spec_for,
)
from app.models.schemas import ProblemDetails, ProblemError, TypoWarning

log = structlog.get_logger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"
REQUEST_ID_HEADER = "X-Request-Id"
GENERIC_DETAIL = "The server could not complete the request."
LOC_PREFIXES = {"body": "", "header": "/headers", "query": "/query", "path": "/path"}


def _pointer(location: tuple[Any, ...]) -> str:
    """Turn a Pydantic error location into a JSON pointer."""
    if not location:
        return ""
    head, *rest = location
    prefix = LOC_PREFIXES.get(str(head))
    parts = rest if prefix is not None else location
    base = prefix or ""
    return base + "".join(f"/{str(part).replace('~', '~0').replace('/', '~1')}" for part in parts)


def request_id_of(request: Request) -> str:
    """The request id the middleware assigned, or an empty string outside a request."""
    return str(getattr(request.state, "request_id", ""))


def problem_response(
    request: Request,
    spec: ProblemSpec,
    detail: str,
    *,
    errors: list[ProblemError] | None = None,
    matched_on: list[Any] | None = None,
    suggestion: TypoWarning | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build a problem+json response."""
    body = ProblemDetails(
        type=spec.type_uri,
        title=spec.title,
        status=spec.status,
        detail=detail,
        instance=request.url.path,
        request_id=request_id_of(request),
        errors=errors or [],
        matched_on=matched_on,
        suggestion=suggestion,
    )
    response_headers = {REQUEST_ID_HEADER: body.request_id, **(headers or {})}
    return JSONResponse(
        status_code=spec.status,
        content=jsonable_encoder(body.model_dump(exclude_none=True)),
        media_type=PROBLEM_MEDIA_TYPE,
        headers=response_headers,
    )


async def handle_domain_error(request: Request, error: Exception) -> JSONResponse:
    """Map a typed domain error to its problem response."""
    assert isinstance(error, DomainError)
    spec = spec_for(error)
    errors = (
        [ProblemError(pointer=f"/{error.field}", code=spec.code, message=error.message)]
        if error.field
        else []
    )
    headers: dict[str, str] = {}
    if isinstance(error, RateLimited | RegistrationBusy):
        headers["Retry-After"] = str(error.retry_after)
    suggestion = None
    if isinstance(error, EmailRejected) and error.suggested_email:
        suggestion = TypoWarning(
            message=f"Did you mean {error.suggested_email}?",
            suggested_email=error.suggested_email,
            source="rules",
        )
    return problem_response(
        request,
        spec,
        error.message,
        errors=errors,
        matched_on=list(error.matched_on) if isinstance(error, DuplicateCustomer) else None,
        suggestion=suggestion,
        headers=headers,
    )


async def handle_validation_error(request: Request, error: Exception) -> JSONResponse:
    """Map a request-shape error to 422 `validation-error`, without echoing any input value."""
    assert isinstance(error, RequestValidationError)
    problems = [
        ProblemError(
            pointer=_pointer(tuple(item["loc"])),
            code=str(item["type"]),
            message=str(item["msg"]),
        )
        for item in error.errors()
    ]
    return problem_response(
        request,
        VALIDATION_ERROR,
        "One or more fields are missing or not valid.",
        errors=problems,
    )


async def handle_http_exception(request: Request, error: Exception) -> JSONResponse:
    """Map routing errors such as 404 and 405 to problem+json."""
    assert isinstance(error, StarletteHTTPException)
    spec = ProblemSpec(
        f"http-{error.status_code}", _http_title(error.status_code), error.status_code, "error"
    )
    return problem_response(request, spec, _http_title(error.status_code))


def _http_title(status: int) -> str:
    return {404: "Not found", 405: "Method not allowed"}.get(status, "Request failed")


async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
    """Answer any other exception with a generic 500 and log only its type."""
    log.error(
        "unhandled_error",
        error_type=type(error).__name__,
        request_id=request_id_of(request),
    )
    return problem_response(request, INTERNAL_ERROR, GENERIC_DETAIL)


def install_problem_handlers(app: FastAPI) -> None:
    """Register every handler on the app."""
    app.add_exception_handler(DomainError, handle_domain_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected_error)


def problem_docs(
    *specs: ProblemSpec,
    description: str,
    status: int | None = None,
    retry_after: bool = False,
) -> dict[int | str, dict[str, Any]]:
    """Build a `responses=` entry documenting one status with one example per problem type."""
    status_code = status or specs[0].status
    examples = {
        spec.code: {
            "summary": spec.title,
            "value": {
                "type": spec.type_uri,
                "title": spec.title,
                "status": spec.status,
                "detail": spec.title,
                "instance": "/api/v1/customers/register",
                "request_id": "7c2f8f3e9b6a4d0c8a1e5b7d9f2a4c6e",
                "errors": [],
            },
        }
        for spec in specs
    }
    headers: dict[str, Any] = {
        REQUEST_ID_HEADER: {"description": "Request id.", "schema": {"type": "string"}}
    }
    if retry_after:
        headers["Retry-After"] = {
            "description": "Seconds to wait before retrying.",
            "schema": {"type": "integer"},
        }
    return {
        status_code: {
            "model": ProblemDetails,
            "description": description,
            "headers": headers,
            "content": {"application/json": {"examples": examples}},
        }
    }


def merge_docs(*parts: dict[int | str, dict[str, Any]]) -> dict[int | str, dict[str, Any]]:
    """Combine `problem_docs` entries into one `responses=` map."""
    merged: dict[int | str, dict[str, Any]] = {}
    for part in parts:
        merged.update(part)
    return merged


def apply_problem_media_type(schema: dict[str, Any]) -> dict[str, Any]:
    """Serve every 4xx and 5xx body in the spec as `application/problem+json`."""
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for status, response in operation.get("responses", {}).items():
                if str(status).startswith(("4", "5")) and "content" in response:
                    content = response["content"]
                    if "application/json" in content:
                        content[PROBLEM_MEDIA_TYPE] = content.pop("application/json")
    return schema


__all__ = ["PROBLEM_TYPE_PREFIX", "install_problem_handlers", "merge_docs", "problem_docs"]
