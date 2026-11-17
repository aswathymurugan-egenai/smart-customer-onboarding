"""The committed OpenAPI document is the contract; these tests hold the code to it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.export_openapi import TARGET, generate_schema, render

SPEC: dict[str, Any] = generate_schema()
OPERATIONS = {
    (method, path): operation
    for path, item in SPEC["paths"].items()
    for method, operation in item.items()
}
EXPECTED_OPERATION_IDS = {
    "registerCustomer",
    "validateEmail",
    "checkDuplicateCustomer",
    "chatWithAssistant",
}


def test_the_regenerated_spec_equals_the_committed_file_byte_for_byte() -> None:
    assert Path(TARGET).read_text(encoding="utf-8") == render(SPEC)


def test_the_committed_file_parses_as_openapi_3_1() -> None:
    committed = yaml.safe_load(Path(TARGET).read_text(encoding="utf-8"))

    assert committed["openapi"].startswith("3.1")
    assert committed["paths"] == SPEC["paths"]


def test_the_four_operations_are_published_with_ids_tags_summaries_and_descriptions() -> None:
    assert {op["operationId"] for op in OPERATIONS.values()} == EXPECTED_OPERATION_IDS
    for operation in OPERATIONS.values():
        assert operation["tags"]
        assert operation["summary"]
        assert operation["description"]


def test_every_error_response_is_a_problem_json_document_referencing_problem_details() -> None:
    for (_, path), operation in OPERATIONS.items():
        for status, response in operation["responses"].items():
            if not status.startswith(("4", "5")):
                continue
            content = response["content"]
            assert list(content) == ["application/problem+json"], (path, status)
            assert content["application/problem+json"]["schema"] == {
                "$ref": "#/components/schemas/ProblemDetails"
            }, (path, status)


def test_every_operation_documents_a_generic_500() -> None:
    for operation in OPERATIONS.values():
        assert "500" in operation["responses"]


def test_every_schema_property_has_a_description() -> None:
    missing = [
        f"{schema_name}.{prop_name}"
        for schema_name, schema in SPEC["components"]["schemas"].items()
        for prop_name, prop in schema.get("properties", {}).items()
        if "description" not in prop
    ]

    assert missing == []


def test_every_schema_has_an_example_with_fictional_values() -> None:
    wire_models = {
        "AddressInput",
        "CustomerInput",
        "TypoWarning",
        "DuplicateWarning",
        "RegistrationCreated",
        "EmailValidationResult",
        "DuplicateCheckResult",
        "CustomerDraft",
        "ChatRequest",
        "AssistantReply",
        "ProblemDetails",
    }
    schemas = SPEC["components"]["schemas"]

    assert all(schemas[name].get("examples") for name in wire_models)
    text = yaml.safe_dump(SPEC)
    assert "@example.test" in text


def test_register_documents_201_409_and_422() -> None:
    responses = OPERATIONS[("post", "/api/v1/customers/register")]["responses"]

    assert {"201", "403", "409", "422", "429", "500", "503"} <= set(responses)


def test_validate_and_check_duplicate_document_200_and_never_409() -> None:
    for path in ("/api/v1/customers/validate", "/api/v1/customers/check-duplicate"):
        responses = OPERATIONS[("post", path)]["responses"]
        assert "200" in responses
        assert "409" not in responses


def test_register_documents_the_idempotency_header_and_the_replay_header() -> None:
    operation = OPERATIONS[("post", "/api/v1/customers/register")]
    header = next(p for p in operation["parameters"] if p["name"] == "Idempotency-Key")

    assert header["in"] == "header"
    assert header["description"]
    assert "Idempotent-Replayed" in operation["responses"]["201"]["headers"]
    assert "Location" not in operation["responses"]["201"].get("headers", {})
    assert "no Location header" in operation["responses"]["201"]["description"]


@pytest.mark.parametrize("status", ["429", "503"])
def test_throttling_responses_document_retry_after(status: str) -> None:
    responses = OPERATIONS[("post", "/api/v1/customers/register")]["responses"]

    assert "Retry-After" in responses[status]["headers"]


def test_the_probes_are_not_published() -> None:
    assert not [path for path in SPEC["paths"] if "healthz" in path]


def test_request_models_forbid_unknown_fields() -> None:
    schemas = SPEC["components"]["schemas"]

    for name in ("CustomerInput", "AddressInput", "ChatRequest", "EmailValidationRequest"):
        assert schemas[name]["additionalProperties"] is False


def test_the_register_422_lists_every_documented_problem_type() -> None:
    examples = OPERATIONS[("post", "/api/v1/customers/register")]["responses"]["422"]["content"][
        "application/problem+json"
    ]["examples"]

    assert set(examples) == {
        "email-invalid",
        "email-disposable",
        "email-domain-undeliverable",
        "phone-invalid",
        "tax-id-invalid",
        "idempotency-key-reused",
        "validation-error",
    }
