"""Proves the registration transaction's behavior against real BigQuery.

The offline suite cannot show that the table lock closes the insert-only MERGE race. These
tests run it, record the abort's error reason, and measure retry timing and latency.
"""

from __future__ import annotations

import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from google.api_core import exceptions as api_exceptions
from google.cloud import bigquery

from app.services.bq_repository import register_parameters
from app.services.sql_templates import render_template
from scripts.apply_schema import apply_schema
from tests.builders import make_attempt, make_record

TRIALS = 20
CONCURRENCY = 5
LATENCY_RUNS = 30
MAX_RETRY_FAILURE_RATE = 0.05
RETRY_WINDOW_SECONDS = 10.0
LOCK_STATEMENT = "DELETE FROM `{project}.{dataset}.customers` WHERE FALSE;"


def unique_record(email: str, *, suffix: str) -> Any:
    return make_record(
        f"id-{suffix}-{uuid.uuid4().hex[:8]}",
        email=email,
        phone_e164=None,
        tax_id=None,
        tax_id_type=None,
    )


def run_script(
    client: bigquery.Client, sql: str, record: Any, attempt_suffix: str
) -> tuple[list[Any], Exception | None, float]:
    """Run one registration script and return its rows, any error, and the elapsed seconds."""
    attempt = make_attempt(event_id=f"event-{attempt_suffix}-{uuid.uuid4().hex[:8]}")
    config = bigquery.QueryJobConfig(query_parameters=register_parameters(record, attempt))
    started = time.monotonic()
    try:
        rows = list(client.query(sql, job_config=config).result())
        return rows, None, time.monotonic() - started
    except api_exceptions.GoogleAPICallError as error:
        return [], error, time.monotonic() - started


def count_rows(client: bigquery.Client, project: str, dataset: str, email: str) -> int:
    sql = f"SELECT COUNT(*) AS n FROM `{project}.{dataset}.customers` WHERE email = @email"
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("email", "STRING", email)]
    )
    return int(next(iter(client.query(sql, job_config=config).result()))["n"])


def error_summary(error: Exception) -> dict[str, Any]:
    return {
        "type": type(error).__name__,
        "reasons": [item.get("reason") for item in getattr(error, "errors", []) or []],
        "message": str(getattr(error, "message", error))[:240],
    }


def race(
    client: bigquery.Client, project: str, dataset: str, sql: str, label: str
) -> dict[str, Any]:
    """Run TRIALS rounds of CONCURRENCY simultaneous registrations for one new email each."""
    inserted_once = 0
    duplicated = 0
    aborts: list[dict[str, Any]] = []
    for trial in range(TRIALS):
        email = f"{label}-{trial}-{uuid.uuid4().hex[:6]}@example.test"
        with ThreadPoolExecutor(CONCURRENCY) as pool:
            futures = [
                pool.submit(run_script, client, sql, unique_record(email, suffix=label), label)
                for _ in range(CONCURRENCY)
            ]
            results = [future.result() for future in futures]
        aborts.extend(error_summary(error) for _, error, _ in results if error is not None)
        rows = count_rows(client, project, dataset, email)
        inserted_once += rows == 1
        duplicated += rows > 1
    return {
        "trials": TRIALS,
        "inserted_exactly_once": inserted_once,
        "trials_with_duplicates": duplicated,
        "aborts": len(aborts),
        "abort_samples": aborts[:3],
    }


def test_the_ddl_applies_with_daily_partitioning_and_clustering_and_a_rerun_changes_nothing(
    client: bigquery.Client, project: str, dataset: str, location: str
) -> None:
    first = client.get_table(f"{project}.{dataset}.customers")
    tables_before = sorted(t.table_id for t in client.list_tables(f"{project}.{dataset}"))

    tables_after = apply_schema(client, project, dataset, location)

    assert first.time_partitioning is not None
    assert first.time_partitioning.field == "created_at"
    assert first.clustering_fields == ["email", "normalized_name"]
    assert tables_after == tables_before == ["customers", "registration_audit_logs"]


def test_with_the_lock_every_trial_inserts_exactly_once_and_no_key_is_duplicated(
    client: bigquery.Client, project: str, dataset: str, findings: dict[str, Any]
) -> None:
    sql = render_template("register_customer", project=project, dataset=dataset)

    result = race(client, project, dataset, sql, "locked")
    checks = list(
        client.query(
            render_template("checks/duplicate_keys", project=project, dataset=dataset)
        ).result()
    )

    findings["with_lock"] = result
    assert result["inserted_exactly_once"] == TRIALS
    assert checks == []


def test_without_the_lock_records_whether_concurrent_merges_insert_duplicates(
    client: bigquery.Client, project: str, dataset: str, findings: dict[str, Any]
) -> None:
    sql = render_template("register_customer", project=project, dataset=dataset)
    lock = LOCK_STATEMENT.format(project=project, dataset=dataset)
    assert lock in sql
    unlocked = sql.replace(lock, "")

    findings["without_lock"] = race(client, project, dataset, unlocked, "unlocked")


def test_a_retry_after_an_abort_succeeds_or_sees_the_duplicate_within_ten_seconds(
    client: bigquery.Client, project: str, dataset: str, findings: dict[str, Any]
) -> None:
    sql = render_template("register_customer", project=project, dataset=dataset)
    failures = 0
    waits: list[float] = []
    for trial in range(TRIALS):
        email = f"retry-{trial}-{uuid.uuid4().hex[:6]}@example.test"
        with ThreadPoolExecutor(CONCURRENCY) as pool:
            futures = [
                pool.submit(run_script, client, sql, unique_record(email, suffix="retry"), "r")
                for _ in range(CONCURRENCY)
            ]
            results = [future.result() for future in futures]
        for _, error, _ in results:
            if error is None:
                continue
            started = time.monotonic()
            while True:
                rows, retry_error, _ = run_script(
                    client, sql, unique_record(email, suffix="retry"), "r2"
                )
                if retry_error is None:
                    waits.append(time.monotonic() - started)
                    assert rows[0]["outcome"] in {"created", "duplicate"}
                    break
                if time.monotonic() - started > RETRY_WINDOW_SECONDS:
                    failures += 1
                    break
                time.sleep(0.5)
    attempts = failures + len(waits)
    findings["retry_timing"] = {
        "retried_calls": attempts,
        "failed_within_window": failures,
        "median_wait_seconds": statistics.median(waits) if waits else None,
        "max_wait_seconds": max(waits) if waits else None,
    }
    assert attempts == 0 or failures / attempts <= MAX_RETRY_FAILURE_RATE


def test_the_script_reports_created_and_duplicate_through_its_final_select(
    client: bigquery.Client, project: str, dataset: str
) -> None:
    sql = render_template("register_customer", project=project, dataset=dataset)
    email = f"shape-{uuid.uuid4().hex[:8]}@example.test"
    record = unique_record(email, suffix="shape")

    created, error, _ = run_script(client, sql, record, "s1")
    assert error is None
    duplicate, error, _ = run_script(client, sql, unique_record(email, suffix="shape"), "s2")
    assert error is None

    assert [row["outcome"] for row in created] == ["created"]
    assert created[0]["customer_id"] == record.customer_id
    assert [row["outcome"] for row in duplicate] == ["duplicate"]
    assert list(duplicate[0]["matched_on"]) == ["email"]
    assert count_rows(client, project, dataset, email) == 1


def test_register_latency_percentiles_over_thirty_runs(
    client: bigquery.Client, project: str, dataset: str, findings: dict[str, Any]
) -> None:
    sql = render_template("register_customer", project=project, dataset=dataset)
    durations: list[float] = []
    for _ in range(LATENCY_RUNS):
        email = f"latency-{uuid.uuid4().hex[:10]}@example.test"
        _, error, elapsed = run_script(client, sql, unique_record(email, suffix="lat"), "l")
        assert error is None
        durations.append(elapsed)
    ordered = sorted(durations)
    findings["latency_seconds"] = {
        "p50": statistics.median(ordered),
        "p95": ordered[int(0.95 * (len(ordered) - 1))],
    }
