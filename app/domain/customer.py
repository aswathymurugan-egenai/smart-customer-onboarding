"""Immutable value objects shared by the services and the repositories.

Nothing here imports a web framework, a database client, or a wire model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CustomerType = Literal["individual", "business"]
MxStatus = Literal["pass", "unknown"]
AdvisoryStatus = Literal["ok", "unavailable", "disabled"]
RegisterOutcome = Literal["created", "replay", "fingerprint_mismatch", "duplicate"]
Channel = Literal["form", "assistant", "api"]
MatchField = Literal["email", "phone", "tax_id"]


@dataclass(frozen=True, slots=True)
class Address:
    """A postal address as the person entered it."""

    line1: str
    city: str
    country_code: str
    line2: str | None = None
    region: str | None = None
    postal_code: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedCustomer:
    """A customer whose values are in canonical form and ready to match or store.

    `tax_id` holds the normalized raw value in memory only. Repositories receive the keyed
    hash and the last four characters instead.
    """

    customer_type: CustomerType
    given_name: str
    family_name: str | None
    company_name: str | None
    normalized_name: str
    name_key: str
    email: str
    email_as_entered: str
    email_local_part: str
    email_domain: str
    phone_e164: str | None
    tax_id_type: str | None
    tax_id: str | None
    address: Address | None
    normalized_address: str | None
    postal_code_key: str | None


@dataclass(frozen=True, slots=True)
class CustomerRecord:
    """The row `register_customer.sql` writes. It carries no raw tax ID."""

    customer_id: str
    customer: NormalizedCustomer
    mx_status: MxStatus
    tax_id_hash: str | None
    tax_id_last4: str | None
    hash_key_version: str
    source_channel: Channel


@dataclass(frozen=True, slots=True)
class AttemptAudit:
    """The audit columns shared by the transactional insert and the standalone insert."""

    event_id: str
    request_id: str
    idempotency_key: str | None
    request_fingerprint: str | None
    channel: Channel
    email_hash: str | None
    client_hash: str
    mx_status: str | None
    advisory_status: str | None
    typo_suggested_domain: str | None
    fuzzy_candidate_ids: tuple[str, ...]
    fuzzy_max_confidence: float | None
    advisory_model: str | None
    lock_retries: int
    latency_ms: int


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One append-only audit row for an attempt that did not create a customer."""

    attempt: AttemptAudit
    operation: Literal["register", "check_duplicate"]
    outcome: str
    http_status: int
    customer_id: str | None = None
    matched_on: tuple[str, ...] = field(default_factory=tuple)
    problem_codes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RegisterResult:
    """What one registration transaction reported."""

    outcome: RegisterOutcome
    customer_id: str | None
    matched_on: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class MatchProbe:
    """The keys an exact-match lookup compares."""

    email: str
    phone_e164: str | None
    tax_id_hash: str | None


@dataclass(frozen=True, slots=True)
class BlockingProbe:
    """The keys the fuzzy blocking query compares."""

    normalized_name: str
    name_key: str
    postal_code_key: str | None
    country_code: str | None
    business_domain: str | None


@dataclass(frozen=True, slots=True)
class CandidateRow:
    """An existing customer returned by blocking, with the fields scoring needs.

    The customer id, the email local part, and the phone never leave the process in a model
    prompt.
    """

    customer_id: str
    customer_type: str
    company_name: str | None
    normalized_name: str
    name_key: str
    normalized_address: str | None
    city: str | None
    postal_code_key: str | None
    country_code: str | None
    email_domain: str
    email_local_part: str
