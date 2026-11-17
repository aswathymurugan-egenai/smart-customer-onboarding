"""Test doubles: a BigQuery client, a scripted advisor, a fake resolver, a clock, and a runner.

The BigQuery double is built on `create_autospec(bigquery.Client)`, so the repository calls the
same methods it would on a real client. Its `query()` picks a fake job by the SQL template and
keeps just enough state to answer like the real transaction would.
"""

from __future__ import annotations

import random
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import create_autospec

from google.adk.events import Event, EventActions
from google.adk.sessions import InMemorySessionService
from google.api_core import exceptions as api_exceptions
from google.cloud import bigquery
from google.genai import types

from app.agents.registration_agent import (
    AGENT_NAME,
    AgentRun,
    AssistantServices,
    RegistrationAssistant,
    build_tools,
)
from app.config import Settings
from app.domain.errors import AdvisorFailure
from app.models.advice import CandidateVerdict, FuzzyAdvice, TypoAdvice
from app.models.schemas import AssistantTurn
from app.services.guard import RequestGuard
from app.services.ports import ApplicantView, CandidateView, MxLookup

LOCK_CONFLICT_MESSAGE = "Transaction is aborted due to concurrent update against table customers."


class FakeClock:
    """A clock whose `sleep` advances time instantly."""

    def __init__(self) -> None:
        self._now = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        self._monotonic = 1000.0
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        self._monotonic += seconds
        self._now += timedelta(seconds=seconds)


class SequenceIds:
    """Deterministic ids: `id-1`, `id-2`, and so on."""

    def __init__(self) -> None:
        self._count = 0

    def new_id(self) -> str:
        self._count += 1
        return f"id-{self._count}"


class FakeMx:
    """Answers MX lookups from a table, defaulting to `pass`."""

    def __init__(self, answers: dict[str, MxLookup] | None = None) -> None:
        self.answers = answers or {}
        self.calls: list[str] = []

    async def lookup(self, domain: str) -> MxLookup:
        self.calls.append(domain)
        return self.answers.get(domain, "pass")


class ScriptedAdvisor:
    """An advisor whose answers and failures the test scripts."""

    enabled = True
    model_name = "scripted-model"

    def __init__(self) -> None:
        self.typo_advice: TypoAdvice | None = None
        self.fuzzy_verdicts: dict[str, tuple[str, float, list[str]]] = {}
        self.fail_typo: AdvisorFailure | None = None
        self.fail_fuzzy: AdvisorFailure | None = None
        self.typo_calls: list[str] = []
        self.fuzzy_calls: list[tuple[ApplicantView, list[CandidateView]]] = []

    async def suggest_domain(self, domain: str) -> TypoAdvice:
        self.typo_calls.append(domain)
        if self.fail_typo:
            raise self.fail_typo
        return self.typo_advice or TypoAdvice(
            is_likely_typo=False, suggested_domain=None, confidence=0.0
        )

    async def assess_candidates(
        self, applicant: ApplicantView, candidates: Sequence[CandidateView]
    ) -> FuzzyAdvice:
        self.fuzzy_calls.append((applicant, list(candidates)))
        if self.fail_fuzzy:
            raise self.fail_fuzzy
        verdicts = []
        for candidate in candidates:
            verdict, confidence, reasons = self.fuzzy_verdicts.get(
                candidate.ref, self.fuzzy_verdicts.get("*", ("different", 0.1, []))
            )
            verdicts.append(
                CandidateVerdict(
                    ref=candidate.ref,
                    verdict=verdict,  # type: ignore[arg-type]
                    confidence=confidence,
                    reasons=reasons,  # type: ignore[arg-type]
                )
            )
        return FuzzyAdvice(candidates=verdicts)


@dataclass
class QueryCall:
    """One query the repository ran."""

    sql: str
    params: dict[str, Any]
    labels: dict[str, str]


class FakeJob:
    """A completed query job."""

    def __init__(self, rows: list[dict[str, Any]], error: Exception | None = None) -> None:
        self._rows = rows
        self._error = error

    def result(self, timeout: float | None = None) -> list[dict[str, Any]]:
        if self._error:
            raise self._error
        return self._rows


@dataclass
class FakeBigQuery:
    """A BigQuery client double with a small state machine behind `query()`."""

    customers: list[dict[str, Any]] = field(default_factory=list)
    audit: list[dict[str, Any]] = field(default_factory=list)
    created_keys: dict[str, tuple[str, str]] = field(default_factory=dict)
    fuzzy_rows: list[dict[str, Any]] = field(default_factory=list)
    register_faults: list[Exception | None] = field(default_factory=list)
    calls: list[QueryCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.client = create_autospec(bigquery.Client, instance=True)
        self.client.query.side_effect = self._query
        self.client.get_dataset.return_value = object()

    @staticmethod
    def _params(config: bigquery.QueryJobConfig | None) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for parameter in (config.query_parameters if config else None) or []:
            if isinstance(parameter, bigquery.ArrayQueryParameter):
                values[parameter.name] = list(parameter.values)
            else:
                values[parameter.name] = parameter.value
        return values

    def _query(
        self, sql: str, job_config: bigquery.QueryJobConfig | None = None, **_: Any
    ) -> FakeJob:
        params = self._params(job_config)
        labels = dict(job_config.labels) if job_config and job_config.labels else {}
        self.calls.append(QueryCall(sql, params, labels))
        if "DECLARE replay" in sql:
            return self._register(params)
        if "SELECT field" in sql:
            return FakeJob([{"field": name} for name in self._matches(params)])
        if "ORDER BY created_at DESC" in sql:
            return FakeJob(list(self.fuzzy_rows))
        if "INSERT INTO" in sql and "registration_audit_logs" in sql:
            self.audit.append(params)
            return FakeJob([])
        raise AssertionError(f"Unexpected SQL in test: {sql[:60]}")

    def _matches(self, params: dict[str, Any]) -> list[str]:
        found: set[str] = set()
        for row in self.customers:
            if row["email"] == params.get("email"):
                found.add("email")
            if params.get("phone_e164") and row["phone_e164"] == params["phone_e164"]:
                found.add("phone")
            if params.get("tax_id_hash") and row["tax_id_hash"] == params["tax_id_hash"]:
                found.add("tax_id")
        return sorted(found)

    def _register(self, params: dict[str, Any]) -> FakeJob:
        if self.register_faults:
            fault = self.register_faults.pop(0)
            if fault is not None:
                return FakeJob([], error=fault)
        key = params["idempotency_key"]
        if key and key in self.created_keys:
            customer_id, fingerprint = self.created_keys[key]
            outcome = (
                "replay"
                if fingerprint == params["request_fingerprint"]
                else ("fingerprint_mismatch")
            )
            return FakeJob([{"outcome": outcome, "customer_id": customer_id, "matched_on": []}])
        matched = self._matches(params)
        if matched:
            return FakeJob([{"outcome": "duplicate", "customer_id": None, "matched_on": matched}])
        self.customers.append(params)
        if key:
            self.created_keys[key] = (params["customer_id"], params["request_fingerprint"])
        self.audit.append({**params, "outcome": "created"})
        return FakeJob(
            [{"outcome": "created", "customer_id": params["customer_id"], "matched_on": []}]
        )


def lock_conflict() -> api_exceptions.BadRequest:
    """The error BigQuery raises when a transaction loses the table lock."""
    return api_exceptions.BadRequest(LOCK_CONFLICT_MESSAGE)


def candidate_row(**overrides: Any) -> dict[str, Any]:
    """A row as `find_fuzzy_candidates.sql` returns it."""
    row = {
        "customer_id": "cand-1",
        "customer_type": "individual",
        "company_name": None,
        "normalized_name": "muller smith jane",
        "name_key": "jane muller smith",
        "normalized_address": "1 elm street springfield il 62701 us",
        "city": "Springfield",
        "postal_code_key": "62701",
        "country_code": "US",
        "email_domain": "example.test",
        "email_local_part": "j.muller",
    }
    row.update(overrides)
    return row


class FakeState(dict[str, Any]):
    """A dict that remembers which keys a tool wrote."""

    def __init__(self, initial: dict[str, Any]) -> None:
        super().__init__(initial)
        self.changes: dict[str, Any] = {}

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        self.changes[key] = value


class FakeToolContext:
    """Stands in for ADK's tool context: a `state` mapping and nothing else."""

    def __init__(self, state: dict[str, Any] | None = None) -> None:
        self.state = FakeState(state or {})


@dataclass
class FakeTurn:
    """What a runner script sees during one turn."""

    message: str
    context: FakeToolContext
    tools: dict[str, Any]

    async def call(self, tool_name: str, **arguments: Any) -> dict[str, Any]:
        """Call a tool the way ADK would, injecting the tool context."""
        result: dict[str, Any] = await self.tools[tool_name].func(
            tool_context=self.context, **arguments
        )
        return result


Script = Callable[[FakeTurn], Awaitable[AssistantTurn]]


class FakeRunner:
    """A runner that yields real ADK `Event` objects for a scripted turn."""

    def __init__(
        self,
        session_service: InMemorySessionService,
        tools: dict[str, Any],
        script: Script,
    ) -> None:
        self._sessions = session_service
        self._tools = tools
        self._script = script
        self.turns = 0

    async def run_async(
        self,
        *,
        user_id: str,
        session_id: str,
        new_message: types.Content,
        state_delta: dict[str, Any] | None = None,
    ) -> AsyncIterator[Event]:
        from app.agents.registration_agent import APP_NAME  # noqa: PLC0415

        self.turns += 1
        session = await self._sessions.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
        assert session is not None
        if state_delta:
            await self._sessions.append_event(
                session, Event(author="user", actions=EventActions(state_delta=state_delta))
            )
        session = await self._sessions.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
        assert session is not None
        text = "".join(part.text or "" for part in (new_message.parts or []))
        turn = FakeTurn(
            message=text, context=FakeToolContext(dict(session.state)), tools=self._tools
        )
        answer = await self._script(turn)
        if turn.context.state.changes:
            await self._sessions.append_event(
                session,
                Event(
                    author=AGENT_NAME,
                    actions=EventActions(state_delta=dict(turn.context.state.changes)),
                ),
            )
        yield Event(
            author=AGENT_NAME,
            content=types.Content(role="model", parts=[types.Part(text=answer.model_dump_json())]),
        )


def assistant_factory(
    primary_script: Script,
    *,
    fallback_script: Script | None = None,
    primary_model: str = "fake-primary",
    fallback_model: str = "fake-fallback",
) -> Callable[[Settings, AssistantServices, RequestGuard], RegistrationAssistant]:
    """Build a factory that wires a `RegistrationAssistant` around fake runners."""

    def factory(
        settings: Settings, services: AssistantServices, guard: RequestGuard
    ) -> RegistrationAssistant:
        sessions = InMemorySessionService()
        tools = {tool.name: tool for tool in build_tools(services)}
        fallback = (
            AgentRun(FakeRunner(sessions, tools, fallback_script), fallback_model)
            if fallback_script
            else None
        )
        return RegistrationAssistant(
            settings=settings,
            guard=guard,
            hasher=services.hasher,
            clock=services.clock,
            session_service=sessions,
            primary=AgentRun(FakeRunner(sessions, tools, primary_script), primary_model),
            fallback=fallback,
        )

    return factory


def seeded_rng() -> random.Random:
    """A deterministic jitter source."""
    return random.Random(7)  # noqa: S311
