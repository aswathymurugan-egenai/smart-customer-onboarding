"""Pure normalization functions: raw input in, canonical values out.

Every function is deterministic and free of I/O. Failures raise the typed errors in
`app.domain.errors`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import email_validator
import phonenumbers

from app.domain.customer import Address
from app.domain.errors import EmailInvalid, PhoneInvalid, TaxIdInvalid

LEGAL_SUFFIXES = frozenset(
    {
        "inc",
        "incorporated",
        "llc",
        "ltd",
        "limited",
        "gmbh",
        "plc",
        "corp",
        "corporation",
        "co",
        "pvt",
    }
)

TAX_ID_PATTERNS: dict[str, re.Pattern[str]] = {
    "us_ein": re.compile(r"\d{9}"),
    "gb_vat": re.compile(r"GB(?:\d{9}|\d{12})"),
    "in_pan": re.compile(r"[A-Z]{5}\d{4}[A-Z]"),
    "other": re.compile(r"[A-Z0-9]{4,30}"),
}

_TOKEN = re.compile(r"[^\W_]+")
_TAX_ID_SEPARATORS = re.compile(r"[\s\-]+")
_NON_ALNUM = re.compile(r"[^A-Z0-9]")
_FOLD_PASSES = 5


@dataclass(frozen=True, slots=True)
class NormalizedName:
    """A name reduced to comparable tokens."""

    normalized_name: str
    name_key: str


def split_email(email: str) -> tuple[str, str]:
    """Split a canonical address into its local part and its domain."""
    local_part, _, domain = email.rpartition("@")
    return local_part, domain


def canonical_email(raw: str, *, allow_reserved_domains: bool = False) -> str:
    """Return the trimmed, lowercased address with an IDNA-encoded domain.

    `allow_reserved_domains` admits names such as `.test` that email-validator refuses by
    default. Only local development and tests turn it on.
    """
    try:
        validated = email_validator.validate_email(
            raw.strip(),
            check_deliverability=False,
            test_environment=allow_reserved_domains,
        )
    except email_validator.EmailNotValidError as error:
        raise EmailInvalid("The email address is not valid.") from error
    local_part = validated.local_part.lower()
    return f"{local_part}@{validated.ascii_domain.lower()}"


def _fold(text: str) -> str:
    """Strip accents and case until the text stops changing.

    Unicode decomposition and case folding can each produce characters the other would
    change, so the loop runs to a fixed point. That makes the result idempotent.
    """
    current = text
    for _ in range(_FOLD_PASSES):
        decomposed = unicodedata.normalize("NFKD", current)
        stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
        folded = stripped.casefold()
        if folded == current:
            break
        current = folded
    return current


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(_fold(text))


def normalize_name(text: str, *, business: bool) -> NormalizedName:
    """Reduce a person or company name to casefolded, accent-free, punctuation-free tokens.

    Business names also lose trailing legal suffixes such as `inc` or `gmbh`. `name_key`
    holds the same tokens sorted alphabetically, so swapped name order yields the same key.
    """
    tokens = _tokens(text)
    if business:
        while len(tokens) > 1 and tokens[-1] in LEGAL_SUFFIXES:
            tokens.pop()
    return NormalizedName(
        normalized_name=" ".join(tokens),
        name_key=" ".join(sorted(tokens)),
    )


def normalize_phone(raw: str, default_region: str | None) -> str:
    """Return the number in E.164, using `default_region` when the input has no country code."""
    try:
        parsed = phonenumbers.parse(raw, default_region)
    except phonenumbers.NumberParseException as error:
        raise PhoneInvalid("The phone number cannot be read.") from error
    if not phonenumbers.is_valid_number(parsed):
        raise PhoneInvalid("The phone number is not valid for its region.")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def normalize_tax_id(raw: str, tax_id_type: str) -> str:
    """Strip spaces and dashes, uppercase, and check the pattern for `tax_id_type`."""
    pattern = TAX_ID_PATTERNS.get(tax_id_type)
    if pattern is None:
        raise TaxIdInvalid("The tax ID type is not supported.")
    cleaned = _TAX_ID_SEPARATORS.sub("", raw).upper()
    if not pattern.fullmatch(cleaned):
        raise TaxIdInvalid("The tax ID does not match the format for its type.")
    return cleaned


def normalize_postal_code(raw: str) -> str:
    """Uppercase the postal code and drop everything except letters and digits."""
    return _NON_ALNUM.sub("", raw.upper())


def normalize_address(address: Address) -> str:
    """Join the address parts into one comparable token string."""
    parts = [
        address.line1,
        address.line2 or "",
        address.city,
        address.region or "",
        address.postal_code or "",
        address.country_code,
    ]
    return " ".join(_tokens(" ".join(parts)))
