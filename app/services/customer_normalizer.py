"""Turns a wire `CustomerInput` into a `NormalizedCustomer`."""

from __future__ import annotations

from pathlib import Path

from app.domain.customer import Address, BlockingProbe, CandidateRow, NormalizedCustomer
from app.domain.errors import EmailInvalid, InputInvalid
from app.domain.normalize import (
    canonical_email,
    normalize_address,
    normalize_name,
    normalize_phone,
    normalize_postal_code,
    normalize_tax_id,
    split_email,
)
from app.models.schemas import CustomerInput

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_domain_list(path: Path) -> frozenset[str]:
    """Read a one-domain-per-line file, skipping blank lines and `#` comments."""
    lines = (line.strip().lower() for line in path.read_text(encoding="utf-8").splitlines())
    return frozenset(line for line in lines if line and not line.startswith("#"))


class CustomerNormalizer:
    """Builds canonical customer values and the keys derived from them."""

    def __init__(self, *, free_mail_domains: frozenset[str], allow_reserved_domains: bool) -> None:
        self._free_mail = free_mail_domains
        self._allow_reserved = allow_reserved_domains

    def normalize(self, request: CustomerInput) -> NormalizedCustomer:
        """Normalize every field. Raises the typed domain error for the first bad value."""
        email = canonical_email(request.email, allow_reserved_domains=self._allow_reserved)
        local_part, domain = split_email(email)
        business = request.customer_type == "business"
        name_text = (
            request.company_name or ""
            if business
            else " ".join(part for part in (request.given_name, request.family_name) if part)
        )
        name = normalize_name(name_text, business=business)
        if not name.normalized_name:
            raise InputInvalid(
                "The name has no letters or digits.",
                field="company_name" if business else "given_name",
            )
        address = (
            Address(
                line1=request.address.line1,
                line2=request.address.line2,
                city=request.address.city,
                region=request.address.region,
                postal_code=request.address.postal_code,
                country_code=request.address.country_code,
            )
            if request.address
            else None
        )
        return NormalizedCustomer(
            customer_type=request.customer_type,
            given_name=request.given_name,
            family_name=request.family_name,
            company_name=request.company_name,
            normalized_name=name.normalized_name,
            name_key=name.name_key,
            email=email,
            email_as_entered=request.email,
            email_local_part=local_part,
            email_domain=domain,
            phone_e164=(
                normalize_phone(request.phone, address.country_code if address else None)
                if request.phone
                else None
            ),
            tax_id_type=request.tax_id_type,
            tax_id=(
                normalize_tax_id(request.tax_id, request.tax_id_type)
                if request.tax_id and request.tax_id_type
                else None
            ),
            address=address,
            normalized_address=normalize_address(address) if address else None,
            postal_code_key=(
                normalize_postal_code(address.postal_code)
                if address and address.postal_code
                else None
            )
            or None,
        )

    def safe_canonical_email(self, raw: str) -> str | None:
        """Return the canonical address, or None when the syntax is invalid. For audit hashing."""
        try:
            return canonical_email(raw, allow_reserved_domains=self._allow_reserved)
        except EmailInvalid:
            return None

    def business_domain(self, customer: NormalizedCustomer) -> str | None:
        """Return the email domain when it identifies a business, and None otherwise."""
        if customer.customer_type != "business" or customer.email_domain in self._free_mail:
            return None
        return customer.email_domain

    def row_business_domain(self, row: CandidateRow) -> str | None:
        """Return a candidate's email domain when it identifies a business."""
        if row.customer_type != "business" or row.email_domain in self._free_mail:
            return None
        return row.email_domain

    def blocking_probe(self, customer: NormalizedCustomer) -> BlockingProbe:
        """Build the keys the fuzzy blocking query compares."""
        return BlockingProbe(
            normalized_name=customer.normalized_name,
            name_key=customer.name_key,
            postal_code_key=customer.postal_code_key,
            country_code=customer.address.country_code if customer.address else None,
            business_domain=self.business_domain(customer),
        )
