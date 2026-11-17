"""The in-memory repository mirrors the transaction's rules."""

from __future__ import annotations

import asyncio

from app.domain.customer import BlockingProbe, MatchProbe
from app.services.memory_repository import IDEMPOTENCY_WINDOW, InMemoryCustomerRepository
from tests.builders import make_attempt, make_record
from tests.fakes import FakeClock


def repository() -> tuple[InMemoryCustomerRepository, FakeClock]:
    clock = FakeClock()
    return InMemoryCustomerRepository(clock), clock


async def test_twenty_concurrent_registrations_of_one_email_create_exactly_one() -> None:
    repo, _ = repository()

    results = await asyncio.gather(
        *(
            repo.register(
                make_record(f"c{n}", phone_e164=None, tax_id=None, tax_id_type=None),
                make_attempt(),
            )
            for n in range(20)
        )
    )

    outcomes = [result.outcome for result in results]
    assert outcomes.count("created") == 1
    assert outcomes.count("duplicate") == 19
    assert len(repo.customers) == 1


async def test_a_shared_phone_or_tax_id_is_a_duplicate_naming_each_key() -> None:
    repo, _ = repository()
    await repo.register(make_record("c1"), make_attempt())

    result = await repo.register(make_record("c2", email="other@example.test"), make_attempt())

    assert result.outcome == "duplicate"
    assert result.matched_on == ("phone", "tax_id")


async def test_a_replay_returns_the_original_customer_within_the_window() -> None:
    repo, clock = repository()
    await repo.register(make_record("c1"), make_attempt(idempotency_key="k"))

    replay = await repo.register(make_record("c2"), make_attempt(idempotency_key="k"))
    clock.advance(IDEMPOTENCY_WINDOW.total_seconds() + 1)
    expired = await repo.register(
        make_record("c3", email="third@example.test", phone_e164=None, tax_id=None),
        make_attempt(idempotency_key="k"),
    )

    assert (replay.outcome, replay.customer_id) == ("replay", "c1")
    assert expired.outcome == "created"


async def test_a_reused_key_with_a_different_fingerprint_is_reported() -> None:
    repo, _ = repository()
    await repo.register(make_record("c1"), make_attempt(idempotency_key="k"))

    result = await repo.register(
        make_record("c2"), make_attempt(idempotency_key="k", request_fingerprint="different")
    )

    assert result.outcome == "fingerprint_mismatch"


async def test_exact_matches_name_each_key() -> None:
    repo, _ = repository()
    await repo.register(make_record("c1"), make_attempt())

    found = await repo.find_exact_matches(MatchProbe("jane.doe@example.test", "+14155550100", None))

    assert found == ("email", "phone")


async def test_blocking_returns_customers_sharing_a_name_or_postal_code() -> None:
    repo, _ = repository()
    await repo.register(make_record("c1"), make_attempt())
    await repo.register(
        make_record(
            "c2",
            email="x@example.test",
            phone_e164=None,
            tax_id=None,
            tax_id_type=None,
            normalized_name="zed",
            name_key="zed",
        ),
        make_attempt(),
    )

    by_name = await repo.find_fuzzy_candidates(
        BlockingProbe("jane doe", "doe jane", None, None, None), 50
    )
    by_postal = await repo.find_fuzzy_candidates(
        BlockingProbe("nobody", "nobody", "62701", "US", None), 50
    )
    none = await repo.find_fuzzy_candidates(
        BlockingProbe("nobody", "nobody", "99999", "US", None), 50
    )

    assert [row.customer_id for row in by_name] == ["c1"]
    assert {row.customer_id for row in by_postal} == {"c1", "c2"}
    assert none == []


async def test_blocking_respects_the_row_limit() -> None:
    repo, _ = repository()
    for n in range(5):
        await repo.register(
            make_record(
                f"c{n}", email=f"u{n}@example.test", phone_e164=None, tax_id=None, tax_id_type=None
            ),
            make_attempt(),
        )

    rows = await repo.find_fuzzy_candidates(BlockingProbe("x", "x", "62701", "US", None), 3)

    assert len(rows) == 3
