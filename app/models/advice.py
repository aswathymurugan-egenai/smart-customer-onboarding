"""Structured answers the advisor asks the model for.

These are the response schemas handed to the model and the shapes the advisor validates
afterward. They never appear on the wire.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.schemas import DuplicateReason

Verdict = Literal["likely_same", "possibly_same", "different"]


class TypoAdvice(BaseModel):
    """The model's judgment on whether an email domain is a mistyped common domain."""

    is_likely_typo: bool = Field(description="True when the domain looks like a slip.")
    suggested_domain: str | None = Field(
        default=None, description="The domain the person probably meant, or null."
    )
    confidence: float = Field(description="Confidence between 0 and 1.")


class CandidateVerdict(BaseModel):
    """The model's verdict on one candidate, identified by an opaque reference."""

    ref: str = Field(description="The reference the candidate was sent under, such as c1.")
    verdict: Verdict = Field(description="likely_same, possibly_same, or different.")
    confidence: float = Field(description="Confidence between 0 and 1.")
    reasons: list[DuplicateReason] = Field(
        default_factory=list, description="Reason codes for the verdict."
    )


class FuzzyAdvice(BaseModel):
    """The model's verdicts on every candidate it was sent."""

    candidates: list[CandidateVerdict] = Field(description="One entry per candidate.")
