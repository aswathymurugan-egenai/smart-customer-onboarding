"""In-memory customer repository for local development and offline tests.

It implements the same port as the BigQuery adapter, with one `asyncio.Lock` around
`register` standing in for the table lock. It loads only when local adapters are allowed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from app.domain.customer import (
    AttemptAudit,
    AuditEvent,
    BlockingProbe,
    CandidateRow,
    CustomerRecord,
    MatchProbe,
    RegisterOutcome,
    RegisterResult,
)
from app.domain.normalize import normalize_postal_code
from app.services.ports import Clock

IDEMPOTENCY_WINDOW = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class _CreatedRow:
    """The audit row written with a created customer; replay checks read it."""

    idempotency_key: str | None
    request_fingerprint: str | None
    customer_id: str
    created_at_seconds: float


class InMemoryCustomerRepository:
    """Holds customers and audit events in process memory."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = asyncio.Lock()
        self._customers: list[CustomerRecord] = []
        self._created: list[_CreatedRow] = []
        self._events: list[AuditEvent] = []

    @property
    def customers(self) -> tuple[CustomerRecord, ...]:
        """Every stored customer, oldest first."""
        return tuple(self._customers)

    @property
    def audit_events(self) -> tuple[AuditEvent, ...]:
        """Every audit event recorded through `record_attempt`."""
        return tuple(self._events)

    def _matches(self, probe: MatchProbe) -> tuple[str, ...]:
        found: set[str] = set()
        for stored in self._customers:
            customer = stored.customer
            if customer.email == probe.email:
                found.add("email")
            if probe.phone_e164 and customer.phone_e164 == probe.phone_e164:
                found.add("phone")
            if probe.tax_id_hash and stored.tax_id_hash == probe.tax_id_hash:
                found.add("tax_id")
        return tuple(sorted(found))

    def _replay(self, attempt: AttemptAudit) -> _CreatedRow | None:
        if not attempt.idempotency_key:
            return None
        cutoff = self._clock.now() - IDEMPOTENCY_WINDOW
        for row in self._created:
            if row.idempotency_key == attempt.idempotency_key and (
                row.created_at_seconds >= cutoff.timestamp()
            ):
                return row
        return None

    async def register(self, record: CustomerRecord, attempt: AttemptAudit) -> RegisterResult:
        """Register one customer under the lock, mirroring `register_customer.sql`."""
        async with self._lock:
            replay = self._replay(attempt)
            if replay is not None:
                outcome: RegisterOutcome = (
                    "replay"
                    if replay.request_fingerprint == attempt.request_fingerprint
                    else "fingerprint_mismatch"
                )
                return RegisterResult(outcome=outcome, customer_id=replay.customer_id)

            customer = record.customer
            matched_on = self._matches(
                MatchProbe(
                    email=customer.email,
                    phone_e164=customer.phone_e164,
                    tax_id_hash=record.tax_id_hash,
                )
            )
            if matched_on:
                return RegisterResult(outcome="duplicate", customer_id=None, matched_on=matched_on)

            self._customers.append(record)
            self._created.append(
                _CreatedRow(
                    idempotency_key=attempt.idempotency_key,
                    request_fingerprint=attempt.request_fingerprint,
                    customer_id=record.customer_id,
                    created_at_seconds=self._clock.now().timestamp(),
                )
            )
            return RegisterResult(outcome="created", customer_id=record.customer_id)

    async def find_exact_matches(self, probe: MatchProbe) -> tuple[str, ...]:
        """Return the matching key names, sorted."""
        return self._matches(probe)

    async def find_fuzzy_candidates(self, probe: BlockingProbe, limit: int) -> list[CandidateRow]:
        """Return customers that share a blocking key, newest first."""
        rows: list[CandidateRow] = []
        for stored in reversed(self._customers):
            customer = stored.customer
            address = customer.address
            postal_key = (
                normalize_postal_code(address.postal_code)
                if address and address.postal_code
                else None
            )
            shares_postal = (
                probe.postal_code_key is not None
                and postal_key == probe.postal_code_key
                and address is not None
                and address.country_code == probe.country_code
            )
            shares_domain = (
                probe.business_domain is not None
                and customer.customer_type == "business"
                and customer.email_domain == probe.business_domain
            )
            if not (
                customer.normalized_name == probe.normalized_name
                or customer.name_key == probe.name_key
                or shares_postal
                or shares_domain
            ):
                continue
            rows.append(
                CandidateRow(
                    customer_id=stored.customer_id,
                    customer_type=customer.customer_type,
                    company_name=customer.company_name,
                    normalized_name=customer.normalized_name,
                    name_key=customer.name_key,
                    normalized_address=customer.normalized_address,
                    city=address.city if address else None,
                    postal_code_key=postal_key,
                    country_code=address.country_code if address else None,
                    email_domain=customer.email_domain,
                    email_local_part=customer.email_local_part,
                )
            )
            if len(rows) >= limit:
                break
        return rows

    async def record_attempt(self, event: AuditEvent) -> None:
        """Append an audit event."""
        self._events.append(event)

    async def check_ready(self) -> None:
        """The in-memory store is always reachable."""
        return None
