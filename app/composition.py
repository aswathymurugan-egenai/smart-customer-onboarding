"""The composition root: builds every adapter and service once and wires them together.

This is the only module that names concrete adapters. Tests substitute fakes through
`ComponentOverrides`, so the whole app runs with no credentials and no network.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.adk.sessions import BaseSessionService
from google.cloud import bigquery

from app.agents.registration_agent import (
    AssistantServices,
    RegistrationAssistant,
    build_assistant,
    configure_vertex_environment,
)
from app.config import Settings
from app.domain.matching import MatchThresholds
from app.services.advisor import DisabledAdvisor, GeminiAdvisor
from app.services.audit import AuditRecorder
from app.services.bot_check import StubBotVerifier
from app.services.bq_repository import BigQueryCustomerRepository
from app.services.customer_normalizer import CustomerNormalizer
from app.services.dns_mx import AsyncMxResolver
from app.services.duplicate_detection import DuplicateDetectionService
from app.services.email_validation import DomainLists, EmailValidationService
from app.services.guard import RequestGuard
from app.services.memory_repository import InMemoryCustomerRepository
from app.services.pii import PiiHasher
from app.services.ports import (
    Advisor,
    BotVerifier,
    Clock,
    CustomerRepository,
    IdGenerator,
    MxResolver,
)
from app.services.rate_limit import SlidingWindowRateLimiter
from app.services.registration import RegistrationService, RetryPolicy
from app.services.runtime import SystemClock, Uuid7Generator

AssistantFactory = Callable[[Settings, AssistantServices, RequestGuard], RegistrationAssistant]


@dataclass(frozen=True, slots=True)
class ComponentOverrides:
    """Substitutes for the adapters that need credentials or the network."""

    bq_client: Any | None = None
    genai_client: Any | None = None
    advisor: Advisor | None = None
    mx: MxResolver | None = None
    clock: Clock | None = None
    lists: DomainLists | None = None
    ids: IdGenerator | None = None
    rng: random.Random | None = None
    repository: CustomerRepository | None = None
    bot_verifier: BotVerifier | None = None
    session_service: BaseSessionService | None = None
    assistant_factory: AssistantFactory | None = None


@dataclass(slots=True)
class Components:
    """Everything the routes and the lifespan use."""

    settings: Settings
    repository: CustomerRepository
    email_validation: EmailValidationService
    duplicates: DuplicateDetectionService
    registration: RegistrationService
    guard: RequestGuard
    clock: Clock
    assistant: RegistrationAssistant | None = None
    closers: list[Callable[[], Any]] = field(default_factory=list)

    async def close(self) -> None:
        """Release clients. A failing closer never blocks the others."""
        for closer in self.closers:
            outcome = closer()
            if asyncio.iscoroutine(outcome):
                await outcome


def _build_repository(
    settings: Settings,
    overrides: ComponentOverrides,
    clock: Clock,
    closers: list[Callable[[], Any]],
) -> CustomerRepository:
    if overrides.repository is not None:
        return overrides.repository
    if settings.customer_store == "memory":
        return InMemoryCustomerRepository(clock)
    client = overrides.bq_client or bigquery.Client(
        project=settings.gcp_project, location=settings.bq_location
    )
    closers.append(client.close)
    assert settings.gcp_project is not None
    return BigQueryCustomerRepository(
        client,
        settings.gcp_project,
        settings.bq_dataset,
        job_timeout_seconds=settings.bq_job_timeout_seconds,
    )


def _build_advisor(
    settings: Settings, overrides: ComponentOverrides, closers: list[Callable[[], Any]]
) -> Advisor:
    if overrides.advisor is not None:
        return overrides.advisor
    if not settings.advisor_enabled:
        return DisabledAdvisor()
    client = overrides.genai_client or genai.Client(
        vertexai=True, project=settings.gcp_project, location=settings.genai_location
    )
    closers.append(client.close)
    return GeminiAdvisor(
        client,
        model=settings.gemini_advisor_model,
        timeout_seconds=settings.advisory_budget_seconds,
    )


def build_components(settings: Settings, overrides: ComponentOverrides | None = None) -> Components:
    """Construct and wire every component from validated settings."""
    overrides = overrides or ComponentOverrides()
    closers: list[Callable[[], Any]] = []
    clock = overrides.clock or SystemClock()
    ids = overrides.ids or Uuid7Generator()
    lists = overrides.lists or DomainLists.load()
    hasher = PiiHasher(settings.hash_key, settings.hash_key_version)
    verifier = overrides.bot_verifier or StubBotVerifier(
        allow_local_adapters=settings.allow_local_adapters
    )
    guard = RequestGuard(SlidingWindowRateLimiter(settings, clock), verifier)
    repository = _build_repository(settings, overrides, clock, closers)
    advisor = _build_advisor(settings, overrides, closers)
    normalizer = CustomerNormalizer(
        free_mail_domains=lists.free_mail,
        allow_reserved_domains=settings.email_allow_reserved_domains,
    )
    audit = AuditRecorder(repository=repository, hasher=hasher, clock=clock, ids=ids)
    email_validation = EmailValidationService(
        lists=lists,
        mx=overrides.mx or AsyncMxResolver(settings.mx_timeout_seconds),
        advisor=advisor,
        guard=guard,
        min_typo_confidence=settings.typo_min_confidence,
        allow_reserved_domains=settings.email_allow_reserved_domains,
    )
    duplicates = DuplicateDetectionService(
        repository=repository,
        advisor=advisor,
        normalizer=normalizer,
        hasher=hasher,
        guard=guard,
        audit=audit,
        thresholds=MatchThresholds(
            name_floor=settings.fuzzy_name_floor,
            name_with_signal_floor=settings.fuzzy_name_with_signal_floor,
            address_signal_floor=settings.fuzzy_address_floor,
            max_candidates=settings.fuzzy_max_candidates_for_model,
        ),
        blocking_limit=settings.fuzzy_blocking_limit,
        min_warning_confidence=settings.duplicate_warning_min_confidence,
        advisory_budget_seconds=settings.advisory_budget_seconds,
    )
    registration = RegistrationService(
        repository=repository,
        email_validation=email_validation,
        duplicates=duplicates,
        advisor=advisor,
        normalizer=normalizer,
        hasher=hasher,
        guard=guard,
        audit=audit,
        clock=clock,
        ids=ids,
        advisory_budget_seconds=settings.advisory_budget_seconds,
        retry=RetryPolicy(
            budget_seconds=settings.lock_retry_budget_seconds,
            base_seconds=settings.lock_retry_base_seconds,
            max_retries=settings.lock_retry_max_attempts,
            retry_after_seconds=settings.lock_retry_after_seconds,
        ),
        rng=overrides.rng,
    )
    components = Components(
        settings=settings,
        repository=repository,
        email_validation=email_validation,
        duplicates=duplicates,
        registration=registration,
        guard=guard,
        clock=clock,
        closers=closers,
    )
    if settings.assistant_enabled:
        services = AssistantServices(
            email_validation=email_validation,
            duplicates=duplicates,
            registration=registration,
            hasher=hasher,
            clock=clock,
        )
        if overrides.assistant_factory is not None:
            components.assistant = overrides.assistant_factory(settings, services, guard)
        else:
            configure_vertex_environment(settings)
            components.assistant = build_assistant(
                settings, services, guard, session_service=overrides.session_service
            )
    return components
