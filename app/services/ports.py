"""Ports: the interfaces the services depend on.

Concrete adapters (BigQuery, DNS, Gemini, the system clock) are wired once, in the lifespan.
Tests supply fakes that satisfy the same Protocols.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from app.config import Operation
from app.domain.customer import (
    AttemptAudit,
    AuditEvent,
    BlockingProbe,
    CandidateRow,
    CustomerRecord,
    MatchProbe,
    RegisterResult,
)
from app.models.advice import FuzzyAdvice, TypoAdvice

MxLookup = Literal["pass", "fail", "unknown"]


@dataclass(frozen=True, slots=True)
class ApplicantView:
    """The applicant fields a model may see. No phone, tax ID, email local part, or id."""

    customer_type: str
    normalized_name: str
    company_name: str | None
    city: str | None
    postal_code: str | None
    country_code: str | None
    business_domain: str | None


@dataclass(frozen=True, slots=True)
class CandidateView:
    """A candidate under an opaque reference, with the same field limits as the applicant."""

    ref: str
    customer_type: str
    normalized_name: str
    company_name: str | None
    city: str | None
    postal_code: str | None
    country_code: str | None
    business_domain: str | None


class CustomerRepository(Protocol):
    """Reads and writes customers and the audit trail."""

    async def register(self, record: CustomerRecord, attempt: AttemptAudit) -> RegisterResult:
        """Run the registration transaction. Raises `LockConflict` when it loses the lock."""
        ...

    async def find_exact_matches(self, probe: MatchProbe) -> tuple[str, ...]:
        """Return which of email, phone, and tax_id already belong to a customer."""
        ...

    async def find_fuzzy_candidates(self, probe: BlockingProbe, limit: int) -> list[CandidateRow]:
        """Return up to `limit` customers that share a blocking key with the probe."""
        ...

    async def record_attempt(self, event: AuditEvent) -> None:
        """Append one audit row for an attempt that did not create a customer."""
        ...

    async def check_ready(self) -> None:
        """Raise when the backing store cannot be reached."""
        ...


class MxResolver(Protocol):
    """Looks up whether a domain accepts mail."""

    async def lookup(self, domain: str) -> MxLookup:
        """Return `pass`, `fail`, or `unknown` for a timeout or resolver error."""
        ...


class Advisor(Protocol):
    """Produces advice with a model. Failures raise `AdvisorFailure`."""

    enabled: bool
    model_name: str

    async def suggest_domain(self, domain: str) -> TypoAdvice:
        """Judge whether `domain` is a mistyped common mail domain."""
        ...

    async def assess_candidates(
        self, applicant: ApplicantView, candidates: Sequence[CandidateView]
    ) -> FuzzyAdvice:
        """Judge whether each candidate is the same person or company as the applicant."""
        ...


class RateLimiter(Protocol):
    """Enforces a per-client allowance for each operation."""

    def check(self, client_id: str, operation: Operation) -> None:
        """Record one call, or raise `RateLimited` when the allowance is spent."""
        ...


class BotVerifier(Protocol):
    """Decides whether a bot-check token proves a human."""

    async def verify(self, token: str, client_id: str) -> bool:
        """Return True when the token is accepted."""
        ...


class Clock(Protocol):
    """Time source, injectable so retry and expiry logic is testable."""

    def now(self) -> datetime:
        """Current UTC time."""
        ...

    def monotonic(self) -> float:
        """Monotonic seconds, for measuring durations."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Wait without blocking the event loop."""
        ...


class IdGenerator(Protocol):
    """Produces identifiers."""

    def new_id(self) -> str:
        """Return a fresh time-ordered unique id."""
        ...
