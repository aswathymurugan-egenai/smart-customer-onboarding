"""One structured call to each configured Gemini model id through Vertex AI.

A failure here blocks the advisor and assistant until the model question is answered. The
deterministic registration path does not depend on it.
"""

from __future__ import annotations

import os

import pytest
from google import genai

from app.config import Settings
from app.services.advisor import GeminiAdvisor

DEFAULT_MODEL = Settings.model_fields["gemini_advisor_model"].default
CONFIGURED_MODELS = sorted(
    {
        os.environ.get("GEMINI_ADVISOR_MODEL", DEFAULT_MODEL),
        os.environ.get("GEMINI_ASSISTANT_MODEL", DEFAULT_MODEL),
    }
)


@pytest.mark.parametrize("model", CONFIGURED_MODELS)
async def test_the_configured_model_answers_a_structured_typo_request(
    model: str, project: str
) -> None:
    client = genai.Client(
        vertexai=True,
        project=project,
        location=os.environ.get("GENAI_LOCATION", "us-central1"),
    )
    advisor = GeminiAdvisor(client, model=model, timeout_seconds=30)

    advice = await advisor.suggest_domain("gmial.com")

    assert 0.0 <= advice.confidence <= 1.0
