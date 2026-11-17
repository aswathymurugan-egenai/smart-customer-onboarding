"""Builders for domain objects with fictional values."""

from __future__ import annotations

from typing import Any

from app.domain.customer import (
    Address,
    AttemptAudit,
    CustomerRecord,
    NormalizedCustomer,
)


def make_customer(**overrides: Any) -> NormalizedCustomer:
    """A normalized individual customer."""
    values: dict[str, Any] = {
        "customer_type": "individual",
        "given_name": "Jane",
        "family_name": "Doe",
        "company_name": None,
        "normalized_name": "jane doe",
        "name_key": "doe jane",
        "email": "jane.doe@example.test",
        "email_as_entered": "Jane.Doe@Example.TEST",
        "email_local_part": "jane.doe",
        "email_domain": "example.test",
        "phone_e164": "+14155550100",
        "tax_id_type": "us_ein",
        "tax_id": "123456789",
        "address": Address(
            line1="100 Example Street",
            city="Springfield",
            country_code="US",
            region="IL",
            postal_code="62701",
        ),
        "normalized_address": "100 example street springfield il 62701 us",
        "postal_code_key": "62701",
    }
    values.update(overrides)
    return NormalizedCustomer(**values)


def make_attempt(**overrides: Any) -> AttemptAudit:
    """Audit columns for one attempt."""
    values: dict[str, Any] = {
        "event_id": "event-1",
        "request_id": "request-1",
        "idempotency_key": None,
        "request_fingerprint": "fingerprint-1",
        "channel": "form",
        "email_hash": "email-hash",
        "client_hash": "client-hash",
        "mx_status": "pass",
        "advisory_status": "ok",
        "typo_suggested_domain": None,
        "fuzzy_candidate_ids": (),
        "fuzzy_max_confidence": None,
        "advisory_model": None,
        "lock_retries": 0,
        "latency_ms": 12,
    }
    values.update(overrides)
    return AttemptAudit(**values)


def make_record(customer_id: str = "customer-1", **customer_overrides: Any) -> CustomerRecord:
    """A record ready for a repository, with a tax-ID hash when the customer has a tax ID."""
    customer = make_customer(**customer_overrides)
    return CustomerRecord(
        customer_id=customer_id,
        customer=customer,
        mx_status="pass",
        tax_id_hash=f"hash-of-{customer.tax_id}" if customer.tax_id else None,
        tax_id_last4=customer.tax_id[-4:] if customer.tax_id else None,
        hash_key_version="v1",
        source_channel="form",
    )
