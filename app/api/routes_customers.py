"""Customer routes: register, validate, and check for duplicates."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response

from app.api.dependencies import (
    get_duplicate_service,
    get_email_service,
    get_registration_service,
    get_request_context,
)
from app.api.problems import merge_docs, problem_docs
from app.domain import errors
from app.models.problem_catalog import spec_for
from app.models.schemas import (
    CustomerInput,
    DuplicateCheckResult,
    EmailValidationRequest,
    EmailValidationResult,
    RegistrationCreated,
)
from app.services.duplicate_detection import DuplicateDetectionService
from app.services.email_validation import EmailValidationService
from app.services.guard import RequestContext
from app.services.registration import RegistrationService

router = APIRouter(prefix="/api/v1/customers", tags=["customers"])

_INTERNAL = problem_docs(spec_for(RuntimeError()), description="Unexpected server error.")
_RATE_LIMITED = problem_docs(
    spec_for(errors.RateLimited(1)),
    description="The client exceeded its allowance for this operation.",
    retry_after=True,
)
_BOT_CHECK = problem_docs(spec_for(errors.BotCheckFailed("")), description="The bot check failed.")

REGISTER_DOCS = merge_docs(
    problem_docs(
        spec_for(errors.DuplicateCustomer(["email"])),
        description="An existing customer already owns the email, phone, or tax ID.",
    ),
    problem_docs(
        spec_for(errors.EmailInvalid("")),
        spec_for(errors.EmailDisposable("")),
        spec_for(errors.EmailUndeliverable("")),
        spec_for(errors.PhoneInvalid("")),
        spec_for(errors.TaxIdInvalid("")),
        spec_for(errors.IdempotencyKeyReused("")),
        spec_for(errors.InputInvalid("")),
        description="The request failed validation.",
    ),
    problem_docs(
        spec_for(errors.RegistrationBusy(60)),
        description="Registration is busy. Retry after the interval in Retry-After.",
        retry_after=True,
    ),
    _RATE_LIMITED,
    _BOT_CHECK,
    _INTERNAL,
)
VALIDATE_DOCS = merge_docs(
    problem_docs(
        spec_for(errors.InputInvalid("")),
        description="The request body is malformed.",
    ),
    _RATE_LIMITED,
    _INTERNAL,
)
CHECK_DOCS = merge_docs(
    problem_docs(
        spec_for(errors.EmailInvalid("")),
        spec_for(errors.PhoneInvalid("")),
        spec_for(errors.TaxIdInvalid("")),
        spec_for(errors.InputInvalid("")),
        description="The request failed validation.",
    ),
    _RATE_LIMITED,
    _BOT_CHECK,
    _INTERNAL,
)

RequestCtx = Annotated[RequestContext, Depends(get_request_context)]


@router.post(
    "/register",
    status_code=201,
    response_model=RegistrationCreated,
    operation_id="registerCustomer",
    summary="Register a customer",
    responses={
        201: {
            "description": (
                "The customer was created, or an earlier request with the same Idempotency-Key "
                "was replayed. The response has no Location header because the API exposes no "
                "customer read endpoint; the body carries the customer id."
            ),
            "headers": {
                "X-Request-Id": {"description": "Request id.", "schema": {"type": "string"}},
                "Idempotent-Replayed": {
                    "description": "`true` when the response replays an earlier request.",
                    "schema": {"type": "string"},
                },
            },
        },
        **REGISTER_DOCS,
    },
)
async def register_customer(
    body: CustomerInput,
    response: Response,
    ctx: RequestCtx,
    service: Annotated[RegistrationService, Depends(get_registration_service)],
    idempotency_key: Annotated[
        UUID | None,
        Header(
            alias="Idempotency-Key",
            description=(
                "A UUID the client generates once per registration attempt. Repeating the "
                "request with the same key and body within 24 hours returns the original result."
            ),
        ),
    ] = None,
) -> RegistrationCreated:
    """Register a customer.

    Deterministic checks decide the outcome: syntax, the disposable-domain list, the MX lookup,
    and an exact email, phone, or tax-ID match inside one BigQuery transaction. The model adds
    typo and likely-duplicate warnings and never changes the status.
    """
    outcome = await service.register(body, ctx, str(idempotency_key) if idempotency_key else None)
    if outcome.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return RegistrationCreated(
        customer_id=outcome.customer_id,
        email=outcome.email,
        warnings=outcome.warnings,
        advisory_status=outcome.advisory_status,
    )


@router.post(
    "/validate",
    response_model=EmailValidationResult,
    operation_id="validateEmail",
    summary="Validate an email address",
    responses=VALIDATE_DOCS,
)
async def validate_email(
    body: EmailValidationRequest,
    ctx: RequestCtx,
    service: Annotated[EmailValidationService, Depends(get_email_service)],
) -> EmailValidationResult:
    """Check an email address and return the verdict.

    An invalid address is a successful check, so the status stays 200 and the body carries the
    problems. A 422 means the request body itself is malformed.
    """
    return await service.validate(body.email, ctx)


@router.post(
    "/check-duplicate",
    response_model=DuplicateCheckResult,
    operation_id="checkDuplicateCustomer",
    summary="Check whether a customer already exists",
    responses=CHECK_DOCS,
)
async def check_duplicate_customer(
    body: CustomerInput,
    ctx: RequestCtx,
    service: Annotated[DuplicateDetectionService, Depends(get_duplicate_service)],
) -> DuplicateCheckResult:
    """Report which of email, phone, and tax ID already belong to a customer.

    The call writes no customer. A found match is a successful check, so the status stays 200.
    The response names the matched fields and never another customer's data.
    """
    return await service.check(body, ctx)
