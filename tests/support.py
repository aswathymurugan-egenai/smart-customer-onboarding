"""Helpers that build the real service graph around test doubles."""

from __future__ import annotations

from typing import Any

from app.composition import ComponentOverrides, Components, build_components
from app.models.schemas import CustomerInput
from app.services.email_validation import DomainLists
from app.services.guard import RequestContext
from app.services.memory_repository import InMemoryCustomerRepository
from tests.conftest import make_settings, test_lists
from tests.fakes import FakeClock, FakeMx, ScriptedAdvisor, SequenceIds, seeded_rng


class Graph:
    """The wired services and the doubles behind them."""

    def __init__(self, components: Components, **doubles: Any) -> None:
        self.components = components
        self.clock: FakeClock = doubles["clock"]
        self.advisor: ScriptedAdvisor = doubles["advisor"]
        self.mx: FakeMx = doubles["mx"]
        self.repository: InMemoryCustomerRepository = components.repository  # type: ignore[assignment]
        self.registration = components.registration
        self.duplicates = components.duplicates
        self.email = components.email_validation

    def ctx(self, client: str = "203.0.113.7", channel: str = "form") -> RequestContext:
        return RequestContext(
            request_id="req-1",
            client_id=client,
            started_at=self.clock.monotonic(),
            channel=channel,  # type: ignore[arg-type]
        )


def make_graph(
    *,
    advisor: Any = None,
    mx: FakeMx | None = None,
    repository: Any = None,
    lists: DomainLists | None = None,
    **settings_overrides: Any,
) -> Graph:
    """Build the services on the in-memory store with fake time, ids, MX, and advisor."""
    clock = FakeClock()
    scripted = ScriptedAdvisor()
    fake_mx = mx or FakeMx()
    settings = make_settings(customer_store="memory", assistant_enabled=False, **settings_overrides)
    overrides = ComponentOverrides(
        advisor=advisor if advisor is not None else scripted,
        mx=fake_mx,
        clock=clock,
        ids=SequenceIds(),
        rng=seeded_rng(),
        lists=lists or test_lists(),
        genai_client=object(),
        repository=repository,
    )
    components = build_components(settings, overrides)
    return Graph(components, clock=clock, advisor=scripted, mx=fake_mx)


def customer_input(**overrides: Any) -> CustomerInput:
    """A valid registration with fictional values."""
    values: dict[str, Any] = {
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
    values.update(overrides)
    return CustomerInput.model_validate(values)
