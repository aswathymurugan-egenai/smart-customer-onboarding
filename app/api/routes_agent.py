"""Assistant route: one chat turn."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.registration_agent import RegistrationAssistant
from app.api.dependencies import get_assistant, get_request_context
from app.api.problems import merge_docs, problem_docs
from app.domain import errors
from app.domain.errors import AssistantUnavailable
from app.models.problem_catalog import spec_for
from app.models.schemas import AssistantReply, ChatRequest
from app.services.guard import RequestContext

router = APIRouter(prefix="/api/v1/agent", tags=["assistant"])

CHAT_DOCS = merge_docs(
    problem_docs(spec_for(errors.InputInvalid("")), description="The request body is malformed."),
    problem_docs(
        spec_for(errors.RateLimited(1)),
        description="The client exceeded its chat allowance.",
        retry_after=True,
    ),
    problem_docs(spec_for(RuntimeError()), description="Unexpected server error."),
    problem_docs(
        spec_for(errors.AssistantUnavailable("")),
        description="The assistant model failed and no fallback answered, or the assistant is off.",
    ),
)


@router.post(
    "/chat",
    response_model=AssistantReply,
    operation_id="chatWithAssistant",
    summary="Send one message to the signup assistant",
    responses=CHAT_DOCS,
)
async def chat_with_assistant(
    body: ChatRequest,
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    assistant: Annotated[RegistrationAssistant | None, Depends(get_assistant)],
) -> AssistantReply:
    """Answer one turn of the conversation.

    The assistant explains validation results and can register the person, but only when the
    request carries `action = confirm_registration`. The `registration` field of the reply is
    copied from the register tool's result and never from the model's text.
    """
    if assistant is None:
        raise AssistantUnavailable("The assistant is switched off.")
    return await assistant.chat(body, ctx)
