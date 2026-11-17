"""Structured JSON logging to stdout through an allow-list.

Only the keys in `ALLOWED_KEYS` ever reach the output. Names, emails, phone numbers, tax IDs,
addresses, client addresses, and chat text are not on the list, so a careless `log.info(...)`
call cannot leak them.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

ALLOWED_KEYS = frozenset(
    {
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
)
QUIET_LOGGERS = (
    "google_adk",
    "google.adk",
    "google_genai",
    "google.genai",
    "google.auth",
    "httpx",
    "httpcore",
    "urllib3",
    "asyncio",
)


def allow_list(
    _logger: object, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Drop every key that is not on the allow-list."""
    return {key: value for key, value in event_dict.items() if key in ALLOWED_KEYS}


def configure_logging(level: str = "INFO") -> None:
    """Send structlog and standard-library records to stdout as allow-listed JSON."""
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
    ]
    structlog.configure(
        processors=[*shared, allow_list, structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[structlog.stdlib.add_log_level, *shared[2:]],
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                allow_list,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.WARNING)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True
