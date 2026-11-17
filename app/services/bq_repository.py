"""BigQuery adapter for the customer repository.

Customer rows are written only by DML query jobs, never by streaming inserts, so the table
lock taken in `register_customer.sql` covers every write. Every request value travels as a
query parameter.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, cast

from google.api_core import exceptions as api_exceptions
from google.cloud import bigquery

from app.domain.customer import (
    AttemptAudit,
    AuditEvent,
    BlockingProbe,
    CandidateRow,
    CustomerRecord,
    MatchProbe,
    RegisterOutcome,
    RegisterResult,
)
from app.domain.errors import LockConflict
from app.services.sql_templates import render_template

QueryParameter = bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter

JOB_LABELS = {"app": "registration-api"}
ABSENT_TEXT = ""
ABSENT_NUMBER = -1.0
LOCK_CONFLICT_MARKERS = ("aborted due to concurrent update",)
REGISTER_OUTCOMES: frozenset[str] = frozenset(
    {"created", "replay", "fingerprint_mismatch", "duplicate"}
)


def _text(name: str, value: str | None) -> bigquery.ScalarQueryParameter:
    return bigquery.ScalarQueryParameter(
        name, "STRING", value if value is not None else ABSENT_TEXT
    )


def _integer(name: str, value: int) -> bigquery.ScalarQueryParameter:
    return bigquery.ScalarQueryParameter(name, "INT64", value)


def _flag(name: str, value: bool) -> bigquery.ScalarQueryParameter:
    return bigquery.ScalarQueryParameter(name, "BOOL", value)


def _number(name: str, value: float | None) -> bigquery.ScalarQueryParameter:
    return bigquery.ScalarQueryParameter(
        name, "FLOAT64", value if value is not None else ABSENT_NUMBER
    )


def _texts(name: str, values: Sequence[str]) -> bigquery.ArrayQueryParameter:
    return bigquery.ArrayQueryParameter(name, "STRING", list(values))


def audit_parameters(attempt: AttemptAudit) -> list[QueryParameter]:
    """Parameters for the audit columns that both the transaction and the standalone insert use."""
    return [
        _text("event_id", attempt.event_id),
        _text("request_id", attempt.request_id),
        _text("idempotency_key", attempt.idempotency_key),
        _text("request_fingerprint", attempt.request_fingerprint),
        _text("email_hash", attempt.email_hash),
        _text("client_hash", attempt.client_hash),
        _text("advisory_status", attempt.advisory_status),
        _text("typo_suggested_domain", attempt.typo_suggested_domain),
        _texts("fuzzy_candidate_ids", attempt.fuzzy_candidate_ids),
        _number("fuzzy_max_confidence", attempt.fuzzy_max_confidence),
        _text("advisory_model", attempt.advisory_model),
        _integer("lock_retries", attempt.lock_retries),
        _integer("latency_ms", attempt.latency_ms),
    ]


def register_parameters(record: CustomerRecord, attempt: AttemptAudit) -> list[QueryParameter]:
    """Every parameter `register_customer.sql` declares, and no others."""
    customer = record.customer
    address = customer.address
    return [
        *audit_parameters(attempt),
        _text("mx_status", record.mx_status),
        _text("source_channel", record.source_channel),
        _text("customer_id", record.customer_id),
        _text("customer_type", customer.customer_type),
        _text("given_name", customer.given_name),
        _text("family_name", customer.family_name),
        _text("company_name", customer.company_name),
        _text("normalized_name", customer.normalized_name),
        _text("name_key", customer.name_key),
        _text("email", customer.email),
        _text("email_as_entered", customer.email_as_entered),
        _text("email_local_part", customer.email_local_part),
        _text("email_domain", customer.email_domain),
        _text("phone_e164", customer.phone_e164),
        _text("tax_id_type", customer.tax_id_type),
        _text("tax_id_hash", record.tax_id_hash),
        _text("tax_id_last4", record.tax_id_last4),
        _text("hash_key_version", record.hash_key_version),
        _flag("has_address", address is not None),
        _text("address_line1", address.line1 if address else None),
        _text("address_line2", address.line2 if address else None),
        _text("address_city", address.city if address else None),
        _text("address_region", address.region if address else None),
        _text("address_postal_code", address.postal_code if address else None),
        _text("address_country_code", address.country_code if address else None),
        _text("normalized_address", customer.normalized_address),
    ]


def exact_match_parameters(probe: MatchProbe) -> list[QueryParameter]:
    """Parameters for `find_exact_matches.sql`."""
    return [
        _text("email", probe.email),
        _text("phone_e164", probe.phone_e164),
        _text("tax_id_hash", probe.tax_id_hash),
    ]


def fuzzy_parameters(probe: BlockingProbe, limit: int) -> list[QueryParameter]:
    """Parameters for `find_fuzzy_candidates.sql`."""
    return [
        _text("normalized_name", probe.normalized_name),
        _text("name_key", probe.name_key),
        _text("postal_code_key", probe.postal_code_key),
        _text("country_code", probe.country_code),
        _text("business_domain", probe.business_domain),
        _integer("max_rows", limit),
    ]


def event_parameters(event: AuditEvent) -> list[QueryParameter]:
    """Parameters for `insert_audit_event.sql`."""
    return [
        *audit_parameters(event.attempt),
        _text("channel", event.attempt.channel),
        _text("operation", event.operation),
        _text("outcome", event.outcome),
        _integer("http_status", event.http_status),
        _text("customer_id", event.customer_id),
        _text("mx_status", event.attempt.mx_status),
        _texts("matched_on", event.matched_on),
        _texts("problem_codes", event.problem_codes),
    ]


def _is_lock_conflict(error: api_exceptions.GoogleAPICallError) -> bool:
    haystack = [str(getattr(error, "message", "")), str(error)]
    haystack.extend(str(detail.get("message", "")) for detail in getattr(error, "errors", []) or [])
    return any(marker in text.lower() for text in haystack for marker in LOCK_CONFLICT_MARKERS)


class BigQueryCustomerRepository:
    """Customer repository backed by a BigQuery dataset.

    The client is synchronous, so every job runs in a worker thread with a per-job timeout.
    """

    def __init__(
        self,
        client: bigquery.Client,
        project: str,
        dataset: str,
        *,
        job_timeout_seconds: float = 30.0,
    ) -> None:
        self._client = client
        self._project = project
        self._dataset = dataset
        self._timeout = job_timeout_seconds
        self._sql = {
            name: render_template(name, project=project, dataset=dataset)
            for name in (
                "register_customer",
                "find_exact_matches",
                "find_fuzzy_candidates",
                "insert_audit_event",
            )
        }

    def _run_sync(
        self, operation: str, template: str, parameters: list[QueryParameter]
    ) -> list[Any]:
        config = bigquery.QueryJobConfig(
            query_parameters=parameters,
            labels={**JOB_LABELS, "operation": operation},
        )
        try:
            job = self._client.query(self._sql[template], job_config=config)
            return list(job.result(timeout=self._timeout))
        except api_exceptions.GoogleAPICallError as error:
            if _is_lock_conflict(error):
                raise LockConflict(
                    "The customers table is locked by another registration."
                ) from error
            raise

    async def _run(
        self, operation: str, template: str, parameters: list[QueryParameter]
    ) -> list[Any]:
        return await asyncio.to_thread(self._run_sync, operation, template, parameters)

    async def register(self, record: CustomerRecord, attempt: AttemptAudit) -> RegisterResult:
        """Run `register_customer.sql` and map its final row to a `RegisterResult`."""
        rows = await self._run(
            "register", "register_customer", register_parameters(record, attempt)
        )
        if len(rows) != 1:
            raise RuntimeError("The registration script returned no outcome row.")
        row = rows[0]
        outcome = str(row["outcome"])
        if outcome not in REGISTER_OUTCOMES:
            raise RuntimeError(f"The registration script returned an unknown outcome: {outcome}")
        customer_id = row["customer_id"]
        return RegisterResult(
            outcome=cast(RegisterOutcome, outcome),
            customer_id=str(customer_id) if customer_id else None,
            matched_on=tuple(row["matched_on"] or ()),
        )

    async def find_exact_matches(self, probe: MatchProbe) -> tuple[str, ...]:
        """Return the matching key names, sorted."""
        rows = await self._run(
            "find_exact_matches", "find_exact_matches", exact_match_parameters(probe)
        )
        return tuple(str(row["field"]) for row in rows)

    async def find_fuzzy_candidates(self, probe: BlockingProbe, limit: int) -> list[CandidateRow]:
        """Return blocked candidates for likely-duplicate scoring."""
        rows = await self._run(
            "find_fuzzy_candidates", "find_fuzzy_candidates", fuzzy_parameters(probe, limit)
        )
        return [
            CandidateRow(
                customer_id=str(row["customer_id"]),
                customer_type=str(row["customer_type"]),
                company_name=row["company_name"],
                normalized_name=str(row["normalized_name"]),
                name_key=str(row["name_key"]),
                normalized_address=row["normalized_address"],
                city=row["city"],
                postal_code_key=row["postal_code_key"] or None,
                country_code=row["country_code"],
                email_domain=str(row["email_domain"]),
                email_local_part=str(
                    row["email_local_part"],
                ),
            )
            for row in rows
        ]

    async def record_attempt(self, event: AuditEvent) -> None:
        """Append an audit row with a standalone parameterized INSERT."""
        await self._run("record_attempt", "insert_audit_event", event_parameters(event))

    async def check_ready(self) -> None:
        """Read the dataset's metadata to prove the store is reachable."""
        await asyncio.to_thread(
            self._client.get_dataset, f"{self._project}.{self._dataset}", timeout=self._timeout
        )
