"""Email validation: syntax, the disposable list, MX, and typo advice."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.domain.customer import MxStatus
from app.domain.email_rules import is_disposable, typo_suggestion
from app.domain.errors import (
    AdvisorFailure,
    EmailDisposable,
    EmailInvalid,
    EmailUndeliverable,
)
from app.domain.normalize import canonical_email, split_email
from app.models.schemas import (
    EmailCheckResults,
    EmailProblem,
    EmailValidationResult,
    TypoWarning,
)
from app.services.customer_normalizer import DATA_DIR, load_domain_list
from app.services.guard import RequestContext, RequestGuard
from app.services.ports import Advisor, MxLookup, MxResolver

TYPO_MESSAGE = "Did you mean {email}?"


@dataclass(frozen=True, slots=True)
class DomainLists:
    """The disposable and free-mail domain sets, loaded once at startup."""

    disposable: frozenset[str]
    free_mail: frozenset[str]

    @classmethod
    def load(cls, data_dir: Path = DATA_DIR) -> DomainLists:
        """Read both lists from the data directory."""
        return cls(
            disposable=load_domain_list(data_dir / "disposable_domains.txt"),
            free_mail=load_domain_list(data_dir / "free_mail_domains.txt"),
        )


@dataclass(frozen=True, slots=True)
class EmailCheck:
    """A registrable address: the canonical form and its MX status."""

    email: str
    mx_status: MxStatus


class EmailValidationService:
    """Runs the email rules and, when the rules find no typo, asks the advisor."""

    def __init__(
        self,
        *,
        lists: DomainLists,
        mx: MxResolver,
        advisor: Advisor,
        guard: RequestGuard,
        min_typo_confidence: float,
        allow_reserved_domains: bool,
    ) -> None:
        self._guard = guard
        self._lists = lists
        self._mx = mx
        self._advisor = advisor
        self._min_confidence = min_typo_confidence
        self._allow_reserved = allow_reserved_domains

    def rules_suggestion(self, email: str) -> TypoWarning | None:
        """Suggest a correction from deterministic rules alone. No model call."""
        local_part, domain = split_email(email)
        corrected = typo_suggestion(domain, self._lists.free_mail)
        if corrected is None:
            return None
        return self._warning(f"{local_part}@{corrected}", source="rules")

    async def model_suggestion(self, email: str) -> TypoWarning | None:
        """Ask the advisor about the domain and accept only a suggestion that holds up.

        Raises `AdvisorFailure` when the model call fails. Free-mail domains are known good
        and skip the call.
        """
        local_part, domain = split_email(email)
        if not self._advisor.enabled or domain in self._lists.free_mail:
            return None
        advice = await self._advisor.suggest_domain(domain)
        suggested = (advice.suggested_domain or "").strip().lower()
        if not advice.is_likely_typo or not suggested or suggested == domain:
            return None
        if advice.confidence < self._min_confidence:
            return None
        try:
            suggested_email = canonical_email(
                f"{local_part}@{suggested}", allow_reserved_domains=self._allow_reserved
            )
        except EmailInvalid:
            return None
        accepted = suggested in self._lists.free_mail or await self._mx.lookup(suggested) == "pass"
        return self._warning(suggested_email, source="model") if accepted else None

    async def assert_registrable(self, email: str) -> EmailCheck:
        """Return the canonical address and MX status, or raise the matching domain error."""
        canonical = canonical_email(email, allow_reserved_domains=self._allow_reserved)
        _, domain = split_email(canonical)
        suggestion = self.rules_suggestion(canonical)
        suggested_email = suggestion.suggested_email if suggestion else None
        if is_disposable(domain, self._lists.disposable):
            raise EmailDisposable(
                "The email domain accepts disposable addresses.", suggested_email=suggested_email
            )
        lookup = await self._mx.lookup(domain)
        if lookup == "fail":
            raise EmailUndeliverable(
                "The email domain cannot receive mail.", suggested_email=suggested_email
            )
        return EmailCheck(email=canonical, mx_status="pass" if lookup == "pass" else "unknown")

    async def validate(
        self, raw_email: str, ctx: RequestContext | None = None
    ) -> EmailValidationResult:
        """Run every check and report the verdict. An invalid address is a normal result.

        A request context applies the `validate` rate limit. The assistant's tool passes none,
        because the chat request already counted against its own limit.
        """
        if ctx is not None:
            await self._guard.enforce("validate", ctx)
        entered = raw_email.strip()
        try:
            canonical = canonical_email(entered, allow_reserved_domains=self._allow_reserved)
        except EmailInvalid as error:
            return EmailValidationResult(
                email_as_entered=entered,
                normalized_email=None,
                is_valid=False,
                checks=EmailCheckResults(syntax="fail", disposable="skipped", mx="skipped"),
                problems=[EmailProblem(code="email-invalid", message=error.message)],
                suggestion=None,
            )
        _, domain = split_email(canonical)
        problems: list[EmailProblem] = []
        disposable = is_disposable(domain, self._lists.disposable)
        if disposable:
            problems.append(
                EmailProblem(
                    code="email-disposable",
                    message="The email domain accepts disposable addresses.",
                )
            )
            mx_check: MxLookup | None = None
        else:
            mx_check = await self._mx.lookup(domain)
            if mx_check == "fail":
                problems.append(
                    EmailProblem(
                        code="email-domain-undeliverable",
                        message="The email domain cannot receive mail.",
                    )
                )
        suggestion = self.rules_suggestion(canonical)
        if suggestion is None and not disposable:
            try:
                suggestion = await self.model_suggestion(canonical)
            except AdvisorFailure:
                suggestion = None
        return EmailValidationResult(
            email_as_entered=entered,
            normalized_email=canonical,
            is_valid=not problems,
            checks=EmailCheckResults(
                syntax="pass",
                disposable="fail" if disposable else "pass",
                mx="skipped" if mx_check is None else mx_check,
            ),
            problems=problems,
            suggestion=suggestion,
        )

    @staticmethod
    def _warning(email: str, *, source: Literal["rules", "model"]) -> TypoWarning:
        return TypoWarning(
            message=TYPO_MESSAGE.format(email=email), suggested_email=email, source=source
        )
