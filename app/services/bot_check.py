"""Bot verification.

The `BotVerifier` port lives in `app.services.ports`. A real provider waits for the abuse
providers decision, so only the local stub exists.
"""

from __future__ import annotations

import hmac

from app.config import ConfigurationError

LOCAL_TOKEN = "local"  # noqa: S105 - a fixed local-only token, not a credential


class StubBotVerifier:
    """Accepts the fixed token `local`. It loads only when local adapters are allowed."""

    def __init__(self, *, allow_local_adapters: bool) -> None:
        if not allow_local_adapters:
            raise ConfigurationError(
                "The stub bot verifier loads only with ALLOW_LOCAL_ADAPTERS=true."
            )

    async def verify(self, token: str, client_id: str) -> bool:
        """Return True only for the local token."""
        return hmac.compare_digest(token.encode("utf-8"), LOCAL_TOKEN.encode("utf-8"))
