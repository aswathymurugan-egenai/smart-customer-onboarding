"""Registration: the flow that turns a validated submission into a stored customer.

Deterministic checks and the BigQuery transaction decide 201, 409, or 422. The advisor only
adds warnings, and a failure there removes the warnings without changing the status.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

import structlog

from app.domain.customer import (
    AdvisoryStatus,
    AttemptAudit,
    AuditEvent,
    CustomerRecord,
    NormalizedCustomer,
    RegisterResult,
)
from app.domain.errors import (
    DuplicateCustomer,
    IdempotencyKeyReused,
    LockConflict,
    RegistrationBusy,
)
from app.models.problem_catalog import spec_for
from app.models.schemas import (
    AdvisoryWarning,
    CustomerInput,
    DuplicateWarning,
    TypoWarning,
)
from app.services.audit import AuditRecorder
from app.services.customer_normalizer import CustomerNormalizer
from app.services.duplicate_detection import (
    DuplicateAssessment,
    DuplicateDetectionService,
    customer_fingerprint_body,
)
from app.services.email_validation import EmailValidationService
from app.services.guard import RequestContext, RequestGuard
from app.services.pii import PiiHasher, last_characters
from app.services.ports import Advisor, Clock, CustomerRepository, IdGenerator

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RegistrationOutcome:
    """A successful registration, or the replay of an earlier one."""

    customer_id: str
    email: str
    warnings: list[AdvisoryWarning]
    advisory_status: AdvisoryStatus
    replayed: bool


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How a registration retries when it loses the table lock."""

    budget_seconds: float
    base_seconds: float
    max_retries: int
    retry_after_seconds: int


@dataclass(frozen=True, slots=True)
class _Advice:
    warnings: list[AdvisoryWarning]
    status: AdvisoryStatus
    typo_domain: str | None
    duplicates: DuplicateAssessment | None
    model: str | None


@dataclass(slots=True)
class _Trace:
    """What the flow learned so far, kept for the audit row if the request fails."""

    canonical_email: str | None
    mx_status: str | None = None
    advice: _Advice | None = None
    lock_retries: int = 0


class RegistrationService:
    """Owns the registration transaction and its retry loop."""

    def __init__(
        self,
        *,
        repository: CustomerRepository,
        email_validation: EmailValidationService,
        duplicates: DuplicateDetectionService,
        advisor: Advisor,
        normalizer: CustomerNormalizer,
        hasher: PiiHasher,
        guard: RequestGuard,
        audit: AuditRecorder,
        clock: Clock,
        ids: IdGenerator,
        advisory_budget_seconds: float,
        retry: RetryPolicy,
        rng: random.Random | None = None,
    ) -> None:
        self._repository = repository
        self._email = email_validation
        self._duplicates = duplicates
        self._advisor = advisor
        self._normalizer = normalizer
        self._hasher = hasher
        self._guard = guard
        self._audit = audit
        self._clock = clock
        self._ids = ids
        self._advisory_budget = advisory_budget_seconds
        self._retry = retry
        self._rng = rng or random.Random()  # noqa: S311 - jitter, not security

    async def register(
        self, request: CustomerInput, ctx: RequestContext, idempotency_key: str | None = None
    ) -> RegistrationOutcome:
        """Register a customer, or raise the typed error that explains why not.

        Every outcome other than a created customer appends one audit row. The created row is
        written inside the transaction.
        """
        fingerprint = self._hasher.fingerprint(customer_fingerprint_body(request))
        trace = _Trace(canonical_email=self._normalizer.safe_canonical_email(request.email))
        try:
            return await self._run(request, ctx, idempotency_key, fingerprint, trace)
        except Exception as error:
            await self._audit_failure(error, ctx, idempotency_key, fingerprint, trace)
            raise

    async def _run(
        self,
        request: CustomerInput,
        ctx: RequestContext,
        idempotency_key: str | None,
        fingerprint: str,
        trace: _Trace,
    ) -> RegistrationOutcome:
        await self._guard.enforce("register", ctx, request.bot_token)
        customer = self._normalizer.normalize(request)
        check = await self._email.assert_registrable(customer.email)
        trace.mx_status = check.mx_status
        advice = await self._advise(customer, trace)
        record = CustomerRecord(
            customer_id=self._ids.new_id(),
            customer=customer,
            mx_status=check.mx_status,
            tax_id_hash=self._hasher.tax_id(customer.tax_id) if customer.tax_id else None,
            tax_id_last4=last_characters(customer.tax_id) if customer.tax_id else None,
            hash_key_version=self._hasher.key_version,
            source_channel=ctx.channel,
        )
        result = await self._commit(record, ctx, idempotency_key, fingerprint, trace)
        return await self._complete(
            result, record, ctx, idempotency_key, fingerprint, advice, trace
        )

    async def _advise(self, customer: NormalizedCustomer, trace: _Trace) -> _Advice:
        rules = self._email.rules_suggestion(customer.email)
        if not self._advisor.enabled:
            advice = self._build_advice(rules, None, "disabled", None)
        else:
            advice = await self._advise_with_model(customer, rules)
        trace.advice = advice
        return advice

    async def _advise_with_model(
        self, customer: NormalizedCustomer, rules: TypoWarning | None
    ) -> _Advice:
        typo: TypoWarning | None = rules
        assessment: DuplicateAssessment | None = None
        failed = False
        try:
            async with asyncio.timeout(self._advisory_budget):
                typo_result, dup_result = await asyncio.gather(
                    self._model_typo(customer.email, rules),
                    self._duplicates.assess(customer),
                    return_exceptions=True,
                )
        except TimeoutError:
            log.warning("advice_timed_out", error_type="TimeoutError")
            return self._build_advice(rules, None, "unavailable", self._advisor.model_name)
        if isinstance(typo_result, BaseException):
            log.warning("typo_advice_failed", error_type=type(typo_result).__name__)
            failed = True
        else:
            typo = typo_result
        if isinstance(dup_result, BaseException):
            log.warning("duplicate_advice_failed", error_type=type(dup_result).__name__)
            failed = True
        else:
            assessment = dup_result
        status: AdvisoryStatus = "unavailable" if failed else "ok"
        return self._build_advice(typo, assessment, status, self._advisor.model_name)

    async def _model_typo(self, email: str, rules: TypoWarning | None) -> TypoWarning | None:
        if rules is not None:
            return rules
        return await self._email.model_suggestion(email)

    @staticmethod
    def _build_advice(
        typo: TypoWarning | None,
        assessment: DuplicateAssessment | None,
        status: AdvisoryStatus,
        model: str | None,
    ) -> _Advice:
        warnings: list[AdvisoryWarning] = []
        if typo is not None:
            warnings.append(typo)
        duplicate: DuplicateWarning | None = assessment.warning if assessment else None
        if duplicate is not None:
            warnings.append(duplicate)
        return _Advice(
            warnings=warnings,
            status=status,
            typo_domain=typo.suggested_email.rpartition("@")[2] if typo else None,
            duplicates=assessment,
            model=model,
        )

    async def _commit(
        self,
        record: CustomerRecord,
        ctx: RequestContext,
        idempotency_key: str | None,
        fingerprint: str,
        trace: _Trace,
    ) -> RegisterResult:
        started = self._clock.monotonic()
        while True:
            attempt = self._attempt_for(ctx, idempotency_key, fingerprint, trace)
            try:
                return await self._repository.register(record, attempt)
            except LockConflict:
                elapsed = self._clock.monotonic() - started
                if trace.lock_retries >= self._retry.max_retries or (
                    elapsed >= self._retry.budget_seconds
                ):
                    raise RegistrationBusy(
                        self._retry.retry_after_seconds, lock_retries=trace.lock_retries
                    ) from None
                trace.lock_retries += 1
                ceiling = self._retry.base_seconds * 2 ** (trace.lock_retries - 1)
                delay = min(self._rng.uniform(0, ceiling), self._retry.budget_seconds - elapsed)
                await self._clock.sleep(delay)

    async def _complete(
        self,
        result: RegisterResult,
        record: CustomerRecord,
        ctx: RequestContext,
        idempotency_key: str | None,
        fingerprint: str,
        advice: _Advice,
        trace: _Trace,
    ) -> RegistrationOutcome:
        if result.outcome == "duplicate":
            raise DuplicateCustomer(result.matched_on)
        if result.outcome == "fingerprint_mismatch":
            raise IdempotencyKeyReused("The idempotency key was used with a different request.")
        email = record.customer.email
        if result.outcome == "replay" and result.customer_id:
            await self._audit.record(
                AuditEvent(
                    attempt=self._attempt_for(ctx, idempotency_key, fingerprint, trace),
                    operation="register",
                    outcome="replay",
                    http_status=201,
                    customer_id=result.customer_id,
                )
            )
            return RegistrationOutcome(result.customer_id, email, [], advice.status, True)
        return RegistrationOutcome(
            customer_id=record.customer_id,
            email=email,
            warnings=advice.warnings,
            advisory_status=advice.status,
            replayed=False,
        )

    def _attempt_for(
        self, ctx: RequestContext, idempotency_key: str | None, fingerprint: str, trace: _Trace
    ) -> AttemptAudit:
        advice = trace.advice
        return self._audit.attempt(
            ctx,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            canonical_email=trace.canonical_email,
            mx_status=trace.mx_status,
            advisory_status=advice.status if advice else None,
            typo_suggested_domain=advice.typo_domain if advice else None,
            fuzzy_candidate_ids=advice.duplicates.candidate_ids
            if advice and advice.duplicates
            else (),
            fuzzy_max_confidence=(
                advice.duplicates.max_confidence if advice and advice.duplicates else None
            ),
            advisory_model=advice.model if advice else None,
            lock_retries=trace.lock_retries,
        )

    async def _audit_failure(
        self,
        error: Exception,
        ctx: RequestContext,
        idempotency_key: str | None,
        fingerprint: str,
        trace: _Trace,
    ) -> None:
        spec = spec_for(error)
        await self._audit.record(
            AuditEvent(
                attempt=self._attempt_for(ctx, idempotency_key, fingerprint, trace),
                operation="register",
                outcome=spec.outcome,
                http_status=spec.status,
                matched_on=error.matched_on if isinstance(error, DuplicateCustomer) else (),
                problem_codes=(spec.code,),
            )
        )
