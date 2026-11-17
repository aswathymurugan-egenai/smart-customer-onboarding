"""Likely-duplicate pre-scoring: compare an applicant with blocked candidates.

The thresholds arrive as arguments. They are uncalibrated defaults until labeled duplicate
pairs exist, and the model never sees a candidate this module did not select.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from rapidfuzz import fuzz

from app.domain.customer import CandidateRow, NormalizedCustomer


@dataclass(frozen=True, slots=True)
class ComparisonVector:
    """How closely one candidate resembles the applicant, on each signal."""

    name_similarity: float
    address_similarity: float
    same_postal_code: bool
    same_business_domain: bool
    local_part_similarity: float


@dataclass(frozen=True, slots=True)
class MatchThresholds:
    """Cut-offs for sending a candidate to the model."""

    name_floor: float = 0.80
    name_with_signal_floor: float = 0.60
    address_signal_floor: float = 0.85
    max_candidates: int = 5


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    """A candidate row with its comparison vector."""

    row: CandidateRow
    vector: ComparisonVector


def _ratio(left: str | None, right: str | None, scorer: Callable[[str, str], float]) -> float:
    if not left or not right:
        return 0.0
    return float(scorer(left, right)) / 100.0


def compare(
    applicant: NormalizedCustomer,
    candidate: CandidateRow,
    *,
    applicant_business_domain: str | None,
) -> ComparisonVector:
    """Build the comparison vector for one applicant and one candidate.

    `applicant_business_domain` is the applicant's email domain when the applicant is a
    business on a non-free-mail domain, and `None` otherwise.
    """
    same_business_domain = (
        applicant_business_domain is not None
        and candidate.customer_type == "business"
        and candidate.email_domain == applicant_business_domain
    )
    return ComparisonVector(
        name_similarity=_ratio(
            applicant.normalized_name, candidate.normalized_name, fuzz.token_sort_ratio
        ),
        address_similarity=_ratio(
            applicant.normalized_address, candidate.normalized_address, fuzz.token_set_ratio
        ),
        same_postal_code=(
            applicant.postal_code_key is not None
            and applicant.postal_code_key == candidate.postal_code_key
        ),
        same_business_domain=same_business_domain,
        local_part_similarity=_ratio(
            applicant.email_local_part, candidate.email_local_part, fuzz.ratio
        ),
    )


def select_for_review(
    scored: Sequence[ScoredCandidate], thresholds: MatchThresholds
) -> list[ScoredCandidate]:
    """Pick the candidates worth a model's attention, best name match first.

    A candidate qualifies on a strong name match alone, or on a middling name match backed by
    a shared postal code, a shared business domain, or a close address.
    """

    def qualifies(item: ScoredCandidate) -> bool:
        vector = item.vector
        if vector.name_similarity >= thresholds.name_floor:
            return True
        if vector.name_similarity < thresholds.name_with_signal_floor:
            return False
        return (
            vector.same_postal_code
            or vector.same_business_domain
            or vector.address_similarity >= thresholds.address_signal_floor
        )

    qualified = [item for item in scored if qualifies(item)]
    qualified.sort(key=lambda item: item.vector.name_similarity, reverse=True)
    return qualified[: thresholds.max_candidates]
