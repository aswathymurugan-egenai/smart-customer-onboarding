"""Application factory: lifespan, middleware, routes, and the OpenAPI document."""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections.abc import AsyncIterator, MutableMapping
from contextlib import asynccontextmanager, suppress
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api import health, routes_agent, routes_customers
from app.api.problems import apply_problem_media_type, install_problem_handlers
from app.composition import ComponentOverrides, build_components
from app.config import Settings, load_settings
from app.logging import configure_logging

API_TITLE = "Smart Customer Onboarding API"
API_VERSION = "1.0.0"
API_CONTACT = {"name": "Customer onboarding team"}
API_DESCRIPTION = """\
Registers customers into BigQuery and runs a conversational signup assistant.

Deterministic checks decide every outcome: **201** created, **409** an existing customer owns
the email, phone, or tax ID, **422** the input is invalid. A model adds typo and
likely-duplicate warnings and never changes a status code.

Every error is `application/problem+json` (RFC 9457) with a stable `type` URI. Every response
echoes `X-Request-Id`.
"""
OPENAPI_TAGS = [
    {"name": "customers", "description": "Register customers and check emails and duplicates."},
    {"name": "assistant", "description": "The conversational signup assistant."},
]
REQUEST_ID_HEADER = "x-request-id"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
CORS_METHODS = ["GET", "POST", "OPTIONS"]
CORS_REQUEST_HEADERS = ["Content-Type", "Idempotency-Key", "X-Request-Id"]
CORS_EXPOSED_HEADERS = ["X-Request-Id", "Retry-After", "Idempotent-Replayed"]
MILLISECONDS = 1000

log = structlog.get_logger("app.access")


class RequestContextMiddleware:
    """Assigns a request id, echoes it, and writes one access-log line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            name.decode("latin-1"): value.decode("latin-1") for name, value in scope["headers"]
        }
        supplied = headers.get(REQUEST_ID_HEADER, "")
        request_id = supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else uuid.uuid4().hex
        started = time.monotonic()
        state: MutableMapping[str, Any] = scope.setdefault("state", {})
        state["request_id"] = request_id
        state["started_at"] = started
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                response_headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != REQUEST_ID_HEADER.encode()
                ]
                response_headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            route = scope.get("route")
            template = getattr(route, "path", None) or "unmatched"
            log.info(
                "request",
                route=f"{scope['method']} {template}",
                status=status,
                duration_ms=int((time.monotonic() - started) * MILLISECONDS),
            )
            structlog.contextvars.clear_contextvars()


def create_app(
    settings: Settings | None = None, overrides: ComponentOverrides | None = None
) -> FastAPI:
    """Build the FastAPI app. With no arguments it reads settings from the environment."""
    resolved = settings or load_settings()
    configure_logging(resolved.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        components = build_components(resolved, overrides)
        app.state.components = components
        app.state.draining = False
        janitor: asyncio.Task[None] | None = None
        if components.assistant is not None:
            janitor = asyncio.create_task(components.assistant.run_janitor())
        try:
            yield
        finally:
            app.state.draining = True
            if janitor is not None:
                janitor.cancel()
                with suppress(asyncio.CancelledError):
                    await janitor
            await components.close()

    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        description=API_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        contact=API_CONTACT,
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.draining = False
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_allow_origins,
        allow_credentials=False,
        allow_methods=CORS_METHODS,
        allow_headers=CORS_REQUEST_HEADERS,
        expose_headers=CORS_EXPOSED_HEADERS,
    )
    app.add_middleware(RequestContextMiddleware)
    install_problem_handlers(app)
    app.include_router(routes_customers.router)
    app.include_router(routes_agent.router)
    app.include_router(health.router)

    def build_openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(
                title=app.title,
                version=app.version,
                description=app.description,
                tags=OPENAPI_TAGS,
                contact=API_CONTACT,
                routes=app.routes,
            )
            app.openapi_schema = apply_problem_media_type(schema)
        return app.openapi_schema

    app.openapi = build_openapi  # type: ignore[method-assign]
    return app
