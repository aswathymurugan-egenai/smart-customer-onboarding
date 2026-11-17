"""Shared fixtures. Every test runs through httpx against `create_app()` with no credentials
and no network."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.composition import AssistantFactory, ComponentOverrides
from app.config import Settings
from app.main import create_app
from app.services.email_validation import DomainLists
from tests.fakes import (
    FakeBigQuery,
    FakeClock,
    FakeMx,
    ScriptedAdvisor,
    SequenceIds,
    seeded_rng,
)

HASH_KEY = "test-hash-key-0123456789"
ALLOWED_ORIGIN = "http://localhost:3000"
TEST_DISPOSABLE = frozenset({"mailinator.test", "tempmail.test"})


def make_settings(**overrides: Any) -> Settings:
    """Settings for tests: BigQuery store with a fake client, local adapters allowed."""
    values: dict[str, Any] = {
        "gcp_project": "test-project-1",
        "customer_store": "bigquery",
        "allow_local_adapters": True,
        "email_allow_reserved_domains": True,
        "cors_allow_origins": [ALLOWED_ORIGIN],
        "pii_hash_key": SecretStr(HASH_KEY),
        "advisor_enabled": True,
        "assistant_enabled": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_lists() -> DomainLists:
    """A small disposable list plus the real free-mail list."""
    return DomainLists(disposable=TEST_DISPOSABLE, free_mail=DomainLists.load().free_mail)


@dataclass
class Harness:
    """A running app and the doubles behind it."""

    app: FastAPI
    client: httpx.AsyncClient
    bq: FakeBigQuery
    advisor: ScriptedAdvisor
    mx: FakeMx
    clock: FakeClock
    settings: Settings


@asynccontextmanager
async def running_harness(
    *,
    assistant_factory: AssistantFactory | None = None,
    advisor: ScriptedAdvisor | None = None,
    mx: FakeMx | None = None,
    bq: FakeBigQuery | None = None,
    lists: DomainLists | None = None,
    **settings_overrides: Any,
) -> AsyncIterator[Harness]:
    """Start the app with the lifespan running and yield a client wired to it."""
    settings = make_settings(**settings_overrides)
    fake_bq = bq or FakeBigQuery()
    fake_advisor = advisor or ScriptedAdvisor()
    fake_mx = mx or FakeMx()
    clock = FakeClock()
    overrides = ComponentOverrides(
        bq_client=fake_bq.client,
        genai_client=object(),
        advisor=fake_advisor if settings.advisor_enabled else None,
        mx=fake_mx,
        clock=clock,
        ids=SequenceIds(),
        rng=seeded_rng(),
        lists=lists or test_lists(),
        assistant_factory=assistant_factory,
    )
    app = create_app(settings, overrides)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield Harness(app, client, fake_bq, fake_advisor, fake_mx, clock, settings)


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    """The default app: advisor on, assistant off."""
    async with running_harness(assistant_enabled=False) as running:
        yield running
