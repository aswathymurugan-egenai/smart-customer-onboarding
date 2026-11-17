"""Validated runtime configuration.

Everything that varies between deploys comes from the environment, a `.env` file, or a
mounted secrets directory. The process refuses to boot on a missing or malformed value.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SecretsSettingsSource,
    SettingsConfigDict,
)

PROJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
DATASET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,1024}$")
LOCATION_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9-]{1,30}$")
MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9._/:-]{1,100}$")
ORIGIN_PATTERN = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?$")

SECRETS_DIR_VARIABLE = "SECRETS_DIR"
DEFAULT_SECRETS_DIR = "/run/secrets"
MIN_HASH_KEY_LENGTH = 16

Operation = Literal["register", "check_duplicate", "validate", "chat"]


@dataclass(frozen=True, slots=True)
class RateRule:
    """An allowance of `limit` calls per `window_seconds` for one client and operation."""

    limit: int
    window_seconds: int


class ConfigurationError(ValueError):
    """Raised for a configuration value that must stop the process from booting."""


class Settings(BaseSettings):
    """All runtime settings. Field names map to upper-case environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Platform and storage.
    gcp_project: str | None = Field(
        default=None, description="GCP project for BigQuery and Vertex AI."
    )
    bq_dataset: str = "customer_ops"
    bq_location: str = "US"
    genai_location: str = "us-central1"
    customer_store: Literal["bigquery", "memory"] = "bigquery"
    bq_job_timeout_seconds: float = Field(default=30.0, gt=0)

    # Local adapters. Deployed configuration never sets allow_local_adapters.
    allow_local_adapters: bool = False
    bot_check_provider: Literal["stub"] = "stub"
    email_allow_reserved_domains: bool = False

    # HTTP edge.
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    trust_proxy_headers: bool = False

    # Models. The ids are configuration because the Gemini 2.5 line is being retired.
    gemini_advisor_model: str = "gemini-2.5-flash"
    gemini_assistant_model: str = "gemini-2.5-flash"
    advisor_enabled: bool = True
    assistant_enabled: bool = True
    llm_fallback_model: str | None = None

    # Budgets, in seconds.
    mx_timeout_seconds: float = Field(default=2.0, gt=0)
    advisory_budget_seconds: float = Field(default=4.0, gt=0)
    chat_budget_seconds: float = Field(default=20.0, gt=0)
    lock_retry_budget_seconds: float = Field(default=10.0, gt=0)
    lock_retry_base_seconds: float = Field(default=0.5, gt=0)
    lock_retry_max_attempts: int = Field(default=3, ge=0, le=10)
    lock_retry_after_seconds: int = Field(default=60, ge=1)
    readiness_cache_seconds: float = Field(default=30.0, ge=0)

    # Likely-duplicate matching. These are uncalibrated defaults until labeled pairs exist.
    fuzzy_blocking_limit: int = Field(default=50, ge=1, le=500)
    fuzzy_name_floor: float = Field(default=0.80, ge=0, le=1)
    fuzzy_name_with_signal_floor: float = Field(default=0.60, ge=0, le=1)
    fuzzy_address_floor: float = Field(default=0.85, ge=0, le=1)
    fuzzy_max_candidates_for_model: int = Field(default=5, ge=1, le=5)
    duplicate_warning_min_confidence: float = Field(default=0.60, ge=0, le=1)
    typo_min_confidence: float = Field(default=0.70, ge=0, le=1)

    # Rate limits, per client and operation.
    rate_register_limit: int = Field(default=5, ge=1)
    rate_register_window_seconds: int = Field(default=600, ge=1)
    rate_check_duplicate_limit: int = Field(default=10, ge=1)
    rate_check_duplicate_window_seconds: int = Field(default=600, ge=1)
    rate_validate_limit: int = Field(default=30, ge=1)
    rate_validate_window_seconds: int = Field(default=60, ge=1)
    rate_chat_limit: int = Field(default=20, ge=1)
    rate_chat_window_seconds: int = Field(default=600, ge=1)

    # Assistant session bounds.
    chat_max_turns_per_session: int = Field(default=30, ge=1)
    chat_max_prompt_chars: int = Field(default=12_000, ge=1)
    chat_max_tool_calls_per_turn: int = Field(default=4, ge=1)
    session_idle_seconds: float = Field(default=1800.0, gt=0)
    session_max_count: int = Field(default=1000, ge=1)
    session_janitor_interval_seconds: float = Field(default=60.0, gt=0)

    # Secrets. Read from the environment or the mounted secrets directory.
    pii_hash_key: SecretStr | None = None
    hash_key_version: str = "v1"
    bot_check_secret: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Add the mounted secrets directory after the environment sources."""
        sources: tuple[PydanticBaseSettingsSource, ...] = (
            init_settings,
            env_settings,
            dotenv_settings,
        )
        secrets_dir = Path(os.environ.get(SECRETS_DIR_VARIABLE, DEFAULT_SECRETS_DIR))
        if secrets_dir.is_dir():
            sources += (SecretsSettingsSource(settings_cls, secrets_dir=secrets_dir),)
        return sources

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("cors_allow_origins")
    @classmethod
    def _check_origins(cls, origins: list[str]) -> list[str]:
        if not origins:
            raise ValueError("CORS_ALLOW_ORIGINS must list at least one origin.")
        for origin in origins:
            if origin == "*" or not ORIGIN_PATTERN.fullmatch(origin):
                raise ValueError(
                    f"CORS_ALLOW_ORIGINS entry {origin!r} must be an exact http(s) origin "
                    "such as https://app.example.com, with no wildcard and no path."
                )
        return origins

    @field_validator("gcp_project")
    @classmethod
    def _check_project(cls, value: str | None) -> str | None:
        if value is not None and not PROJECT_ID_PATTERN.fullmatch(value):
            raise ValueError("GCP_PROJECT is not a valid GCP project id.")
        return value

    @field_validator("bq_dataset")
    @classmethod
    def _check_dataset(cls, value: str) -> str:
        if not DATASET_ID_PATTERN.fullmatch(value):
            raise ValueError("BQ_DATASET may contain only letters, digits, and underscores.")
        return value

    @field_validator("bq_location", "genai_location")
    @classmethod
    def _check_location(cls, value: str) -> str:
        if not LOCATION_PATTERN.fullmatch(value):
            raise ValueError("Location names may contain only letters, digits, and hyphens.")
        return value

    @field_validator("gemini_advisor_model", "gemini_assistant_model", "llm_fallback_model")
    @classmethod
    def _check_model_id(cls, value: str | None) -> str | None:
        if value is not None and not MODEL_ID_PATTERN.fullmatch(value):
            raise ValueError("Model ids may contain only letters, digits, and . _ / : -")
        return value

    @model_validator(mode="after")
    def _check_deployment_rules(self) -> Self:
        if self.customer_store == "bigquery" and not self.gcp_project:
            raise ValueError("GCP_PROJECT is required when CUSTOMER_STORE is bigquery.")
        local_only = {
            "CUSTOMER_STORE=memory": self.customer_store == "memory",
            "BOT_CHECK_PROVIDER=stub": self.bot_check_provider == "stub",
            "EMAIL_ALLOW_RESERVED_DOMAINS=true": self.email_allow_reserved_domains,
        }
        if not self.allow_local_adapters:
            active = [name for name, on in local_only.items() if on]
            if active:
                raise ValueError(
                    f"{', '.join(active)} load only with ALLOW_LOCAL_ADAPTERS=true, which "
                    "deployed configuration never sets."
                )
        if self.pii_hash_key is None or (
            len(self.pii_hash_key.get_secret_value()) < MIN_HASH_KEY_LENGTH
        ):
            raise ValueError(
                f"PII_HASH_KEY is required and must hold at least {MIN_HASH_KEY_LENGTH} characters."
            )
        if (self.advisor_enabled or self.assistant_enabled) and not self.gcp_project:
            raise ValueError(
                "GCP_PROJECT is required while ADVISOR_ENABLED or ASSISTANT_ENABLED is true, "
                "because Gemini runs on Vertex AI in that project."
            )
        if self.llm_fallback_model and self.openai_api_key is None:
            raise ValueError("LLM_FALLBACK_MODEL needs OPENAI_API_KEY.")
        return self

    def rate_rule(self, operation: Operation) -> RateRule:
        """Return the allowance for `operation`."""
        rules = {
            "register": RateRule(self.rate_register_limit, self.rate_register_window_seconds),
            "check_duplicate": RateRule(
                self.rate_check_duplicate_limit, self.rate_check_duplicate_window_seconds
            ),
            "validate": RateRule(self.rate_validate_limit, self.rate_validate_window_seconds),
            "chat": RateRule(self.rate_chat_limit, self.rate_chat_window_seconds),
        }
        return rules[operation]

    @property
    def hash_key(self) -> bytes:
        """The HMAC key for tax-ID, email, client, and request hashes."""
        if self.pii_hash_key is None:  # unreachable after validation; keeps mypy honest
            raise ConfigurationError("PII_HASH_KEY is not configured.")
        return self.pii_hash_key.get_secret_value().encode("utf-8")


def load_settings() -> Settings:
    """Load settings from the process environment. Raises on any invalid value."""
    return Settings()
