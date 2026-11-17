"""The BigQuery repository against a client double built with `create_autospec`."""

from __future__ import annotations

import pytest
from google.api_core import exceptions as api_exceptions

from app.domain.customer import AuditEvent, BlockingProbe, MatchProbe
from app.domain.errors import LockConflict
from app.services.bq_repository import BigQueryCustomerRepository
from tests.builders import make_attempt, make_record
from tests.fakes import FakeBigQuery, lock_conflict

PROJECT = "test-project-1"
DATASET = "customer_ops"


def repository(bq: FakeBigQuery) -> BigQueryCustomerRepository:
    return BigQueryCustomerRepository(bq.client, PROJECT, DATASET)


async def test_a_hostile_given_name_travels_as_a_parameter_and_never_in_the_sql_text() -> None:
    bq = FakeBigQuery()
    hostile = "'; DROP TABLE customers; --"

    await repository(bq).register(make_record(given_name=hostile), make_attempt())

    call = bq.calls[-1]
    assert call.params["given_name"] == hostile
    assert "DROP TABLE" not in call.sql
    assert hostile not in call.sql


async def test_absent_optional_values_become_empty_strings_and_a_negative_sentinel() -> None:
    bq = FakeBigQuery()
    record = make_record(
        family_name=None, phone_e164=None, tax_id=None, tax_id_type=None, address=None
    )

    await repository(bq).register(record, make_attempt())

    params = bq.calls[-1].params
    for name in ("family_name", "company_name", "phone_e164", "tax_id_hash", "address_line1"):
        assert params[name] == ""
    assert params["has_address"] is False
    assert params["fuzzy_max_confidence"] == -1.0
    assert params["fuzzy_candidate_ids"] == []


async def test_jobs_are_labeled_with_the_app_and_the_operation() -> None:
    bq = FakeBigQuery()

    await repository(bq).register(make_record(), make_attempt())
    await repository(bq).find_exact_matches(MatchProbe("a@b.co", None, None))

    assert [call.labels for call in bq.calls] == [
        {"app": "registration-api", "operation": "register"},
        {"app": "registration-api", "operation": "find_exact_matches"},
    ]


async def test_the_concurrent_update_abort_raises_lock_conflict() -> None:
    bq = FakeBigQuery(register_faults=[lock_conflict()])

    with pytest.raises(LockConflict):
        await repository(bq).register(make_record(), make_attempt())


async def test_other_bigquery_errors_pass_through_unchanged() -> None:
    bq = FakeBigQuery(register_faults=[api_exceptions.Forbidden("no access")])

    with pytest.raises(api_exceptions.Forbidden):
        await repository(bq).register(make_record(), make_attempt())


async def test_result_rows_map_to_the_four_outcomes() -> None:
    bq = FakeBigQuery()
    repo = repository(bq)

    created = await repo.register(make_record("c1"), make_attempt(idempotency_key="k1"))
    replay = await repo.register(make_record("c2"), make_attempt(idempotency_key="k1"))
    mismatch = await repo.register(
        make_record("c3"), make_attempt(idempotency_key="k1", request_fingerprint="other")
    )
    duplicate = await repo.register(make_record("c4"), make_attempt())

    assert (created.outcome, created.customer_id) == ("created", "c1")
    assert (replay.outcome, replay.customer_id) == ("replay", "c1")
    assert mismatch.outcome == "fingerprint_mismatch"
    assert (duplicate.outcome, duplicate.matched_on) == ("duplicate", ("email", "phone", "tax_id"))


async def test_an_unknown_outcome_from_the_script_is_an_error() -> None:
    bq = FakeBigQuery()
    bq.client.query.side_effect = lambda *a, **k: type(
        "J",
        (),
        {
            "result": lambda self, timeout=None: [
                {"outcome": "weird", "customer_id": None, "matched_on": []}
            ]
        },
    )()

    with pytest.raises(RuntimeError):
        await repository(bq).register(make_record(), make_attempt())


async def test_no_method_uses_a_streaming_insert() -> None:
    bq = FakeBigQuery()
    repo = repository(bq)

    await repo.register(make_record(), make_attempt())
    await repo.record_attempt(AuditEvent(make_attempt(), "register", "duplicate", 409))
    await repo.find_fuzzy_candidates(BlockingProbe("jane", "jane", None, None, None), 50)

    bq.client.insert_rows_json.assert_not_called()
    bq.client.insert_rows.assert_not_called()


async def test_readiness_reads_the_dataset_metadata() -> None:
    bq = FakeBigQuery()

    await repository(bq).check_ready()

    bq.client.get_dataset.assert_called_once()
    assert bq.client.get_dataset.call_args.args[0] == f"{PROJECT}.{DATASET}"


async def test_audit_events_carry_array_parameters_and_no_raw_personal_values() -> None:
    bq = FakeBigQuery()
    event = AuditEvent(
        make_attempt(),
        "register",
        "duplicate",
        409,
        matched_on=("email",),
        problem_codes=("customer-duplicate",),
    )

    await repository(bq).record_attempt(event)

    params = bq.calls[-1].params
    assert params["matched_on"] == ["email"]
    assert params["problem_codes"] == ["customer-duplicate"]
    assert params["http_status"] == 409
    assert "jane.doe" not in str(params)
