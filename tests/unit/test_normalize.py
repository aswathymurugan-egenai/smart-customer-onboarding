"""Normalization: canonical emails, names, phones, tax IDs, and addresses."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.customer import Address
from app.domain.errors import EmailInvalid, PhoneInvalid, TaxIdInvalid
from app.domain.normalize import (
    canonical_email,
    normalize_address,
    normalize_name,
    normalize_phone,
    normalize_postal_code,
    normalize_tax_id,
    split_email,
)


def test_canonical_email_trims_lowercases_and_keeps_the_domain() -> None:
    assert (
        canonical_email("  Jane.Doe@Example.TEST ", allow_reserved_domains=True)
        == "jane.doe@example.test"
    )


def test_canonical_email_encodes_an_internationalized_domain_as_ascii() -> None:
    assert canonical_email("jane@münchen.de") == "jane@xn--mnchen-3ya.de"


def test_reserved_test_domains_are_refused_unless_explicitly_allowed() -> None:
    with pytest.raises(EmailInvalid):
        canonical_email("jane@example.test")


@pytest.mark.parametrize(
    "raw",
    ["plainaddress", "jane@", "@example.com", "jane doe@example.com", "jane@@example.com", ""],
)
def test_malformed_addresses_are_rejected(raw: str) -> None:
    with pytest.raises(EmailInvalid):
        canonical_email(raw)


def test_split_email_returns_local_part_and_domain() -> None:
    assert split_email("jane.doe@example.com") == ("jane.doe", "example.com")


def test_swapped_name_order_shares_a_name_key() -> None:
    first = normalize_name("Müller-Smith, Jane", business=False)
    second = normalize_name("jane muller smith", business=False)

    assert first.name_key == second.name_key == "jane muller smith"
    assert first.normalized_name == "muller smith jane"


def test_legal_suffixes_are_dropped_from_business_names_only() -> None:
    assert (
        normalize_name("Acme Inc.", business=True).normalized_name
        == normalize_name("ACME Incorporated", business=True).normalized_name
        == "acme"
    )
    assert normalize_name("Acme Inc.", business=False).normalized_name == "acme inc"


def test_a_business_name_made_only_of_a_suffix_keeps_it() -> None:
    assert normalize_name("Inc", business=True).normalized_name == "inc"


@pytest.mark.parametrize(
    ("raw", "region", "expected"),
    [
        ("(415) 555-0100", "US", "+14155550100"),
        ("+1 415 555 0100", None, "+14155550100"),
        ("+44 20 7946 0958", None, "+442079460958"),
    ],
)
def test_phone_numbers_become_e164(raw: str, region: str | None, expected: str) -> None:
    assert normalize_phone(raw, region) == expected


@pytest.mark.parametrize(("raw", "region"), [("555-0100", None), ("hello", "US"), ("+1 123", None)])
def test_unreadable_phone_numbers_are_rejected(raw: str, region: str | None) -> None:
    with pytest.raises(PhoneInvalid):
        normalize_phone(raw, region)


@pytest.mark.parametrize(
    ("tax_id_type", "valid", "invalid"),
    [
        ("us_ein", "12-3456789", "12-345678"),
        ("gb_vat", "gb 123 456 789", "GB12345"),
        ("in_pan", "abcde1234f", "ABCD1234F"),
        ("other", "ab-1234", "a-1"),
    ],
)
def test_each_tax_id_type_accepts_one_valid_value_and_rejects_one_invalid(
    tax_id_type: str, valid: str, invalid: str
) -> None:
    assert normalize_tax_id(valid, tax_id_type) == valid.replace("-", "").replace(" ", "").upper()
    with pytest.raises(TaxIdInvalid):
        normalize_tax_id(invalid, tax_id_type)


def test_an_unknown_tax_id_type_is_rejected() -> None:
    with pytest.raises(TaxIdInvalid):
        normalize_tax_id("123456789", "ssn")


def test_postal_code_keeps_only_uppercase_letters_and_digits() -> None:
    assert normalize_postal_code("sw1a 1aa") == "SW1A1AA"


def test_address_normalization_joins_every_part() -> None:
    address = Address(
        line1="100 Example St.",
        city="Springfield",
        country_code="US",
        region="IL",
        postal_code="62701",
    )

    assert normalize_address(address) == "100 example st springfield il 62701 us"


@given(st.text(max_size=60), st.booleans())
def test_name_normalization_is_idempotent(text: str, business: bool) -> None:
    once = normalize_name(text, business=business)
    twice = normalize_name(once.normalized_name, business=business)

    assert twice.normalized_name == once.normalized_name
    assert twice.name_key == once.name_key


@given(st.lists(st.from_regex(r"[a-z]{1,8}", fullmatch=True), min_size=1, max_size=6), st.randoms())
def test_name_key_ignores_token_order(words: list[str], random: object) -> None:
    shuffled = list(words)
    random.shuffle(shuffled)  # type: ignore[attr-defined]

    assert (
        normalize_name(" ".join(words), business=False).name_key
        == normalize_name(" ".join(shuffled), business=False).name_key
    )


@given(st.emails())
def test_email_canonicalization_is_idempotent(email: str) -> None:
    try:
        once = canonical_email(email)
    except EmailInvalid:
        return

    assert canonical_email(once) == once
