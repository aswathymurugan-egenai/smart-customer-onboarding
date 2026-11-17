"""The assistant's tools, callbacks, and construction, called directly with a fake tool context."""

from __future__ import annotations

import uuid
from typing import Any

from app.agents.registration_agent import (
    AGENT_NAME,
    DETECT_TOOL,
    REGISTER_TOOL,
    STATE_CLIENT_ID,
    STATE_CONFIRMED,
    STATE_CONFIRMED_FINGERPRINT,
    STATE_OUTCOME,
    STATE_REQUEST_ID,
    STATE_SESSION_ID,
    STATE_SNAPSHOT,
    STATE_TOOL_CALLS,
    STATE_TURNS,
    VALIDATE_TOOL,
    AssistantServices,
    build_agent,
    build_callbacks,
    build_tools,
    redact_snapshot,
)
from app.services.pii import PiiHasher
from tests.conftest import HASH_KEY, make_settings
from tests.fakes import FakeToolContext
from tests.support import Graph, customer_input, make_graph

SESSION_ID = str(uuid.UUID("6f1c1bde-3a64-4f2c-9a54-52f7a2d0a111"))


def services_for(graph: Graph) -> tuple[AssistantServices, PiiHasher]:
    hasher = PiiHasher(HASH_KEY.encode(), "v1")
    services = AssistantServices(
        email_validation=graph.email,
        duplicates=graph.duplicates,
        registration=graph.registration,
        hasher=hasher,
        clock=graph.clock,
    )
    return services, hasher


def draft() -> dict[str, Any]:
    return customer_input().model_dump(mode="json", exclude={"bot_token"}, exclude_none=True)


def turn_state(
    hasher: PiiHasher,
    *,
    snapshot: dict[str, Any] | None = None,
    confirm: bool = False,
    fingerprint: str | None = None,
) -> FakeToolContext:
    snapshot = draft() if snapshot is None else snapshot
    return FakeToolContext(
        {
            STATE_SESSION_ID: SESSION_ID,
            STATE_REQUEST_ID: "req-1",
            STATE_CLIENT_ID: "203.0.113.7",
            STATE_SNAPSHOT: snapshot,
            STATE_CONFIRMED: confirm,
            STATE_CONFIRMED_FINGERPRINT: (
                fingerprint
                if fingerprint is not None
                else (hasher.fingerprint(snapshot) if confirm else None)
            ),
        }
    )


async def test_register_returns_needs_confirmation_without_the_confirm_flag() -> None:
    graph = make_graph()
    services, hasher = services_for(graph)
    tools = {t.name: t for t in build_tools(services)}
    context = turn_state(hasher, confirm=False)

    result = await tools[REGISTER_TOOL].func(tool_context=context)

    assert result == {"status": "needs_confirmation"}
    assert context.state[STATE_OUTCOME] == result
    assert graph.repository.customers == ()


async def test_register_returns_needs_confirmation_when_the_confirmed_fingerprint_differs() -> None:
    graph = make_graph()
    services, hasher = services_for(graph)
    tools = {t.name: t for t in build_tools(services)}
    context = turn_state(hasher, confirm=True, fingerprint="a-fingerprint-for-another-form")

    result = await tools[REGISTER_TOOL].func(tool_context=context)

    assert result == {"status": "needs_confirmation"}
    assert graph.repository.customers == ()


async def test_register_creates_once_with_a_matching_flag_and_a_second_call_replays() -> None:
    graph = make_graph()
    services, hasher = services_for(graph)
    tools = {t.name: t for t in build_tools(services)}
    context = turn_state(hasher, confirm=True)

    first = await tools[REGISTER_TOOL].func(tool_context=context)
    second = await tools[REGISTER_TOOL].func(tool_context=context)

    assert first["status"] == "created"
    assert second["status"] == "created"
    assert second["customer_id"] == first["customer_id"]
    assert len(graph.repository.customers) == 1
    assert graph.repository.customers[0].source_channel == "assistant"
    assert context.state[STATE_OUTCOME] == second


async def test_register_reports_an_incomplete_form_with_the_blocking_fields() -> None:
    graph = make_graph()
    services, hasher = services_for(graph)
    tools = {t.name: t for t in build_tools(services)}
    context = turn_state(hasher, snapshot={"given_name": "Jane"}, confirm=True)

    result = await tools[REGISTER_TOOL].func(tool_context=context)

    assert result == {"status": "incomplete_form", "fields": ["email"]}


async def test_register_reports_a_duplicate_with_matched_fields_only() -> None:
    graph = make_graph()
    services, hasher = services_for(graph)
    tools = {t.name: t for t in build_tools(services)}
    await graph.registration.register(customer_input(), graph.ctx(), None)
    context = turn_state(hasher, confirm=True)

    result = await tools[REGISTER_TOOL].func(tool_context=context)

    assert result == {"status": "duplicate", "matched_on": ["email", "phone", "tax_id"]}


async def test_register_reports_a_rejected_registration_with_its_problem_code() -> None:
    graph = make_graph()
    services, hasher = services_for(graph)
    tools = {t.name: t for t in build_tools(services)}
    snapshot = {**draft(), "email": "x@mailinator.test"}
    context = turn_state(hasher, snapshot=snapshot, confirm=True)

    result = await tools[REGISTER_TOOL].func(tool_context=context)

    assert result["status"] == "rejected"
    assert result["problem"] == "email-disposable"
    assert result["field"] == "email"


async def test_detect_returns_matched_field_names_and_the_warning_only() -> None:
    graph = make_graph()
    services, hasher = services_for(graph)
    tools = {t.name: t for t in build_tools(services)}
    await graph.registration.register(customer_input(), graph.ctx(), None)
    context = turn_state(hasher)

    result = await tools[DETECT_TOOL].func(tool_context=context)

    assert result == {
        "status": "checked",
        "exact_matches": ["email", "phone", "tax_id"],
        "possible_duplicate": None,
        "advisory_status": "ok",
    }


async def test_detect_without_likely_duplicates_makes_no_model_call() -> None:
    graph = make_graph()
    services, hasher = services_for(graph)
    tools = {t.name: t for t in build_tools(services)}

    await tools[DETECT_TOOL].func(tool_context=turn_state(hasher), include_likely_duplicates=False)

    assert graph.advisor.fuzzy_calls == []


async def test_detect_reports_an_incomplete_form() -> None:
    graph = make_graph()
    services, hasher = services_for(graph)
    tools = {t.name: t for t in build_tools(services)}

    result = await tools[DETECT_TOOL].func(tool_context=turn_state(hasher, snapshot={}))

    assert result == {"status": "incomplete_form", "fields": ["form"]}


async def test_validate_passes_the_email_through_to_the_validation_service() -> None:
    graph = make_graph()
    services, hasher = services_for(graph)
    tools = {t.name: t for t in build_tools(services)}

    result = await tools[VALIDATE_TOOL].func(
        email="jane@gmial.com", tool_context=turn_state(hasher)
    )

    assert result["email_as_entered"] == "jane@gmial.com"
    assert result["suggestion"]["suggested_email"] == "jane@gmail.com"


def test_the_agent_has_exactly_the_three_named_tools_and_only_two_model_visible_parameters() -> (
    None
):
    graph = make_graph()
    services, _ = services_for(graph)

    agent = build_agent(make_settings(customer_store="memory"), services, model="gemini-2.5-flash")

    assert agent.name == AGENT_NAME
    assert [tool.name for tool in agent.tools] == [VALIDATE_TOOL, DETECT_TOOL, REGISTER_TOOL]  # type: ignore[union-attr]
    properties: set[str] = set()
    for tool in agent.tools:
        declaration = tool._get_declaration()  # type: ignore[union-attr]
        schema = declaration.parameters_json_schema or {}
        properties |= set(schema.get("properties", {}))
    assert properties == {"email", "include_likely_duplicates"}


def test_the_register_tool_exposes_no_parameters_the_model_could_fill() -> None:
    graph = make_graph()
    services, _ = services_for(graph)
    tool = next(t for t in build_tools(services) if t.name == REGISTER_TOOL)

    declaration = tool._get_declaration()

    assert not (declaration.parameters_json_schema or {}).get("properties")


def test_the_instruction_redacts_the_tax_id_and_phone_to_their_last_four_characters() -> None:
    redacted = redact_snapshot(draft())

    assert "tax_id" not in redacted
    assert "phone" not in redacted
    assert redacted["tax_id_last4"] == "6789"
    assert redacted["phone_last4"] == "0100"
    assert redacted["email"] == "jane.doe@example.test"


def test_a_fifth_tool_call_in_one_turn_is_refused_before_the_tool_runs() -> None:
    _, before_tool = build_callbacks(make_settings(customer_store="memory"))
    context = FakeToolContext({STATE_CONFIRMED: True})
    tool = type("T", (), {"name": VALIDATE_TOOL})()

    results = [before_tool(tool, {}, context) for _ in range(5)]

    assert results[:4] == [None, None, None, None]
    assert results[4] == {"status": "tool_call_limit_reached"}
    assert context.state[STATE_TOOL_CALLS] == 5


def test_the_register_tool_is_refused_by_the_callback_when_the_flag_is_off() -> None:
    _, before_tool = build_callbacks(make_settings(customer_store="memory"))
    context = FakeToolContext({STATE_CONFIRMED: False})
    tool = type("T", (), {"name": REGISTER_TOOL})()

    result = before_tool(tool, {}, context)

    assert result == {"status": "needs_confirmation"}
    assert context.state[STATE_OUTCOME] == {"status": "needs_confirmation"}


def test_a_turn_past_the_session_limit_is_refused_before_the_model_is_called() -> None:
    before_model, _ = build_callbacks(
        make_settings(customer_store="memory", chat_max_turns_per_session=2)
    )
    llm_request = type("R", (), {"contents": [], "config": None})()

    within = before_model(FakeToolContext({STATE_TURNS: 2}), llm_request)
    beyond = before_model(FakeToolContext({STATE_TURNS: 3}), llm_request)

    assert within is None
    assert beyond is not None
    assert "limit" in beyond.content.parts[0].text
