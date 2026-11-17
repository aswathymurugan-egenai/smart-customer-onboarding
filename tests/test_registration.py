"""API behavior of the registration service, one test per behavior."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from app.domain.errors import AdvisorFailure
from app.models.schemas import AssistantTurn
from tests.conftest import ALLOWED_ORIGIN, Harness, running_harness
from tests.fakes import (
    FakeMx,
    FakeTurn,
    assistant_factory,
    candidate_row,
    lock_conflict,
)

REGISTER = "/api/v1/customers/register"
VALIDATE = "/api/v1/customers/validate"
CHECK = "/api/v1/customers/check-duplicate"
CHAT = "/api/v1/agent/chat"
PROBLEM = "urn:smart-customer-onboarding:problem:"


def customer_body(**overrides: Any) -> dict[str, Any]:
    """A complete, valid registration body with fictional values."""
    body: dict[str, Any] = {
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
    body.update(overrides)
    return body


def minimal_body(email: str, **overrides: Any) -> dict[str, Any]:
    """A registration with only the required fields."""
    return {"given_name": "Sam", "email": email, "bot_token": "local", **overrides}


def last_register_call(harness: Harness) -> Any:
    return next(call for call in reversed(harness.bq.calls) if "DECLARE replay" in call.sql)


async def test_valid_registration_returns_201_and_sends_every_value_as_a_parameter(
    harness: Harness,
) -> None:
    response = await harness.client.post(REGISTER, json=customer_body())

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "created"
    assert payload["customer_id"]
    assert payload["email"] == "jane.doe@example.test"
    call = last_register_call(harness)
    assert call.params["email"] == "jane.doe@example.test"
    assert call.params["phone_e164"] == "+14155550100"
    assert call.params["tax_id_hash"] != "123456789"
    assert call.params["tax_id_last4"] == "6789"
    for value in ("jane.doe", "Springfield", "Example Street", "123456789", "4155550100"):
        assert value not in call.sql


@pytest.mark.parametrize(
    "email",
    ["plainaddress", "jane@", "@example.test", "jane doe@example.test", "jane@@example.test"],
)
async def test_malformed_email_returns_422_email_invalid_and_writes_no_customer(
    harness: Harness, email: str
) -> None:
    response = await harness.client.post(REGISTER, json=customer_body(email=email))

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"] == f"{PROBLEM}email-invalid"
    assert body["errors"][0]["pointer"] == "/email"
    assert harness.bq.customers == []


async def test_disposable_domain_returns_422_email_disposable(harness: Harness) -> None:
    response = await harness.client.post(REGISTER, json=customer_body(email="x@mailinator.test"))

    assert response.status_code == 422
    assert response.json()["type"] == f"{PROBLEM}email-disposable"
    assert harness.bq.customers == []


async def test_domain_without_mx_or_address_records_returns_422_undeliverable() -> None:
    async with running_harness(assistant_enabled=False, mx=FakeMx({"nowhere.test": "fail"})) as h:
        response = await h.client.post(REGISTER, json=customer_body(email="a@nowhere.test"))

    assert response.status_code == 422
    assert response.json()["type"] == f"{PROBLEM}email-domain-undeliverable"


async def test_mx_timeout_still_registers_with_unknown_mx_status() -> None:
    async with running_harness(
        assistant_enabled=False, mx=FakeMx({"example.test": "unknown"})
    ) as h:
        response = await h.client.post(REGISTER, json=customer_body())

        assert response.status_code == 201
        assert last_register_call(h).params["mx_status"] == "unknown"


async def test_existing_email_returns_409_naming_email_and_no_other_customer_data(
    harness: Harness,
) -> None:
    first = await harness.client.post(REGISTER, json=customer_body())
    first_id = first.json()["customer_id"]

    response = await harness.client.post(
        REGISTER,
        json=customer_body(given_name="Someone", phone="+1 415 555 0101", tax_id="98-7654321"),
    )

    assert response.status_code == 409
    body = response.json()
    assert body["type"] == f"{PROBLEM}customer-duplicate"
    assert body["matched_on"] == ["email"]
    assert first_id not in response.text
    assert "Doe" not in response.text
    assert "customer_id" not in body


async def test_matching_phone_and_tax_id_return_409_naming_both(harness: Harness) -> None:
    await harness.client.post(REGISTER, json=customer_body())

    response = await harness.client.post(REGISTER, json=customer_body(email="other@example.test"))

    assert response.status_code == 409
    assert response.json()["matched_on"] == ["phone", "tax_id"]


async def test_near_duplicate_returns_201_with_a_possible_duplicate_warning(
    harness: Harness,
) -> None:
    harness.bq.fuzzy_rows = [candidate_row()]
    harness.advisor.fuzzy_verdicts["*"] = (
        "likely_same",
        0.9,
        ["swapped_name_order", "address_variant"],
    )

    response = await harness.client.post(
        REGISTER, json=customer_body(given_name="Jane", family_name="Muller-Smith")
    )

    assert response.status_code == 201
    payload = response.json()
    [warning] = payload["warnings"]
    assert warning["code"] == "possible_duplicate"
    assert warning["confidence"] == 0.9
    assert warning["reasons"] == ["swapped_name_order", "address_variant"]
    assert payload["advisory_status"] == "ok"
    assert "cand-1" not in response.text
    audit_created = next(row for row in harness.bq.audit if row.get("outcome") == "created")
    assert audit_created["fuzzy_candidate_ids"] == ["cand-1"]


async def test_advisor_failure_returns_201_with_unavailable_status_and_no_warning(
    harness: Harness,
) -> None:
    harness.bq.fuzzy_rows = [candidate_row()]
    harness.advisor.fail_fuzzy = AdvisorFailure("unavailable")

    response = await harness.client.post(
        REGISTER, json=customer_body(given_name="Jane", family_name="Muller Smith")
    )

    assert response.status_code == 201
    assert response.json()["advisory_status"] == "unavailable"
    assert response.json()["warnings"] == []


async def test_common_domain_typo_warns_from_rules_without_a_model_call(harness: Harness) -> None:
    response = await harness.client.post(REGISTER, json=customer_body(email="jane@gmial.com"))

    assert response.status_code == 201
    [warning] = response.json()["warnings"]
    assert warning["code"] == "possible_typo"
    assert warning["suggested_email"] == "jane@gmail.com"
    assert warning["source"] == "rules"
    assert harness.advisor.typo_calls == []


async def test_lock_conflict_is_retried_and_then_registers(harness: Harness) -> None:
    harness.bq.register_faults = [lock_conflict(), None]

    response = await harness.client.post(REGISTER, json=customer_body())

    assert response.status_code == 201
    assert last_register_call(harness).params["lock_retries"] == 1
    assert len(harness.clock.sleeps) == 1


async def test_lock_conflicts_past_the_budget_return_503_with_retry_after(
    harness: Harness,
) -> None:
    harness.bq.register_faults = [lock_conflict() for _ in range(10)]

    response = await harness.client.post(REGISTER, json=customer_body())

    assert response.status_code == 503
    assert response.headers["retry-after"] == "60"
    assert response.json()["type"] == f"{PROBLEM}registration-busy"
    assert harness.bq.customers == []
    [busy] = [row for row in harness.bq.audit if row.get("outcome") == "busy"]
    assert busy["lock_retries"] == 3


async def test_same_idempotency_key_and_body_replay_the_original_registration(
    harness: Harness,
) -> None:
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    first = await harness.client.post(REGISTER, json=customer_body(), headers=headers)

    second = await harness.client.post(REGISTER, json=customer_body(), headers=headers)

    assert first.status_code == second.status_code == 201
    assert second.json()["customer_id"] == first.json()["customer_id"]
    assert second.headers["idempotent-replayed"] == "true"
    assert "idempotent-replayed" not in first.headers
    assert len(harness.bq.customers) == 1


async def test_same_idempotency_key_with_a_different_body_returns_422(harness: Harness) -> None:
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    await harness.client.post(REGISTER, json=customer_body(), headers=headers)

    response = await harness.client.post(
        REGISTER, json=customer_body(given_name="Janet"), headers=headers
    )

    assert response.status_code == 422
    assert response.json()["type"] == f"{PROBLEM}idempotency-key-reused"


async def test_sixth_register_call_from_one_client_returns_429_with_retry_after(
    harness: Harness,
) -> None:
    for index in range(5):
        await harness.client.post(REGISTER, json=minimal_body(f"user{index}@example.test"))

    response = await harness.client.post(REGISTER, json=minimal_body("user5@example.test"))

    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 1
    assert response.json()["type"] == f"{PROBLEM}rate-limited"


async def test_missing_bot_token_returns_403(harness: Harness) -> None:
    response = await harness.client.post(REGISTER, json=customer_body(bot_token=""))

    assert response.status_code == 403
    assert response.json()["type"] == f"{PROBLEM}bot-check-failed"
    assert harness.bq.customers == []


async def test_validate_returns_200_with_is_valid_false_for_an_invalid_email(
    harness: Harness,
) -> None:
    response = await harness.client.post(VALIDATE, json={"email": "not-an-email"})

    assert response.status_code == 200
    body = response.json()
    assert body["is_valid"] is False
    assert body["normalized_email"] is None
    assert body["problems"][0]["code"] == "email-invalid"


async def test_check_duplicate_reports_exact_and_likely_matches_and_writes_no_customer(
    harness: Harness,
) -> None:
    await harness.client.post(REGISTER, json=customer_body())
    harness.bq.fuzzy_rows = [candidate_row()]
    harness.advisor.fuzzy_verdicts["*"] = ("possibly_same", 0.7, ["name_variant"])

    response = await harness.client.post(
        CHECK, json=customer_body(given_name="Jane", family_name="Muller Smith")
    )

    assert response.status_code == 200
    body = response.json()
    assert body["exact_matches"] == ["email", "phone", "tax_id"]
    assert body["possible_duplicate"]["reasons"] == ["name_variant"]
    assert len(harness.bq.customers) == 1
    assert any(row.get("operation") == "check_duplicate" for row in harness.bq.audit)


def draft_snapshot() -> dict[str, Any]:
    """The form as the UI sends it with a chat turn: a registration body without the bot token."""
    return {key: value for key, value in customer_body().items() if key != "bot_token"}


def chat_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"session_id": str(uuid.uuid4()), "message": "Hello"}
    body.update(overrides)
    return body


async def test_chat_returns_the_mocked_runner_reply() -> None:
    async def script(turn: FakeTurn) -> AssistantTurn:
        return AssistantTurn(message="Hello there.", suggested_actions=["review_field"])

    async with running_harness(assistant_factory=assistant_factory(script)) as h:
        response = await h.client.post(CHAT, json=chat_body())

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Hello there."
    assert body["suggested_actions"] == ["review_field"]
    assert body["model"] == "fake-primary"
    assert body["used_fallback"] is False
    assert body["registration"] is None


async def test_chat_turn_without_a_confirm_action_registers_nobody_even_if_the_model_asks() -> None:
    async def script(turn: FakeTurn) -> AssistantTurn:
        await turn.call("register_customer_bq_tool")
        return AssistantTurn(message="Registered!")

    async with running_harness(assistant_factory=assistant_factory(script)) as h:
        response = await h.client.post(CHAT, json=chat_body(form_snapshot=draft_snapshot()))

        assert response.status_code == 200
        assert response.json()["registration"]["status"] == "needs_confirmation"
        assert h.bq.customers == []


async def test_chat_turn_with_a_confirm_action_registers_once_and_reports_the_tool_result() -> None:
    async def script(turn: FakeTurn) -> AssistantTurn:
        await turn.call("register_customer_bq_tool")
        return AssistantTurn(message="Done.", suggested_actions=["confirm_registration"])

    async with running_harness(assistant_factory=assistant_factory(script)) as h:
        body = chat_body(form_snapshot=draft_snapshot(), action="confirm_registration")
        first = await h.client.post(CHAT, json=body)
        second = await h.client.post(CHAT, json=body)

        registration = first.json()["registration"]
        assert registration["status"] == "created"
        assert registration["customer_id"] == h.bq.customers[0]["customer_id"]
        assert first.json()["suggested_actions"] == []
        assert second.json()["registration"]["customer_id"] == registration["customer_id"]
        assert len(h.bq.customers) == 1
        assert h.bq.customers[0]["source_channel"] == "assistant"


async def test_chat_model_failure_returns_503_and_the_fallback_answers_when_configured() -> None:
    async def failing(turn: FakeTurn) -> AssistantTurn:
        raise TimeoutError

    async def backup(turn: FakeTurn) -> AssistantTurn:
        return AssistantTurn(message="Fallback here.")

    async with running_harness(assistant_factory=assistant_factory(failing)) as h:
        unavailable = await h.client.post(CHAT, json=chat_body())
    async with running_harness(
        assistant_factory=assistant_factory(failing, fallback_script=backup)
    ) as h:
        answered = await h.client.post(CHAT, json=chat_body())

    assert unavailable.status_code == 503
    assert unavailable.json()["type"] == f"{PROBLEM}assistant-unavailable"
    assert answered.status_code == 200
    assert answered.json()["used_fallback"] is True
    assert answered.json()["model"] == "fake-fallback"


async def test_cors_preflight_from_an_unlisted_origin_gets_no_allow_origin_header(
    harness: Harness,
) -> None:
    headers = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }

    refused = await harness.client.options(
        REGISTER, headers={**headers, "Origin": "https://evil.example"}
    )
    allowed = await harness.client.options(REGISTER, headers={**headers, "Origin": ALLOWED_ORIGIN})

    assert "access-control-allow-origin" not in refused.headers
    assert allowed.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


async def test_no_log_line_contains_submitted_personal_data(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secrets = ["Zephyrine", "Quillfeather", "zeph.unique", "4155550123", "AB1234", "wombat phrase"]
    allowed_keys = {
        "event",
        "level",
        "timestamp",
        "request_id",
        "route",
        "status",
        "outcome",
        "duration_ms",
        "problem_type",
        "advisory_status",
        "lock_retries",
        "model",
        "used_fallback",
        "error_type",
    }

    async def script(turn: FakeTurn) -> AssistantTurn:
        return AssistantTurn(message="ok")

    async with running_harness(assistant_factory=assistant_factory(script)) as h:
        body = customer_body(
            given_name="Zephyrine",
            family_name="Quillfeather",
            email="zeph.unique@example.test",
            phone="+1 415 555 0123",
            tax_id_type="other",
            tax_id="AB-1234",
            address={"line1": "77 Quillfeather Lane", "city": "Elmsville", "country_code": "US"},
        )
        await h.client.post(REGISTER, json=body)
        await h.client.post(REGISTER, json=body)
        await h.client.post(VALIDATE, json={"email": "zeph.unique@example.test"})
        await h.client.post(CHECK, json=body)
        await h.client.post(CHAT, json=chat_body(message="my wombat phrase"))
        h.bq.register_faults = [RuntimeError("boom Zephyrine")]
        await h.client.post(REGISTER, json=customer_body(email="boom@example.test"))

    output = capsys.readouterr().out
    lines = [line for line in output.splitlines() if line.strip()]
    assert lines
    for line in lines:
        assert set(json.loads(line)) <= allowed_keys
    for secret in secrets:
        assert secret not in output
