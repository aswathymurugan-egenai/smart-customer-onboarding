"""Email validation: each check, the typo rules, and the advisor's domain check."""

from __future__ import annotations

import pytest

from app.domain.errors import (
    AdvisorFailure,
    EmailDisposable,
    EmailInvalid,
    EmailUndeliverable,
    RateLimited,
)
from app.models.advice import TypoAdvice
from app.services.email_validation import DomainLists
from tests.fakes import FakeMx
from tests.support import make_graph


async def test_a_malformed_address_fails_syntax_and_skips_the_other_checks() -> None:
    graph = make_graph()

    result = await graph.email.validate("not-an-email")

    assert not result.is_valid
    assert result.normalized_email is None
    assert result.checks.model_dump() == {
        "syntax": "fail",
        "disposable": "skipped",
        "mx": "skipped",
    }
    assert [p.code for p in result.problems] == ["email-invalid"]
    assert graph.mx.calls == []


async def test_a_disposable_domain_fails_the_disposable_check_without_an_mx_lookup() -> None:
    graph = make_graph()

    result = await graph.email.validate("x@mailinator.test")

    assert not result.is_valid
    assert result.checks.disposable == "fail"
    assert result.checks.mx == "skipped"
    assert [p.code for p in result.problems] == ["email-disposable"]


async def test_a_domain_without_mail_records_fails_the_mx_check() -> None:
    graph = make_graph(mx=FakeMx({"nowhere.test": "fail"}))

    result = await graph.email.validate("x@nowhere.test")

    assert not result.is_valid
    assert [p.code for p in result.problems] == ["email-domain-undeliverable"]


async def test_an_mx_timeout_leaves_the_address_valid_with_an_unknown_check() -> None:
    graph = make_graph(mx=FakeMx({"example.test": "unknown"}))

    result = await graph.email.validate("jane@example.test")

    assert result.is_valid
    assert result.checks.mx == "unknown"


async def test_a_rule_suggestion_skips_the_advisor() -> None:
    graph = make_graph()

    result = await graph.email.validate("jane@gmial.com")

    assert result.suggestion is not None
    assert result.suggestion.source == "rules"
    assert result.suggestion.suggested_email == "jane@gmail.com"
    assert graph.advisor.typo_calls == []


async def test_a_model_suggestion_is_accepted_when_confident_and_deliverable() -> None:
    graph = make_graph()
    graph.advisor.typo_advice = TypoAdvice(
        is_likely_typo=True, suggested_domain="acme-corp.test", confidence=0.9
    )

    result = await graph.email.validate("jane@acme-cop.test")

    assert result.suggestion is not None
    assert result.suggestion.source == "model"
    assert result.suggestion.suggested_email == "jane@acme-corp.test"
    assert graph.mx.calls[-1] == "acme-corp.test"


async def test_a_model_suggestion_whose_domain_fails_mx_is_discarded() -> None:
    graph = make_graph(mx=FakeMx({"acme-corp.test": "fail"}))
    graph.advisor.typo_advice = TypoAdvice(
        is_likely_typo=True, suggested_domain="acme-corp.test", confidence=0.9
    )

    result = await graph.email.validate("jane@acme-cop.test")

    assert result.suggestion is None


@pytest.mark.parametrize(
    "advice",
    [
        TypoAdvice(is_likely_typo=True, suggested_domain="acme-corp.test", confidence=0.5),
        TypoAdvice(is_likely_typo=False, suggested_domain="acme-corp.test", confidence=0.9),
        TypoAdvice(is_likely_typo=True, suggested_domain="acme-cop.test", confidence=0.9),
        TypoAdvice(is_likely_typo=True, suggested_domain=None, confidence=0.9),
        TypoAdvice(is_likely_typo=True, suggested_domain="bad domain!", confidence=0.9),
    ],
    ids=["low-confidence", "not-a-typo", "same-domain", "no-domain", "malformed-domain"],
)
async def test_a_weak_or_unusable_model_suggestion_is_ignored(advice: TypoAdvice) -> None:
    graph = make_graph()
    graph.advisor.typo_advice = advice

    result = await graph.email.validate("jane@acme-cop.test")

    assert result.suggestion is None


async def test_an_advisor_failure_leaves_the_suggestion_empty() -> None:
    graph = make_graph()
    graph.advisor.fail_typo = AdvisorFailure("unavailable")

    result = await graph.email.validate("jane@acme-cop.test")

    assert result.is_valid
    assert result.suggestion is None


async def test_free_mail_domains_are_not_sent_to_the_model() -> None:
    graph = make_graph()

    await graph.email.validate("jane@gmail.com")

    assert graph.advisor.typo_calls == []


async def test_a_disposable_domain_is_not_sent_to_the_model() -> None:
    graph = make_graph()

    await graph.email.validate("jane@mailinator.test")

    assert graph.advisor.typo_calls == []


async def test_the_register_path_raises_the_matching_error_for_each_failure() -> None:
    graph = make_graph(mx=FakeMx({"nowhere.test": "fail"}))

    with pytest.raises(EmailInvalid):
        await graph.email.assert_registrable("nope")
    with pytest.raises(EmailDisposable):
        await graph.email.assert_registrable("x@mailinator.test")
    with pytest.raises(EmailUndeliverable) as undeliverable:
        await graph.email.assert_registrable("x@nowhere.test")
    assert undeliverable.value.suggested_email is None


async def test_a_disposable_typo_domain_carries_the_rule_suggestion() -> None:
    graph = make_graph(
        lists=DomainLists(
            disposable=frozenset({"gmial.com"}), free_mail=DomainLists.load().free_mail
        )
    )

    with pytest.raises(EmailDisposable) as raised:
        await graph.email.assert_registrable("jane@gmial.com")

    assert raised.value.suggested_email == "jane@gmail.com"


async def test_validate_applies_the_per_client_limit_when_given_a_context() -> None:
    graph = make_graph()
    ctx = graph.ctx()

    for _ in range(30):
        await graph.email.validate("jane@example.test", ctx)

    with pytest.raises(RateLimited):
        await graph.email.validate("jane@example.test", ctx)
