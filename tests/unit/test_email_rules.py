"""Disposable-domain lookup and typo suggestions."""

from __future__ import annotations

import pytest

from app.domain.email_rules import is_disposable, parent_domains, typo_suggestion
from app.services.email_validation import DomainLists

FREE_MAIL = DomainLists.load().free_mail


def test_parent_domains_list_the_domain_then_each_parent_with_a_dot() -> None:
    assert parent_domains("a.b.example.com") == ["a.b.example.com", "b.example.com", "example.com"]


def test_a_subdomain_of_a_disposable_domain_is_disposable() -> None:
    disposable = frozenset({"mailinator.test"})

    assert is_disposable("team.mailinator.test", disposable)
    assert is_disposable("mailinator.test", disposable)
    assert not is_disposable("notmailinator.test", disposable)


@pytest.mark.parametrize(
    "domain", ["gmial.com", "gmail.con", "gmail.cmo", "hotmial.com", "yaho.com"]
)
def test_near_misses_of_common_providers_suggest_the_real_domain(domain: str) -> None:
    suggestion = typo_suggestion(domain, FREE_MAIL)

    assert suggestion is not None
    assert suggestion in FREE_MAIL


def test_gmial_and_gmail_con_both_suggest_gmail_com() -> None:
    assert typo_suggestion("gmial.com", FREE_MAIL) == "gmail.com"
    assert typo_suggestion("gmail.con", FREE_MAIL) == "gmail.com"


@pytest.mark.parametrize("domain", ["example.test", "acme-widgets.io", "gmail.com", "outlook.com"])
def test_unrelated_and_correct_domains_suggest_nothing(domain: str) -> None:
    assert typo_suggestion(domain, FREE_MAIL) is None


def test_short_provider_domains_tolerate_only_one_edit() -> None:
    assert typo_suggestion("aox.com", FREE_MAIL) == "aol.com"
    assert typo_suggestion("aoxy.com", FREE_MAIL) is None
