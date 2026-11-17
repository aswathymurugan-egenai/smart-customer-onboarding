"""Liveness and readiness probes. Neither appears in the published spec."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import get_components

router = APIRouter(prefix="/healthz", include_in_schema=False)


@router.get("/live")
async def live() -> dict[str, str]:
    """The process is alive. This check touches no dependency."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """The service can take traffic: not draining, and the store answers.

    The store check is cached so a probe storm does not become a query storm.
    """
    state = request.app.state
    if getattr(state, "draining", False):
        return JSONResponse({"status": "draining"}, status_code=503)
    components = get_components(request)
    ttl = components.settings.readiness_cache_seconds
    now = time.monotonic()
    cached = getattr(state, "ready_checked_at", None)
    if cached is not None and now - cached < ttl:
        return JSONResponse({"status": "ok"})
    try:
        await components.repository.check_ready()
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    state.ready_checked_at = now
    return JSONResponse({"status": "ok"})
