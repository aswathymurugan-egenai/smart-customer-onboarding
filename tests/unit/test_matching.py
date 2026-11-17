"""Likely-duplicate pre-scoring and candidate selection."""

from __future__ import annotations

import pytest

from app.domain.customer import CandidateRow, NormalizedCustomer
from app.domain.matching import (
    ComparisonVector,
    MatchThresholds,
    ScoredCandidate,
    compare,
    select_for_review,
)


def applicant(**overrides: object) -> NormalizedCustomer:
    values: dict[str, object] = {
        "customer_type": "individual",
        "given_name": "Jane",
        "family_name": "Smith",
        "company_name": None,
        "normalized_name": "jane smith",
        "name_key": "jane smith",
        "email": "jane@example.com",
        "email_as_entered": "jane@example.com",
        "email_local_part": "jane",
        "email_domain": "example.com",
        "phone_e164": None,
        "tax_id_type": None,
        "tax_id": None,
        "address": None,
        "normalized_address": "1 elm street springfield 62701 us",
        "postal_code_key": "62701",
    }
    values.update(overrides)
    return NormalizedCustomer(**values)  # type: ignore[arg-type]


def candidate(**overrides: object) -> CandidateRow:
    values: dict[str, object] = {
        "customer_id": "c-1",
        "customer_type": "individual",
        "company_name": None,
        "normalized_name": "jane smith",
        "name_key": "jane smith",
        "normalized_address": "1 elm street springfield 62701 us",
        "city": "Springfield",
        "postal_code_key": "62701",
        "country_code": "US",
        "email_domain": "other.com",
        "email_local_part": "j.smith",
    }
    values.update(overrides)
    return CandidateRow(**values)  # type: ignore[arg-type]


def scored(vector: ComparisonVector) -> ScoredCandidate:
    return ScoredCandidate(candidate(), vector)


def vector(**overrides: object) -> ComparisonVector:
    values: dict[str, object] = {
        "name_similarity": 0.0,
        "address_similarity": 0.0,
        "same_postal_code": False,
        "same_business_domain": False,
        "local_part_similarity": 0.0,
    }
    values.update(overrides)
    return ComparisonVector(**values)  # type: ignore[arg-type]


def test_swapped_token_order_scores_as_an_identical_name() -> None:
    result = compare(
        applicant(normalized_name="smith jane"), candidate(), applicant_business_domain=None
    )

    assert result.name_similarity == 1.0


def test_a_shared_postal_code_and_close_address_are_reported() -> None:
    result = compare(applicant(), candidate(), applicant_business_domain=None)

    assert result.same_postal_code
    assert result.address_similarity >= 0.85


def test_a_shared_business_domain_needs_a_business_candidate() -> None:
    row = candidate(customer_type="business", email_domain="acme.com")

    shared = compare(applicant(), row, applicant_business_domain="acme.com")
    individual = compare(
        applicant(), candidate(email_domain="acme.com"), applicant_business_domain="acme.com"
    )

    assert shared.same_business_domain
    assert not individual.same_business_domain


def test_a_strong_name_match_alone_qualifies() -> None:
    assert select_for_review([scored(vector(name_similarity=0.80))], MatchThresholds())


def test_a_middling_name_needs_a_second_signal() -> None:
    weak = scored(vector(name_similarity=0.65))
    with_postal = scored(vector(name_similarity=0.65, same_postal_code=True))
    with_address = scored(vector(name_similarity=0.65, address_similarity=0.9))

    assert select_for_review([weak], MatchThresholds()) == []
    assert select_for_review([with_postal], MatchThresholds()) == [with_postal]
    assert select_for_review([with_address], MatchThresholds()) == [with_address]


def test_a_name_below_the_floor_never_qualifies_even_with_every_signal() -> None:
    item = scored(vector(name_similarity=0.5, same_postal_code=True, same_business_domain=True))

    assert select_for_review([item], MatchThresholds()) == []


def test_at_most_five_candidates_go_forward_best_name_first() -> None:
    items = [scored(vector(name_similarity=0.80 + i * 0.01)) for i in range(8)]

    selected = select_for_review(items, MatchThresholds())

    assert len(selected) == 5
    similarities = [item.vector.name_similarity for item in selected]
    assert similarities == sorted(similarities, reverse=True)
    assert similarities[0] == pytest.approx(0.87)
