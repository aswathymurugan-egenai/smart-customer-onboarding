"""Pydantic v2 wire models: every request and response body the API publishes.

Each model forbids unknown fields, documents every field, and carries fictional examples
only (`@example.test` addresses and 555-01xx numbers).
"""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CustomerTypeName = Literal["individual", "business"]
TaxIdTypeName = Literal["us_ein", "gb_vat", "in_pan", "other"]
MatchedField = Literal["email", "phone", "tax_id"]
SuggestedAction = Literal["apply_email_suggestion", "confirm_registration", "review_field"]
AdvisoryStatusName = Literal["ok", "unavailable", "disabled"]
DuplicateReason = Literal[
    "name_variant",
    "nickname",
    "swapped_name_order",
    "corporate_alias",
    "address_variant",
    "shared_business_domain",
]
CheckVerdict = Literal["pass", "fail", "unknown", "skipped"]
AssistantRegistrationStatus = Literal[
    "created", "duplicate", "needs_confirmation", "incomplete_form", "rejected", "busy"
]

MAX_EMAIL_LENGTH = 254


class WireModel(BaseModel):
    """Base for every wire model: unknown fields are rejected and strings are trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _blank_to_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


class AddressInput(WireModel):
    """A postal address."""

    line1: str = Field(min_length=1, max_length=200, description="First address line.")
    line2: str | None = Field(
        default=None, max_length=200, description="Second address line, such as a unit number."
    )
    city: str = Field(min_length=1, max_length=100, description="City or town.")
    region: str | None = Field(default=None, max_length=100, description="State or province.")
    postal_code: str | None = Field(default=None, max_length=20, description="Postal or ZIP code.")
    country_code: str = Field(
        pattern=r"^[A-Z]{2}$", description="ISO 3166-1 alpha-2 country code, upper case."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "line1": "100 Example Street",
                    "city": "Springfield",
                    "region": "IL",
                    "postal_code": "62701",
                    "country_code": "US",
                }
            ]
        }
    )

    @field_validator("line2", "region", "postal_code", mode="before")
    @classmethod
    def _optional_blank(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("country_code", mode="before")
    @classmethod
    def _upper_country(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class CustomerInput(WireModel):
    """The values a person submits to register."""

    customer_type: CustomerTypeName = Field(
        default="individual", description="Whether the customer is a person or a business."
    )
    given_name: str = Field(min_length=1, max_length=100, description="Given name or first name.")
    family_name: str | None = Field(
        default=None, max_length=100, description="Family name. Omit when the person gave one name."
    )
    company_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Company name. Required for a business and not allowed for an individual.",
    )
    email: str = Field(
        min_length=3,
        max_length=MAX_EMAIL_LENGTH,
        description="Email address. It is the primary unique key.",
    )
    phone: str | None = Field(
        default=None,
        max_length=32,
        description="Phone number. Without a country code it is read in the address country.",
    )
    tax_id_type: TaxIdTypeName | None = Field(
        default=None, description="Kind of tax or government id. Required when tax_id is given."
    )
    tax_id: str | None = Field(
        default=None,
        max_length=40,
        description="Tax or government id. Stored as a keyed hash plus its last four characters.",
    )
    address: AddressInput | None = Field(
        default=None, description="Postal address. It improves likely-duplicate matching."
    )
    bot_token: str = Field(
        default="", max_length=2048, description="Proof from the bot check, when one is enforced."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "customer_type": "individual",
                    "given_name": "Jane",
                    "family_name": "Doe",
                    "email": "jane.doe@example.test",
                    "phone": "+1 415 555 0100",
                    "tax_id_type": "us_ein",
                    "tax_id": "12-3456789",
                    "address": {
                        "line1": "100 Example Street",
                        "city": "Springfield",
                        "region": "IL",
                        "postal_code": "62701",
                        "country_code": "US",
                    },
                    "bot_token": "local",
                }
            ]
        }
    )

    @field_validator("family_name", "company_name", "phone", "tax_id_type", "tax_id", mode="before")
    @classmethod
    def _optional_blank(cls, value: object) -> object:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def _check_cross_field_rules(self) -> Self:
        if self.customer_type == "business" and self.company_name is None:
            raise ValueError("company_name is required for a business.")
        if self.customer_type == "individual" and self.company_name is not None:
            raise ValueError("company_name is only allowed for a business.")
        if (self.tax_id_type is None) != (self.tax_id is None):
            raise ValueError("tax_id_type and tax_id must be given together.")
        return self


class AddressDraft(WireModel):
    """An address as typed so far; every part is optional."""

    line1: str | None = Field(default=None, max_length=200, description="First address line.")
    line2: str | None = Field(default=None, max_length=200, description="Second address line.")
    city: str | None = Field(default=None, max_length=100, description="City or town.")
    region: str | None = Field(default=None, max_length=100, description="State or province.")
    postal_code: str | None = Field(default=None, max_length=20, description="Postal or ZIP code.")
    country_code: str | None = Field(
        default=None, max_length=2, description="ISO 3166-1 alpha-2 country code."
    )

    @field_validator("*", mode="before")
    @classmethod
    def _blank(cls, value: object) -> object:
        return _blank_to_none(value)


class CustomerDraft(WireModel):
    """The form as the person has filled it so far, sent with a chat turn.

    It has the fields of `CustomerInput`, all optional, and no bot token.
    """

    customer_type: CustomerTypeName | None = Field(
        default=None, description="Whether the customer is a person or a business."
    )
    given_name: str | None = Field(default=None, max_length=100, description="Given name.")
    family_name: str | None = Field(default=None, max_length=100, description="Family name.")
    company_name: str | None = Field(default=None, max_length=200, description="Company name.")
    email: str | None = Field(
        default=None, max_length=MAX_EMAIL_LENGTH, description="Email address."
    )
    phone: str | None = Field(default=None, max_length=32, description="Phone number.")
    tax_id_type: TaxIdTypeName | None = Field(default=None, description="Kind of tax id.")
    tax_id: str | None = Field(default=None, max_length=40, description="Tax or government id.")
    address: AddressDraft | None = Field(default=None, description="Postal address so far.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "customer_type": "individual",
                    "given_name": "Jane",
                    "family_name": "Doe",
                    "email": "jane.doe@example.test",
                }
            ]
        }
    )

    @field_validator(
        "customer_type",
        "given_name",
        "family_name",
        "company_name",
        "email",
        "phone",
        "tax_id_type",
        "tax_id",
        mode="before",
    )
    @classmethod
    def _blank(cls, value: object) -> object:
        return _blank_to_none(value)


class EmailValidationRequest(WireModel):
    """The address to check."""

    email: str = Field(min_length=3, max_length=MAX_EMAIL_LENGTH, description="Email address.")

    model_config = ConfigDict(json_schema_extra={"examples": [{"email": "jane.doe@example.test"}]})


class TypoWarning(WireModel):
    """A suggested correction for a likely mistyped email domain."""

    code: Literal["possible_typo"] = Field(
        default="possible_typo", description="Stable warning code."
    )
    message: str = Field(max_length=300, description="Human-readable explanation.")
    suggested_email: str = Field(max_length=MAX_EMAIL_LENGTH, description="The corrected address.")
    source: Literal["rules", "model"] = Field(
        description="Whether a deterministic rule or the model produced the suggestion."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "code": "possible_typo",
                    "message": "Did you mean jane@gmail.com?",
                    "suggested_email": "jane@gmail.com",
                    "source": "rules",
                }
            ]
        }
    )


class DuplicateWarning(WireModel):
    """A warning that the applicant may already be a customer under different details."""

    code: Literal["possible_duplicate"] = Field(
        default="possible_duplicate", description="Stable warning code."
    )
    message: str = Field(max_length=300, description="Human-readable explanation.")
    confidence: float = Field(ge=0, le=1, description="Model-reported confidence, 0 to 1.")
    reasons: list[DuplicateReason] = Field(
        max_length=3, description="Up to three reason codes for the suspicion."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "code": "possible_duplicate",
                    "message": "A customer with a very similar name and address may already exist.",
                    "confidence": 0.82,
                    "reasons": ["swapped_name_order", "address_variant"],
                }
            ]
        }
    )


AdvisoryWarning = Annotated[TypoWarning | DuplicateWarning, Field(discriminator="code")]


class RegistrationCreated(WireModel):
    """The result of a successful registration."""

    customer_id: str = Field(description="Identifier of the customer.")
    status: Literal["created"] = Field(default="created", description="Always `created`.")
    email: str = Field(description="The canonical email address stored for the customer.")
    warnings: list[AdvisoryWarning] = Field(
        default_factory=list, max_length=5, description="Typo and likely-duplicate warnings."
    )
    advisory_status: AdvisoryStatusName = Field(
        description="Whether the model produced advice: ok, unavailable, or disabled."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "customer_id": "0192f6a0-7c1e-7d3b-9a52-5a7d3f6c9e10",
                    "status": "created",
                    "email": "jane.doe@example.test",
                    "warnings": [],
                    "advisory_status": "ok",
                }
            ]
        }
    )


class EmailCheckResults(WireModel):
    """The outcome of each email check."""

    syntax: CheckVerdict = Field(description="Syntax check.")
    disposable: CheckVerdict = Field(description="Disposable-domain check.")
    mx: CheckVerdict = Field(description="Mail-exchanger lookup.")


class EmailProblem(WireModel):
    """One reason an email address is not acceptable."""

    code: str = Field(max_length=100, description="Stable problem code.")
    message: str = Field(max_length=300, description="Human-readable explanation.")


class EmailValidationResult(WireModel):
    """The verdict on an email address."""

    email_as_entered: str = Field(description="The address as submitted, trimmed.")
    normalized_email: str | None = Field(
        description="The canonical address, or null when the syntax check failed."
    )
    is_valid: bool = Field(description="True when no check failed.")
    checks: EmailCheckResults = Field(description="Per-check outcomes.")
    problems: list[EmailProblem] = Field(description="Why the address failed, when it did.")
    suggestion: TypoWarning | None = Field(
        description="A suggested correction, or null when none applies."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "email_as_entered": "jane@gmial.com",
                    "normalized_email": "jane@gmial.com",
                    "is_valid": True,
                    "checks": {"syntax": "pass", "disposable": "pass", "mx": "pass"},
                    "problems": [],
                    "suggestion": {
                        "code": "possible_typo",
                        "message": "Did you mean jane@gmail.com?",
                        "suggested_email": "jane@gmail.com",
                        "source": "rules",
                    },
                }
            ]
        }
    )


class DuplicateCheckResult(WireModel):
    """The outcome of a duplicate check. It never names another customer."""

    exact_matches: list[MatchedField] = Field(
        description="Which of email, phone, and tax_id already belong to a customer."
    )
    possible_duplicate: DuplicateWarning | None = Field(
        description="A likely-duplicate warning, or null."
    )
    advisory_status: AdvisoryStatusName = Field(
        description="Whether the model produced advice: ok, unavailable, or disabled."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"exact_matches": ["email"], "possible_duplicate": None, "advisory_status": "ok"}
            ]
        }
    )


class LastResult(WireModel):
    """What the form last received from the API, passed to the assistant for context."""

    status: int = Field(ge=100, le=599, description="HTTP status the form last received.")
    problem_type: str | None = Field(
        default=None, max_length=200, description="Problem type URI when the status was an error."
    )
    matched_on: list[MatchedField] = Field(
        default_factory=list, max_length=3, description="Fields a 409 named."
    )
    warnings: list[AdvisoryWarning] = Field(
        default_factory=list, max_length=5, description="Warnings that came with a 201."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": 409,
                    "problem_type": "urn:smart-customer-onboarding:problem:customer-duplicate",
                    "matched_on": ["email"],
                    "warnings": [],
                }
            ]
        }
    )


class ChatRequest(WireModel):
    """One turn of conversation with the assistant."""

    session_id: UUID = Field(
        description="Conversation id, generated by the client once per session."
    )
    message: str = Field(min_length=1, max_length=2000, description="The person's message.")
    form_snapshot: CustomerDraft | None = Field(
        default=None, description="The form as it stands now."
    )
    last_result: LastResult | None = Field(
        default=None, description="The status, problem type, and warnings the form last received."
    )
    action: Literal["confirm_registration"] | None = Field(
        default=None,
        description="Set only after the person clicked the confirmation button in the dialog.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "session_id": "6f1c1bde-3a64-4f2c-9a54-52f7a2d0a111",
                    "message": "Why was my email rejected?",
                    "form_snapshot": {"given_name": "Jane", "email": "jane@mailinator.example"},
                    "last_result": {
                        "status": 422,
                        "problem_type": "urn:smart-customer-onboarding:problem:email-disposable",
                    },
                    "action": None,
                }
            ]
        }
    )


class AssistantRegistration(WireModel):
    """A registration outcome copied by code from the register tool's result."""

    status: AssistantRegistrationStatus = Field(description="What the register tool reported.")
    customer_id: str | None = Field(default=None, description="Set when the status is created.")
    matched_on: list[MatchedField] = Field(
        default_factory=list, max_length=3, description="Fields a duplicate matched."
    )


class AssistantReply(WireModel):
    """The assistant's answer to one turn."""

    session_id: UUID = Field(description="Conversation id.")
    message: str = Field(max_length=4000, description="The assistant's message.")
    suggested_actions: list[SuggestedAction] = Field(
        max_length=3, description="Buttons the UI may offer."
    )
    registration: AssistantRegistration | None = Field(
        description="Set when the register tool ran this turn. Taken from the tool, not the model."
    )
    model: str = Field(description="Id of the model that answered.")
    used_fallback: bool = Field(description="True when the fallback model answered.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "session_id": "6f1c1bde-3a64-4f2c-9a54-52f7a2d0a111",
                    "message": "That domain accepts disposable addresses. Please use another.",
                    "suggested_actions": ["review_field"],
                    "registration": None,
                    "model": "gemini-2.5-flash",
                    "used_fallback": False,
                }
            ]
        }
    )


class AssistantTurn(BaseModel):
    """The structured answer the assistant model must return.

    It is the agent's output schema and never appears on the wire. It leaves unknown fields
    allowed in the schema it hands the model, and the assistant wrapper validates the answer.
    """

    message: str = Field(max_length=4000, description="What to tell the person.")
    suggested_actions: list[SuggestedAction] = Field(
        default_factory=list, max_length=3, description="Buttons the UI may offer."
    )


class ProblemError(WireModel):
    """One field-level error inside a problem document."""

    pointer: str = Field(description="JSON pointer to the offending field, such as `/email`.")
    code: str = Field(description="Stable error code.")
    message: str = Field(description="Human-readable explanation.")


class ProblemDetails(WireModel):
    """An RFC 9457 problem document, served as `application/problem+json`."""

    type: str = Field(description="Stable problem type URI.")
    title: str = Field(description="Short, human-readable summary of the problem type.")
    status: int = Field(description="HTTP status code.")
    detail: str = Field(description="Human-readable explanation of this occurrence.")
    instance: str = Field(description="Request path the problem occurred on.")
    request_id: str = Field(description="Request id, also returned in the X-Request-Id header.")
    errors: list[ProblemError] = Field(
        default_factory=list, description="Field-level errors, when the problem concerns fields."
    )
    matched_on: list[MatchedField] | None = Field(
        default=None, description="For a duplicate: which keys matched an existing customer."
    )
    suggestion: TypoWarning | None = Field(
        default=None, description="A suggested correction, where one applies."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "type": "urn:smart-customer-onboarding:problem:customer-duplicate",
                    "title": "Customer already registered",
                    "status": 409,
                    "detail": "A customer already exists with the same email.",
                    "instance": "/api/v1/customers/register",
                    "request_id": "7c2f8f3e9b6a4d0c8a1e5b7d9f2a4c6e",
                    "errors": [],
                    "matched_on": ["email"],
                }
            ]
        }
    )
