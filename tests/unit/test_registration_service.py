"""The registration flow: retries, outcomes, audit rows, advice, and abuse controls."""

from __future__ import annotations

import asyncio

import pytest

from app.domain.customer import RegisterResult
from app.domain.errors import (
    AdvisorFailure,
    BotCheckFailed,
    DuplicateCustomer,
    EmailDisposable,
    EmailInvalid,
    IdempotencyKeyReused,
    LockConflict,
    PhoneInvalid,
    RateLimited,
    RegistrationBusy,
)
from app.models.advice import TypoAdvice
from app.services.advisor import DisabledAdvisor
from app.services.rate_limit import SlidingWindowRateLimiter
from tests.builders import make_attempt, make_record
from tests.conftest import make_settings
from tests.fakes import FakeClock
from tests.support import Graph, customer_input, make_graph


class ConflictingRepository:
    """Raises `LockConflict` a set number of times, then delegates to a real store."""

    def __init__(self, inner: object, conflicts: int) -> None:
        self._inner = inner
        self.conflicts = conflicts
        self.attempts: list[int] = []

    async def register(self, record: object, attempt: object) -> RegisterResult:
        self.attempts.append(attempt.lock_retries)  # type: ignore[attr-defined]
        if self.conflicts > 0:
            self.conflicts -= 1
            raise LockConflict
        return await self._inner.register(record, attempt)  # type: ignore[attr-defined]

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


def graph_with_conflicts(conflicts: int, **settings: object) -> tuple[Graph, ConflictingRepository]:
    base = make_graph()
    wrapper = ConflictingRepository(base.repository, conflicts)
    graph = make_graph(repository=wrapper, **settings)
    return graph, wrapper


async def test_two_lock_conflicts_then_success_registers_with_two_retries_recorded() -> None:
    graph, repo = graph_with_conflicts(2)

    outcome = await graph.registration.register(customer_input(), graph.ctx(), None)

    assert not outcome.replayed
    assert repo.attempts == [0, 1, 2]
    assert len(graph.clock.sleeps) == 2


async def test_backoff_delays_are_jittered_within_a_doubling_ceiling() -> None:
    graph, _ = graph_with_conflicts(3)

    await graph.registration.register(customer_input(), graph.ctx(), None)

    first, second, third = graph.clock.sleeps
    assert 0 <= first <= 0.5
    assert 0 <= second <= 1.0
    assert 0 <= third <= 2.0


async def test_conflicts_past_the_retry_limit_raise_registration_busy_with_retry_after() -> None:
    graph, repo = graph_with_conflicts(99)

    with pytest.raises(RegistrationBusy) as busy:
        await graph.registration.register(customer_input(), graph.ctx(), None)

    assert busy.value.retry_after == 60
    assert busy.value.lock_retries == 3
    assert len(repo.attempts) == 4
    assert [event.outcome for event in graph.repository.audit_events] == ["busy"]
    assert graph.repository.audit_events[0].attempt.lock_retries == 3


async def test_conflicts_past_the_time_budget_stop_retrying_early() -> None:
    graph, repo = graph_with_conflicts(
        99, lock_retry_budget_seconds=1.0, lock_retry_base_seconds=1000
    )

    with pytest.raises(RegistrationBusy):
        await graph.registration.register(customer_input(), graph.ctx(), None)

    assert len(repo.attempts) == 2
    assert graph.clock.sleeps == [1.0]


async def test_a_created_registration_stores_a_keyed_tax_id_hash_and_writes_no_audit_event() -> (
    None
):
    graph = make_graph()

    outcome = await graph.registration.register(customer_input(), graph.ctx(), None)

    [stored] = graph.repository.customers
    assert stored.customer_id == outcome.customer_id
    assert stored.tax_id_hash
    assert stored.tax_id_hash != "123456789"
    assert len(stored.tax_id_hash) == 64
    assert stored.tax_id_last4 == "6789"
    assert graph.repository.audit_events == ()


async def test_the_register_outcomes_map_to_a_result_or_a_typed_error() -> None:
    graph = make_graph()
    key = "6f1c1bde-3a64-4f2c-9a54-52f7a2d0a111"
    created = await graph.registration.register(customer_input(), graph.ctx(), key)

    replay = await graph.registration.register(customer_input(), graph.ctx(), key)
    with pytest.raises(IdempotencyKeyReused):
        await graph.registration.register(customer_input(given_name="Janet"), graph.ctx(), key)
    with pytest.raises(DuplicateCustomer) as duplicate:
        await graph.registration.register(customer_input(), graph.ctx(), None)

    assert not created.replayed
    assert replay.replayed
    assert replay.customer_id == created.customer_id
    assert replay.warnings == []
    assert duplicate.value.matched_on == ("email", "phone", "tax_id")


async def test_each_non_created_outcome_writes_exactly_one_audit_row() -> None:
    graph = make_graph(rate_register_limit=50)
    key = "6f1c1bde-3a64-4f2c-9a54-52f7a2d0a111"
    await graph.registration.register(customer_input(), graph.ctx(), key)
    failures = [
        (customer_input(given_name="Janet"), key, IdempotencyKeyReused),
        (customer_input(), None, DuplicateCustomer),
        (customer_input(email="x@mailinator.test"), None, EmailDisposable),
        (
            customer_input(email="bad", phone=None, tax_id=None, tax_id_type=None),
            None,
            EmailInvalid,
        ),
        (customer_input(email="y@example.test", phone="12"), None, PhoneInvalid),
        (customer_input(bot_token="wrong"), None, BotCheckFailed),
    ]

    await graph.registration.register(customer_input(), graph.ctx(), key)
    for request, idempotency_key, error_type in failures:
        before = len(graph.repository.audit_events)
        with pytest.raises(error_type):
            await graph.registration.register(request, graph.ctx(), idempotency_key)
        assert len(graph.repository.audit_events) == before + 1

    events = graph.repository.audit_events
    assert [event.outcome for event in events] == [
        "replay",
        "invalid_input",
        "duplicate",
        "invalid_email",
        "invalid_email",
        "invalid_input",
        "bot_check_failed",
    ]
    assert [event.http_status for event in events] == [201, 422, 409, 422, 422, 422, 403]


async def test_invalid_input_errors_carry_their_field_and_problem_code_into_the_audit_row() -> None:
    graph = make_graph()

    with pytest.raises(PhoneInvalid):
        await graph.registration.register(customer_input(phone="12"), graph.ctx(), None)
    with pytest.raises(EmailDisposable):
        await graph.registration.register(
            customer_input(email="a@mailinator.test"), graph.ctx(), None
        )

    codes = [event.problem_codes for event in graph.repository.audit_events]
    assert codes == [("phone-invalid",), ("email-disposable",)]
    assert all(event.attempt.email_hash for event in graph.repository.audit_events)


async def test_audit_rows_hold_hashes_and_never_raw_personal_values() -> None:
    graph = make_graph()

    with pytest.raises(EmailDisposable):
        await graph.registration.register(
            customer_input(email="zeph.unique@mailinator.test"),
            graph.ctx(client="198.51.100.9"),
            None,
        )

    text = repr(graph.repository.audit_events)
    for raw in ("zeph.unique", "198.51.100.9", "mailinator"):
        assert raw not in text


async def test_an_advisor_failure_registers_without_warnings_and_marks_the_advice_unavailable() -> (
    None
):
    graph = make_graph()
    graph.advisor.fail_typo = AdvisorFailure("unavailable")

    outcome = await graph.registration.register(
        customer_input(email="jane@acme-cop.test"), graph.ctx(), None
    )

    assert outcome.advisory_status == "unavailable"
    assert outcome.warnings == []
    assert len(graph.repository.customers) == 1


async def test_an_advisory_timeout_keeps_the_rule_suggestion_and_still_registers() -> None:
    class SlowAdvisor:
        enabled = True
        model_name = "slow"

        async def suggest_domain(self, domain: str) -> TypoAdvice:
            await asyncio.sleep(1)
            raise AssertionError("unreachable")

        async def assess_candidates(self, *args: object) -> object:
            await asyncio.sleep(1)
            raise AssertionError("unreachable")

    graph = make_graph(advisor=SlowAdvisor(), advisory_budget_seconds=0.05)
    await graph.registration.register(customer_input(email="first@example.test"), graph.ctx(), None)

    outcome = await graph.registration.register(
        customer_input(email="jane@gmial.com", phone=None, tax_id=None, tax_id_type=None),
        graph.ctx(),
        None,
    )

    assert outcome.advisory_status == "unavailable"
    assert [warning.code for warning in outcome.warnings] == ["possible_typo"]


async def test_a_disabled_advisor_still_returns_rule_based_typo_warnings() -> None:
    graph = make_graph(advisor=DisabledAdvisor())

    outcome = await graph.registration.register(
        customer_input(email="jane@gmial.com"), graph.ctx(), None
    )

    assert outcome.advisory_status == "disabled"
    assert outcome.warnings[0].code == "possible_typo"  # type: ignore[union-attr]


async def test_the_assistant_channel_skips_the_bot_check_but_not_the_rate_limit() -> None:
    graph = make_graph(rate_register_limit=1)
    ctx = graph.ctx(channel="assistant")

    await graph.registration.register(customer_input(bot_token=""), ctx, None)
    with pytest.raises(RateLimited):
        await graph.registration.register(
            customer_input(
                email="b@example.test", phone=None, tax_id=None, tax_id_type=None, bot_token=""
            ),
            ctx,
            None,
        )
    assert graph.repository.customers[0].source_channel == "assistant"


async def test_the_rate_limit_is_checked_before_the_bot_check() -> None:
    graph = make_graph(rate_register_limit=1)
    ctx = graph.ctx()
    await graph.registration.register(
        customer_input(email="a@example.test", phone=None, tax_id=None, tax_id_type=None), ctx, None
    )
    with pytest.raises(RateLimited):
        await graph.registration.register(customer_input(bot_token="wrong"), ctx, None)


async def test_a_wrong_bot_token_is_refused() -> None:
    graph = make_graph()

    with pytest.raises(BotCheckFailed):
        await graph.registration.register(customer_input(bot_token="nope"), graph.ctx(), None)


def test_the_sliding_window_resets_after_its_interval() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(
        make_settings(rate_register_limit=2, rate_register_window_seconds=60), clock
    )
    limiter.check("a", "register")
    limiter.check("a", "register")

    with pytest.raises(RateLimited) as limited:
        limiter.check("a", "register")
    limiter.check("b", "register")
    clock.advance(61)
    limiter.check("a", "register")

    assert limited.value.retry_after == 60


def test_the_retry_after_value_counts_down_with_the_window() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(
        make_settings(rate_register_limit=1, rate_register_window_seconds=60), clock
    )
    limiter.check("a", "register")
    clock.advance(45)

    with pytest.raises(RateLimited) as limited:
        limiter.check("a", "register")

    assert limited.value.retry_after == 15


def test_make_record_helper_is_consistent_with_the_attempt_helper() -> None:
    assert make_record().customer.email == "jane.doe@example.test"
    assert make_attempt().channel == "form"
