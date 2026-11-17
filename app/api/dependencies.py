"""FastAPI dependencies: the services and the per-request context.

Handlers receive their service through `Depends` and call one method.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Request

from app.config import Settings
from app.services.duplicate_detection import DuplicateDetectionService
from app.services.email_validation import EmailValidationService
from app.services.guard import RequestContext
from app.services.registration import RegistrationService

if TYPE_CHECKING:
    from app.agents.registration_agent import RegistrationAssistant
    from app.composition import Components

FORWARDED_FOR = "x-forwarded-for"
UNKNOWN_CLIENT = "unknown"


def get_components(request: Request) -> Components:
    """The wired components the lifespan stored on the app."""
    components: Components = request.app.state.components
    return components


def get_settings(components: Components = Depends(get_components)) -> Settings:  # noqa: B008
    """The validated settings."""
    return components.settings


def get_registration_service(
    components: Components = Depends(get_components),  # noqa: B008
) -> RegistrationService:
    """The registration service."""
    return components.registration


def get_duplicate_service(
    components: Components = Depends(get_components),  # noqa: B008
) -> DuplicateDetectionService:
    """The duplicate detection service."""
    return components.duplicates


def get_email_service(
    components: Components = Depends(get_components),  # noqa: B008
) -> EmailValidationService:
    """The email validation service."""
    return components.email_validation


def get_assistant(
    components: Components = Depends(get_components),  # noqa: B008
) -> RegistrationAssistant | None:
    """The assistant, or None when it is switched off."""
    return components.assistant


def client_address(request: Request, *, trust_proxy_headers: bool) -> str:
    """Return the caller's address.

    The first `X-Forwarded-For` hop counts only when the deployment sits behind a proxy that
    sets it (`TRUST_PROXY_HEADERS=true`). Otherwise the socket peer is used.
    """
    if trust_proxy_headers:
        forwarded = request.headers.get(FORWARDED_FOR, "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else UNKNOWN_CLIENT


def get_request_context(
    request: Request,
    components: Components = Depends(get_components),  # noqa: B008
) -> RequestContext:
    """Build the context a service call needs."""
    return RequestContext(
        request_id=str(request.state.request_id),
        client_id=client_address(
            request, trust_proxy_headers=components.settings.trust_proxy_headers
        ),
        started_at=float(request.state.started_at),
    )
