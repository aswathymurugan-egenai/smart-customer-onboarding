"""Duplicate detection: exact key matches, then blocking, scoring, and model verdicts."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

import structlog

from app.domain.customer import (
    AdvisoryStatus,
    AuditEvent,
    CandidateRow,
    MatchProbe,
    NormalizedCustomer,
)
from app.domain.errors import DomainError
from app.domain.matching import MatchThresholds, ScoredCandidate, compare, select_for_review
from app.models.advice import CandidateVerdict
from app.models.problem_catalog import spec_for
from app.models.schemas import (
    CustomerInput,
    DuplicateCheckResult,
    DuplicateReason,
    DuplicateWarning,
)
from app.services.audit import AuditRecorder
from app.services.customer_normalizer import CustomerNormalizer
from app.services.guard import RequestContext, RequestGuard
from app.services.pii import PiiHasher
from app.services.ports import (
    Advisor,
    ApplicantView,
    CandidateView,
    CustomerRepository,
)

log = structlog.get_logger(__name__)

FLAGGED_VERDICTS = frozenset({"likely_same", "possibly_same"})
MAX_REASONS = 3
LIKELY_MESSAGE = "A customer with very similar details probably already exists."
POSSIBLE_MESSAGE = "A customer with similar details may already exist."
OK_STATUS: AdvisoryStatus = "ok"


@dataclass(frozen=True, slots=True)
class DuplicateAssessment:
    """The model-assisted likely-duplicate result for one applicant.

    `candidate_ids` and `max_confidence` feed the audit row and never reach a response.
    """

    warning: DuplicateWarning | None
    candidate_ids: tuple[str, ...]
    max_confidence: float | None
    status: AdvisoryStatus
    model: str | None


def customer_fingerprint_body(request: CustomerInput) -> dict[str, object]:
    """The canonical request body that fingerprints a submission. The bot token is excluded."""
    return request.model_dump(mode="json", exclude={"bot_token"}, exclude_none=True)


class DuplicateDetectionService:
    """Finds exact and likely duplicates without ever naming another customer."""

    def __init__(
        self,
        *,
        repository: CustomerRepository,
        advisor: Advisor,
        normalizer: CustomerNormalizer,
        hasher: PiiHasher,
        guard: RequestGuard,
        audit: AuditRecorder,
        thresholds: MatchThresholds,
        blocking_limit: int,
        min_warning_confidence: float,
        advisory_budget_seconds: float,
    ) -> None:
        self._repository = repository
        self._advisor = advisor
        self._normalizer = normalizer
        self._hasher = hasher
        self._guard = guard
        self._audit = audit
        self._thresholds = thresholds
        self._blocking_limit = blocking_limit
        self._min_confidence = min_warning_confidence
        self._budget = advisory_budget_seconds

    def match_probe(self, customer: NormalizedCustomer) -> MatchProbe:
        """The exact-match keys for a customer, with the tax ID hashed."""
        return MatchProbe(
            email=customer.email,
            phone_e164=customer.phone_e164,
            tax_id_hash=self._hasher.tax_id(customer.tax_id) if customer.tax_id else None,
        )

    async def check(
        self,
        request: CustomerInput,
        ctx: RequestContext,
        *,
        include_likely_duplicates: bool = True,
    ) -> DuplicateCheckResult:
        """Report exact matches and a likely-duplicate warning. Writes no customer.

        With `include_likely_duplicates=False` only the exact-key lookup runs and no model is
        called.
        """
        fingerprint = self._hasher.fingerprint(customer_fingerprint_body(request))
        try:
            await self._guard.enforce("check_duplicate", ctx, request.bot_token)
            customer = self._normalizer.normalize(request)
        except DomainError as error:
            await self._audit_rejection(error, ctx, fingerprint)
            raise
        probe = self.match_probe(customer)
        exact_task = asyncio.create_task(self._repository.find_exact_matches(probe))
        try:
            advisory = (
                await self.advise(customer)
                if include_likely_duplicates
                else DuplicateAssessment(None, (), None, OK_STATUS, None)
            )
        except BaseException:
            exact_task.cancel()
            raise
        exact = await exact_task
        await self._audit.record(
            AuditEvent(
                attempt=self._audit.attempt(
                    ctx,
                    fingerprint=fingerprint,
                    canonical_email=customer.email,
                    advisory_status=advisory.status,
                    fuzzy_candidate_ids=advisory.candidate_ids,
                    fuzzy_max_confidence=advisory.max_confidence,
                    advisory_model=advisory.model,
                ),
                operation="check_duplicate",
                outcome="checked",
                http_status=200,
                matched_on=tuple(exact),
            )
        )
        return DuplicateCheckResult(
            exact_matches=list(exact),
            possible_duplicate=advisory.warning,
            advisory_status=advisory.status,
        )

    async def advise(self, customer: NormalizedCustomer) -> DuplicateAssessment:
        """Run `assess` inside the advisory budget. A failure becomes `unavailable`."""
        if not self._advisor.enabled:
            return DuplicateAssessment(None, (), None, "disabled", None)
        try:
            async with asyncio.timeout(self._budget):
                return await self.assess(customer)
        except Exception as error:
            log.warning("duplicate_advice_failed", error_type=type(error).__name__)
            return DuplicateAssessment(None, (), None, "unavailable", self._advisor.model_name)

    async def assess(self, customer: NormalizedCustomer) -> DuplicateAssessment:
        """Block, pre-score, and ask the model about the best candidates.

        Raises on a repository or model failure. Callers decide how to degrade.
        """
        rows = await self._repository.find_fuzzy_candidates(
            self._normalizer.blocking_probe(customer), self._blocking_limit
        )
        applicant_domain = self._normalizer.business_domain(customer)
        scored = [
            ScoredCandidate(row, compare(customer, row, applicant_business_domain=applicant_domain))
            for row in rows
        ]
        selected = select_for_review(scored, self._thresholds)
        if not selected:
            return DuplicateAssessment(None, (), None, OK_STATUS, None)
        refs = {f"c{index}": item.row for index, item in enumerate(selected, start=1)}
        advice = await self._advisor.assess_candidates(
            self._applicant_view(customer, applicant_domain),
            [self._candidate_view(ref, row) for ref, row in refs.items()],
        )
        return self._to_assessment(advice.candidates, refs)

    def _applicant_view(
        self, customer: NormalizedCustomer, business_domain: str | None
    ) -> ApplicantView:
        address = customer.address
        return ApplicantView(
            customer_type=customer.customer_type,
            normalized_name=customer.normalized_name,
            company_name=customer.company_name,
            city=address.city if address else None,
            postal_code=customer.postal_code_key,
            country_code=address.country_code if address else None,
            business_domain=business_domain,
        )

    def _candidate_view(self, ref: str, row: CandidateRow) -> CandidateView:
        return CandidateView(
            ref=ref,
            customer_type=row.customer_type,
            normalized_name=row.normalized_name,
            company_name=row.company_name,
            city=row.city,
            postal_code=row.postal_code_key,
            country_code=row.country_code,
            business_domain=self._normalizer.row_business_domain(row),
        )

    def _to_assessment(
        self, verdicts: Sequence[CandidateVerdict], refs: dict[str, CandidateRow]
    ) -> DuplicateAssessment:
        flagged = [item for item in verdicts if item.verdict in FLAGGED_VERDICTS]
        if not flagged:
            return DuplicateAssessment(None, (), None, OK_STATUS, self._advisor.model_name)
        candidate_ids = tuple(dict.fromkeys(refs[item.ref].customer_id for item in flagged))
        strongest = max(flagged, key=lambda item: item.confidence)
        warning = None
        if strongest.confidence >= self._min_confidence:
            ordered = sorted(flagged, key=lambda item: item.confidence, reverse=True)
            reasons: list[DuplicateReason] = []
            for item in ordered:
                for reason in item.reasons:
                    if reason not in reasons:
                        reasons.append(reason)
            warning = DuplicateWarning(
                message=LIKELY_MESSAGE if strongest.verdict == "likely_same" else POSSIBLE_MESSAGE,
                confidence=round(strongest.confidence, 2),
                reasons=reasons[:MAX_REASONS],
            )
        return DuplicateAssessment(
            warning=warning,
            candidate_ids=candidate_ids,
            max_confidence=strongest.confidence,
            status=OK_STATUS,
            model=self._advisor.model_name,
        )

    async def _audit_rejection(
        self, error: DomainError, ctx: RequestContext, fingerprint: str
    ) -> None:
        spec = spec_for(error)
        await self._audit.record(
            AuditEvent(
                attempt=self._audit.attempt(ctx, fingerprint=fingerprint),
                operation="check_duplicate",
                outcome=spec.outcome,
                http_status=spec.status,
                problem_codes=(spec.code,),
            )
        )
