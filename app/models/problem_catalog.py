"""The catalog of problem types: one row per typed error, shared by the API and the audit trail."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain import errors

PROBLEM_TYPE_PREFIX = "urn:smart-customer-onboarding:problem:"


@dataclass(frozen=True, slots=True)
class ProblemSpec:
    """How one kind of failure appears on the wire and in the audit table."""

    code: str
    title: str
    status: int
    outcome: str

    @property
    def type_uri(self) -> str:
        """The stable problem type URI."""
        return f"{PROBLEM_TYPE_PREFIX}{self.code}"


VALIDATION_ERROR = ProblemSpec("validation-error", "The request is not valid", 422, "invalid_input")
INTERNAL_ERROR = ProblemSpec("internal-error", "Internal server error", 500, "error")

_CATALOG: dict[type[Exception], ProblemSpec] = {
    errors.EmailInvalid: ProblemSpec(
        "email-invalid", "The email address is not valid", 422, "invalid_email"
    ),
    errors.EmailDisposable: ProblemSpec(
        "email-disposable", "Disposable email addresses are not accepted", 422, "invalid_email"
    ),
    errors.EmailUndeliverable: ProblemSpec(
        "email-domain-undeliverable", "The email domain cannot receive mail", 422, "invalid_email"
    ),
    errors.PhoneInvalid: ProblemSpec(
        "phone-invalid", "The phone number is not valid", 422, "invalid_input"
    ),
    errors.TaxIdInvalid: ProblemSpec(
        "tax-id-invalid", "The tax ID is not valid", 422, "invalid_input"
    ),
    errors.InputInvalid: VALIDATION_ERROR,
    errors.DuplicateCustomer: ProblemSpec(
        "customer-duplicate", "A customer with these details already exists", 409, "duplicate"
    ),
    errors.IdempotencyKeyReused: ProblemSpec(
        "idempotency-key-reused",
        "The idempotency key was used with a different request",
        422,
        "invalid_input",
    ),
    errors.RegistrationBusy: ProblemSpec(
        "registration-busy", "Registration is busy, try again shortly", 503, "busy"
    ),
    errors.RateLimited: ProblemSpec("rate-limited", "Too many requests", 429, "rate_limited"),
    errors.BotCheckFailed: ProblemSpec(
        "bot-check-failed", "The bot check failed", 403, "bot_check_failed"
    ),
    errors.AssistantUnavailable: ProblemSpec(
        "assistant-unavailable", "The assistant is unavailable", 503, "error"
    ),
}


def spec_for(error: BaseException) -> ProblemSpec:
    """Return the catalog row for an error, or the generic internal-error row."""
    for klass in type(error).__mro__:
        spec = _CATALOG.get(klass)
        if spec is not None:
            return spec
    return INTERNAL_ERROR


def all_specs() -> list[ProblemSpec]:
    """Every distinct problem the API can return, for documentation and tests."""
    seen: dict[str, ProblemSpec] = {}
    for spec in (*_CATALOG.values(), VALIDATION_ERROR, INTERNAL_ERROR):
        seen.setdefault(spec.code, spec)
    return list(seen.values())
