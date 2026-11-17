"""Boot rules, probes, and shutdown behavior."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.main import create_app
from tests.conftest import make_settings, running_harness


def settings_kwargs(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "_env_file": None,
        "gcp_project": "test-project-1",
        "customer_store": "memory",
        "allow_local_adapters": True,
        "cors_allow_origins": ["http://localhost:3000"],
        "pii_hash_key": SecretStr("test-hash-key-0123456789"),
        "advisor_enabled": False,
        "assistant_enabled": False,
    }
    values.update(overrides)
    return values


async def test_the_app_boots_on_memory_settings_and_serves_a_request() -> None:
    async with running_harness(customer_store="memory", assistant_enabled=False) as h:
        response = await h.client.get("/healthz/live")

    assert response.status_code == 200


@pytest.mark.parametrize("origins", ["*", "", ["*"], ["https://a.example/path"], ["not a url"]])
def test_boot_refuses_an_empty_or_wildcard_cors_list(origins: object) -> None:
    with pytest.raises(ValidationError):
        Settings(**settings_kwargs(cors_allow_origins=origins))  # type: ignore[arg-type]


def test_a_comma_separated_origin_list_is_split() -> None:
    settings = Settings(**settings_kwargs(cors_allow_origins="http://a.test:3000, https://b.test"))  # type: ignore[arg-type]

    assert settings.cors_allow_origins == ["http://a.test:3000", "https://b.test"]


def test_boot_refuses_the_memory_store_without_local_adapters() -> None:
    with pytest.raises(ValidationError, match="ALLOW_LOCAL_ADAPTERS"):
        Settings(**settings_kwargs(allow_local_adapters=False))  # type: ignore[arg-type]


def test_boot_refuses_a_missing_project_when_the_store_is_bigquery() -> None:
    with pytest.raises(ValidationError, match="GCP_PROJECT"):
        Settings(**settings_kwargs(customer_store="bigquery", gcp_project=None))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [("gcp_project", "Bad Project"), ("bq_dataset", "data-set; DROP"), ("bq_location", "US'")],
)
def test_boot_refuses_an_invalid_project_dataset_or_location(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**settings_kwargs(**{field: value}))  # type: ignore[arg-type]


def test_boot_refuses_a_missing_or_short_hash_key() -> None:
    with pytest.raises(ValidationError, match="PII_HASH_KEY"):
        Settings(**settings_kwargs(pii_hash_key=None))  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="PII_HASH_KEY"):
        Settings(**settings_kwargs(pii_hash_key=SecretStr("short")))  # type: ignore[arg-type]


def test_boot_refuses_a_fallback_model_without_a_key() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(**settings_kwargs(llm_fallback_model="openai/gpt-4o"))  # type: ignore[arg-type]


def test_boot_refuses_enabled_models_without_a_project() -> None:
    with pytest.raises(ValidationError, match="GCP_PROJECT"):
        Settings(**settings_kwargs(gcp_project=None, advisor_enabled=True))  # type: ignore[arg-type]


def test_boot_refuses_reserved_email_domains_without_local_adapters() -> None:
    with pytest.raises(ValidationError, match="ALLOW_LOCAL_ADAPTERS"):
        Settings(
            **settings_kwargs(  # type: ignore[arg-type]
                customer_store="bigquery",
                allow_local_adapters=False,
                email_allow_reserved_domains=True,
            )
        )


def test_secrets_never_appear_in_the_settings_repr() -> None:
    settings = Settings(**settings_kwargs())  # type: ignore[arg-type]

    assert "test-hash-key" not in repr(settings)


def test_secrets_load_from_a_mounted_directory(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = Path(str(tmp_path))
    (secrets / "pii_hash_key").write_text("mounted-secret-key-0123456789")
    monkeypatch.setenv("SECRETS_DIR", str(secrets))
    monkeypatch.setenv("CUSTOMER_STORE", "memory")
    monkeypatch.setenv("ALLOW_LOCAL_ADAPTERS", "true")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("ADVISOR_ENABLED", "false")
    monkeypatch.setenv("ASSISTANT_ENABLED", "false")
    monkeypatch.delenv("PII_HASH_KEY", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.hash_key == b"mounted-secret-key-0123456789"


async def test_liveness_touches_no_dependency_and_readiness_reads_the_store() -> None:
    async with running_harness(assistant_enabled=False) as h:
        live = await h.client.get("/healthz/live")
        ready = await h.client.get("/healthz/ready")

        assert live.status_code == ready.status_code == 200
        h.bq.client.get_dataset.assert_called_once()


async def test_readiness_is_cached_so_a_probe_storm_is_not_a_query_storm() -> None:
    async with running_harness(assistant_enabled=False) as h:
        for _ in range(5):
            await h.client.get("/healthz/ready")

        assert h.bq.client.get_dataset.call_count == 1


async def test_readiness_returns_503_when_the_store_is_unreachable() -> None:
    async with running_harness(assistant_enabled=False) as h:
        h.bq.client.get_dataset.side_effect = RuntimeError("down")

        response = await h.client.get("/healthz/ready")

    assert response.status_code == 503


async def test_readiness_returns_503_while_the_app_is_draining() -> None:
    settings = make_settings(assistant_enabled=False)
    app = create_app(settings)
    app.state.draining = True
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ready = await client.get("/healthz/ready")
        live = await client.get("/healthz/live")

    assert ready.status_code == 503
    assert live.status_code == 200


async def test_shutdown_marks_the_app_draining_and_closes_the_clients() -> None:
    async with running_harness(assistant_enabled=False) as h:
        app = h.app
        assert app.state.draining is False
    assert app.state.draining is True
    h.bq.client.close.assert_called_once()


async def test_the_probes_are_absent_from_the_published_spec() -> None:
    app = create_app(make_settings(assistant_enabled=False))

    assert not [path for path in app.openapi()["paths"] if path.startswith("/healthz")]


async def test_the_advisor_kill_switch_removes_model_calls_and_keeps_every_status() -> None:
    async with running_harness(assistant_enabled=False, advisor_enabled=False) as h:
        created = await h.client.post(
            "/api/v1/customers/register",
            json={"given_name": "Sam", "email": "sam@gmial.com", "bot_token": "local"},
        )
        validated = await h.client.post(
            "/api/v1/customers/validate", json={"email": "sam@example.test"}
        )

    assert created.status_code == 201
    assert created.json()["advisory_status"] == "disabled"
    assert created.json()["warnings"][0]["source"] == "rules"
    assert validated.status_code == 200


async def test_the_assistant_kill_switch_makes_chat_return_503() -> None:
    async with running_harness(assistant_enabled=False) as h:
        response = await h.client.post(
            "/api/v1/agent/chat",
            json={"session_id": "6f1c1bde-3a64-4f2c-9a54-52f7a2d0a111", "message": "hi"},
        )

    assert response.status_code == 503
    assert response.json()["type"].endswith("assistant-unavailable")


async def test_an_unexpected_failure_returns_a_generic_500_problem_without_internals() -> None:
    async with running_harness(assistant_enabled=False) as h:
        h.bq.register_faults = [RuntimeError("secret internal detail: project-x.dataset.table")]
        response = await h.client.post(
            "/api/v1/customers/register",
            json={"given_name": "Sam", "email": "sam@example.test", "bot_token": "local"},
        )

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert "secret internal detail" not in response.text
    assert response.json()["type"].endswith("internal-error")
    assert response.headers["x-request-id"] == response.json()["request_id"]


async def test_a_client_supplied_request_id_is_echoed_when_well_formed_and_replaced_otherwise() -> (
    None
):
    async with running_harness(assistant_enabled=False) as h:
        good = await h.client.get("/healthz/live", headers={"X-Request-Id": "abc12345-trace"})
        bad = await h.client.get("/healthz/live", headers={"X-Request-Id": "bad id!"})

    assert good.headers["x-request-id"] == "abc12345-trace"
    assert bad.headers["x-request-id"] != "bad id!"
    assert len(bad.headers["x-request-id"]) == 32


async def test_a_malformed_idempotency_key_returns_a_422_validation_problem() -> None:
    async with running_harness(assistant_enabled=False) as h:
        response = await h.client.post(
            "/api/v1/customers/register",
            json={"given_name": "Sam", "email": "sam@example.test", "bot_token": "local"},
            headers={"Idempotency-Key": "not-a-uuid"},
        )

    assert response.status_code == 422
    assert response.json()["errors"][0]["pointer"] == "/headers/Idempotency-Key"


async def test_unknown_request_fields_are_rejected_at_the_edge() -> None:
    async with running_harness(assistant_enabled=False) as h:
        response = await h.client.post(
            "/api/v1/customers/register",
            json={
                "given_name": "Sam",
                "email": "sam@example.test",
                "bot_token": "local",
                "is_admin": True,
            },
        )

    assert response.status_code == 422
    assert response.json()["errors"][0]["pointer"] == "/is_admin"
    assert "is_admin" in response.text
    assert "True" not in response.text
