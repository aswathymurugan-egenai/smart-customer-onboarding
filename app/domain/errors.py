"""Typed domain errors.

Business code raises these and never touches a status code. `app/api/problems.py`
translates each one into an RFC 9457 problem response in a single place.
"""

from __future__ import annotations

from collections.abc import Sequence


class DomainError(Exception):
    """Base class for every error the domain and services raise on purpose.

    `field` is the request field the error concerns, when there is one. The API layer turns
    it into a JSON pointer.
    """

    field: str | None = None

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if field is not None:
            self.field = field


class InputInvalid(DomainError):
    """A submitted value passed the schema but cannot be used, such as a name with no letters."""


class EmailInvalid(DomainError):
    """The address fails syntax checks."""

    field = "email"


class EmailRejected(DomainError):
    """An address that passed syntax checks but cannot be used.

    `suggested_email` carries a rule-based correction when the domain looks like a typo, so a
    person who mistyped a common provider sees what they probably meant.
    """

    field = "email"

    def __init__(self, message: str, *, suggested_email: str | None = None) -> None:
        super().__init__(message)
        self.suggested_email = suggested_email


class EmailDisposable(EmailRejected):
    """The address belongs to a disposable-mail domain."""


class EmailUndeliverable(EmailRejected):
    """The domain has neither MX nor address records, so mail cannot reach it."""


class PhoneInvalid(DomainError):
    """The phone number cannot be parsed or is not a valid number for its region."""

    field = "phone"


class TaxIdInvalid(DomainError):
    """The tax ID does not match the pattern for its declared type."""

    field = "tax_id"


class DuplicateCustomer(DomainError):
    """An existing customer already owns one of the unique keys."""

    def __init__(self, matched_on: Sequence[str]) -> None:
        super().__init__("A customer already exists with the same " + ", ".join(matched_on))
        self.matched_on: tuple[str, ...] = tuple(matched_on)


class IdempotencyKeyReused(DomainError):
    """An idempotency key arrived with a different request body than the one it first carried."""


class RegistrationBusy(DomainError):
    """Lock conflicts outlasted the retry budget."""

    def __init__(self, retry_after: int, lock_retries: int = 0) -> None:
        super().__init__("Registration is busy; retry after the interval in Retry-After")
        self.retry_after = retry_after
        self.lock_retries = lock_retries


class RateLimited(DomainError):
    """The client exhausted its allowance for an operation."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many requests; retry after the interval in Retry-After")
        self.retry_after = retry_after


class BotCheckFailed(DomainError):
    """The bot-check token is missing or was rejected."""


class AssistantUnavailable(DomainError):
    """The assistant model failed and no fallback answered."""


class LockConflict(Exception):
    """A registration transaction aborted because another transaction holds the table lock.

    Raised by repositories and handled by the registration service's retry loop. It never
    reaches the transport layer.
    """


class AdvisorFailure(Exception):
    """A model call produced no usable advice.

    `reason` is `invalid_output` when the model answered but the answer failed validation,
    and `unavailable` for a timeout, transport error, or refusal. Callers treat both as an
    advisory that did not happen and never change a status code because of it.
    """

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason
