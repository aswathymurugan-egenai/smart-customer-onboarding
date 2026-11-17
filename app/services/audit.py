"""Builds and records audit rows.

Audit writes are best effort for attempts that did not create a customer: a failed write is
logged by error type and never changes the response.
"""

from __future__ import annotations

import structlog

from app.domain.customer import AttemptAudit, AuditEvent
from app.services.guard import RequestContext
from app.services.pii import PiiHasher
from app.services.ports import Clock, CustomerRepository, IdGenerator

log = structlog.get_logger(__name__)

MILLISECONDS = 1000


class AuditRecorder:
    """Creates `AttemptAudit` values and appends `AuditEvent` rows."""

    def __init__(
        self,
        *,
        repository: CustomerRepository,
        hasher: PiiHasher,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._repository = repository
        self._hasher = hasher
        self._clock = clock
        self._ids = ids

    def attempt(
        self,
        ctx: RequestContext,
        *,
        idempotency_key: str | None = None,
        fingerprint: str | None = None,
        canonical_email: str | None = None,
        mx_status: str | None = None,
        advisory_status: str | None = None,
        typo_suggested_domain: str | None = None,
        fuzzy_candidate_ids: tuple[str, ...] = (),
        fuzzy_max_confidence: float | None = None,
        advisory_model: str | None = None,
        lock_retries: int = 0,
    ) -> AttemptAudit:
        """Build the audit columns for the request in `ctx`, hashing every personal value."""
        elapsed = self._clock.monotonic() - ctx.started_at
        return AttemptAudit(
            event_id=self._ids.new_id(),
            request_id=ctx.request_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            channel=ctx.channel,
            email_hash=self._hasher.email(canonical_email) if canonical_email else None,
            client_hash=self._hasher.client(ctx.client_id),
            mx_status=mx_status,
            advisory_status=advisory_status,
            typo_suggested_domain=typo_suggested_domain,
            fuzzy_candidate_ids=fuzzy_candidate_ids,
            fuzzy_max_confidence=fuzzy_max_confidence,
            advisory_model=advisory_model,
            lock_retries=lock_retries,
            latency_ms=max(0, int(elapsed * MILLISECONDS)),
        )

    async def record(self, event: AuditEvent) -> None:
        """Append `event`. A storage failure is logged and swallowed on purpose."""
        try:
            await self._repository.record_attempt(event)
        except Exception as error:
            log.error("audit_write_failed", error_type=type(error).__name__)
