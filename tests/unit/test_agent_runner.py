"""The assistant on ADK's real `Runner`, with a scripted model in place of Gemini.

This proves the pieces ADK owns: per-turn `state_delta`, the callbacks, tool execution, the
structured final answer, and the confirmation flag clearing after each turn.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from google.adk.models._capabilities import LlmCapabilities
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import ConfigDict

from app.agents.registration_agent import (
    APP_NAME,
    REGISTER_TOOL,
    VALIDATE_TOOL,
    AgentRun,
    AssistantServices,
    RegistrationAssistant,
    build_agent,
)
from app.domain.errors import AssistantUnavailable
from app.models.schemas import AssistantTurn, ChatRequest
from app.services.pii import PiiHasher
from tests.conftest import HASH_KEY, make_settings
from tests.support import Graph, customer_input, make_graph


class ScriptedLlm(BaseLlm):
    """Replays steps: a tool call, or a final structured answer."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    model: str = "scripted-llm"
    steps: list[Any] = []
    requests: list[Any] = []

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=True)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        kind, *rest = self.steps.pop(0)
        if kind == "tool":
            part = types.Part(function_call=types.FunctionCall(name=rest[0], args=rest[1] or {}))
        else:
            part = types.Part(text=AssistantTurn(message=rest[0]).model_dump_json())
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def snapshot() -> dict[str, Any]:
    return customer_input().model_dump(mode="json", exclude={"bot_token"}, exclude_none=True)


def chat(**overrides: Any) -> ChatRequest:
    body: dict[str, Any] = {"session_id": str(uuid.uuid4()), "message": "hello"}
    body.update(overrides)
    return ChatRequest.model_validate(body)


def build(graph: Graph, llm: ScriptedLlm, **settings: Any) -> RegistrationAssistant:
    resolved = make_settings(customer_store="memory", **settings)
    hasher = PiiHasher(HASH_KEY.encode(), "v1")
    services = AssistantServices(
        email_validation=graph.email,
        duplicates=graph.duplicates,
        registration=graph.registration,
        hasher=hasher,
        clock=graph.clock,
    )
    sessions = InMemorySessionService()
    runner = Runner(
        agent=build_agent(resolved, services, model=llm),
        app_name=APP_NAME,
        session_service=sessions,
    )
    return RegistrationAssistant(
        settings=resolved,
        guard=graph.components.guard,
        hasher=hasher,
        clock=graph.clock,
        session_service=sessions,
        primary=AgentRun(runner, "scripted-llm"),
    )


def llm_with(*steps: Any) -> ScriptedLlm:
    return ScriptedLlm(steps=list(steps), requests=[])


async def test_a_plain_answer_comes_back_as_the_reply_message() -> None:
    graph = make_graph()
    assistant = build(graph, llm_with(("final", "Hello! How can I help?")))
    request = chat(form_snapshot={"given_name": "Jane"})

    reply = await assistant.chat(request, graph.ctx(channel="assistant"))

    assert reply.message == "Hello! How can I help?"
    assert reply.model == "scripted-llm"
    assert reply.used_fallback is False
    assert reply.registration is None


async def test_the_instruction_carries_the_redacted_form_and_never_the_raw_tax_id_or_phone() -> (
    None
):
    graph = make_graph()
    llm = llm_with(("final", "ok"))
    assistant = build(graph, llm)

    await assistant.chat(chat(form_snapshot=snapshot()), graph.ctx(channel="assistant"))

    system = str(llm.requests[0].config.system_instruction)
    assert "tax_id_last4" in system
    assert "6789" in system
    assert "12-3456789" not in system
    assert "123456789" not in system
    assert "+1 415 555 0100" not in system
    assert "4155550100" not in system
    assert "<untrusted_data>" in system


async def test_a_model_call_to_register_without_confirmation_registers_nobody() -> None:
    graph = make_graph()
    assistant = build(graph, llm_with(("tool", REGISTER_TOOL, {}), ("final", "Registered!")))

    reply = await assistant.chat(chat(form_snapshot=snapshot()), graph.ctx(channel="assistant"))

    assert reply.registration is not None
    assert reply.registration.status == "needs_confirmation"
    assert graph.repository.customers == ()


async def test_a_confirmed_turn_registers_once_and_the_flag_is_cleared_for_the_next_turn() -> None:
    graph = make_graph()
    session_id = str(uuid.uuid4())
    assistant = build(
        graph,
        llm_with(
            ("tool", REGISTER_TOOL, {}),
            ("final", "Done."),
            ("tool", REGISTER_TOOL, {}),
            ("final", "Again?"),
        ),
    )
    confirmed = chat(session_id=session_id, form_snapshot=snapshot(), action="confirm_registration")
    unconfirmed = chat(session_id=session_id, form_snapshot=snapshot())

    first = await assistant.chat(confirmed, graph.ctx(channel="assistant"))
    second = await assistant.chat(unconfirmed, graph.ctx(channel="assistant"))

    assert first.registration is not None
    assert first.registration.status == "created"
    assert first.registration.customer_id == graph.repository.customers[0].customer_id
    assert second.registration is not None
    assert second.registration.status == "needs_confirmation"
    assert len(graph.repository.customers) == 1


async def test_the_tool_call_cap_stops_a_fifth_call_in_one_turn() -> None:
    graph = make_graph()
    llm = llm_with(*[("tool", VALIDATE_TOOL, {"email": "jane@example.test"})] * 5, ("final", "ok"))
    assistant = build(graph, llm)

    await assistant.chat(chat(), graph.ctx(channel="assistant"))

    last_request_text = str(llm.requests[-1].contents[-1])
    assert "tool_call_limit_reached" in last_request_text


async def test_a_turn_past_the_session_limit_gets_the_limit_message_without_a_model_answer() -> (
    None
):
    graph = make_graph()
    session_id = str(uuid.uuid4())
    assistant = build(
        graph, llm_with(("final", "first"), ("final", "never used")), chat_max_turns_per_session=1
    )

    first = await assistant.chat(chat(session_id=session_id), graph.ctx(channel="assistant"))
    second = await assistant.chat(chat(session_id=session_id), graph.ctx(channel="assistant"))

    assert first.message == "first"
    assert "limit" in second.message


async def test_a_prompt_over_the_size_cap_is_refused_before_the_model_is_called() -> None:
    graph = make_graph()
    llm = llm_with(("final", "never used"))
    assistant = build(graph, llm, chat_max_prompt_chars=50)

    reply = await assistant.chat(chat(message="x" * 500), graph.ctx(channel="assistant"))

    assert "limit" in reply.message
    assert llm.requests == []


async def test_an_unparseable_final_answer_raises_assistant_unavailable() -> None:
    graph = make_graph()

    class RawLlm(ScriptedLlm):
        async def generate_content_async(
            self, llm_request: LlmRequest, stream: bool = False
        ) -> AsyncGenerator[LlmResponse, None]:
            yield LlmResponse(
                content=types.Content(role="model", parts=[types.Part(text="not json at all")])
            )

    assistant = build(graph, RawLlm(steps=[], requests=[]))

    with pytest.raises(AssistantUnavailable):
        await assistant.chat(chat(), graph.ctx(channel="assistant"))


async def test_the_janitor_evicts_idle_sessions_and_the_store_is_capped() -> None:
    graph = make_graph()
    assistant = build(
        graph,
        llm_with(*[("final", "ok")] * 4),
        session_idle_seconds=60,
        session_max_count=2,
    )
    ids = [str(uuid.uuid4()) for _ in range(3)]

    await assistant.chat(chat(session_id=ids[0]), graph.ctx(channel="assistant"))
    await assistant.chat(chat(session_id=ids[1]), graph.ctx(channel="assistant"))
    await assistant.chat(chat(session_id=ids[2]), graph.ctx(channel="assistant"))
    assert assistant.session_count == 2

    graph.clock.advance(61)
    removed = await assistant.evict_idle()

    assert removed == 2
    assert assistant.session_count == 0
