"""Per-request context and the abuse controls that run before any work."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Operation
from app.domain.customer import Channel
from app.domain.errors import BotCheckFailed
from app.services.ports import BotVerifier, RateLimiter

BOT_CHECKED_OPERATIONS: frozenset[Operation] = frozenset({"register", "check_duplicate"})


@dataclass(frozen=True, slots=True)
class RequestContext:
    """What a service needs to know about the request it serves.

    `client_id` is the caller's address as the rate limiter and the audit hash see it. It is
    never logged. `started_at` is a monotonic reading taken when the request began.
    """

    request_id: str
    client_id: str
    started_at: float
    channel: Channel = "form"


class RequestGuard:
    """Applies the rate limit, then the bot check, for one operation."""

    def __init__(self, limiter: RateLimiter, verifier: BotVerifier) -> None:
        self._limiter = limiter
        self._verifier = verifier

    async def enforce(
        self, operation: Operation, ctx: RequestContext, bot_token: str | None = None
    ) -> None:
        """Raise `RateLimited` or `BotCheckFailed` when the request must stop.

        The assistant channel skips the bot check because chat requests carry no token. It is
        still rate limited under the operation's own allowance.
        """
        self._limiter.check(ctx.client_id, operation)
        needs_bot_check = operation in BOT_CHECKED_OPERATIONS and ctx.channel != "assistant"
        if needs_bot_check and not (
            bot_token and await self._verifier.verify(bot_token, ctx.client_id)
        ):
            raise BotCheckFailed("The bot check did not pass.")
